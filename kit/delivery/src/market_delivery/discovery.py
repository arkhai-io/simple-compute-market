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

from market_identity import Signer

from .config import DeliveryConfig
from .sinks import (
    SINK_ENTRY_POINT_GROUP,
    ConfiguredSink,
    DeclaredSink,
    DeliveryConfigurationError,
    SinkSettings,
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


def discover_sink_settings_models() -> tuple[dict[str, type[SinkSettings]], tuple[str, ...]]:
    """The declared settings model of every installed sink that declares one.

    A sink whose entry point names a plain factory declares nothing and is
    absent here; it still installs and delivers. A deployment schema types
    exactly the sinks returned and leaves every other instance open.
    """

    factories, warnings = discover_sink_factories()
    models = {
        name: factory.settings_model
        for name, factory in factories.items()
        if isinstance(factory, DeclaredSink)
    }
    return models, warnings


def build_delivery_sinks(
    config: DeliveryConfig,
    *,
    factories: Mapping[str, Any] | None = None,
    signer: Signer | None = None,
) -> DeliverySinkSet:
    """Construct the configured instances, or fail naming the instance at fault.

    ``signer`` is the process's marketplace signer, handed to an instance that
    asks to sign rather than carried in its settings: signing material never
    travels through configuration.
    """

    if not config.active:
        return DeliverySinkSet()
    warnings: tuple[str, ...] = ()
    if factories is None:
        factories, warnings = discover_sink_factories()
    built: list[ConfiguredSink] = []
    surviving_warnings = list(warnings)
    for name in config.enabled:
        sink_name = config.sink_for(name)
        if name in factories and sink_name != name:
            # A table named for one sink that instantiates another would make
            # the configuration say one thing and deliver through another.
            raise DeliveryConfigurationError(
                f"delivery instance {name!r} is named for the {name!r} sink but "
                f"states sink {sink_name!r}; name the instance differently"
            )
        factory = factories.get(sink_name)
        if factory is None:
            installed = ", ".join(sorted(factories)) or "none"
            raise DeliveryConfigurationError(
                f"delivery instance {name!r} uses sink {sink_name!r}, which is not "
                f"installed (installed sinks: {installed})"
            )
        settings = config.settings_for(name)
        signs = bool(settings.get("sign"))
        if signs and signer is None:
            raise DeliveryConfigurationError(
                f"delivery instance {name!r} asks to sign, and this process has no "
                "marketplace signer to sign with"
            )
        try:
            sink = factory(settings, signer=signer) if signs else factory(settings)
        except DeliveryConfigurationError:
            raise
        except Exception as exc:  # noqa: BLE001 - the operator owns this input
            raise DeliveryConfigurationError(
                f"delivery instance {name!r} rejected its settings: {exc}"
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
    "discover_sink_settings_models",
]
