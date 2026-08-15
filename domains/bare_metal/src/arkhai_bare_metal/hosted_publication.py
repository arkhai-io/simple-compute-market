"""Trusted bare-metal readiness intersection for hosted listing alternatives."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

from market_core.schemas import SettlementOption
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .hosted_contract import (
    BareMetalHostedOptionFacts,
    FundingProfileId,
    bare_metal_digest,
    bind_bare_metal_hosted_option,
)
from .schema import BARE_METAL_EXECUTOR_KIND, BareMetalListing, SSH_ACCESS_METHOD

_SUPPORTED_PROFILES = frozenset({"card.v1", "us_bank_transfer.v1", "us_ach_debit.v1"})


class BareMetalHostedPublicationPolicy(BaseModel):
    """Strict public seller policy; credentials and provider fields are absent."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    enabled_profiles: tuple[FundingProfileId, ...] = (
        "card.v1",
        "us_bank_transfer.v1",
        "us_ach_debit.v1",
    )
    executor_kind: str = Field(default=BARE_METAL_EXECUTOR_KIND, min_length=1)
    access_method: str = Field(default=SSH_ACCESS_METHOD, min_length=1)
    min_funding_window_seconds: int = Field(default=60, gt=0)
    min_fulfillment_window_seconds: int = Field(default=60, gt=0)

    @field_validator("enabled_profiles", mode="before")
    @classmethod
    def _accept_profile_lists(cls, value: Any) -> Any:
        return tuple(value) if isinstance(value, list) else value

    @field_validator("enabled_profiles")
    @classmethod
    def _validate_profiles(
        cls,
        value: tuple[FundingProfileId, ...],
    ) -> tuple[FundingProfileId, ...]:
        if len(value) != len(set(value)):
            raise ValueError("enabled bare-metal hosted profiles must be unique")
        if not value or not set(value).issubset(_SUPPORTED_PROFILES):
            raise ValueError("enabled bare-metal hosted profiles are invalid")
        return value


class BareMetalHostedPublicationResult(BaseModel):
    """Deterministic ready options and provider-free omission reasons."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    settlement_options: tuple[SettlementOption, ...] = ()
    blockers: dict[str, tuple[str, ...]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_distinct_options(self) -> "BareMetalHostedPublicationResult":
        option_ids = [item.option_id for item in self.settlement_options]
        if len(option_ids) != len(set(option_ids)):
            raise ValueError("bare-metal hosted options must have distinct identities")
        return self


def build_ready_bare_metal_hosted_options(
    *,
    candidate: Mapping[str, Any],
    base_hosted_options: Iterable[SettlementOption | Mapping[str, Any]],
    policy: BareMetalHostedPublicationPolicy,
    offer_expires_at: datetime,
    funding_deadlines: Mapping[str, datetime],
    fulfillment_deadline: datetime,
    now: datetime | None = None,
) -> BareMetalHostedPublicationResult:
    """Intersect trusted physical and hosted readiness one profile at a time."""

    current = now or datetime.now(timezone.utc)
    if (
        current.tzinfo is None
        or offer_expires_at.tzinfo is None
        or fulfillment_deadline.tzinfo is None
    ):
        raise ValueError("publication deadlines must be timezone-aware")
    listing = BareMetalListing.model_validate(candidate.get("listing"))
    required = {
        "derivation_key",
        "site_id",
        "projection_revision",
        "projection_digest",
        "physical_resource_id",
        "machine_id",
        "physical_host_id",
    }
    missing = sorted(
        key for key in required if not candidate.get(key) and candidate.get(key) != 0
    )
    if missing:
        raise ValueError(
            "trusted bare-metal candidate is missing " + ", ".join(missing)
        )
    if listing.machine_id != str(candidate["machine_id"]):
        raise ValueError(
            "candidate machine identity conflicts with its trusted listing"
        )
    if listing.physical_host_id != str(candidate["physical_host_id"]):
        raise ValueError(
            "candidate physical-host identity conflicts with its trusted listing"
        )
    if policy.access_method not in listing.access_methods:
        return BareMetalHostedPublicationResult(
            blockers={
                profile: ("unsupported_access",) for profile in policy.enabled_profiles
            }
        )
    if offer_expires_at <= current or fulfillment_deadline <= current:
        return BareMetalHostedPublicationResult(
            blockers={
                profile: ("expired_offer",) for profile in policy.enabled_profiles
            }
        )

    by_profile: dict[str, SettlementOption] = {}
    for raw_option in base_hosted_options:
        option = SettlementOption.model_validate(raw_option)
        profile = option.params.get("funding_profile")
        if profile not in _SUPPORTED_PROFILES:
            raise ValueError("shared hosted option has an unknown funding profile")
        if profile in by_profile:
            raise ValueError(
                f"shared hosted readiness returned duplicate profile {profile!r}"
            )
        by_profile[str(profile)] = option

    options: list[SettlementOption] = []
    blockers: dict[str, tuple[str, ...]] = {}
    for profile in policy.enabled_profiles:
        base = by_profile.get(profile)
        if base is None:
            blockers[profile] = ("hosted_profile_unready",)
            continue
        funding_deadline = funding_deadlines.get(profile)
        if funding_deadline is None or funding_deadline.tzinfo is None:
            blockers[profile] = ("funding_deadline_unavailable",)
            continue
        if funding_deadline > offer_expires_at:
            blockers[profile] = ("funding_exceeds_offer",)
            continue
        funding_window = (funding_deadline - current).total_seconds()
        fulfillment_window = (fulfillment_deadline - funding_deadline).total_seconds()
        if funding_window < policy.min_funding_window_seconds:
            blockers[profile] = ("funding_window_too_short",)
            continue
        if fulfillment_window < policy.min_fulfillment_window_seconds:
            blockers[profile] = ("fulfillment_window_too_short",)
            continue
        facts = BareMetalHostedOptionFacts(
            derivation_key=str(candidate["derivation_key"]),
            projection_digest=bare_metal_digest(
                {
                    "revision": int(candidate["projection_revision"]),
                    "source_digest": str(candidate["projection_digest"]),
                }
            ),
            site_id=str(candidate["site_id"]),
            executor_kind=policy.executor_kind,
            resource_selection="specific",
            physical_resource_id=str(candidate["physical_resource_id"]),
            physical_host_id=listing.physical_host_id,
            pool_id=(str(candidate["pool_id"]) if candidate.get("pool_id") else None),
            access_method=policy.access_method,
            offer_expires_at=offer_expires_at,
            funding_deadline=funding_deadline,
            fulfillment_deadline=fulfillment_deadline,
        )
        options.append(bind_bare_metal_hosted_option(base, facts=facts).option)

    return BareMetalHostedPublicationResult(
        settlement_options=tuple(options),
        blockers=blockers,
    )


__all__ = [
    "BareMetalHostedPublicationPolicy",
    "BareMetalHostedPublicationResult",
    "build_ready_bare_metal_hosted_options",
]
