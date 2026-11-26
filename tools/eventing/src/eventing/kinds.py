"""Kind declarations, the drafts a producer records, and the catalogue of kinds.

A kind is declared before any event of it is recorded: its name, version, default
severity, declared attributes and their types, dedup key, details model and
summary renderer, and optionally a record-time hook. The declaration never
travels: an event carries only what its envelope holds, so a reader that does not
know the kind still routes and renders it.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

from eventing.envelope import SCALAR_FIELDS, Envelope, Reference, Scalar, Severity

D = TypeVar("D", bound=BaseModel)

ATTRIBUTE_TYPES: tuple[type, ...] = (str, int, float, bool)
"""The types an attribute may be declared with."""

_TOP_LEVEL_KEY_FIELDS = ("subject", "correlation_id", "causation_id")


class EventRefused(ValueError):
    """The recorder refused an event; nothing was written.

    `code` is stable: `undeclared_kind`, `invalid_attributes` or `invalid_details`.
    """

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


class KindRefused(ValueError):
    """A declaration the catalogue refuses, naming the kind and what is wrong."""


@dataclass(frozen=True)
class PrunedTable:
    """A table a record-time hook writes, pruned by time on `timestamp_column`."""

    name: str
    timestamp_column: str


@dataclass(frozen=True)
class RecordHook:
    """Work done in the recording transaction, with the event as recorded.

    `apply` runs in the producer's transaction after the event is written; if it
    raises, the transaction rolls back, the producer's state change included.
    `tables` are the tables it writes, each retained for a time of its own.
    """

    apply: Callable[[Session, Envelope], None]
    tables: tuple[PrunedTable, ...] = ()


@dataclass(frozen=True)
class EventDraft:
    """An event a producer asks to record, before the recorder gives it an envelope.

    A draft can be prepared by one component and recorded by another that does not
    know its kind: the recorder validates it against the catalogue when it records.
    `details` is the kind's details model, or a mapping that validates as one.
    `severity`, when given, overrides the kind's default.
    """

    kind: str
    subject: Reference
    details: BaseModel | Mapping[str, Any]
    attributes: Mapping[str, Scalar] = field(default_factory=dict)
    related: tuple[Reference, ...] = ()
    severity: Severity | None = None
    correlation_id: str | None = None
    causation_id: str | None = None
    occurred_at: datetime | None = None
    extensions: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Kind(Generic[D]):
    """One kind's declaration.

    `dedup_key` names the envelope fields identifying one occurrence: `subject`,
    `correlation_id`, `causation_id`, `attributes.<name>`, `details.<field>`, or
    `related.<type>` (the identifier of the related reference of that type). The
    recorder writes at most one event per kind and key value; an empty key makes
    every recorded event its own occurrence. `summary` renders the one-line text a
    person reads from the draft and its validated details.
    """

    name: str
    version: int
    severity: Severity
    details: type[D]
    summary: Callable[[EventDraft, D], str]
    attributes: Mapping[str, type] = field(default_factory=dict)
    dedup_key: tuple[str, ...] = ()
    hook: RecordHook | None = None

    def draft(
        self,
        *,
        subject: Reference,
        details: D | Mapping[str, Any],
        attributes: Mapping[str, Scalar] | None = None,
        related: Iterable[Reference] = (),
        severity: Severity | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
        occurred_at: datetime | None = None,
        extensions: Mapping[str, Any] | None = None,
    ) -> EventDraft:
        """A draft of an event of this kind."""
        return EventDraft(
            kind=self.name,
            subject=subject,
            details=details,
            attributes=dict(attributes or {}),
            related=tuple(related),
            severity=severity,
            correlation_id=correlation_id,
            causation_id=causation_id,
            occurred_at=occurred_at,
            extensions=dict(extensions or {}),
        )

    def validate_attributes(self, attributes: Mapping[str, Scalar]) -> dict[str, Scalar]:
        """The draft's attributes if each is declared and of its declared type.

        An absent or null attribute is allowed; an integer is accepted where a float
        is declared, and a boolean only where a boolean is.
        """
        undeclared = sorted(set(attributes) - set(self.attributes))
        if undeclared:
            raise EventRefused(
                "invalid_attributes",
                f"{self.name} declares no attribute {', '.join(undeclared)}",
            )
        for name, value in attributes.items():
            if value is not None and not _is_of(value, self.attributes[name]):
                raise EventRefused(
                    "invalid_attributes",
                    f"{self.name}'s attribute {name} is declared "
                    f"{self.attributes[name].__name__}, not {type(value).__name__}",
                )
        return dict(attributes)

    def validate_details(self, details: BaseModel | Mapping[str, Any]) -> D:
        """The draft's details as this kind's details model."""
        if isinstance(details, self.details):
            return details
        if isinstance(details, BaseModel):
            raise EventRefused(
                "invalid_details",
                f"{self.name}'s details are {self.details.__name__}, "
                f"not {type(details).__name__}",
            )
        try:
            return self.details.model_validate(details)
        except ValidationError as error:
            raise EventRefused(
                "invalid_details", f"{self.name}'s details do not validate: {error}"
            ) from error

    def dedup_value(self, draft: EventDraft, details: D) -> str | None:
        """The occurrence's key value as JSON text, or None when the kind has no key."""
        if not self.dedup_key:
            return None
        values: list[Any] = []
        dumped = details.model_dump(mode="json")
        for path in self.dedup_key:
            head, _, name = path.partition(".")
            if path == "subject":
                values.append(str(draft.subject))
            elif path in _TOP_LEVEL_KEY_FIELDS:
                values.append(getattr(draft, path))
            elif head == "attributes":
                values.append(draft.attributes.get(name))
            elif head == "details":
                values.append(dumped.get(name))
            else:
                values.append(next((r.id for r in draft.related if r.type == name), None))
        return json.dumps(values, separators=(",", ":"))


def _is_of(value: object, declared: type) -> bool:
    if declared is float:
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if declared is int:
        return isinstance(value, int) and not isinstance(value, bool)
    return isinstance(value, declared)


class Catalogue:
    """The declared kinds of one store, listable, and the columns routes may name.

    `schema_prefix` begins each event's `data_schema`, which is
    `<schema_prefix>:<kind>:<version>`.
    """

    def __init__(self, kinds: Iterable[Kind[Any]] = (), *, schema_prefix: str = "urn:event") -> None:
        self._kinds: dict[str, Kind[Any]] = {}
        self._attribute_types: dict[str, type] = {}
        self.schema_prefix = schema_prefix
        for kind in kinds:
            self.declare(kind)

    def declare(self, kind: Kind[Any]) -> None:
        """Add `kind`, refusing a second kind of its name or a declaration that
        cannot be routed or keyed."""
        if kind.name in self._kinds:
            raise KindRefused(f"kind {kind.name} is declared twice")
        if kind.version < 1:
            raise KindRefused(f"kind {kind.name}'s version must be at least 1")
        for name, declared in kind.attributes.items():
            if name in SCALAR_FIELDS:
                raise KindRefused(f"kind {kind.name}'s attribute {name} is an envelope field")
            if declared not in ATTRIBUTE_TYPES:
                raise KindRefused(
                    f"kind {kind.name}'s attribute {name} is declared {declared!r}; "
                    "an attribute is a str, int, float or bool"
                )
            # A route reads every kind's attribute of one name as one column.
            known = self._attribute_types.get(name)
            if known is not None and known is not declared:
                raise KindRefused(
                    f"kind {kind.name}'s attribute {name} is declared {declared.__name__}, "
                    f"another kind declares it {known.__name__}"
                )
        for path in kind.dedup_key:
            if not _key_path_valid(kind, path):
                raise KindRefused(f"kind {kind.name}'s dedup key names {path}, no field of it")
        self._kinds[kind.name] = kind
        for name, declared in kind.attributes.items():
            self._attribute_types[name] = declared

    def kinds(self) -> tuple[Kind[Any], ...]:
        """Every declared kind, by name."""
        return tuple(self._kinds[name] for name in sorted(self._kinds))

    def require(self, name: str) -> Kind[Any]:
        """The kind named `name`, or `EventRefused` as `undeclared_kind`."""
        kind = self._kinds.get(name)
        if kind is None:
            raise EventRefused("undeclared_kind", f"no kind {name} is declared")
        return kind

    def data_schema(self, kind: Kind[Any]) -> str:
        return f"{self.schema_prefix}:{kind.name}:{kind.version}"

    def columns(self) -> dict[str, type]:
        """The columns a route may name: the envelope's scalar fields, then every
        declared attribute."""
        return {**SCALAR_FIELDS, **self._attribute_types}

    def decode_details(self, envelope: Envelope) -> BaseModel | None:
        """The event's details as its kind's model, or None where this catalogue
        cannot read them.

        The kind version is read before the details: an event of a version other
        than the declared one, or of a kind not declared here, is read from its
        envelope alone, and its details are left as they are.
        """
        kind = self._kinds.get(envelope.kind)
        if kind is None or kind.version != envelope.kind_version:
            return None
        decoded: BaseModel = kind.details.model_validate(envelope.details)
        return decoded


def _key_path_valid(kind: Kind[Any], path: str) -> bool:
    if path in _TOP_LEVEL_KEY_FIELDS:
        return True
    head, dot, name = path.partition(".")
    if not dot or not name:
        return False
    if head == "attributes":
        return name in kind.attributes
    if head == "details":
        return name in kind.details.model_fields
    return head == "related"
