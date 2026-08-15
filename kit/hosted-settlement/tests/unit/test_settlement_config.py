from __future__ import annotations

import base64
from types import SimpleNamespace

import pytest
from market_core.schemas import SettlementOption
from market_hosted_settlement import (
    MECHANISM,
    REQUIRED_STRIPE_CAPABILITIES,
    FundingMode,
    FundingProfile,
    HostedConditionalEscrowClient,
    StripePublicationInput,
    StripeSettlementConfig,
    create_stripe_registration,
    stripe_contract_fingerprint,
)
from market_hosted_settlement.settlement_config import stripe_preflight
from market_identity import (
    AuthorityBindingState,
    AuthorityPayerBinding,
    Identity,
    IdentityScheme,
)
from market_settlement_runtime import (
    MechanismReadiness,
    SettlementConfigurationError,
    SettlementConfigurationRegistry,
    SettlementPublicationClause,
    compile_settlement_clause,
    settlement_clause_matches,
)
from pydantic import ValidationError


def _identity(byte: int = 7) -> Identity:
    identifier = base64.urlsafe_b64encode(bytes([byte]) * 32).rstrip(b"=").decode()
    return Identity(scheme=IdentityScheme.ED25519, identifier=identifier)


class FakeSigner:
    identity = _identity()

    def sign(self, message: bytes) -> bytes:
        return bytes([5]) * 64


def _profile_readiness(
    profile: FundingProfile,
    *,
    ready: bool = True,
) -> SimpleNamespace:
    return SimpleNamespace(profile=profile, ready=ready)


class ObservationalClient:
    def __init__(
        self,
        *,
        fail: bool = False,
        health_ready: dict[FundingProfile, bool] | None = None,
        account_ready: dict[FundingProfile, bool] | None = None,
        capabilities: tuple[str, ...] = REQUIRED_STRIPE_CAPABILITIES,
    ) -> None:
        self.fail = fail
        self.health_ready = health_ready or {}
        self.account_ready = account_ready or {}
        self.capabilities = capabilities
        self.read_calls: list[str] = []
        self.mutation_calls: list[str] = []
        self.request_ids: list[str] = []

    async def health(self, *, request_id: str):
        self.request_ids.append(request_id)
        self.read_calls.append("health")
        if self.fail:
            raise RuntimeError(
                "https://secret-host.example cus_secret pm_secret webhook-secret"
            )
        return SimpleNamespace(
            ready=True,
            manifest_digest="sha256:" + "ab" * 32,
            api_version="0.2.0",
            schema_version=5,
            payer_profile_protocol="arkhai.payer-profile.v1",
            funding_authorization_protocol="arkhai.funding-authorization.v1",
            funding_profile_protocol="arkhai.funding-profile.v1",
            capabilities=self.capabilities,
            funding_profiles=tuple(
                _profile_readiness(
                    profile,
                    ready=self.health_ready.get(profile, True),
                )
                for profile in FundingProfile
            ),
        )

    async def account_readiness(self, account_ref: str, *, request_id: str):
        self.request_ids.append(request_id)
        self.read_calls.append("account_readiness")
        return SimpleNamespace(
            account_ref=account_ref,
            ready=True,
            capabilities=("transfers",),
            funding_profiles=tuple(
                _profile_readiness(
                    profile,
                    ready=self.account_ready.get(profile, True),
                )
                for profile in FundingProfile
            ),
        )

    async def create_payer_profile(self, *args, **kwargs):
        self.mutation_calls.append("create_payer_profile")
        raise AssertionError("preflight must not mutate payer state")

    async def materialize(self, *args, **kwargs):
        self.mutation_calls.append("materialize")
        raise AssertionError("preflight must not materialize settlement")

    async def aclose(self) -> None:
        return None


def _condition() -> dict:
    return {
        "condition_id": "vm-fulfillment",
        "evaluator": {
            "kind": "builtin.v1",
            "version": "trivial.v1",
            "params": {"kind": "trivial"},
        },
        "demand": {"encoding": "application/jcs+json", "value": {}},
    }


def _config(**updates) -> StripeSettlementConfig:
    payload = {
        "enabled": True,
        "base_url": "https://settlement.example",
        "authority_id": "authority-main",
        "environment": "production",
        "authority": {"principals": [_identity().model_dump(mode="json")]},
        "expected_manifest_digest": "sha256:" + "ab" * 32,
        "account_ref": "seller-main",
        "currency": "usd",
        "country": "US",
        "condition_profile": "vm-fulfillment",
        "condition_profiles": {"vm-fulfillment": _condition()},
    }
    payload.update(updates)
    return StripeSettlementConfig.model_validate(payload)


def _clause(
    profile: FundingProfile,
    interaction: FundingMode = FundingMode.INTERACTIVE,
    *,
    rate: str = "1.25",
) -> SettlementPublicationClause:
    return SettlementPublicationClause(
        mechanism=MECHANISM,
        asset="usd",
        rate=rate,
        per="hour",
        mechanism_input={
            "funding_profile": profile.value,
            "interaction": interaction.value,
            "funds_flow": "separate_charges_transfers",
        },
    )


def _readiness(
    config: StripeSettlementConfig,
    *,
    ready: dict[FundingProfile, bool] | None = None,
) -> MechanismReadiness:
    states = ready or {profile: True for profile in FundingProfile}
    return MechanismReadiness(
        mechanism=MECHANISM,
        configured=True,
        enabled=True,
        ready=any(states.values()),
        contract_version="0.2.0",
        schema_version="5",
        public_details={
            "contract_fingerprint": stripe_contract_fingerprint(config),
            "profiles": {
                profile.value: {
                    "ready": is_ready,
                    "blockers": [],
                    "interactions": [
                        FundingMode.INTERACTIVE.value,
                        FundingMode.SAVED_INSTRUMENT.value,
                    ],
                    "currency": "usd",
                    "country": "US",
                }
                for profile, is_ready in states.items()
            },
        },
    )


@pytest.mark.parametrize(
    "field",
    [
        "provider_secret",
        "admin_token",
        "webhook_secret",
        "database_url",
        "stripe_account_id",
        "payment_method_types",
        "method",
        "customer_id",
        "instrument_ref",
        "action_url",
    ],
)
def test_config_rejects_provider_legacy_and_sensitive_fields(field: str) -> None:
    with pytest.raises(ValidationError):
        StripeSettlementConfig.model_validate({field: "must-not-cross-boundary"})


@pytest.mark.parametrize(
    ("updates", "match"),
    [
        ({"currency": "eur"}, "usd"),
        ({"currency": "USD"}, "usd"),
        ({"country": "DE"}, "US"),
        ({"expected_api_version": "0.2"}, "0.2.0"),
        ({"expected_schema_version": 4}, "5"),
        ({"required_capabilities": ("payer-profile.v1",)}, "exactly match"),
    ],
)
def test_config_is_exact_and_closed(updates: dict, match: str) -> None:
    with pytest.raises(ValidationError, match=match):
        _config(**updates)


@pytest.mark.parametrize(
    ("value", "valid"),
    [
        (
            {
                "funding_profile": "card.v1",
                "interaction": "interactive",
            },
            True,
        ),
        (
            {
                "funding_profile": "us_ach_debit.v1",
                "interaction": "saved_instrument",
            },
            True,
        ),
        (
            {
                "funding_profile": "us_bank_transfer.v1",
                "interaction": "saved_instrument",
            },
            False,
        ),
        ({"funding_profile": "card", "interaction": "interactive"}, False),
        ({"method": "card", "interaction": "interactive"}, False),
        ({"payment_method_types": ["card"], "interaction": "interactive"}, False),
        (
            {
                "funding_profile": "sepa_debit",
                "interaction": "interactive",
            },
            False,
        ),
    ],
)
def test_publication_input_admits_only_exact_profiles_and_modes(
    value: dict,
    valid: bool,
) -> None:
    if valid:
        assert StripePublicationInput.model_validate(value).funding_profile in FundingProfile
    else:
        with pytest.raises(ValidationError):
            StripePublicationInput.model_validate(value)


def test_seller_publication_fields_remain_role_scoped() -> None:
    registry = SettlementConfigurationRegistry([create_stripe_registration()])
    raw = {
        "priority": [MECHANISM],
        "stripe": {
            "enabled": True,
            "account_ref": "seller-main",
            "currency": "usd",
            "country": "US",
        },
    }
    with pytest.raises(
        SettlementConfigurationError, match="does not apply to role 'buyer'"
    ):
        registry.resolve(raw, role="buyer")
    assert registry.resolve(raw, role="seller").mechanism_config(
        "stripe"
    ).account_ref == "seller-main"


@pytest.mark.asyncio
async def test_buyer_preflight_checks_exact_contract_without_mutation() -> None:
    config = _config(account_ref=None, condition_profile=None, condition_profiles={})
    client = ObservationalClient()
    status = await stripe_preflight(
        config,
        {"marketplace_signer": FakeSigner(), "preflight_client": client},
        "buyer",
    )
    assert status.ready is True
    assert status.contract_version == "0.2.0"
    assert status.schema_version == "5"
    assert tuple(status.public_details["profiles"]) == tuple(
        profile.value for profile in FundingProfile
    )
    assert client.read_calls == ["health"]
    assert client.mutation_calls == []


@pytest.mark.asyncio
async def test_profile_readiness_is_independent_and_ordered() -> None:
    clauses = (
        _clause(FundingProfile.CARD),
        _clause(FundingProfile.US_ACH_DEBIT, FundingMode.SAVED_INSTRUMENT),
    )
    client = ObservationalClient(
        account_ready={FundingProfile.US_ACH_DEBIT: False}
    )
    status = await stripe_preflight(
        _config(),
        {
            "marketplace_signer": FakeSigner(),
            "preflight_client": client,
            "publication_clauses": clauses,
        },
        "seller",
    )
    profiles = status.public_details["profiles"]
    assert status.ready is True
    assert tuple(profiles) == ("card.v1", "us_ach_debit.v1")
    assert profiles["card.v1"]["ready"] is True
    assert profiles["us_ach_debit.v1"]["ready"] is False
    assert profiles["us_ach_debit.v1"]["blockers"] == [
        {
            "code": "hosted.account_profile_unready",
            "message": "the seller account is not ready for the funding profile",
        }
    ]


@pytest.mark.asyncio
async def test_missing_profile_capability_blocks_only_that_profile() -> None:
    capabilities = tuple(
        capability
        for capability in REQUIRED_STRIPE_CAPABILITIES
        if capability != "funding-profile.us_bank_transfer.v1"
    )
    status = await stripe_preflight(
        _config(),
        {
            "marketplace_signer": FakeSigner(),
            "preflight_client": ObservationalClient(capabilities=capabilities),
        },
        "seller",
    )
    assert status.ready is True
    assert status.public_details["profiles"]["card.v1"]["ready"] is True
    assert status.public_details["profiles"]["us_bank_transfer.v1"]["ready"] is False


@pytest.mark.asyncio
async def test_preflight_failure_is_sanitized_and_observational() -> None:
    client = ObservationalClient(fail=True)
    status = await stripe_preflight(
        _config(),
        {"marketplace_signer": FakeSigner(), "preflight_client": client},
        "seller",
    )
    projection = status.model_dump_json()
    assert [blocker.code for blocker in status.blockers] == ["hosted.preflight_failed"]
    assert "secret-host" not in projection
    assert "cus_secret" not in projection
    assert "pm_secret" not in projection
    assert "webhook-secret" not in projection
    assert client.mutation_calls == []


def test_options_are_deterministic_distinct_and_profile_exact() -> None:
    config = _config()
    registration = create_stripe_registration()
    resources = {"claimant_principal": _identity(8)}
    card = registration.option_builder(
        config,
        _readiness(config),
        {**resources, "publication_clause": _clause(FundingProfile.CARD)},
        "seller",
    )["settlement_options"][0]
    card_retry = registration.option_builder(
        config,
        _readiness(config),
        {**resources, "publication_clause": _clause(FundingProfile.CARD)},
        "seller",
    )["settlement_options"][0]
    ach = registration.option_builder(
        config,
        _readiness(config),
        {
            **resources,
            "publication_clause": _clause(FundingProfile.US_ACH_DEBIT),
        },
        "seller",
    )["settlement_options"][0]
    assert card == card_retry
    assert card["option_id"] != ach["option_id"]
    assert card["params"]["funding_profile"] == "card.v1"
    assert ach["params"]["funding_profile"] == "us_ach_debit.v1"
    assert card["params"]["interaction"] == "interactive"
    assert card["params"]["funds_flow"] == "separate_charges_transfers"
    assert "payment_method_types" not in card["params"]
    assert "method" not in card["params"]


def test_unready_clause_is_suppressed_without_suppressing_ready_peer() -> None:
    config = _config()
    readiness = _readiness(
        config,
        ready={
            FundingProfile.CARD: True,
            FundingProfile.US_ACH_DEBIT: False,
        },
    )
    registration = create_stripe_registration()
    card = registration.option_builder(
        config,
        readiness,
        {
            "claimant_principal": _identity(),
            "publication_clause": _clause(FundingProfile.CARD),
        },
        "seller",
    )
    ach = registration.option_builder(
        config,
        readiness,
        {
            "claimant_principal": _identity(),
            "publication_clause": _clause(FundingProfile.US_ACH_DEBIT),
        },
        "seller",
    )
    assert len(card["settlement_options"]) == 1
    assert ach == {"accepted_escrows": [], "settlement_options": []}


def test_clause_projection_uses_profile_currency_interaction_and_flow() -> None:
    config = _config()
    registration = create_stripe_registration()
    registry = SettlementConfigurationRegistry([registration])
    wire = registration.option_builder(
        config,
        _readiness(config),
        {
            "claimant_principal": _identity(),
            "publication_clause": _clause(
                FundingProfile.US_ACH_DEBIT,
                FundingMode.SAVED_INSTRUMENT,
            ),
        },
        "seller",
    )["settlement_options"][0]
    option = SettlementOption.model_validate(wire)
    before = option.model_dump(mode="json")
    clause = compile_settlement_clause(
        "mechanism=stripe stripe.funding_profile=us_ach_debit.v1 "
        "stripe.currency=usd stripe.interaction=saved_instrument "
        "stripe.funds_flow=separate_charges_transfers",
        registry,
    )
    assert settlement_clause_matches(clause, option, registry) is True
    assert option.model_dump(mode="json") == before


def _compatibility_context(
    *,
    principal: Identity | None = None,
    binding_principal: Identity | None = None,
    profile_ready: bool = True,
) -> dict:
    selected = principal or _identity()
    bound = binding_principal or selected
    return {
        "selected_principal": selected.model_dump(mode="json"),
        "selected_payer_binding": AuthorityPayerBinding(
            authority_id="authority-main",
            environment="production",
            binding_ref="payer_binding_opaque",
            bound_principal=bound,
            state=AuthorityBindingState.ACTIVE,
        ),
        "funding_profiles": tuple(profile.value for profile in FundingProfile),
        "currencies": ("usd",),
        "countries": ("US",),
        "interactions": ("interactive", "saved_instrument"),
        "profile_readiness": {
            "card.v1": {
                "interactive": profile_ready,
                "saved_instrument": profile_ready,
            }
        },
    }


def test_buyer_compatibility_requires_exact_binding_readiness_and_release() -> None:
    seller_config = _config()
    buyer_config = _config(
        account_ref=None,
        condition_profile=None,
        condition_profiles={},
    )
    registration = create_stripe_registration()
    option = registration.option_builder(
        seller_config,
        _readiness(seller_config),
        {
            "claimant_principal": _identity(9),
            "publication_clause": _clause(FundingProfile.CARD),
        },
        "seller",
    )["settlement_options"][0]
    assert registration.buyer_compatibility(
        buyer_config, option, _compatibility_context()
    )
    assert not registration.buyer_compatibility(
        buyer_config,
        option,
        _compatibility_context(binding_principal=_identity(6)),
    )
    assert not registration.buyer_compatibility(
        buyer_config,
        option,
        _compatibility_context(profile_ready=False),
    )
    changed = {
        **option,
        "params": {
            **option["params"],
            "contract_fingerprint": "sha256:" + "00" * 32,
        },
    }
    assert not registration.buyer_compatibility(
        buyer_config, changed, _compatibility_context()
    )


def test_registration_factory_and_publication_validation_are_exact() -> None:
    registration = create_stripe_registration(command_group="command-sentinel")
    assert registration.command_group == "command-sentinel"
    assert {
        field.descriptor.name for field in registration.clause_fields
    } == {
        "stripe.funding_profile",
        "stripe.currency",
        "stripe.interaction",
        "stripe.funds_flow",
    }
    registry = SettlementConfigurationRegistry([create_stripe_registration()])
    config = registry.resolve(
        {
            "priority": [MECHANISM],
            "stripe": _config().model_dump(mode="python"),
        },
        role="seller",
    )
    value = registry.validate_publication_input(
        MECHANISM,
        {
            "funding_profile": "card.v1",
            "interaction": "interactive",
        },
        config,
        role="seller",
    )
    assert value.model_dump(mode="json") == {
        "funding_profile": "card.v1",
        "interaction": "interactive",
        "funds_flow": "separate_charges_transfers",
    }
    with pytest.raises(SettlementConfigurationError):
        registry.validate_publication_input(
            MECHANISM,
            {"method": "card"},
            config,
            role="seller",
        )


def test_factory_wraps_only_the_released_client() -> None:
    raw = ObservationalClient()
    captured = []

    def factory(config):
        captured.append(config)
        return raw

    client = create_stripe_registration().client_factory(
        _config(),
        {"marketplace_signer": FakeSigner(), "hosted_client_factory": factory},
        "seller",
    )
    assert type(client) is HostedConditionalEscrowClient
    assert captured[0].caller_role == "storefront"
