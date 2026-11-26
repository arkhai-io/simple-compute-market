"""The event-sink consumer: a service's events delivered to the sinks its routes select.

One consumer of the service's eventing system, with one destination per enabled
sink instance. Each event goes to the sinks the deployment's routes select for
it, at least once each, under its own identity; each sink's outcome is that
destination's delivery state. A sink failing an event is retried with backoff,
until the delivery's age passes the consumer's maximum, when the delivery is
abandoned and the event handed to the finally sink: the log, or a sink instance
named for it. Introduction delivery, which claims at most once, does not pass
through here.

A sink is handed an ``EventDeliverable``: the event's summary as its rendering,
its envelope as its payload, and its subject (``<type>:<id>``) as its
reference. A sink that reads anything else of a delivery event, such as its
``obligation_ref``, fails the delivery, reported by its exception's class.

This module needs the distribution's ``events`` extra, which installs the
eventing component.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable, Sequence
from datetime import datetime, timedelta
from typing import Any

from eventing import (
    Catalogue,
    Consumer,
    Envelope,
    FinallySink,
    LogFinallySink,
    RetryPolicy,
    Route,
    Routes,
)
from eventing.consumers import DEFAULT_HOLD
from sqlalchemy.orm import Session, sessionmaker

from .dispatch import deliver_one
from .sinks import ConfiguredSink, DeliveryConfigurationError, DeliveryError

#: The consumer's name in the service's event store.
EVENT_SINK_CONSUMER = "event-sinks"

#: The finally sink that writes an abandoned event to the log.
LOG_FINALLY_SINK = "log"


class EventDeliverable:
    """An event as a sink delivers it."""

    def __init__(self, envelope: Envelope) -> None:
        self._envelope = envelope

    @property
    def rendered(self) -> str:
        return self._envelope.summary

    @property
    def reference(self) -> str:
        return str(self._envelope.subject)

    def payload(self) -> dict[str, Any]:
        return self._envelope.model_dump(mode="json")


class SinkDestination:
    """One configured sink as a destination of the consumer."""

    def __init__(self, configured: ConfiguredSink) -> None:
        self._configured = configured

    def deliver(self, envelope: Envelope) -> None:
        failure = deliver_one(self._configured, EventDeliverable(envelope))
        if failure is not None:
            raise DeliveryError(failure)


class SinkFinallySink:
    """A finally sink delivering each abandoned event to one sink instance.

    A failure raises, so the abandonment is not applied and is tried again on a
    later cycle, as the consumer treats any finally sink that fails.
    """

    def __init__(self, configured: ConfiguredSink) -> None:
        self._configured = configured

    def abandoned(
        self, *, consumer: str, destination: str, envelope: Envelope, last_error: str | None
    ) -> None:
        failure = deliver_one(self._configured, EventDeliverable(envelope))
        if failure is not None:
            raise DeliveryError(failure)


def build_event_sink_consumer(
    *,
    session_factory: sessionmaker[Session],
    sinks: Sequence[ConfiguredSink],
    routes: Iterable[Route],
    catalogue: Catalogue,
    clock: Callable[[], datetime],
    max_age: timedelta | None,
    finally_sink: str = LOG_FINALLY_SINK,
    runner: str | None = None,
    hold: timedelta = DEFAULT_HOLD,
    logger: logging.Logger | None = None,
) -> Consumer:
    """The event-sink consumer over the service's event store.

    Refuses, as ``eventing.RouteRefused``, a route the eventing component
    refuses — an unparseable or disallowed condition, a column no declared kind
    has, a sink not enabled — and, as ``DeliveryConfigurationError``, a finally
    sink that is neither the log nor an enabled sink instance. ``runner`` names
    the process holding the consumer, stable across its restarts.
    """

    destinations = {configured.name: SinkDestination(configured) for configured in sinks}
    selection = Routes(routes, catalogue, enabled=tuple(destinations))
    final: FinallySink
    if finally_sink == LOG_FINALLY_SINK:
        final = LogFinallySink(logger)
    else:
        named = {configured.name: configured for configured in sinks}
        if finally_sink not in named:
            raise DeliveryConfigurationError(
                f"the finally sink {finally_sink!r} is neither {LOG_FINALLY_SINK!r} nor "
                f"an enabled sink instance ({', '.join(sorted(named)) or 'none enabled'})"
            )
        final = SinkFinallySink(named[finally_sink])
    return Consumer(
        EVENT_SINK_CONSUMER,
        session_factory=session_factory,
        destinations=destinations,
        clock=clock,
        retry=RetryPolicy(max_age=max_age),
        select=selection.select,
        finally_sink=final,
        runner=runner,
        hold=hold,
    )


__all__ = [
    "EVENT_SINK_CONSUMER",
    "LOG_FINALLY_SINK",
    "EventDeliverable",
    "SinkDestination",
    "SinkFinallySink",
    "build_event_sink_consumer",
]
