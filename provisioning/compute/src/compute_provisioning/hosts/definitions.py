"""Host definitions documents: validation, reconciliation, and export.

A host definitions document declares hosts with the host registration
contract's field names, as a top-level ``hosts`` list of
``HostDefinition`` entries::

    hosts:
      - host_id: kvm1
        pool_id: vm-default       # optional; omitted or null, the host is unplaced
        enabled: true             # optional, default true
        connection:
          kind: ssh
          version: 2              # required: a document's meaning has no default
          public:
            ssh_host: 192.0.2.5
            key_path: /home/appuser/.ssh/id_ed25519

An entry declares its whole host: applying it registers the host or replaces
all of its non-secret state, so an omitted ``pool_id`` unplaces the host and an
omitted ``enabled`` enables it. Hosts the document does not name are left as
they are and reported. The document never carries a credential: a key is named
by its file path, or kept from the stored host by naming none.

Validation runs in two stages. The first is structural and reads nothing
stored; it reports every problem with its location. Only a document with no
structural problem is checked against stored state, where every refusal is
reported too: the apply continues past one so that a single submission shows
them all. Nothing here opens a session or commits; the caller commits only an
outcome with no problem and rolls back any other, which discards whatever a
refused entry, or a hook refusing it, wrote.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import yaml
from compute_provisioning_contracts import (
    ConnectionSubmission,
    HostDefinition,
    HostDefinitionProblem,
    HostDefinitionProblemCode,
    HostDefinitionsDiff,
)
from pydantic import ValidationError
from sqlalchemy.orm import Session

from compute_provisioning.hosts.service import (
    HostAuthority,
    PoolChangeRefusedError,
    UnknownPoolError,
)

_ROOT_FIELDS = frozenset({"hosts"})

# Validation error types with a code of their own; any other is a value of the
# wrong type.
_PROBLEM_CODES = {
    "missing": HostDefinitionProblemCode.REQUIRED_FIELD,
    "extra_forbidden": HostDefinitionProblemCode.UNKNOWN_FIELD,
    "string_too_short": HostDefinitionProblemCode.INVALID_VALUE,
    "greater_than_equal": HostDefinitionProblemCode.INVALID_VALUE,
}

_SECRETS_LOCATION = ("connection", "secrets")


@dataclass(frozen=True)
class HostDefinitionsOutcome:
    """What reconciling one document did in the caller's session.

    ``diff`` holds the entries accepted, whether they would be committed or not,
    and ``not_named`` the registered hosts the document leaves as they are. A
    structurally invalid document is never checked against stored state, so
    both are empty for it.
    """

    diff: HostDefinitionsDiff
    not_named: tuple[str, ...]
    problems: tuple[HostDefinitionProblem, ...]

    @property
    def valid(self) -> bool:
        return not self.problems


def _problem(path: str, code: HostDefinitionProblemCode, message: str) -> HostDefinitionProblem:
    return HostDefinitionProblem(path=path, code=code.value, message=message)


def _load_entries(yaml_text: str) -> tuple[list[Any] | None, list[HostDefinitionProblem]]:
    """The document's ``hosts`` list, or ``None`` when there is none to read."""
    try:
        parsed = yaml.safe_load(yaml_text)
    except yaml.YAMLError as exc:
        return None, [_problem("$", HostDefinitionProblemCode.INVALID_YAML, f"invalid YAML: {exc}")]
    if not isinstance(parsed, dict):
        # An empty document parses to None, which is no mapping either.
        return None, [
            _problem("$", HostDefinitionProblemCode.INVALID_TYPE, "the document's root must be a mapping")
        ]
    problems = [
        _problem(str(name), HostDefinitionProblemCode.UNKNOWN_FIELD, f"unknown top-level field '{name}'")
        for name in sorted(set(parsed) - _ROOT_FIELDS, key=str)
    ]
    if "hosts" not in parsed:
        problems.append(
            _problem("hosts", HostDefinitionProblemCode.REQUIRED_FIELD, "the document needs a top-level 'hosts' list")
        )
        return None, problems
    entries = parsed["hosts"]
    if not isinstance(entries, list):
        problems.append(_problem("hosts", HostDefinitionProblemCode.INVALID_TYPE, "'hosts' must be a list"))
        return None, problems
    return entries, problems


def _entry_problem(base: str, error: Any) -> HostDefinitionProblem:
    location = tuple(error["loc"])
    if error["type"] == "extra_forbidden" and location == _SECRETS_LOCATION:
        return _problem(
            f"{base}.connection.secrets",
            HostDefinitionProblemCode.CONNECTION_SECRETS,
            "a host definitions document carries no credential: name a key by its key_path",
        )
    return _problem(
        base + "".join(f".{part}" for part in location),
        _PROBLEM_CODES.get(error["type"], HostDefinitionProblemCode.INVALID_TYPE),
        error["msg"],
    )


def _validate_entry(index: int, raw: Any) -> tuple[HostDefinition | None, list[HostDefinitionProblem]]:
    """One entry as a host definition, or every problem that prevents it.

    The model is strict by its own configuration, so a quoted number or
    boolean, and ``enabled: null``, are the wrong type rather than coerced.
    """
    base = f"hosts[{index}]"
    try:
        return HostDefinition.model_validate(raw), []
    except ValidationError as exc:
        return None, [_entry_problem(base, error) for error in exc.errors()]


def _duplicate_host_ids(entries: Sequence[Any]) -> list[HostDefinitionProblem]:
    """Every entry naming a host an earlier entry names.

    Read from the raw entries, so a duplicate is reported even beside an
    entry's other problems.
    """
    problems: list[HostDefinitionProblem] = []
    first_seen: dict[str, str] = {}
    for index, entry in enumerate(entries):
        host_id = entry.get("host_id") if isinstance(entry, dict) else None
        if not isinstance(host_id, str) or not host_id:
            continue
        base = f"hosts[{index}]"
        if host_id in first_seen:
            problems.append(
                _problem(
                    f"{base}.host_id",
                    HostDefinitionProblemCode.DUPLICATE_HOST_ID,
                    f"host '{host_id}' is also named at {first_seen[host_id]}",
                )
            )
        else:
            first_seen[host_id] = base
    return problems


def parse_host_definitions(
    yaml_text: str,
) -> tuple[tuple[HostDefinition, ...], tuple[HostDefinitionProblem, ...]]:
    """Validate a document's structure; return its entries and every problem.

    Reads nothing stored. Any problem makes the document unappliable, so the
    entries matter only when there is none, and then they are in document order.
    """
    entries, problems = _load_entries(yaml_text)
    if entries is None:
        return (), tuple(problems)
    definitions: list[HostDefinition] = []
    for index, raw in enumerate(entries):
        definition, entry_problems = _validate_entry(index, raw)
        problems.extend(entry_problems)
        if definition is not None:
            definitions.append(definition)
    problems.extend(_duplicate_host_ids(entries))
    return tuple(definitions), tuple(problems)


def reconcile_host_definitions_in_session(
    db: Session, hosts: HostAuthority, yaml_text: str
) -> HostDefinitionsOutcome:
    """Apply a document's entries in the caller's session and report the result.

    Each entry is written through the host authority's session-scoped write,
    which builds its connection through the kind's codec with the stored
    connection as the previous one and compares the result with the stored
    host, so an equal entry writes nothing and runs no hook. A refusal — an
    unknown pool, a connection its codec refuses, a pool-change hook refusing
    the move — is recorded at its entry and the next entry is applied, so every
    refusal is reported. The caller commits only a valid outcome.
    """
    definitions, structural = parse_host_definitions(yaml_text)
    if structural:
        return HostDefinitionsOutcome(HostDefinitionsDiff(), (), structural)

    named = {definition.host_id for definition in definitions}
    not_named = tuple(host_id for host_id in hosts.host_ids_in_session(db) if host_id not in named)
    diff = HostDefinitionsDiff()
    problems: list[HostDefinitionProblem] = []
    for index, definition in enumerate(definitions):
        base = f"hosts[{index}]"
        host_id = definition.host_id
        connection = ConnectionSubmission(
            kind=definition.connection.kind,
            version=definition.connection.version,
            public=definition.connection.public,
        )
        try:
            change = hosts.put_host_in_session(
                db, host_id, connection, pool_id=definition.pool_id, enabled=definition.enabled
            )
        except UnknownPoolError as exc:
            problems.append(_problem(f"{base}.pool_id", HostDefinitionProblemCode.UNKNOWN_POOL, f"host '{host_id}': {exc}"))
        except PoolChangeRefusedError as exc:
            problems.append(
                _problem(f"{base}.pool_id", HostDefinitionProblemCode.POOL_CHANGE_REFUSED, f"host '{host_id}': {exc}")
            )
        except ValueError as exc:
            problems.append(
                _problem(f"{base}.connection", HostDefinitionProblemCode.INVALID_CONNECTION, f"host '{host_id}': {exc}")
            )
        else:
            getattr(diff, change).append(host_id)
    return HostDefinitionsOutcome(diff, not_named, tuple(problems))


def render_host_definitions(definitions: Sequence[HostDefinition]) -> str:
    """A host definitions document stating ``definitions``, in the order given.

    Every entry states its ``pool_id`` and ``enabled`` whatever their values, so
    the document reads the same whatever the defaults; a public field with no
    value is left out, as an entry that omits it means the same.
    """
    hosts = [
        {
            "host_id": definition.host_id,
            "pool_id": definition.pool_id,
            "enabled": definition.enabled,
            "connection": {
                "kind": definition.connection.kind,
                "version": definition.connection.version,
                "public": {
                    name: value for name, value in definition.connection.public.items() if value is not None
                },
            },
        }
        for definition in definitions
    ]
    return yaml.safe_dump({"hosts": hosts}, sort_keys=False)


__all__ = [
    "HostDefinitionsOutcome",
    "parse_host_definitions",
    "reconcile_host_definitions_in_session",
    "render_host_definitions",
]
