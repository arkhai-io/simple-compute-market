"""The envelope every event carries, which a consumer reads without knowing its kind.

Anything a consumer acts on without knowing the kind — routing, filtering,
deduplicating, ordering, correlating — is an envelope field; `details` holds only
what a reader of that kind wants, and follows the kind's `kind_version`.

The envelope evolves by addition alone: a field is only ever added, as optional, so
a reader built for an earlier envelope ignores what it does not know and still
reads every event. `envelope_version` changes only with an incompatible change.
`extensions` are carried unchanged by every reader and interpreted by none.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Union

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictFloat, StrictInt, StrictStr

ENVELOPE_VERSION = 1
"""The envelope version this component writes and reads."""

Scalar = Union[StrictStr, StrictInt, StrictFloat, StrictBool, None]
"""An attribute's value: a scalar, kept as its own type rather than coerced."""


class Severity(str, Enum):
    """How urgently an operator should look, in ascending order."""

    INFO = "info"
    WARNING = "warning"
    ACTION_REQUIRED = "action_required"

    @property
    def rank(self) -> int:
        """The severity's place in the order, for comparing severities as numbers."""
        return _RANKS[self]


_RANKS = {Severity.INFO: 0, Severity.WARNING: 1, Severity.ACTION_REQUIRED: 2}


def severity_rank(severity: Severity | str) -> int:
    """The rank of `severity`: `info` 0, `warning` 1, `action_required` 2."""
    return Severity(severity).rank


class Reference(BaseModel):
    """A thing an event is about or names: its type and its identifier."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    type: str
    id: str

    def __str__(self) -> str:
        return f"{self.type}:{self.id}"


class Source(BaseModel):
    """The service that recorded an event, and the instance of it."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    service: str
    instance: str


class Envelope(BaseModel):
    """One recorded event.

    `sequence` orders events within one store: no event commits with a lower
    sequence than an event already visible, so a consumer that has read every event
    up to a sequence has missed none below it. `id` is the event's stable identity,
    the one every delivery of it carries.
    """

    model_config = ConfigDict(extra="ignore", frozen=True)

    envelope_version: int
    id: str
    kind: str
    kind_version: int
    data_schema: str
    source: Source
    sequence: int
    occurred_at: datetime
    severity: Severity
    subject: Reference
    related: tuple[Reference, ...] = ()
    correlation_id: str | None = None
    causation_id: str | None = None
    attributes: dict[str, Scalar] = Field(default_factory=dict)
    summary: str
    details: dict[str, Any] = Field(default_factory=dict)
    extensions: dict[str, Any] = Field(default_factory=dict)

    @property
    def severity_rank(self) -> int:
        return self.severity.rank

    def to_json(self) -> str:
        """The envelope as JSON, as it is stored and as sinks receive it."""
        return self.model_dump_json()

    @classmethod
    def from_json(cls, raw: str | bytes) -> Envelope:
        """Read an envelope, ignoring any field this reader does not know."""
        return cls.model_validate_json(raw)

    def scalar_fields(self) -> dict[str, Any]:
        """The envelope's scalar fields by their column names (`SCALAR_FIELDS`).

        `source` and `subject` are flattened into two columns each, and
        `occurred_at` is its ISO 8601 UTC text, which orders as the instants do.
        """
        return {
            "envelope_version": self.envelope_version,
            "id": self.id,
            "kind": self.kind,
            "kind_version": self.kind_version,
            "data_schema": self.data_schema,
            "source_service": self.source.service,
            "source_instance": self.source.instance,
            "sequence": self.sequence,
            "occurred_at": iso_utc(self.occurred_at),
            "severity": self.severity.value,
            "severity_rank": self.severity.rank,
            "subject_type": self.subject.type,
            "subject_id": self.subject.id,
            "correlation_id": self.correlation_id,
            "causation_id": self.causation_id,
            "summary": self.summary,
        }


SCALAR_FIELDS: dict[str, type] = {
    "envelope_version": int,
    "id": str,
    "kind": str,
    "kind_version": int,
    "data_schema": str,
    "source_service": str,
    "source_instance": str,
    "sequence": int,
    "occurred_at": str,
    "severity": str,
    "severity_rank": int,
    "subject_type": str,
    "subject_id": str,
    "correlation_id": str,
    "causation_id": str,
    "summary": str,
}
"""The envelope's scalar fields as a route reads them: each column's name and type."""


def iso_utc(instant: datetime) -> str:
    """`instant` as ISO 8601 UTC text ending in `Z`."""
    return instant.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
