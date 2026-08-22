"""The ``[Delivery]`` section, identical on the seller and buyer sides.

    [Delivery]
    enabled = ["file", "webhook"]
    timeout_seconds = 10.0

    [Delivery.file]
    path = "~/introductions.jsonl"

    [Delivery.webhook]
    url = "https://example.invalid/hook"

Per-sink tables sit directly under the section rather than under a nested
``sinks`` key: an operator writes ``[Delivery.file]``, which is what TOML makes
natural, and the loader separates the section's own scalars from the sink
tables by shape.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .sinks import DEFAULT_TIMEOUT_SECONDS, DeliveryConfigurationError

_SECTION_KEYS = {"enabled", "timeout_seconds"}


class DeliveryConfig(BaseModel):
    """One side's complete delivery configuration."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    enabled: tuple[str, ...] = ()
    timeout_seconds: float = Field(default=DEFAULT_TIMEOUT_SECONDS, gt=0)
    settings: dict[str, dict[str, Any]] = Field(default_factory=dict)

    @property
    def active(self) -> bool:
        return bool(self.enabled)

    def settings_for(self, name: str) -> dict[str, Any]:
        return dict(self.settings.get(name, {}))


def load_delivery_config(section: Mapping[str, Any] | None) -> DeliveryConfig:
    """Read one ``[Delivery]`` section; absent or empty means no delivery."""

    if not section:
        return DeliveryConfig()
    raw = dict(section)
    enabled_raw = raw.pop("enabled", ())
    timeout = raw.pop("timeout_seconds", DEFAULT_TIMEOUT_SECONDS)
    for key in tuple(raw):
        if not isinstance(raw[key], Mapping):
            raise DeliveryConfigurationError(
                f"[Delivery] has an unknown setting {key!r}; per-sink settings "
                "belong in their own [Delivery.<sink>] table"
            )
    if isinstance(enabled_raw, str):
        enabled_raw = [enabled_raw]
    try:
        enabled = tuple(str(name) for name in enabled_raw)
    except TypeError as exc:
        raise DeliveryConfigurationError(
            "[Delivery] enabled must be a list of sink names"
        ) from exc
    duplicates = sorted({name for name in enabled if enabled.count(name) > 1})
    if duplicates:
        raise DeliveryConfigurationError(
            f"[Delivery] enables the same sink twice: {', '.join(duplicates)}"
        )
    unknown_settings = sorted(set(raw) - set(enabled) - _SECTION_KEYS)
    settings = {name: dict(value) for name, value in raw.items()}
    config = DeliveryConfig(
        enabled=enabled,
        timeout_seconds=float(timeout),
        settings=settings,
    )
    if unknown_settings:
        # Settings for a sink nobody enabled are almost always a typo in
        # `enabled`, and staying silent means the operator discovers it at the
        # one moment delivery was supposed to happen.
        raise DeliveryConfigurationError(
            "[Delivery] configures sinks that are not enabled: "
            + ", ".join(unknown_settings)
        )
    return config


__all__ = ["DeliveryConfig", "load_delivery_config"]
