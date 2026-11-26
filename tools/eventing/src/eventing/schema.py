"""The component's tables, and the schema steps a service's migration chain applies.

The component owns no migration engine: each service applies `SCHEMA_STEPS`, in
order, from its own chain, each step under its `name` as the migration's identity.
A step is fixed DDL for one schema version and is never edited once released; a
later change to the tables is a further step. The `Table` objects below are how the
component reads and writes those tables, and describe the schema the steps build.

The DDL holds to types SQLite and PostgreSQL both accept. Times are stored as UTC
without a zone, converted by `to_stored` and `from_stored`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger,
    Column,
    Connection,
    DateTime,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    text,
)

SEQUENCE_COUNTER = "events"
"""The counter row every event's `sequence` is allocated from."""

metadata = MetaData()

events = Table(
    "eventing_events",
    metadata,
    Column("sequence", BigInteger, primary_key=True, autoincrement=False),
    Column("id", String, nullable=False),
    Column("kind", String, nullable=False),
    Column("kind_version", Integer, nullable=False),
    Column("dedup_key", Text, nullable=False),
    Column("severity_rank", Integer, nullable=False),
    Column("subject_type", String, nullable=False),
    Column("subject_id", String, nullable=False),
    Column("occurred_at", DateTime, nullable=False),
    Column("recorded_at", DateTime, nullable=False),
    Column("envelope", Text, nullable=False),
    UniqueConstraint("id", name="uq_eventing_events_id"),
    UniqueConstraint("kind", "dedup_key", name="uq_eventing_events_occurrence"),
    Index("ix_eventing_events_subject", "subject_type", "subject_id"),
    Index("ix_eventing_events_recorded_at", "recorded_at"),
)

related = Table(
    "eventing_related",
    metadata,
    Column("event_sequence", BigInteger, primary_key=True, autoincrement=False),
    Column("type", String, primary_key=True),
    Column("id", String, primary_key=True),
    Index("ix_eventing_related_reference", "type", "id"),
)

sequence_counter = Table(
    "eventing_sequence",
    metadata,
    Column("name", String, primary_key=True),
    Column("value", BigInteger, nullable=False),
)

consumers = Table(
    "eventing_consumers",
    metadata,
    Column("name", String, primary_key=True),
    Column("position", BigInteger, nullable=False),
    Column("created_at", DateTime, nullable=False),
)

destinations = Table(
    "eventing_destinations",
    metadata,
    Column("consumer", String, primary_key=True),
    Column("name", String, primary_key=True),
    Column("state", String, nullable=False),
    Column("added_at_position", BigInteger, nullable=False),
    Column("added_at", DateTime, nullable=False),
    Column("state_changed_at", DateTime, nullable=False),
    Column("state_reason", Text),
)

deliveries = Table(
    "eventing_deliveries",
    metadata,
    Column("consumer", String, primary_key=True),
    Column("destination", String, primary_key=True),
    Column("event_sequence", BigInteger, primary_key=True, autoincrement=False),
    Column("state", String, nullable=False),
    Column("attempts", Integer, nullable=False),
    Column("last_error", Text),
    Column("created_at", DateTime, nullable=False),
    Column("last_attempted_at", DateTime),
    Column("next_attempt_at", DateTime, nullable=False),
    Column("finished_at", DateTime),
    Index("ix_eventing_deliveries_event", "event_sequence"),
)

TABLES = ("events", "deliveries")
"""The component's tables retention is configured for, by their retention names:
`events` holds the events and their references, `deliveries` the finished
deliveries and the retired destinations with none left."""


@dataclass(frozen=True)
class SchemaStep:
    """One schema version's DDL, applied once on the service's connection."""

    version: int
    statements: tuple[str, ...]

    @property
    def name(self) -> str:
        """The step's identity in a service's migration ledger."""
        return f"eventing_{self.version:04d}"

    def apply(self, connection: Connection) -> None:
        for statement in self.statements:
            connection.execute(text(statement))


_VERSION_1 = (
    """
    CREATE TABLE eventing_events (
        sequence BIGINT NOT NULL,
        id VARCHAR NOT NULL,
        kind VARCHAR NOT NULL,
        kind_version INTEGER NOT NULL,
        dedup_key TEXT NOT NULL,
        severity_rank INTEGER NOT NULL,
        subject_type VARCHAR NOT NULL,
        subject_id VARCHAR NOT NULL,
        occurred_at TIMESTAMP NOT NULL,
        recorded_at TIMESTAMP NOT NULL,
        envelope TEXT NOT NULL,
        PRIMARY KEY (sequence),
        CONSTRAINT uq_eventing_events_id UNIQUE (id),
        CONSTRAINT uq_eventing_events_occurrence UNIQUE (kind, dedup_key)
    )
    """,
    "CREATE INDEX ix_eventing_events_subject ON eventing_events (subject_type, subject_id)",
    "CREATE INDEX ix_eventing_events_recorded_at ON eventing_events (recorded_at)",
    """
    CREATE TABLE eventing_related (
        event_sequence BIGINT NOT NULL,
        type VARCHAR NOT NULL,
        id VARCHAR NOT NULL,
        PRIMARY KEY (event_sequence, type, id)
    )
    """,
    "CREATE INDEX ix_eventing_related_reference ON eventing_related (type, id)",
    """
    CREATE TABLE eventing_sequence (
        name VARCHAR NOT NULL,
        value BIGINT NOT NULL,
        PRIMARY KEY (name)
    )
    """,
    # The counter row every event's sequence is allocated from: the recorder
    # updates it and never creates it, so the schema seeds it.
    f"INSERT INTO eventing_sequence (name, value) VALUES ('{SEQUENCE_COUNTER}', 0)",
    """
    CREATE TABLE eventing_consumers (
        name VARCHAR NOT NULL,
        position BIGINT NOT NULL,
        created_at TIMESTAMP NOT NULL,
        PRIMARY KEY (name)
    )
    """,
    """
    CREATE TABLE eventing_destinations (
        consumer VARCHAR NOT NULL,
        name VARCHAR NOT NULL,
        state VARCHAR NOT NULL,
        added_at_position BIGINT NOT NULL,
        added_at TIMESTAMP NOT NULL,
        state_changed_at TIMESTAMP NOT NULL,
        state_reason TEXT,
        PRIMARY KEY (consumer, name)
    )
    """,
    """
    CREATE TABLE eventing_deliveries (
        consumer VARCHAR NOT NULL,
        destination VARCHAR NOT NULL,
        event_sequence BIGINT NOT NULL,
        state VARCHAR NOT NULL,
        attempts INTEGER NOT NULL,
        last_error TEXT,
        created_at TIMESTAMP NOT NULL,
        last_attempted_at TIMESTAMP,
        next_attempt_at TIMESTAMP NOT NULL,
        finished_at TIMESTAMP,
        PRIMARY KEY (consumer, destination, event_sequence)
    )
    """,
    "CREATE INDEX ix_eventing_deliveries_event ON eventing_deliveries (event_sequence)",
)

SCHEMA_STEPS: tuple[SchemaStep, ...] = (SchemaStep(1, _VERSION_1),)
"""Every schema step, in the order a chain applies them."""


def to_stored(instant: datetime) -> datetime:
    """`instant` as the zoneless UTC value the tables store."""
    return instant.astimezone(timezone.utc).replace(tzinfo=None)


def from_stored(stored: datetime) -> datetime:
    """A stored time as an aware UTC datetime."""
    return stored.replace(tzinfo=timezone.utc)

