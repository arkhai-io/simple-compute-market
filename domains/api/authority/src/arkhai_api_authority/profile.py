"""What a service root hands the authority: its capacity profile and configuration."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from arkhai_api.labels import IssuanceLabel
from market_resource_pools_contracts.backing import CapacityBacking
from market_resource_pools_contracts.hints import (
    ADVERTISABLE_MODES_POLICY_TAG,
    CAPACITY_BACKING_POLICY_TAG,
)

_MODE = re.compile(r"^[a-z][a-z0-9_]*$")
_KEY_PREFIX = re.compile(r"^[a-z][a-z0-9]*$")


@dataclass(frozen=True)
class CapacityProfile:
    """The one offering mode and seeded pool a deployment of the authority serves.

    The authority reads every mode, provider, pool, and backing value from here
    and names none itself, so two domains' deployments differ only in the
    profile their roots pass.
    """

    offering_mode: str
    pool_provider: str
    pool_id: str
    pool_label: str
    deliverable_modes: frozenset[str]
    advertisable_modes: frozenset[str]
    backing: CapacityBacking

    def __post_init__(self) -> None:
        for name in ("offering_mode", "pool_provider"):
            if not _MODE.fullmatch(getattr(self, name)):
                raise ValueError(f"{name} must be lowercase words joined by underscores")
        for name in ("pool_id", "pool_label"):
            if not str(getattr(self, name)).strip():
                raise ValueError(f"{name} must not be empty")
        for name in ("deliverable_modes", "advertisable_modes"):
            modes = getattr(self, name)
            if not modes or any(not _MODE.fullmatch(mode) for mode in modes):
                raise ValueError(f"{name} must name at least one offering mode")
        if self.offering_mode not in self.deliverable_modes:
            raise ValueError("deliverable_modes must include offering_mode")
        if not self.advertisable_modes <= self.deliverable_modes:
            raise ValueError("a pool advertises only what it delivers")

    def pool_policy_tags(self) -> dict[str, Any]:
        """The seeded pool's declarations, as the pool resolver reads them."""

        return {
            "deliverable_modes": sorted(self.deliverable_modes),
            ADVERTISABLE_MODES_POLICY_TAG: sorted(self.advertisable_modes),
            CAPACITY_BACKING_POLICY_TAG: self.backing.label,
        }


@dataclass(frozen=True)
class AuthorityConfig:
    """One deployment's label, profile, database, key namespace, and reported distribution."""

    label: IssuanceLabel
    profile: CapacityProfile
    database_url: str
    distribution: str
    key_prefix: str

    def __post_init__(self) -> None:
        if not self.database_url.strip():
            raise ValueError("database_url must not be empty")
        if not self.distribution.strip():
            raise ValueError("distribution must not be empty")
        if not _KEY_PREFIX.fullmatch(self.key_prefix):
            raise ValueError("key_prefix must be lowercase letters and digits")
