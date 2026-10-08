"""Capacity-definitions documents: shape, validation, and reconciliation.

A capacity-definitions document declares capacity resources in bulk. Its
root field ``resources`` holds entries, each a ``CapacityDeclaration`` with
the same fields a registration request and a resource listing use::

    resources:
      - resource_id: compute-kvm1-001
        pool_id: default
        resource_type: compute.gpu
        resource_subtype: h200        # optional
        host_id: kvm1                 # optional
        capacity: {gpu_count: 8, ram_gb: 2048}
        attributes: {gpu_model: H200} # optional
        enabled: true                 # optional, default true

An entry replaces the whole declaration it names, exactly as a registration
does: an optional field it omits is cleared, not kept. The legacy scalar
``total_units`` is not accepted, and ``resource_type`` is required rather
than defaulted, so a document never supplies a value its author did not
write. Validation reports every problem it finds, each with its location.

Reconciliation compares each entry with the stored declaration and registers
only created and updated entries, because registration appends a capacity
event even when it changes nothing. Refusals that only stored state can
decide come from registration itself, not from rules restated here.
Declarations the document does not name are left as they are.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import yaml
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.orm import Session

from .declarations import CapacityDeclaration
from .ledger import CapacityConflictError, CapacityLedgerService, UnknownPoolError

_ROOT_FIELDS = frozenset({"resources"})

# Validation error types reported under this document's problem codes; any
# other type is a value of the wrong type.
_PROBLEM_CODES = {
    "missing": "required_field",
    "string_too_short": "required_field",
    "too_short": "required_field",
    "extra_forbidden": "unknown_field",
    "invalid_amount": "invalid_amount",
    "reserved_attribute": "reserved_attribute",
}


class CapacityDefinitionProblem(BaseModel):
    """One problem found in a capacity-definitions document."""

    path: str
    code: str
    message: str


class CapacityDefinitionsDiff(BaseModel):
    """What reconciling a document changes, by resource id.

    There is no ``disabled`` list: a document never removes or disables a
    declaration it does not name.
    """

    created: list[str] = Field(default_factory=list)
    updated: list[str] = Field(default_factory=list)
    unchanged: list[str] = Field(default_factory=list)


class CapacityDefinitionsImportRequest(BaseModel):
    yaml_text: str = Field(
        description="Capacity-definitions YAML with a top-level 'resources' list."
    )
    validate_only: bool = Field(
        default=False,
        description=(
            "Report the problems and the planned changes without applying "
            "either."
        ),
    )


class CapacityDefinitionsImportResponse(BaseModel):
    applied: bool
    diff: CapacityDefinitionsDiff
    problems: list[CapacityDefinitionProblem] = Field(default_factory=list)


@dataclass(frozen=True)
class CapacityDefinitionsOutcome:
    """The result of reconciling one document.

    ``problems`` empty means every entry was accepted. The declarations were
    written into the caller's session either way, so the caller commits only
    when the outcome is ``valid`` and it intends to apply.
    """

    diff: CapacityDefinitionsDiff
    problems: tuple[CapacityDefinitionProblem, ...]

    @property
    def valid(self) -> bool:
        return not self.problems


def _problem(path: str, code: str, message: str) -> CapacityDefinitionProblem:
    return CapacityDefinitionProblem(path=path, code=code, message=message)


def _load_entries(
    yaml_text: str,
) -> tuple[list[Any] | None, list[CapacityDefinitionProblem]]:
    """The document's ``resources`` list, or ``None`` when there is none.

    Reports unparseable YAML, a root that is not a mapping, unknown root
    fields, and a missing or non-list ``resources``.
    """
    try:
        parsed = yaml.safe_load(yaml_text)
    except yaml.YAMLError as exc:
        return None, [_problem("$", "invalid_yaml", f"invalid YAML: {exc}")]
    if not isinstance(parsed, dict):
        return None, [_problem("$", "invalid_type", "YAML root must be a mapping")]
    problems = [
        _problem(str(name), "unknown_field", f"unknown top-level field '{name}'")
        for name in sorted(set(parsed) - _ROOT_FIELDS, key=str)
    ]
    entries = parsed.get("resources")
    if not isinstance(entries, list):
        problems.append(
            _problem(
                "resources", "invalid_type", "YAML must have a top-level 'resources' list"
            )
        )
        return None, problems
    return entries, problems


def _validate_entry(
    index: int, raw: Any
) -> tuple[CapacityDeclaration | None, list[CapacityDefinitionProblem]]:
    """One entry as a declaration, or every problem that prevents it.

    Validation is strict: a quoted number or boolean is the wrong type, not a
    value to coerce.
    """
    base = f"resources[{index}]"
    try:
        return CapacityDeclaration.model_validate(raw, strict=True), []
    except ValidationError as exc:
        return None, [
            _problem(
                base + "".join(f".{part}" for part in error["loc"]),
                _PROBLEM_CODES.get(error["type"], "invalid_type"),
                error["msg"],
            )
            for error in exc.errors()
        ]


def _cross_entry_problems(entries: Sequence[Any]) -> list[CapacityDefinitionProblem]:
    """A resource id or host named by more than one entry.

    Reads the raw entries, so a duplicate is reported even beside an entry's
    other problems.
    """
    problems: list[CapacityDefinitionProblem] = []
    for field, code, noun in (
        ("resource_id", "duplicate_resource_id", "resource"),
        ("host_id", "duplicate_host_id", "host"),
    ):
        first_seen: dict[str, str] = {}
        for index, entry in enumerate(entries):
            value = entry.get(field) if isinstance(entry, dict) else None
            if not isinstance(value, str) or not value:
                continue
            base = f"resources[{index}]"
            if value in first_seen:
                problems.append(
                    _problem(
                        f"{base}.{field}",
                        code,
                        f"{noun} '{value}' is also named at {first_seen[value]}",
                    )
                )
            else:
                first_seen[value] = base
    return problems


def parse_capacity_definitions(
    yaml_text: str,
) -> tuple[tuple[CapacityDeclaration, ...], tuple[CapacityDefinitionProblem, ...]]:
    """Validate a document's structure and return its declarations and problems.

    Structural only: nothing here reads stored state. Any problem makes the
    document unappliable, so the declarations matter only when there are
    none, and then they are in document order.
    """
    entries, problems = _load_entries(yaml_text)
    if entries is None:
        return (), tuple(problems)
    declarations: list[CapacityDeclaration] = []
    for index, raw in enumerate(entries):
        declaration, entry_problems = _validate_entry(index, raw)
        problems.extend(entry_problems)
        if declaration is not None:
            declarations.append(declaration)
    problems.extend(_cross_entry_problems(entries))
    return tuple(declarations), tuple(problems)


def reconcile_capacity_definitions_in_session(
    db: Session,
    ledger: CapacityLedgerService,
    yaml_text: str,
) -> CapacityDefinitionsOutcome:
    """Reconcile a document into the caller's transaction and report the result.

    A structurally invalid document is reported and goes no further: stored
    state is consulted only for a document whose every entry is a
    declaration. Every created or updated entry is then registered through
    ``register_declaration_in_session``, so the refusals only stored state
    can decide (an unknown pool, a host another declaration names, a pool
    move under a live obligation) are registration's own. Each refusal is recorded as a problem
    rather than ending the reconciliation, so one import reports all of them.

    Registration's refusals all happen before it writes, so the session holds
    exactly the accepted entries afterwards. The caller commits only when the
    outcome is valid and it means to apply the document; otherwise it rolls
    back, which is also how a validate-only request sees stored-state
    refusals without applying anything. Neither opens a session nor commits,
    and the caller holds ``ledger.serialized()`` around its whole transaction.
    """
    declarations, structural = parse_capacity_definitions(yaml_text)
    if structural:
        return CapacityDefinitionsOutcome(CapacityDefinitionsDiff(), structural)

    problems: list[CapacityDefinitionProblem] = []
    diff = CapacityDefinitionsDiff()
    for index, declaration in enumerate(declarations):
        base = f"resources[{index}]"
        try:
            change = ledger.declaration_change_in_session(db, declaration)
            if change == "unchanged":
                diff.unchanged.append(declaration.resource_id)
                continue
            ledger.register_declaration_in_session(db, declaration)
        except UnknownPoolError as exc:
            problems.append(_problem(f"{base}.pool_id", "unknown_pool", str(exc)))
            continue
        except CapacityConflictError as exc:
            problems.append(_problem(base, "conflict", str(exc)))
            continue
        except ValueError as exc:
            problems.append(_problem(base, "invalid_declaration", str(exc)))
            continue
        getattr(diff, change).append(declaration.resource_id)
    return CapacityDefinitionsOutcome(diff, tuple(problems))
