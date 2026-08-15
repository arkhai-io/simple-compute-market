"""Typed configuration and registration for introduction-only settlement."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any

from market_core.schemas import SettlementOption, derive_settlement_option_id
from market_settlement_runtime import (
    AcceptedObligationArtifacts,
    ComparisonOperator,
    FieldDescriptor,
    MechanismReadiness,
    MechanismRegistration,
    QueryValueType,
    ReadinessBlocker,
    SettlementClauseField,
    SettlementPublicationClause,
    SettlementRole,
)
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .client import ContactExchangeClient

MECHANISM = "contact-exchange.v1"
CONTACT_CONFIG_KEY = "contact"
INTRODUCTION_ASSET = "introduction"

_PROFILE_KEY = re.compile(r"^[a-z0-9][a-z0-9_.-]*$")
_MAX_PROFILES = 32
_MAX_CHANNEL_CHARS = 128
_MAX_TERMS_CHARS = 4000
_MAX_PAYLOAD_ENTRIES = 16
_MAX_PAYLOAD_KEY_CHARS = 64
_MAX_PAYLOAD_VALUE_CHARS = 512
_CLAUSE_OPERATORS = frozenset(
    {
        ComparisonOperator.EQUAL,
        ComparisonOperator.NOT_EQUAL,
        ComparisonOperator.IN,
        ComparisonOperator.NOT_IN,
    }
)


class ContactProfile(BaseModel):
    """One public offered introduction: a channel plus prose commercial terms.

    Both fields are published verbatim in the listing option; contact data
    never belongs here.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    channel: str = Field(min_length=1, max_length=_MAX_CHANNEL_CHARS)
    terms: str = Field(min_length=1, max_length=_MAX_TERMS_CHARS)

    @field_validator("channel")
    @classmethod
    def require_trimmed_channel(cls, value: str) -> str:
        if value != value.strip():
            raise ValueError("contact channel must be trimmed")
        return value


class ContactPublicationInput(BaseModel):
    """Select one offered profile for one ordered publication clause."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    profile: str = Field(min_length=1)


class ContactSettlementConfig(BaseModel):
    """Strict contact-exchange settings.

    ``contact_payload`` is the seller's held contact data: bounded, opaque,
    and revealed only through the authenticated introduction surface after
    acceptance. It must never reach readiness details, options, or listings.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    enabled: bool = False
    contact_payload: dict[str, str] = Field(
        default_factory=dict,
        repr=False,
        json_schema_extra={"roles": ["seller"], "secret": True},
    )
    profiles: dict[str, ContactProfile] = Field(
        default_factory=dict,
        json_schema_extra={"roles": ["seller"]},
    )

    @field_validator("contact_payload")
    @classmethod
    def bound_contact_payload(cls, value: dict[str, str]) -> dict[str, str]:
        if len(value) > _MAX_PAYLOAD_ENTRIES:
            raise ValueError(
                f"contact payload allows at most {_MAX_PAYLOAD_ENTRIES} entries"
            )
        for key, item in value.items():
            if not key or len(key) > _MAX_PAYLOAD_KEY_CHARS:
                raise ValueError("contact payload keys must be short and non-empty")
            if not item.strip() or len(item) > _MAX_PAYLOAD_VALUE_CHARS:
                raise ValueError(
                    "contact payload values must be non-blank and bounded"
                )
        return value

    @field_validator("profiles")
    @classmethod
    def bound_profiles(cls, value: dict[str, ContactProfile]) -> dict[str, ContactProfile]:
        if len(value) > _MAX_PROFILES:
            raise ValueError(f"at most {_MAX_PROFILES} contact profiles are allowed")
        invalid = sorted(key for key in value if not _PROFILE_KEY.fullmatch(key))
        if invalid:
            raise ValueError(
                f"invalid contact profile keys: {', '.join(invalid)}"
            )
        return value

    @model_validator(mode="after")
    def payload_stays_out_of_profiles(self) -> ContactSettlementConfig:
        published = json.dumps(
            {key: item.model_dump(mode="json") for key, item in self.profiles.items()},
            ensure_ascii=False,
            sort_keys=True,
        )
        leaked = sorted(
            key
            for key, item in self.contact_payload.items()
            if item and item in published
        )
        if leaked:
            raise ValueError(
                "contact payload values must not appear in published profiles: "
                + ", ".join(leaked)
            )
        return self


def contact_preflight(
    section: BaseModel,
    resources: Mapping[str, Any],
    role: SettlementRole,
) -> MechanismReadiness:
    """Observe configuration completeness only; there is nothing to probe."""

    config = ContactSettlementConfig.model_validate(section)
    blockers: list[ReadinessBlocker] = []
    if role == "seller":
        if not config.profiles:
            blockers.append(
                ReadinessBlocker(
                    code="no_contact_profiles",
                    message="no contact profiles are configured",
                )
            )
        if not config.contact_payload:
            blockers.append(
                ReadinessBlocker(
                    code="no_contact_payload",
                    message="no contact payload is configured to reveal",
                )
            )
    channels = sorted({profile.channel for profile in config.profiles.values()})
    return MechanismReadiness(
        mechanism=MECHANISM,
        configured=True,
        enabled=True,
        ready=not blockers,
        blockers=tuple(blockers),
        capabilities=("introduction.v1",),
        public_details={"channels": channels} if role == "seller" else {},
    )


def contact_client_factory(
    section: BaseModel,
    resources: Mapping[str, Any],
    role: SettlementRole,
) -> ContactExchangeClient:
    ContactSettlementConfig.model_validate(section)
    return ContactExchangeClient()


def _principal_json(value: Any) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, Mapping):
        return dict(value)
    raise ValueError("contact-exchange option requires a claimant principal")


def contact_option_builder(
    section: BaseModel,
    readiness: MechanismReadiness,
    resources: Mapping[str, Any],
    role: SettlementRole,
) -> dict[str, list[Any]]:
    """Build one rateless option for one exact ready publication clause."""

    if role != "seller":
        raise ValueError("contact-exchange listing options are seller-owned")
    config = ContactSettlementConfig.model_validate(section)
    if not config.enabled or not readiness.ready:
        return {"accepted_escrows": [], "settlement_options": []}
    raw_clause = resources.get("publication_clause")
    if raw_clause is None:
        raise ValueError("contact-exchange publication requires one ordered clause")
    clause = SettlementPublicationClause.model_validate(raw_clause)
    if clause.mechanism != MECHANISM:
        raise ValueError("publication clause does not select contact exchange")
    if clause.asset != INTRODUCTION_ASSET:
        raise ValueError(
            f"contact-exchange asset must be {INTRODUCTION_ASSET!r}"
        )
    if clause.rate is not None:
        raise ValueError("contact exchange declines scalar rates")
    publication_input = ContactPublicationInput.model_validate(clause.mechanism_input)
    profile = config.profiles.get(publication_input.profile)
    if profile is None:
        raise ValueError("publication selects an unoffered contact profile")
    params = {
        "profile": publication_input.profile,
        "channel": profile.channel,
        "terms": profile.terms,
        "claimant_principal": _principal_json(resources.get("claimant_principal")),
    }
    public_payload = json.dumps(params, ensure_ascii=False, sort_keys=True)
    if any(
        value and value in public_payload
        for value in config.contact_payload.values()
    ):
        raise ValueError("contact payload must not reach a published option")
    option = {
        "option_id": derive_settlement_option_id(
            mechanism=MECHANISM,
            asset=INTRODUCTION_ASSET,
            rates=[],
            params=params,
        ),
        "mechanism": MECHANISM,
        "asset": INTRODUCTION_ASSET,
        "rates": [],
        "params": params,
    }
    return {"accepted_escrows": [], "settlement_options": [option]}


def _value(container: Any, name: str, default: Any = None) -> Any:
    if isinstance(container, Mapping):
        return container.get(name, default)
    return getattr(container, name, default)


def contact_buyer_compatibility(
    section: BaseModel,
    option: Any,
    public_context: Mapping[str, Any],
) -> bool:
    """An enabled buyer accepts any well-shaped rateless introduction option."""

    config = ContactSettlementConfig.model_validate(section)
    if not config.enabled:
        return False
    return (
        _value(option, "mechanism") == MECHANISM
        and _value(option, "asset") == INTRODUCTION_ASSET
        and not _value(option, "rates")
    )


def contact_accepted_obligation_builder(
    section: BaseModel,
    option: Any,
    context: Mapping[str, Any],
) -> AcceptedObligationArtifacts:
    """Build the one non-financial introduction obligation from a selection.

    The obligation carries no amount and no asset — the deal's value does not
    reduce to a number — and the contact payload never enters it; the payload
    travels only on the authenticated reveal surface.
    """

    config = ContactSettlementConfig.model_validate(section)
    selected = SettlementOption.model_validate(option)
    if selected.rates:
        raise ValueError("contact exchange declines scalar rates")
    buyer = _principal_json(context.get("buyer_principal"))
    seller = _principal_json(context.get("seller_principal"))
    expiration_unix = int(context.get("expiration_unix") or 0)
    if expiration_unix <= 0:
        raise ValueError("introduction acceptance requires an expiration")
    advertised_claimant = selected.params.get("claimant_principal")
    if not isinstance(advertised_claimant, Mapping) or (
        dict(advertised_claimant) != seller
    ):
        raise ValueError("contact option claimant does not match the listing seller")
    params = dict(selected.params)
    for key in context.get("domain_param_keys", ()):
        params.pop(key, None)
    # Principals bind into the obligation params exactly as buyers rebuild
    # them from the advertised option, so buyer-side strict comparison holds.
    params["payer_principal"] = buyer
    params["claimant_principal"] = seller
    introduction_package: dict[str, Any] = {
        "option_id": selected.option_id,
        "profile": params.get("profile"),
        "channel": params.get("channel"),
        "terms": params.get("terms"),
    }
    listing_id = context.get("listing_id")
    if isinstance(listing_id, str) and listing_id:
        introduction_package["listing_id"] = listing_id
    negotiated_context = context.get("negotiated_context")
    if isinstance(negotiated_context, Mapping) and negotiated_context:
        introduction_package["negotiated_context"] = dict(negotiated_context)
    public_payload = json.dumps(
        {"params": params, "introduction": introduction_package},
        ensure_ascii=False,
        sort_keys=True,
    )
    if any(
        value and value in public_payload
        for value in config.contact_payload.values()
    ):
        raise ValueError("contact payload must not reach an accepted obligation")
    return AcceptedObligationArtifacts(
        obligation={
            "payer": "buyer",
            "claimant": "seller",
            "payer_principal": buyer,
            "claimant_principal": seller,
            # ``asset`` is the nominal deliverable tag from the advertised
            # option; the amount stays absent — the deal's value does not
            # reduce to a number.
            "asset": selected.asset,
            "expiration_unix": expiration_unix,
            "conditions": [],
            "mechanism": MECHANISM,
            "params": params,
        },
        amount=None,
        service_terms={MECHANISM: introduction_package},
    )


def contact_channel_projection(option: Any) -> str | None:
    """Project the exact advertised introduction channel."""

    params = _value(option, "params", {})
    value = _value(params, "channel") if isinstance(params, Mapping) else None
    return value if isinstance(value, str) and value else None


def validate_contact_publication_input(
    section: BaseModel,
    value: BaseModel,
    role: SettlementRole,
) -> BaseModel:
    """Validate one exact public clause input against the offered profiles."""

    config = ContactSettlementConfig.model_validate(section)
    if role != "seller":
        raise ValueError("contact-exchange publication input is seller-owned")
    parsed = ContactPublicationInput.model_validate(value)
    if parsed.profile not in config.profiles:
        raise ValueError(f"unoffered contact profile {parsed.profile!r}")
    return parsed


def create_contact_exchange_registration(
    *, command_group: Any | None = None
) -> MechanismRegistration:
    """Return the explicit common-contract registration for contact exchange."""

    return MechanismRegistration(
        mechanism_id=MECHANISM,
        config_key=CONTACT_CONFIG_KEY,
        config_model=ContactSettlementConfig,
        roles=frozenset({"buyer", "seller"}),
        negotiates_scalar_amount=False,
        preflight=contact_preflight,
        client_factory=contact_client_factory,
        option_builder=contact_option_builder,
        buyer_compatibility=contact_buyer_compatibility,
        accepted_obligation_builder=contact_accepted_obligation_builder,
        command_group=command_group,
        public_detail_keys=frozenset({"channels"}),
        clause_fields=(
            SettlementClauseField(
                descriptor=FieldDescriptor(
                    name="contact.channel",
                    value_type=QueryValueType.STRING,
                    operators=_CLAUSE_OPERATORS,
                    description="exact advertised introduction channel",
                ),
                roles=frozenset({"buyer", "seller"}),
                projector=contact_channel_projection,
            ),
        ),
        publication_input_model=ContactPublicationInput,
        publication_input_validator=validate_contact_publication_input,
    )
