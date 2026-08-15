"""Provider-neutral hosted settlement codecs for the bare-metal domain."""

from __future__ import annotations

import base64
import hashlib
import json
import re
from datetime import datetime
from typing import Any, Literal, Mapping

from market_core.schemas import (
    SettlementOption,
    SettlementSelection,
    derive_settlement_option_id,
)
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

FundingProfileId = Literal[
    "card.v1",
    "us_bank_transfer.v1",
    "us_ach_debit.v1",
]
InteractionMode = Literal["interactive", "saved_instrument"]
ResourceSelection = Literal["specific", "fungible"]

BARE_METAL_HOSTED_OPTION_KIND = "bare_metal.hosted-option.v1"
BARE_METAL_BUYER_DEMAND_KIND = "bare_metal.buyer-demand.v1"
BARE_METAL_ACCEPTED_BINDING_KIND = "bare_metal.accepted-hosted-binding.v1"
HOSTED_MECHANISM = "fiat.stripe.v1"

_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_OPENSSH_ED25519 = re.compile(r"^ssh-ed25519 ([A-Za-z0-9+/]+={0,2})(?: ([^\r\n]+))?$")
_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
_SENSITIVE_KEYS = frozenset(
    {
        "action_url",
        "client_secret",
        "connection_details",
        "credential",
        "credentials",
        "executor_result",
        "password",
        "payment_method",
        "private_key",
        "provider",
        "provider_id",
        "provider_metadata",
        "raw_result",
        "secret",
        "token",
        "username",
    }
)
_HOSTED_PARAM_KEYS = frozenset(
    {
        "account_ref",
        "authority_id",
        "claimant_principal",
        "condition",
        "contract_fingerprint",
        "country",
        "environment",
        "funding_profile",
        "funds_flow",
        "interaction",
    }
)


def canonical_bare_metal_json(value: Any) -> str:
    """Serialize a public domain value for stable identity derivation."""

    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json", exclude_none=True)
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def bare_metal_digest(value: Any) -> str:
    """Return a canonical lower-case SHA-256 reference."""

    return (
        "sha256:"
        + hashlib.sha256(canonical_bare_metal_json(value).encode()).hexdigest()
    )


def _public_json(value: Any, *, path: str) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        raise ValueError(f"{path} must not contain binary floating-point values")
    if isinstance(value, (list, tuple)):
        return [
            _public_json(item, path=f"{path}[{index}]")
            for index, item in enumerate(value)
        ]
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str) or not key:
                raise ValueError(f"{path} keys must be non-empty strings")
            if key.lower() in _SENSITIVE_KEYS:
                raise ValueError(f"{path} contains forbidden field {key!r}")
            result[key] = _public_json(item, path=f"{path}.{key}")
        return result
    raise ValueError(f"{path} must contain only public JSON values")


class CanonicalPrincipal(BaseModel):
    """Canonical marketplace principal, never a hosted/provider identity."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    scheme: str = Field(min_length=1)
    identifier: str = Field(min_length=1)

    @field_validator("scheme", "identifier")
    @classmethod
    def _validate_component(cls, value: str) -> str:
        if value != value.strip() or _TOKEN.fullmatch(value) is None:
            raise ValueError("principal components must be trimmed public tokens")
        return value


class BareMetalHostedOptionFacts(BaseModel):
    """Seller-authored physical facts bound into a shared settlement option."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    kind: Literal["bare_metal.hosted-option.v1"] = BARE_METAL_HOSTED_OPTION_KIND
    derivation_key: str = Field(min_length=1)
    projection_digest: str
    site_id: str = Field(min_length=1)
    executor_kind: str = Field(min_length=1)
    resource_selection: ResourceSelection
    physical_resource_id: str | None = None
    physical_host_id: str | None = None
    pool_id: str | None = None
    access_method: Literal["ssh"] = "ssh"
    offer_expires_at: datetime
    funding_deadline: datetime
    fulfillment_deadline: datetime

    @field_validator("projection_digest")
    @classmethod
    def _validate_projection_digest(cls, value: str) -> str:
        if _SHA256.fullmatch(value) is None:
            raise ValueError("projection_digest must be a lower-case SHA-256 reference")
        return value

    @model_validator(mode="after")
    def _validate_authority_facts(self) -> "BareMetalHostedOptionFacts":
        if self.resource_selection == "specific":
            if not self.physical_resource_id or not self.physical_host_id:
                raise ValueError(
                    "specific-resource option requires trusted resource identities"
                )
        elif self.physical_resource_id is not None or self.physical_host_id is not None:
            raise ValueError(
                "fungible option must not publish its assigned Physical Resource"
            )
        if self.funding_deadline > self.offer_expires_at:
            raise ValueError("funding deadline must not exceed offer expiry")
        if self.funding_deadline > self.fulfillment_deadline:
            raise ValueError("funding deadline must not exceed fulfillment deadline")
        return self


class BareMetalHostedOption(BaseModel):
    """Exact provider-neutral hosted alternative from a trusted listing."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    option: SettlementOption
    facts: BareMetalHostedOptionFacts
    funding_profile: FundingProfileId
    interaction: InteractionMode
    amount_minor_per_unit: int = Field(gt=0)
    currency: Literal["usd"] = "usd"
    claimant_principal: CanonicalPrincipal

    @model_validator(mode="after")
    def _validate_option(self) -> "BareMetalHostedOption":
        option = self.option
        if option.mechanism != HOSTED_MECHANISM or option.asset != self.currency:
            raise ValueError("option must select the exact hosted USD mechanism")
        if len(option.rates) != 1 or option.rates[0].field != "amount":
            raise ValueError("bare-metal hosted option requires one amount rate")
        if option.rates[0].value != self.amount_minor_per_unit:
            raise ValueError("hosted option amount does not match its canonical rate")
        params = option.params
        if params.get("funding_profile") != self.funding_profile:
            raise ValueError("hosted option funding profile does not match")
        if params.get("interaction") != self.interaction:
            raise ValueError("hosted option interaction does not match")
        if params.get("claimant_principal") != self.claimant_principal.model_dump(
            mode="json"
        ):
            raise ValueError("hosted option claimant does not match")
        if params.get("bare_metal") != self.facts.model_dump(
            mode="json", exclude_none=True
        ):
            raise ValueError("hosted option does not preserve trusted bare-metal facts")
        if (
            self.funding_profile == "us_bank_transfer.v1"
            and self.interaction == "saved_instrument"
        ):
            raise ValueError("push bank transfer does not support saved instruments")
        return self


class BareMetalBuyerDemand(BaseModel):
    """Strict buyer-owned demand; seller/site/commercial fields are forbidden."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    kind: Literal["bare_metal.buyer-demand.v1"] = BARE_METAL_BUYER_DEMAND_KIND
    duration_seconds: int = Field(gt=0)
    access_method: Literal["ssh"] = "ssh"
    ssh_public_key: str
    settlement: SettlementSelection
    allow_off_session: bool = False

    @field_validator("ssh_public_key")
    @classmethod
    def _validate_ssh_public_key(cls, value: str) -> str:
        if value != value.strip() or "\n" in value or "\r" in value:
            raise ValueError("SSH public key must be one trimmed line")
        match = _OPENSSH_ED25519.fullmatch(value)
        if match is None:
            raise ValueError("only OpenSSH ssh-ed25519 public keys are supported")
        try:
            decoded = base64.b64decode(match.group(1), validate=True)
        except ValueError as exc:
            raise ValueError("SSH public key has invalid base64") from exc
        if len(decoded) < 32:
            raise ValueError("SSH public key body is incomplete")
        return value


class BareMetalAcceptedHostedBinding(BaseModel):
    """Immutable storefront-derived hosted/commercial authority binding."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    kind: Literal["bare_metal.accepted-hosted-binding.v1"] = (
        BARE_METAL_ACCEPTED_BINDING_KIND
    )
    agreement_ref: str = Field(min_length=1)
    negotiation_id: str = Field(min_length=1)
    listing_id: str = Field(min_length=1)
    obligation_ref: str = Field(min_length=1)
    option: BareMetalHostedOption
    buyer_principal: CanonicalPrincipal
    seller_principal: CanonicalPrincipal
    claimant_principal: CanonicalPrincipal
    demand_digest: str
    listing_digest: str
    seller_terms_digest: str
    accepted_plan_digest: str
    access_public_digest: str
    authorization_expires_at: datetime
    billable_hold_ref: str | None = None
    billable_hold_expires_at: datetime | None = None
    funding_deadline: datetime

    @field_validator(
        "demand_digest",
        "listing_digest",
        "seller_terms_digest",
        "accepted_plan_digest",
        "access_public_digest",
    )
    @classmethod
    def _validate_digest(cls, value: str) -> str:
        if _SHA256.fullmatch(value) is None:
            raise ValueError("accepted binding digests must be SHA-256 references")
        return value

    @model_validator(mode="after")
    def _validate_binding(self) -> "BareMetalAcceptedHostedBinding":
        if self.claimant_principal != self.option.claimant_principal:
            raise ValueError("accepted claimant must equal the advertised claimant")
        if (self.billable_hold_ref is None) != (self.billable_hold_expires_at is None):
            raise ValueError("billable hold reference and expiry must appear together")
        facts = self.option.facts
        bounds = [
            facts.offer_expires_at,
            facts.funding_deadline,
            facts.fulfillment_deadline,
            self.authorization_expires_at,
        ]
        if self.billable_hold_expires_at is not None:
            bounds.append(self.billable_hold_expires_at)
        if self.funding_deadline != min(bounds):
            raise ValueError(
                "accepted funding deadline must be the minimum authority bound"
            )
        return self

    @property
    def binding_digest(self) -> str:
        return bare_metal_digest(self)


def bind_bare_metal_hosted_option(
    option: SettlementOption | Mapping[str, Any],
    *,
    facts: BareMetalHostedOptionFacts,
) -> BareMetalHostedOption:
    """Bind trusted physical facts into one ready shared hosted option."""

    base = SettlementOption.model_validate(option)
    if base.mechanism != HOSTED_MECHANISM or base.asset != "usd":
        raise ValueError("bare-metal hosted binding requires a hosted USD option")
    if len(base.rates) != 1 or base.rates[0].field != "amount":
        raise ValueError("bare-metal hosted binding requires one amount rate")
    params = dict(base.params)
    if set(params) != _HOSTED_PARAM_KEYS:
        unknown = sorted(set(params).difference(_HOSTED_PARAM_KEYS))
        missing = sorted(_HOSTED_PARAM_KEYS.difference(params))
        details = []
        if unknown:
            details.append("unknown: " + ", ".join(unknown))
        if missing:
            details.append("missing: " + ", ".join(missing))
        raise ValueError(
            "invalid hosted option parameters (" + "; ".join(details) + ")"
        )
    if "bare_metal" in params:
        raise ValueError(
            "base hosted option must not carry caller-supplied bare-metal facts"
        )
    params["bare_metal"] = facts.model_dump(mode="json", exclude_none=True)
    bound = SettlementOption(
        option_id=derive_settlement_option_id(
            mechanism=base.mechanism,
            asset=base.asset,
            rates=base.rates,
            params=params,
        ),
        mechanism=base.mechanism,
        asset=base.asset,
        rates=base.rates,
        params=params,
    )
    claimant = CanonicalPrincipal.model_validate(params.get("claimant_principal"))
    return BareMetalHostedOption(
        option=bound,
        facts=facts,
        funding_profile=params.get("funding_profile"),
        interaction=params.get("interaction"),
        amount_minor_per_unit=bound.rates[0].value,
        claimant_principal=claimant,
    )


def decode_bare_metal_hosted_option_facts(
    value: BareMetalHostedOptionFacts | Mapping[str, Any],
) -> BareMetalHostedOptionFacts:
    """Decode the JSON-valued facts carried inside a settlement option."""

    if isinstance(value, BareMetalHostedOptionFacts):
        return value
    return BareMetalHostedOptionFacts.model_validate_json(
        canonical_bare_metal_json(value)
    )


def validate_buyer_selection(
    *,
    demand: BareMetalBuyerDemand | Mapping[str, Any],
    advertised_options: list[SettlementOption | Mapping[str, Any]],
) -> BareMetalHostedOption:
    """Resolve one exact advertised option before negotiation or mutation."""

    parsed = BareMetalBuyerDemand.model_validate(demand)
    decoded = [SettlementOption.model_validate(option) for option in advertised_options]
    matches = [
        option for option in decoded if option.option_id == parsed.settlement.option_id
    ]
    if len(matches) != 1:
        raise ValueError("buyer must select one exact advertised settlement option")
    selected = matches[0]
    if parsed.settlement.mechanism != selected.mechanism:
        raise ValueError(
            "buyer settlement mechanism does not match the advertised option"
        )
    facts = decode_bare_metal_hosted_option_facts(selected.params.get("bare_metal"))
    hosted = BareMetalHostedOption(
        option=selected,
        facts=facts,
        funding_profile=selected.params.get("funding_profile"),
        interaction=selected.params.get("interaction"),
        amount_minor_per_unit=selected.rates[0].value
        if len(selected.rates) == 1
        else 0,
        claimant_principal=selected.params.get("claimant_principal"),
    )
    if parsed.settlement.expiration_unix != int(facts.funding_deadline.timestamp()):
        raise ValueError(
            "buyer settlement expiry must equal the advertised funding deadline"
        )
    if parsed.allow_off_session != (hosted.interaction == "saved_instrument"):
        raise ValueError("buyer off-session opt-in does not match the selected option")
    return hosted


def derive_accepted_hosted_binding(
    *,
    agreement_ref: str,
    negotiation_id: str,
    listing_id: str,
    obligation_ref: str,
    option: BareMetalHostedOption,
    demand: BareMetalBuyerDemand,
    buyer_principal: CanonicalPrincipal,
    seller_principal: CanonicalPrincipal,
    claimant_principal: CanonicalPrincipal,
    signed_listing: Mapping[str, Any],
    seller_terms: Mapping[str, Any],
    accepted_plan: Mapping[str, Any],
    authorization_expires_at: datetime,
    billable_hold_ref: str | None = None,
    billable_hold_expires_at: datetime | None = None,
) -> BareMetalAcceptedHostedBinding:
    """Derive immutable accepted facts only from signed/trusted artifacts."""

    if demand.settlement.option_id != option.option.option_id:
        raise ValueError("accepted demand does not select the trusted hosted option")
    if claimant_principal != option.claimant_principal:
        raise ValueError("accepted claimant cannot rewrite the advertised claimant")
    bounds = [
        option.facts.offer_expires_at,
        option.facts.funding_deadline,
        option.facts.fulfillment_deadline,
        authorization_expires_at,
    ]
    if billable_hold_expires_at is not None:
        bounds.append(billable_hold_expires_at)
    return BareMetalAcceptedHostedBinding(
        agreement_ref=agreement_ref,
        negotiation_id=negotiation_id,
        listing_id=listing_id,
        obligation_ref=obligation_ref,
        option=option,
        buyer_principal=buyer_principal,
        seller_principal=seller_principal,
        claimant_principal=claimant_principal,
        demand_digest=bare_metal_digest(demand),
        listing_digest=bare_metal_digest(_public_json(signed_listing, path="listing")),
        seller_terms_digest=bare_metal_digest(
            _public_json(seller_terms, path="seller_terms")
        ),
        accepted_plan_digest=bare_metal_digest(
            _public_json(accepted_plan, path="accepted_plan")
        ),
        access_public_digest=bare_metal_digest(
            {"ssh_public_key": demand.ssh_public_key}
        ),
        authorization_expires_at=authorization_expires_at,
        billable_hold_ref=billable_hold_ref,
        billable_hold_expires_at=billable_hold_expires_at,
        funding_deadline=min(bounds),
    )


__all__ = [
    "BARE_METAL_ACCEPTED_BINDING_KIND",
    "BARE_METAL_BUYER_DEMAND_KIND",
    "BARE_METAL_HOSTED_OPTION_KIND",
    "HOSTED_MECHANISM",
    "BareMetalAcceptedHostedBinding",
    "BareMetalBuyerDemand",
    "BareMetalHostedOption",
    "BareMetalHostedOptionFacts",
    "CanonicalPrincipal",
    "FundingProfileId",
    "InteractionMode",
    "bare_metal_digest",
    "bind_bare_metal_hosted_option",
    "canonical_bare_metal_json",
    "decode_bare_metal_hosted_option_facts",
    "derive_accepted_hosted_binding",
    "validate_buyer_selection",
]
