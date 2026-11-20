"""The gateway's settings: the listing it fronts, the model server behind it, its gate, and its time source."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import injected_time
from arkhai_api_gate import GateConfig

PREFIX = "INFERENCE_GATEWAY_"
AUTHORITY_LABEL = "inference-service"
TIME_SOURCE_SETTING = PREFIX + "TIME_SOURCE"
CONTROL_TOKEN_SETTING = PREFIX + "CONTROL_TOKEN"

_REQUIRED = ("STOREFRONT_URL", "RESOURCE_ID", "SERVED_MODEL_NAME", "UPSTREAM_BASE_URL")


@dataclass(frozen=True, kw_only=True)
class GatewaySettings:
    """Which listing the gateway fronts and where its model server is.

    The listing is the storefront's one open listing whose card names
    ``resource_id`` and ``served_model_name``; ``listing_id`` names it directly
    instead, and must still name both.

    ``time_source`` is the time of the world the process reads and the gate
    signs by: ``"wall"`` unless set ``"injected"``, under which the gateway
    serves a time control behind the bearer token ``control_token``.
    """

    storefront_url: str
    resource_id: str
    served_model_name: str
    upstream_base_url: str
    listing_id: str | None = None
    registry_url: str | None = None
    upstream_credential_file: Path | None = None
    listing_retry_seconds: float = 5.0
    time_source: str = injected_time.WALL
    control_token: str | None = None

    @classmethod
    def from_env(cls, environ: Mapping[str, str] = os.environ) -> GatewaySettings:
        def get(name: str) -> str:
            return environ.get(PREFIX + name, "").strip()

        missing = [PREFIX + name for name in _REQUIRED if not get(name)]
        if missing:
            raise ValueError("the gateway needs " + ", ".join(missing))
        credential = get("UPSTREAM_CREDENTIAL_FILE")
        retry = get("LISTING_RETRY_SECONDS")
        return cls(
            storefront_url=get("STOREFRONT_URL").rstrip("/"),
            resource_id=get("RESOURCE_ID"),
            served_model_name=get("SERVED_MODEL_NAME"),
            upstream_base_url=get("UPSTREAM_BASE_URL"),
            listing_id=get("LISTING_ID") or None,
            registry_url=get("REGISTRY_URL") or None,
            upstream_credential_file=Path(credential) if credential else None,
            listing_retry_seconds=float(retry) if retry else 5.0,
            time_source=get("TIME_SOURCE") or injected_time.WALL,
            control_token=get("CONTROL_TOKEN") or None,
        )


def gate_config() -> GateConfig:
    """The gate's settings under the gateway's prefix; the offering supplies its scope and charge."""
    return GateConfig.from_env(PREFIX, authority_label=AUTHORITY_LABEL)
