"""The provisioning service's eventing system: its kinds, its `[Events]`
configuration, and the worker delivering and pruning its events.

The service records the site's kinds and compute provisioning's in its own
database, in the transactions of the changes they report, through one recorder
the site ledger, the job engine and the lease lifecycle share;
``site.lease_ended`` signs and keeps its lease end's report as it is recorded.
Three consumers deliver them: the event-sink consumer, what the deployment's
routes select to the sinks ``[Events.sinks]`` enables, and the storefront
peer's two, the lease-end reports and the capacity-released callbacks.
``EventDeliveryWorker`` runs them, then prunes, on its own timer, with a pause
and a manual cycle that runs the same production cycle. A route or sink the
eventing component refuses refuses the service's start.
"""

from __future__ import annotations

import asyncio
import dataclasses
import logging
import threading
from collections.abc import Mapping, Sequence
from datetime import timedelta
from typing import Any

import injected_time
from compute_provisioning.operator_events import PROVISIONING_KINDS
from eventing import Catalogue, Consumer, Pruner, Recorder, Retention, Route, Source
from market_delivery import SigningAs, build_delivery_sinks, load_delivery_config
from market_delivery.event_sinks import LOG_FINALLY_SINK, build_event_sink_consumer
from market_identity import Signer
from market_site.events import SITE_KINDS, SITE_LEASE_ENDED
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session, sessionmaker

from compute_provisioning_service.event_names import EVENT_SCHEMA_PREFIX, EVENT_SOURCE_SERVICE
from compute_provisioning_service.services.lease_end_reports import lease_end_report_hook

logger = logging.getLogger(__name__)

#: What a signing sink signs an event delivery as: this service, delivering an
#: operator event.
EVENT_DELIVERY_SIGNING = SigningAs(role="service", operation="operator_event_delivery")


class EventRetentionDays(BaseModel):
    """Days each table's rows are kept; 0 keeps every row."""

    model_config = ConfigDict(extra="forbid")

    events: int = Field(default=30, ge=0)
    deliveries: int = Field(default=30, ge=0)
    lease_end_reports: int = Field(default=0, ge=0)


class EventRouteSettings(BaseModel):
    """One ``[Events.routes.<name>]``: a condition and the sinks it selects."""

    model_config = ConfigDict(extra="forbid")

    where: str = Field(min_length=1)
    sinks: list[str] = Field(min_length=1)


class EventsSettings(BaseModel):
    """The ``[Events]`` section."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    retention_days: EventRetentionDays = Field(default_factory=EventRetentionDays)
    delivery_interval_seconds: float = Field(default=10, gt=0)
    sink_max_age_seconds: float = Field(default=86400, gt=0)
    finally_sink: str = Field(default=LOG_FINALLY_SINK, alias="finally", min_length=1)
    sinks: dict[str, Any] = Field(default_factory=dict)
    routes: dict[str, EventRouteSettings] = Field(default_factory=dict)


def _plain(value: Any) -> Any:
    """A configuration value as plain dicts and lists, whatever loader built it."""
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


def events_settings(cfg: Any) -> EventsSettings:
    """The ``[Events]`` section the configuration states, defaults for the rest."""
    raw = cfg.get("Events") if hasattr(cfg, "get") else getattr(cfg, "Events", None)
    return EventsSettings.model_validate(_plain(raw or {}))


def event_catalogue(signer: Signer) -> Catalogue:
    """Every kind this service records: the site's and compute provisioning's,
    ``site.lease_ended`` signing and keeping its lease end's report with the
    service's signer as it is recorded."""
    site_kinds = tuple(
        dataclasses.replace(kind, hook=lease_end_report_hook(signer))
        if kind.name == SITE_LEASE_ENDED.name
        else kind
        for kind in SITE_KINDS
    )
    return Catalogue((*site_kinds, *PROVISIONING_KINDS), schema_prefix=EVENT_SCHEMA_PREFIX)


def event_recorder(catalogue: Catalogue, *, instance: str) -> Recorder:
    return Recorder(
        catalogue,
        source=Source(service=EVENT_SOURCE_SERVICE, instance=instance or "unnamed"),
        clock=injected_time.now_datetime,
    )


def event_runner(instance: str) -> str:
    """The name this process holds its consumers under, stable across its
    restarts, so a restarted service takes its own hold back at once. One
    process serves a site's database at a time."""
    return f"{EVENT_SOURCE_SERVICE}:{instance or 'unnamed'}"


def _days(value: int) -> timedelta | None:
    return None if value == 0 else timedelta(days=value)


def event_pruner(
    session_factory: sessionmaker[Session], catalogue: Catalogue, settings: EventsSettings
) -> Pruner:
    """The pruner over the configured retention. A table is retained by its own
    setting only once a declared kind's record-time hook writes it."""
    hooked = {
        table.name
        for kind in catalogue.kinds()
        if kind.hook is not None
        for table in kind.hook.tables
    }
    retention = settings.retention_days
    tables = {
        name: _days(days)
        for name, days in {"lease_end_reports": retention.lease_end_reports}.items()
        if name in hooked
    }
    return Pruner(
        catalogue,
        session_factory=session_factory,
        clock=injected_time.now_datetime,
        retention=Retention(
            events=_days(retention.events), deliveries=_days(retention.deliveries), tables=tables
        ),
    )


def event_sink_consumer(
    session_factory: sessionmaker[Session],
    catalogue: Catalogue,
    settings: EventsSettings,
    *,
    signer: Signer | None,
    instance: str,
) -> Consumer:
    """The event-sink consumer over ``[Events.sinks]`` and ``[Events.routes]``.

    Raises, naming what is wrong, on a sink that cannot be built, a route the
    eventing component refuses, or a finally sink that names no enabled sink.
    """
    sink_set = build_delivery_sinks(
        load_delivery_config(settings.sinks),
        signer=signer,
        signing=EVENT_DELIVERY_SIGNING,
    )
    for warning in sink_set.warnings:
        logger.warning("[EVENTS] %s", warning)
    return build_event_sink_consumer(
        session_factory=session_factory,
        sinks=sink_set.sinks,
        routes=[
            Route(name=name, where=route.where, destinations=tuple(route.sinks))
            for name, route in settings.routes.items()
        ],
        catalogue=catalogue,
        clock=injected_time.now_datetime,
        max_age=timedelta(seconds=settings.sink_max_age_seconds),
        finally_sink=settings.finally_sink,
        runner=event_runner(instance),
    )


class EventDeliveryWorker:
    """Delivers the service's events through its consumers, then prunes.

    ``run_cycle`` is the one production cycle, whether the timer or an operator
    runs it: each consumer's cycle in turn, then pruning, off the event loop.
    ``deliver`` runs the named consumers' cycles alone, for a producer that has
    just recorded what they deliver. A consumer's cycles run one at a time, a
    later one waiting for the one running, so one that starts after an event
    committed always reads it: a consumer's own cycle does nothing while
    another of the same consumer runs, and a delivery asked for then would
    wait for the timer. Each consumer waits only for its own cycles, never for
    another consumer's deliveries or for pruning. The timer waits out its
    interval through an event a pause sets, so a pause is observed at once,
    and holds at its gate while paused; a pause holds the timer only, not a
    cycle asked for.
    """

    def __init__(
        self,
        consumers: Sequence[Consumer],
        pruner: Pruner,
        *,
        interval_seconds: float,
    ) -> None:
        self._consumers = tuple(consumers)
        self._pruner = pruner
        self._interval = interval_seconds
        self._resume = asyncio.Event()
        self._resume.set()
        self._pause_requested = asyncio.Event()
        self._timer_cycles_in_flight = 0
        self._cycles = {consumer.name: threading.Lock() for consumer in self._consumers}

    def pause(self) -> None:
        self._resume.clear()
        self._pause_requested.set()
        logger.info("[EVENT_DELIVERY] Paused: timer cycles hold at the gate")

    def resume(self) -> None:
        self._pause_requested.clear()
        self._resume.set()
        logger.info("[EVENT_DELIVERY] Resumed")

    @property
    def is_paused(self) -> bool:
        return not self._resume.is_set()

    @property
    def is_at_gate(self) -> bool:
        """Paused with no timer cycle running."""
        return self.is_paused and self._timer_cycles_in_flight == 0

    async def run_cycle(self) -> dict[str, Any]:
        return await asyncio.to_thread(self._cycle)

    async def deliver(self, *names: str) -> dict[str, Any]:
        """Run the cycles of the consumers ``names`` names now, off the event
        loop, and report each; pruning waits for the next full cycle."""
        return await asyncio.to_thread(self._deliver, names)

    def _cycle(self) -> dict[str, Any]:
        consumers = {consumer.name: self._run(consumer) for consumer in self._consumers}
        return {"consumers": consumers, "pruned": self._pruner.prune().removed}

    def _deliver(self, names: Sequence[str]) -> dict[str, Any]:
        unknown = sorted(set(names) - set(self._cycles))
        if unknown:
            raise LookupError(f"no consumer named {', '.join(unknown)}")
        return {
            consumer.name: self._run(consumer)
            for consumer in self._consumers
            if consumer.name in names
        }

    def _run(self, consumer: Consumer) -> dict[str, Any]:
        with self._cycles[consumer.name]:
            return dataclasses.asdict(consumer.run_cycle())

    async def run(self) -> None:
        """Run timer cycles until cancelled."""
        logger.info("[EVENT_DELIVERY] Started (interval=%gs)", self._interval)
        while True:
            try:
                try:
                    await asyncio.wait_for(self._pause_requested.wait(), timeout=self._interval)
                except TimeoutError:
                    pass
                while not self._resume.is_set():
                    await self._resume.wait()
                self._timer_cycles_in_flight += 1
                try:
                    await self.run_cycle()
                finally:
                    self._timer_cycles_in_flight -= 1
            except asyncio.CancelledError:
                logger.info("[EVENT_DELIVERY] Cancelled, shutting down")
                break
            except Exception as exc:
                logger.exception("[EVENT_DELIVERY] Unhandled error in cycle: %s", exc)


__all__ = [
    "EVENT_DELIVERY_SIGNING",
    "EVENT_SCHEMA_PREFIX",
    "EVENT_SOURCE_SERVICE",
    "EventDeliveryWorker",
    "EventRetentionDays",
    "EventRouteSettings",
    "EventsSettings",
    "event_catalogue",
    "event_pruner",
    "event_recorder",
    "event_runner",
    "event_sink_consumer",
    "events_settings",
]
