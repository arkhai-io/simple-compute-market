"""The sink contract: what an installed delivery backend implements.

A sink is a plain synchronous callable over a ``Deliverable``: it reads only
``rendered``, ``payload()`` and ``reference``, so one installed sink serves a
revealed introduction and an operator event alike. Blocking is expected --
writing a file, running a program, opening a socket -- and the dispatcher, not
the sink, owns running it off the caller's critical path and bounding how long
it may take. That keeps a third-party sink to a few lines and keeps every
timeout policy in one place.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

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


class Deliverable(Protocol):
    """What a sink delivers: a rendering for a person, the structured form a sink
    transmits, and the reference naming what it is about."""

    @property
    def rendered(self) -> str: ...

    @property
    def reference(self) -> str: ...

    def payload(self) -> dict[str, Any]: ...


@dataclass(frozen=True, slots=True)
class SigningAs:
    """The role and operation a signing sink signs its requests as.

    A composition states them, so each service signs its deliveries as itself:
    a storefront's introductions as the seller, a provisioning service's events
    as that service.
    """

    role: str
    operation: str


@runtime_checkable
class DeliverySink(Protocol):
    """Deliver one deliverable, or raise."""

    def __call__(self, event: Deliverable) -> None: ...


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
class DeclaredSink:
    """An installed sink that declares the model of its settings beside its factory.

    A sink's entry point may name a plain factory or one of these. Declaring the
    model lets a deployment schema type the sink's settings -- and refuse its
    secret ones where configuration is public -- by discovery, so no storefront
    names a sink in code. A sink declaring nothing still installs and works;
    its settings are simply unknown outside it.
    """

    build: Any
    settings_model: type[SinkSettings]

    def __call__(self, settings: Mapping[str, Any], **kwargs: Any) -> DeliverySink:
        return self.build(settings, **kwargs)


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
    "DeclaredSink",
    "Deliverable",
    "DeliveryConfigurationError",
    "DeliveryError",
    "DeliverySink",
    "SinkFactory",
    "SigningAs",
    "SinkSettings",
]
