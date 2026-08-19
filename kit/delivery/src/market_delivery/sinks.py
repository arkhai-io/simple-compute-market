"""The sink contract: what an installed delivery backend implements.

A sink is a plain synchronous callable. Blocking is expected -- writing a file,
running a program, opening a socket -- and the dispatcher, not the sink, owns
running it off the caller's critical path and bounding how long it may take.
That keeps a third-party sink to a few lines and keeps every timeout policy in
one place.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from .events import DeliveryEvent

#: Installed sinks are discovered here, the same way buyer domains are.
SINK_ENTRY_POINT_GROUP = "market.delivery_sinks"

DEFAULT_TIMEOUT_SECONDS = 10.0


class DeliveryError(RuntimeError):
    """A sink failure whose message the sink has made safe to report.

    A sink raises this when it can describe its own failure without echoing
    the contact payload or its own credentials. Anything else that escapes a
    sink is reported by exception class alone, since an arbitrary message may
    quote what it was handed.
    """


class DeliveryConfigurationError(ValueError):
    """Configuration that cannot produce a working sink set."""


@runtime_checkable
class DeliverySink(Protocol):
    """Deliver one event, or raise."""

    def __call__(self, event: DeliveryEvent) -> None: ...


class SinkFactory(Protocol):
    """Validate one sink's settings and return the sink it configures."""

    def __call__(self, settings: Mapping[str, Any]) -> DeliverySink: ...


class SinkSettings(BaseModel):
    """Base for a sink's own strict settings.

    Strict and closed: a misspelled key is a startup failure rather than a
    setting that silently does nothing on the one day delivery matters.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    timeout_seconds: float | None = Field(default=None, gt=0)


@dataclass(frozen=True, slots=True)
class ConfiguredSink:
    """One named, constructed sink and the bound it runs under."""

    name: str
    sink: DeliverySink
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS


__all__ = [
    "DEFAULT_TIMEOUT_SECONDS",
    "SINK_ENTRY_POINT_GROUP",
    "ConfiguredSink",
    "DeliveryConfigurationError",
    "DeliveryError",
    "DeliverySink",
    "SinkFactory",
    "SinkSettings",
]
