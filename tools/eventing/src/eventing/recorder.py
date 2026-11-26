"""The recorder: an event written through its producer's own session.

An event commits or rolls back with the state change it reports, because it is
written in the producer's transaction; a kind's record-time hook runs in that
transaction too, and its failure rolls the whole transaction back.

`sequence` comes from a single counter row updated in the producer's transaction,
whose row lock is held until that transaction ends. A second transaction recording
an event waits on the row until the first commits or rolls back, so no event
commits with a lower sequence than an event already visible, and a consumer may
always advance its position past every event it has read. On SQLite, which
serializes writers, the lock costs nothing; on PostgreSQL, recording transactions
queue on the row from their record call to their commit.
"""

from __future__ import annotations

import secrets
from collections.abc import Callable
from datetime import datetime

from sqlalchemy import insert, select, update
from sqlalchemy.orm import Session

from eventing import schema
from eventing.envelope import ENVELOPE_VERSION, Envelope, Source
from eventing.kinds import Catalogue, EventDraft

_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def new_event_id(instant: datetime) -> str:
    """A ULID for an event occurring at `instant`: 48 bits of milliseconds, then 80
    random bits, in Crockford base 32, so identities sort by time."""
    value = (int(instant.timestamp() * 1000) << 80) | secrets.randbits(80)
    return "".join(_CROCKFORD[(value >> shift) & 31] for shift in range(125, -1, -5))


class Recorder:
    """Records declared kinds of event for one service instance.

    `clock` reads the time of the world as an aware datetime; it stamps an event's
    `occurred_at` when its draft gives none, and every event's recording time,
    which retention counts from.
    """

    def __init__(self, catalogue: Catalogue, *, source: Source, clock: Callable[[], datetime]) -> None:
        self._catalogue = catalogue
        self._source = source
        self._clock = clock

    def record(self, session: Session, draft: EventDraft) -> Envelope:
        """Write `draft` as an event in `session`'s transaction and return it.

        Refuses, writing nothing, a draft of an undeclared kind or whose attributes
        or details fail its declaration (`EventRefused`). An occurrence already
        recorded — the same kind and dedup-key value — is not written again: the
        existing event is returned and no hook runs.
        """
        kind = self._catalogue.require(draft.kind)
        attributes = kind.validate_attributes(draft.attributes)
        details = kind.validate_details(draft.details)
        dedup = kind.dedup_value(draft, details)

        # The occurrence is looked for only once the counter is held: where the
        # database reads what committed while a transaction waited (PostgreSQL at
        # read committed), a recorder that waited on another recording the same
        # occurrence finds that event rather than failing on the occurrence's
        # unique constraint. A repeat leaves a gap in the sequence, which no
        # consumer depends on.
        sequence: int = session.execute(
            update(schema.sequence_counter)
            .where(schema.sequence_counter.c.name == schema.SEQUENCE_COUNTER)
            .values(value=schema.sequence_counter.c.value + 1)
            .returning(schema.sequence_counter.c.value)
        ).scalar_one()
        if dedup is not None:
            existing: str | None = session.execute(
                select(schema.events.c.envelope).where(
                    schema.events.c.kind == kind.name, schema.events.c.dedup_key == dedup
                )
            ).scalar_one_or_none()
            if existing is not None:
                return Envelope.from_json(existing)

        now = self._clock()
        occurred_at = draft.occurred_at or now
        event_id = new_event_id(occurred_at)
        severity = draft.severity or kind.severity
        envelope = Envelope(
            envelope_version=ENVELOPE_VERSION,
            id=event_id,
            kind=kind.name,
            kind_version=kind.version,
            data_schema=self._catalogue.data_schema(kind),
            source=self._source,
            sequence=sequence,
            occurred_at=occurred_at,
            severity=severity,
            subject=draft.subject,
            related=draft.related,
            correlation_id=draft.correlation_id,
            causation_id=draft.causation_id,
            attributes=attributes,
            summary=kind.summary(draft, details),
            details=details.model_dump(mode="json"),
            extensions=dict(draft.extensions),
        )
        session.execute(
            insert(schema.events).values(
                sequence=sequence,
                id=event_id,
                kind=kind.name,
                kind_version=kind.version,
                # An event of a kind with no dedup key is its own occurrence.
                dedup_key=dedup if dedup is not None else event_id,
                severity_rank=severity.rank,
                subject_type=draft.subject.type,
                subject_id=draft.subject.id,
                occurred_at=schema.to_stored(occurred_at),
                recorded_at=schema.to_stored(now),
                envelope=envelope.to_json(),
            )
        )
        references = {(reference.type, reference.id) for reference in draft.related}
        if references:
            session.execute(
                insert(schema.related),
                [
                    {"event_sequence": sequence, "type": type_, "id": id_}
                    for type_, id_ in sorted(references)
                ],
            )
        if kind.hook is not None:
            kind.hook.apply(session, envelope)
        return envelope
