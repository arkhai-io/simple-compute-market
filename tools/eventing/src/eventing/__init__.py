"""Declared kinds of event, recorded in their producer's transaction and delivered at
least once to each consumer's destinations.

A producer declares a kind once (`Kind`, gathered in a `Catalogue`) and records an
event of it through its own database session (`Recorder.record`). Each named
`Consumer` reads the events in sequence order and delivers them to its
destinations, with per-destination state, park and resume, and a finally sink for
abandoned deliveries. `Routes` select events for destinations with SQL conditions;
`Pruner` retains stored state by time per table; `EventService` serves the reads
and the delivery status. A service's migration chain applies `SCHEMA_STEPS`.
"""

from eventing.consumers import (
    ABANDONED,
    ACTIVE,
    DELIVERED,
    PARKED,
    PENDING,
    RETIRED,
    AbandonDelivery,
    Consumer,
    CycleReport,
    Destination,
    FinallySink,
    LogFinallySink,
    ParkDestination,
    RetryPolicy,
    Selection,
    UnknownDestination,
    park_destination,
    resume_destination,
)
from eventing.envelope import (
    ENVELOPE_VERSION,
    SCALAR_FIELDS,
    Envelope,
    Reference,
    Scalar,
    Severity,
    Source,
    severity_rank,
)
from eventing.kinds import (
    Catalogue,
    EventDraft,
    EventRefused,
    Kind,
    KindRefused,
    PrunedTable,
    RecordHook,
)
from eventing.pruning import PruneReport, Pruner, Retention
from eventing.recorder import Recorder, new_event_id
from eventing.routes import Route, RouteRefused, Routes
from eventing.schema import SCHEMA_STEPS, TABLES, SchemaStep, metadata
from eventing.service import DestinationStatus, EventReader, EventService, EventServiceError

__all__ = [
    "ABANDONED",
    "ACTIVE",
    "DELIVERED",
    "ENVELOPE_VERSION",
    "PARKED",
    "PENDING",
    "RETIRED",
    "SCALAR_FIELDS",
    "SCHEMA_STEPS",
    "TABLES",
    "AbandonDelivery",
    "Catalogue",
    "Consumer",
    "CycleReport",
    "Destination",
    "DestinationStatus",
    "Envelope",
    "EventDraft",
    "EventReader",
    "EventRefused",
    "EventService",
    "EventServiceError",
    "FinallySink",
    "Kind",
    "KindRefused",
    "LogFinallySink",
    "ParkDestination",
    "PruneReport",
    "Pruner",
    "PrunedTable",
    "RecordHook",
    "Recorder",
    "Reference",
    "Retention",
    "RetryPolicy",
    "Route",
    "RouteRefused",
    "Routes",
    "Scalar",
    "SchemaStep",
    "Selection",
    "Severity",
    "Source",
    "UnknownDestination",
    "metadata",
    "new_event_id",
    "park_destination",
    "resume_destination",
    "severity_rank",
]
