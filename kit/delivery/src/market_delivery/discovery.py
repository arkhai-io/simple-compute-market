"""Sink discovery and construction.

Mirrors buyer domain-plugin discovery with the opposite failure posture: a
domain that fails to load is a broken market and raises, while a sink that
fails to load is a lost convenience -- it is reported, skipped, and survived.
What does raise is the operator's own mistake: a name nobody installed, or
settings a sink rejects. Those surface when the set is built, at process or
command start, rather than at the one moment an introduction is revealed.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from importlib.metadata import EntryPoint, entry_points
from typing import Any

from .config import DeliveryConfig
from .sinks import (
    SINK_ENTRY_POINT_GROUP,
    ConfiguredSink,
    DeliveryConfigurationError,
)


@dataclass(frozen=True, slots=True)
class DeliverySinkSet:
    """The constructed sinks plus what the operator should be told about.

    Warnings are returned rather than logged so each side reports them the way
    its operator reads things -- a CLI on its diagnostic stream, a service in
    its log -- without this package choosing a logging posture for both.
    """

    sinks: tuple[ConfiguredSink, ...] = ()
    warnings: tuple[str, ...] = ()

    def __bool__(self) -> bool:
        return bool(self.sinks)


def _iter_entry_points() -> Iterable[EntryPoint]:
    return entry_points(group=SINK_ENTRY_POINT_GROUP)


def discover_sink_factories() -> tuple[dict[str, Any], tuple[str, ...]]:
    """Load every installed sink factory, surviving broken distributions."""

    factories: dict[str, Any] = {}
    warnings: list[str] = []
    for entry_point in _iter_entry_points():
        try:
            factories[entry_point.name] = entry_point.load()
        except Exception as exc:  # noqa: BLE001 - identify broken distributions
            warnings.append(
                f"delivery sink {entry_point.name!r} failed to load "
                f"({type(exc).__name__}); it is skipped"
            )
    return factories, tuple(warnings)


def build_delivery_sinks(
    config: DeliveryConfig,
    *,
    factories: Mapping[str, Any] | None = None,
) -> DeliverySinkSet:
    """Construct the configured sink set, or fail naming the sink at fault."""

    if not config.active:
        return DeliverySinkSet()
    warnings: tuple[str, ...] = ()
    if factories is None:
        factories, warnings = discover_sink_factories()
    built: list[ConfiguredSink] = []
    surviving_warnings = list(warnings)
    for name in config.enabled:
        factory = factories.get(name)
        if factory is None:
            installed = ", ".join(sorted(factories)) or "none"
            raise DeliveryConfigurationError(
                f"delivery sink {name!r} is enabled but not installed "
                f"(installed sinks: {installed})"
            )
        settings = config.settings_for(name)
        try:
            sink = factory(settings)
        except DeliveryConfigurationError:
            raise
        except Exception as exc:  # noqa: BLE001 - the operator owns this input
            raise DeliveryConfigurationError(
                f"delivery sink {name!r} rejected its settings: {exc}"
            ) from exc
        timeout = settings.get("timeout_seconds") or config.timeout_seconds
        built.append(
            ConfiguredSink(name=name, sink=sink, timeout_seconds=float(timeout))
        )
    return DeliverySinkSet(sinks=tuple(built), warnings=tuple(surviving_warnings))


__all__ = [
    "DeliverySinkSet",
    "build_delivery_sinks",
    "discover_sink_factories",
]
