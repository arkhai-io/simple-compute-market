"""Secret-free bare-metal buyer configuration and trusted client composition."""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any

from core_buyer import (
    ResolvedBuyerIdentity,
    resolve_fresh_buyer_identity,
    resolve_recovery_buyer_identity,
)
from market_identity import Identity, TrustedIdentitySet
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from registry_client import SyncRegistryClient

_CONFIG_ENV = "BARE_METAL_BUYER_CONFIG"


class BareMetalBuyerConfig(BaseModel):
    """Public endpoints, trust pins, and bounded buyer defaults."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    registry_url: str = Field(min_length=1)
    registry_authority: str = Field(min_length=1)
    registry_principals: tuple[Identity, ...] = Field(min_length=1, max_length=2)
    default_duration_seconds: int = Field(default=3600, gt=0)
    default_max_rounds: int = Field(default=10, ge=1, le=100)
    timeout_seconds: float = Field(default=30.0, gt=0.0, le=600.0)

    @field_validator("registry_url")
    @classmethod
    def registry_url_has_http_scheme(cls, value: str) -> str:
        normalized = value.rstrip("/")
        if not normalized.startswith(("http://", "https://")):
            raise ValueError("registry_url must use http or https")
        return normalized

    @model_validator(mode="after")
    def trust_is_unique(self) -> BareMetalBuyerConfig:
        if len(set(self.registry_principals)) != len(self.registry_principals):
            raise ValueError("registry_principals must be unique")
        return self

    @property
    def registry_trust(self) -> TrustedIdentitySet:
        return TrustedIdentitySet(identities=self.registry_principals)


def load_bare_metal_buyer_config(
    path: str | Path | None = None,
) -> BareMetalBuyerConfig:
    """Load one strict TOML file selected explicitly or by environment."""

    raw_path = str(path) if path is not None else os.environ.get(_CONFIG_ENV, "")
    if not raw_path.strip():
        raise ValueError(f"bare-metal buyer config is required via {_CONFIG_ENV}")
    selected = Path(raw_path)
    try:
        payload: dict[str, Any] = tomllib.loads(selected.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ValueError(
            f"cannot load bare-metal buyer config {selected}: {exc}"
        ) from exc
    section = payload.get("bare_metal")
    if not isinstance(section, dict):
        raise ValueError("bare-metal buyer config requires [bare_metal]")
    section = dict(section)
    principals = section.get("registry_principals")
    if isinstance(principals, list):
        section["registry_principals"] = tuple(principals)
    return BareMetalBuyerConfig.model_validate(section)


def fresh_identity() -> ResolvedBuyerIdentity:
    """Resolve the active profile signer for new buyer work."""

    return resolve_fresh_buyer_identity()


def recovery_identity(run_id: str) -> ResolvedBuyerIdentity:
    """Resolve the exact retained signer recorded for one run."""

    return resolve_recovery_buyer_identity(run_id)


def registry_client(
    config: BareMetalBuyerConfig,
    identity: ResolvedBuyerIdentity,
) -> SyncRegistryClient:
    """Create a signed registry client without accepting secrets in domain config."""

    return SyncRegistryClient(
        config.registry_url,
        timeout=config.timeout_seconds,
        signer=identity.signer,
        caller_role="buyer",
        expected_registries=config.registry_trust,
        registry_authority=config.registry_authority,
    )
