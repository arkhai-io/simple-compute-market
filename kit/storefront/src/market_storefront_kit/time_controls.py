"""A storefront's time: its configured source, its time route, and its announcement.

Each storefront reads ``[Time] source``, ``"wall"`` by default or ``"injected"``,
and installs that source for its process at its composition root, before anything
reads the time; any other value refuses startup, naming the setting and the value.
The source is configuration: a storefront mounts its time-setting route,
``POST /api/v1/admin/time``, only while its source is injected, so a wall-time
storefront offers no way to change its time, and switching source means
reconfiguring and restarting it.

:class:`StorefrontTimeRouteService` answers that route and the time section of
every storefront's signed system status; each storefront binds it behind its own
administrator authentication, as it binds the trading pause, so the path, the
signed operation and the answers are the same for every storefront and one typed
client drives them all. A refused setting changes nothing: a body other than
``{"now": <Unix seconds>}`` is 422 ``invalid_time`` and an earlier instant 409
``time_moves_forward``.

A storefront whose time is injected says so when it starts, and warns when an
Arkhai payments section beside it declares ``livemode = true``: injected time is
for a lane or a copy of a deployment, never a deployment taking live payments.
Nothing refuses it, since no storefront can recognise production.
"""

from __future__ import annotations

import logging
from typing import Annotated, Any, Literal

import injected_time
from injected_time import TimeRouteError, TimeSource
from pydantic import BeforeValidator

#: The setting a storefront's time source is read from, as a refusal names it.
TIME_SOURCE_SETTING = "[Time] source"


def _known_time_source(value: Any) -> Any:
    try:
        injected_time.source_for(value, setting=TIME_SOURCE_SETTING)
    except injected_time.InvalidTimeSource as error:
        raise ValueError(str(error)) from None
    return value


#: ``[Time] source`` in a typed configuration model: ``"wall"`` or
#: ``"injected"``, any other value refused naming the setting and the value.
TimeSourceSetting = Annotated[
    Literal["wall", "injected"], BeforeValidator(_known_time_source)
]


def configured_time_source(settings: Any) -> Any:
    """The value ``[Time] source`` states in a storefront's settings, or ``None``.

    ``settings`` is the loader's merged settings, read through its ``get``;
    the section's keys are read in any case, as every storefront reads its
    configuration. The value is returned as stated, for
    :func:`install_time_source` to judge.
    """
    section = settings.get("time")
    if not hasattr(section, "items"):
        return section
    return {str(key).lower(): item for key, item in section.items()}.get("source")


def install_time_source(value: object | None) -> TimeSource:
    """Install the process source ``[Time] source`` names, ``"wall"`` when unset.

    Raises ``injected_time.InvalidTimeSource``, naming the setting and the
    value, for anything but ``"wall"`` or ``"injected"``. An injected source
    starts frozen at the wall instant it is installed.
    """
    source = injected_time.source_for(
        injected_time.WALL if value is None else value, setting=TIME_SOURCE_SETTING
    )
    injected_time.install(source)
    return source


def announce_time_source(
    source: TimeSource, *, payments_livemode: bool, logger: logging.Logger
) -> None:
    """Log an injected source at startup, warning beside live payments.

    A wall-time storefront logs nothing here.
    """
    if source.name != injected_time.INJECTED:
        return
    logger.info(
        "[STARTUP] %s is \"injected\": time is held at %s until set through "
        "POST /api/v1/admin/time",
        TIME_SOURCE_SETTING,
        source.now(),
    )
    if payments_livemode:
        logger.warning(
            "%s is \"injected\" while [Settlement.arkhai_payments] livemode is "
            "true: this storefront's time is set by its administrator, not the "
            "wall clock, beside a payments section accepting live receipts",
            TIME_SOURCE_SETTING,
        )


class StorefrontTimeRouteService:
    """A storefront's time-setting route and its status's time section.

    Reads the process's installed source when built, so a route service built
    per request answers for the source the process runs on.
    """

    def __init__(self, source: TimeSource | None = None) -> None:
        self._routes = injected_time.TimeRouteService(
            injected_time.installed() if source is None else source
        )

    @property
    def mounted(self) -> bool:
        """Whether the time-setting route is mounted: the source is injected."""
        return self._routes.settable

    def status(self) -> dict[str, Any]:
        """``{"source": "injected", "now": <instant>}``, or ``{"source": "wall"}``."""
        return self._routes.status()

    def set_time(self, body: str | bytes | bytearray) -> dict[str, Any]:
        """Set the injected source to the instant ``body`` carries, and answer it.

        Raises :class:`injected_time.TimeRouteError` carrying the refusal's
        status, code and detail; nothing changes then.
        """
        return self._routes.set_time(body)


def time_refusal_body(error: TimeRouteError) -> dict[str, str]:
    """The body a refused setting is answered with: its code and its detail."""
    return {"code": error.code, "detail": error.detail}


__all__ = [
    "TIME_SOURCE_SETTING",
    "StorefrontTimeRouteService",
    "TimeRouteError",
    "TimeSourceSetting",
    "announce_time_source",
    "configured_time_source",
    "install_time_source",
    "time_refusal_body",
]
