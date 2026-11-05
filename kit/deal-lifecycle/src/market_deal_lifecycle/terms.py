"""Lifecycle term codec and context-dependent publication/acceptance rules.

Payment capabilities and authority minima are supplied by the composition from
its installed contracts and advertisement copy. This module knows neither
payment schemas nor dispute-interface request vocabulary.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Annotated, Literal
from urllib.parse import urlsplit

from market_deal_lifecycle_contracts.models import Amount, WireModel
from pydantic import ConfigDict, Field, JsonValue, field_validator, model_validator

NonnegativeSeconds = Annotated[int, Field(strict=True, ge=0)]
PositiveSeconds = Annotated[int, Field(strict=True, gt=0)]
Version = Annotated[int, Field(strict=True, ge=1, le=1)]
SettlesThrough = Literal["started_period", "last_boundary", "stop"]
PARTIAL_PERIOD: Mapping[str, str] = MappingProxyType({
    "started_period": "charged", "last_boundary": "returned", "stop": "prorated",
})
SEMANTICS: Mapping[str, str] = MappingProxyType({
    "adjudication": "Required when the mechanism has a lifecycle adapter; forbidden otherwise.",
    "early_termination": "Only entitled accounts may stop; omission grants no entitled stop.",
    "settles_through": "Committed started-period treatment, including at the Agreement horizon.",
    "premature_stop_penalty": "Minor units in the option asset; absent or zero means none.",
    "delivery_deadline_seconds": "Availability after max(commitment instant, Agreement start).",
    "case_hold_max_seconds": "Maximum hold extension; null means unbounded.",
    "bond": "Reserved seller-funded stake; refused unless the mechanism supports it.",
})


class TermModel(WireModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    @model_validator(mode="before")
    @classmethod
    def explicit_null_is_not_omission(cls, value: object) -> object:
        if isinstance(value, dict):
            for key, item in value.items():
                if item is None and key != "case_hold_max_seconds":
                    raise ValueError(f"{key} must be omitted rather than null")
        return value


class DisputeAuthority(TermModel):
    interface: Annotated[str, Field(min_length=1)]
    origin: str
    account: Annotated[str, Field(min_length=1)]
    record_key: Annotated[str, Field(min_length=1)]
    params: dict[str, JsonValue]

    @field_validator("origin")
    @classmethod
    def authority_origin(cls, value: str) -> str:
        url = urlsplit(value)
        if (url.scheme not in {"http", "https"} or not url.hostname or
                url.username is not None or url.password is not None or
                url.path not in {"", "/"} or url.query or url.fragment or value != value.strip()):
            raise ValueError("dispute origin must be an HTTP(S) origin without credentials")
        return value

    @property
    def identity(self) -> tuple[str, str, str, str]:
        return self.interface, self.origin, self.account, self.record_key


class Adjudication(TermModel):
    version: Version
    dispute: DisputeAuthority
    dispute_window_seconds: NonnegativeSeconds
    case_hold_max_seconds: NonnegativeSeconds | None


class Entitlement(TermModel):
    notice_seconds: NonnegativeSeconds
    settles_through: SettlesThrough


class EarlyTermination(TermModel):
    version: Version
    entitlements: dict[Literal["payer", "payee"], Entitlement]
    settles_through: SettlesThrough
    premature_stop_penalty: Amount | None = None

    @field_validator("entitlements")
    @classmethod
    def nonempty_entitlements(cls, value: dict) -> dict:
        if not value:
            raise ValueError("empty entitlements; omit early_termination instead")
        return value

    @property
    def penalty(self) -> int:
        return int(self.premature_stop_penalty or "0")


class Bond(TermModel):
    version: Version
    amount: Amount


class LifecycleTerms(TermModel):
    adjudication: Adjudication
    early_termination: EarlyTermination | None = None
    delivery_deadline_seconds: PositiveSeconds | None = None
    bond: Bond | None = None


@dataclass(frozen=True)
class AuthorityRequirements:
    """A neutral projection of the selected authority's advertisement copy."""

    authority: DisputeAuthority
    mechanisms: frozenset[str]
    minimum_dispute_window_seconds: int
    minimum_case_hold_seconds: int | None

    def __post_init__(self) -> None:
        for value in (self.minimum_dispute_window_seconds, self.minimum_case_hold_seconds):
            if value is not None and (type(value) is not int or value < 0):
                raise ValueError("authority minimums must be nonnegative integers or an unbounded hold")
        if self.minimum_dispute_window_seconds is None:
            raise ValueError("the authority's minimum dispute window is required")


@dataclass(frozen=True)
class TermContext:
    mechanism: str
    has_adapter: bool
    dispute_interfaces: frozenset[str] = frozenset()
    authority: AuthorityRequirements | None = None
    has_stoppable_part: bool = False
    supported_partial_periods: frozenset[str] = frozenset()
    supports_bond: bool = False
    compute: bool = False
    buyer: bool = False
    accepted_authorities: tuple[DisputeAuthority, ...] = ()
    allow_missing_delivery_deadline: bool = False


def decode_terms(value: object) -> LifecycleTerms | None:
    return None if value is None else LifecycleTerms.model_validate(value)


def encode_terms(value: LifecycleTerms) -> dict:
    return value.model_dump(mode="json", exclude_none=True) | {
        # Null is an agreed unbounded cap, not an omitted optional term.
        "adjudication": value.adjudication.model_dump(mode="json"),
    }


def partial_period(value: SettlesThrough, supported: frozenset[str]) -> str:
    mapped = PARTIAL_PERIOD[value]
    if mapped not in supported:
        raise ValueError(f"settles_through {value!r} is unsupported by the installed payment contract")
    return mapped


def validate_terms(value: object, context: TermContext) -> LifecycleTerms | None:
    terms = decode_terms(value)
    if not context.has_adapter:
        if terms is not None:
            raise ValueError(f"{context.mechanism} has no lifecycle adapter")
        return None
    if terms is None:
        raise ValueError("a lifecycle adapter requires adjudication")
    adjudication = terms.adjudication
    dispute = adjudication.dispute
    if dispute.interface not in context.dispute_interfaces:
        raise ValueError(f"no dispute adapter for {dispute.interface}")
    requirement = context.authority
    if requirement is None or requirement.authority != dispute:
        raise ValueError("no advertisement copy for the selected dispute authority")
    if context.mechanism not in requirement.mechanisms:
        raise ValueError(f"{dispute.account} does not advertise {context.mechanism}")
    if context.buyer and dispute not in context.accepted_authorities:
        raise ValueError("unaccepted dispute authority identity or params")
    minimum_window = requirement.minimum_dispute_window_seconds
    if context.compute:
        minimum_window += terms.delivery_deadline_seconds or 0
        if context.buyer and terms.delivery_deadline_seconds is None and not context.allow_missing_delivery_deadline:
            raise ValueError("compute option has no delivery_deadline_seconds")
    if adjudication.dispute_window_seconds < minimum_window:
        raise ValueError("dispute window is below the delivery deadline plus the authority minimum")
    cap, minimum_cap = adjudication.case_hold_max_seconds, requirement.minimum_case_hold_seconds
    if cap is not None and (minimum_cap is None or cap < minimum_cap):
        raise ValueError("case hold cap is below the authority minimum")
    early = terms.early_termination
    if early is not None:
        if not context.has_stoppable_part:
            raise ValueError("early_termination requires a stoppable part")
        for entitlement in early.entitlements.values():
            partial_period(entitlement.settles_through, context.supported_partial_periods)
        partial_period(early.settles_through, context.supported_partial_periods)
    if terms.bond is not None and not context.supports_bond:
        raise ValueError("seller-funded bond is reserved and unsupported")
    return terms
