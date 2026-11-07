"""The ``[Delivery]`` section, identical in shape on the seller and buyer sides.

    [Delivery]
    enabled = ["west-hook", "east-hook", "audit"]
    timeout_seconds = 10.0

    [Delivery.west-hook]
    sink = "webhook"
    url = "https://west.example/hook"

    [Delivery.east-hook]
    sink = "webhook"
    url = "https://east.example/hook"

    [Delivery.audit]
    sink = "file"
    path = "/var/log/introductions.jsonl"

    [Delivery.origins]
    dc-west = ["west-hook", "audit"]
    dc-east = ["east-hook", "audit"]

``enabled`` names sink instances. An instance's table may name the installed
sink it instantiates with ``sink``; a table naming none instantiates the sink
of its own name, which is how ``[Delivery.file]`` has always read. Instance
tables sit directly under the section rather than under a nested key, and the
loader separates the section's own settings from instance tables by name.

``origins`` routes the seller's deliveries by the origin of the listing a deal
was negotiated against. A storefront publishing for several sellers must route:
broadcasting every reveal to every destination would hand one seller's buyers'
contact details to another. The buyer has no origin and may not route.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .sinks import DEFAULT_TIMEOUT_SECONDS, DeliveryConfigurationError

#: Keys of the section itself; no instance may be named after one.
RESERVED_SECTION_KEYS = frozenset({"enabled", "timeout_seconds", "origins"})

#: The instance-table key naming which installed sink the instance instantiates.
SINK_KEY = "sink"

DeliveryRole = Literal["buyer", "seller"]


class DeliveryConfig(BaseModel):
    """One side's complete delivery configuration."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    enabled: tuple[str, ...] = ()
    timeout_seconds: float = Field(default=DEFAULT_TIMEOUT_SECONDS, gt=0)
    settings: dict[str, dict[str, Any]] = Field(default_factory=dict)
    origins: dict[str, tuple[str, ...]] | None = None

    @property
    def active(self) -> bool:
        return bool(self.enabled)

    def sink_for(self, instance: str) -> str:
        """The installed sink ``instance`` instantiates."""

        return str(self.settings.get(instance, {}).get(SINK_KEY, instance))

    def settings_for(self, instance: str) -> dict[str, Any]:
        """The instance's own settings, without the key naming its sink."""

        settings = dict(self.settings.get(instance, {}))
        settings.pop(SINK_KEY, None)
        return settings


def _names(value: Any, *, what: str) -> tuple[str, ...]:
    if isinstance(value, str):
        value = [value]
    try:
        names = tuple(str(name) for name in value)
    except TypeError as exc:
        raise DeliveryConfigurationError(f"[Delivery] {what} must be a list of instance names") from exc
    duplicates = sorted({name for name in names if names.count(name) > 1})
    if duplicates:
        raise DeliveryConfigurationError(
            f"[Delivery] {what} names the same instance twice: {', '.join(duplicates)}"
        )
    return names


def load_delivery_config(
    section: Mapping[str, Any] | None,
    *,
    role: DeliveryRole = "buyer",
) -> DeliveryConfig:
    """Read one ``[Delivery]`` section; absent or empty means no delivery."""

    if not section:
        return DeliveryConfig()
    raw = dict(section)
    enabled = _names(raw.pop("enabled", ()), what="enabled")
    timeout = raw.pop("timeout_seconds", DEFAULT_TIMEOUT_SECONDS)
    origins_raw = raw.pop("origins", None)
    for key in tuple(raw):
        if not isinstance(raw[key], Mapping):
            raise DeliveryConfigurationError(
                f"[Delivery] has an unknown setting {key!r}; instance settings "
                "belong in their own [Delivery.<instance>] table"
            )
    reserved = sorted(set(enabled) & RESERVED_SECTION_KEYS)
    if reserved:
        raise DeliveryConfigurationError(
            f"[Delivery] instances may not be named after section settings: {', '.join(reserved)}"
        )
    unknown_settings = sorted(set(raw) - set(enabled))
    if unknown_settings:
        # Settings for an instance nobody enabled are almost always a typo in
        # `enabled`, and staying silent means the operator discovers it at the
        # one moment delivery was supposed to happen.
        raise DeliveryConfigurationError(
            "[Delivery] configures instances that are not enabled: "
            + ", ".join(unknown_settings)
        )
    origins: dict[str, tuple[str, ...]] | None = None
    if origins_raw is not None:
        if role != "seller":
            raise DeliveryConfigurationError(
                "[Delivery.origins] routes a storefront's deliveries by listing "
                "origin; a buyer has no origin to route by"
            )
        if not isinstance(origins_raw, Mapping):
            raise DeliveryConfigurationError(
                "[Delivery.origins] must map each origin to a list of instance names"
            )
        origins = {
            str(origin): _names(names, what=f"origins.{origin}")
            for origin, names in origins_raw.items()
        }
        routed = {name for names in origins.values() for name in names}
        not_enabled = sorted(routed - set(enabled))
        if not_enabled:
            raise DeliveryConfigurationError(
                "[Delivery.origins] routes instances that are not enabled: "
                + ", ".join(not_enabled)
            )
        unrouted = sorted(set(enabled) - routed)
        if unrouted:
            raise DeliveryConfigurationError(
                "[Delivery.origins] routes no origin to enabled instances: "
                + ", ".join(unrouted)
            )
    return DeliveryConfig(
        enabled=enabled,
        timeout_seconds=float(timeout),
        settings={name: dict(value) for name, value in raw.items()},
        origins=origins,
    )


def validate_delivery_origins(
    config: DeliveryConfig,
    known_origins: Collection[str],
) -> None:
    """Refuse seller-side routing that does not fit the storefront's origins.

    With more than one origin, enabled instances require a routing table,
    whatever kind of event they would carry: broadcasting to every destination
    is the cross-seller disclosure routing exists to prevent.
    """

    known = set(known_origins)
    if config.origins is None:
        if config.active and len(known) > 1:
            raise DeliveryConfigurationError(
                "this storefront publishes for several origins, so [Delivery] "
                "needs a [Delivery.origins] table routing each origin's "
                f"deliveries: {', '.join(sorted(known))}"
            )
        return
    unknown = sorted(set(config.origins) - known)
    if unknown:
        raise DeliveryConfigurationError(
            "[Delivery.origins] names origins this storefront is not configured with: "
            + ", ".join(unknown)
        )


__all__ = [
    "RESERVED_SECTION_KEYS",
    "SINK_KEY",
    "DeliveryConfig",
    "DeliveryRole",
    "load_delivery_config",
    "validate_delivery_origins",
]
