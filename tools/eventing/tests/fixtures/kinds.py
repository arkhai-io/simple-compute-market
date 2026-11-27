"""Kinds, a clock and a store the tests share."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from pydantic import BaseModel
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from eventing import SCHEMA_STEPS, Catalogue, EventDraft, Kind, Reference, Severity

START = datetime(2026, 11, 25, 17, 0, tzinfo=timezone.utc)


class Clock:
    """A clock a test sets and moves."""

    def __init__(self, start: datetime = START) -> None:
        self.instant = start

    def __call__(self) -> datetime:
        return self.instant

    def advance(self, by: timedelta) -> None:
        self.instant += by


class JobDetails(BaseModel):
    queue: str


class DelayDetails(BaseModel):
    reason: str
    attempt: int


def _job_summary(draft: EventDraft, details: JobDetails) -> str:
    return f"Job {draft.subject.id} finished on {details.queue}."


def _delay_summary(draft: EventDraft, details: DelayDetails) -> str:
    return f"Shipment {draft.subject.id} delayed: {details.reason} (attempt {details.attempt})."


JOB_FINISHED = Kind(
    name="jobs.finished",
    version=1,
    severity=Severity.INFO,
    details=JobDetails,
    summary=_job_summary,
    attributes={"duration_seconds": int, "status": str},
    dedup_key=("subject",),
)

SHIPMENT_DELAYED = Kind(
    name="orders.shipment_delayed",
    version=1,
    severity=Severity.ACTION_REQUIRED,
    details=DelayDetails,
    summary=_delay_summary,
    attributes={"carrier": str, "delay_minutes": int, "expedited": bool},
    dedup_key=("subject", "details.attempt"),
)

NOTE_ADDED = Kind(
    name="notes.added",
    version=1,
    severity=Severity.INFO,
    details=JobDetails,
    summary=_job_summary,
)


def catalogue() -> Catalogue:
    return Catalogue([JOB_FINISHED, SHIPMENT_DELAYED, NOTE_ADDED])


def job(job_id: str, *, duration: int = 40, status: str = "succeeded",
        related: tuple[Reference, ...] = ()) -> EventDraft:
    return JOB_FINISHED.draft(
        subject=Reference(type="job", id=job_id),
        details={"queue": "default"},
        attributes={"duration_seconds": duration, "status": status},
        related=related,
    )


@dataclass
class Store:
    engine: Engine
    sessions: sessionmaker[Session]


def open_store(path: Path) -> Iterator[Store]:
    """A SQLite file at `path` built by the schema steps, as a service's chain builds it."""
    engine = create_engine(f"sqlite:///{path}")
    with engine.begin() as connection:
        for step in SCHEMA_STEPS:
            step.apply(connection)
    try:
        yield Store(engine, sessionmaker(engine, expire_on_commit=False))
    finally:
        engine.dispose()
