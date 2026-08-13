from __future__ import annotations

import base64
from types import SimpleNamespace

import pytest
from market_identity import Identity, IdentityScheme
from market_settlement_runtime import (
    SettlementConfigurationError,
    SettlementConfigurationRegistry,
)
from pydantic import ValidationError

from market_hosted_settlement import (
    MECHANISM,
    REQUIRED_STRIPE_CAPABILITIES,
    HostedConditionalEscrowClient,
    StripeSettlementConfig,
    create_stripe_registration,
)
from market_hosted_settlement.settlement_config import stripe_preflight


def _identity(byte: int = 7) -> Identity:
    identifier = base64.urlsafe_b64encode(bytes([byte]) * 32).rstrip(b"=").decode()
    return Identity(scheme=IdentityScheme.ED25519, identifier=identifier)


class FakeSigner:
    identity = _identity()

    def sign(self, message: bytes) -> bytes:
        return bytes([5]) * 64


class ObservationalClient:
    def __init__(self, *, fail: bool = False, account_ready: bool = True) -> None:
        self.fail = fail
        self.account_ready = account_ready
        self.read_calls: list[str] = []
        self.mutation_calls: list[str] = []
        self.request_ids: list[str] = []

    async def health(self, *, request_id: str):
        self.request_ids.append(request_id)
        self.read_calls.append("health")
        if self.fail:
            raise RuntimeError(
                "https://secret-host.example acct_provider_secret webhook-secret"
            )
        return SimpleNamespace(
            ready=True,
            manifest_digest="sha256:" + "ab" * 32,
            api_version="0.1.0",
            schema_version=4,
            capabilities=REQUIRED_STRIPE_CAPABILITIES,
        )

    async def account_readiness(self, account_ref: str, *, request_id: str):
        self.request_ids.append(request_id)
        self.read_calls.append("account_readiness")
        return SimpleNamespace(
            account_ref=account_ref,
            ready=self.account_ready,
            capabilities=("transfers",),
        )

    async def create_account_link(self, *args, **kwargs):
        self.mutation_calls.append("create_account_link")
        raise AssertionError("preflight must not create an Account Link")

    async def materialize(self, *args, **kwargs):
        self.mutation_calls.append("materialize")
        raise AssertionError("preflight must not create Checkout")

    async def publish(self, *args, **kwargs):
        self.mutation_calls.append("publish")
        raise AssertionError("preflight must not publish")

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
        "expected_api_version": "0.1.0",
        "expected_schema_version": 4,
        "account_ref": "seller-main",
        "currency": "usd",
        "condition_profile": "vm-fulfillment",
        "condition_profiles": {"vm-fulfillment": _condition()},
    }
    payload.update(updates)
    return StripeSettlementConfig.model_validate(payload)


@pytest.mark.parametrize(
    "field",
    [
        "provider_secret",
        "admin_token",
        "webhook_secret",
        "database_url",
        "migration_key",
        "stripe_account_id",
    ],
)
def test_stripe_config_rejects_hosted_authority_and_provider_fields(field: str) -> None:
    with pytest.raises(ValidationError):
        StripeSettlementConfig.model_validate({field: "must-not-cross-boundary"})


def test_stripe_config_rejects_credentials_in_public_url() -> None:
    with pytest.raises(ValidationError):
        StripeSettlementConfig(base_url="https://user:secret@settlement.example")


def test_stripe_seller_publication_fields_are_role_scoped() -> None:
    registry = SettlementConfigurationRegistry([create_stripe_registration()])
    raw = {
        "priority": [MECHANISM],
        "stripe": {"enabled": True, "account_ref": "seller-main"},
    }

    with pytest.raises(
        SettlementConfigurationError, match="does not apply to role 'buyer'"
    ):
        registry.resolve(raw, role="buyer")

    resolved = registry.resolve(raw, role="seller")
    assert resolved.mechanism_config("stripe").account_ref == "seller-main"


@pytest.mark.asyncio
async def test_buyer_hosted_preflight_needs_no_wallet_or_seller_fields() -> None:
    config = _config(account_ref=None, condition_profile=None, condition_profiles={})
    client = ObservationalClient()
    resources = {
        "marketplace_signer": FakeSigner(),
        "preflight_client": client,
    }

    status = await stripe_preflight(config, resources, "buyer")

    assert status.ready is True
    assert client.read_calls == ["health"]
    assert client.mutation_calls == []
    assert "account_ref" not in status.public_details


@pytest.mark.asyncio
async def test_seller_preflight_reports_trust_account_and_condition_failures() -> None:
    missing = await stripe_preflight(
        _config(account_ref=None, condition_profile=None, condition_profiles={}),
        {"marketplace_signer": FakeSigner(), "preflight_client": ObservationalClient()},
        "seller",
    )
    assert {blocker.code for blocker in missing.blockers} == {
        "hosted.account_missing",
        "hosted.condition_missing",
    }
    untrusted = await stripe_preflight(
        _config(authority=None),
        {"marketplace_signer": FakeSigner(), "preflight_client": ObservationalClient()},
        "seller",
    )
    assert [blocker.code for blocker in untrusted.blockers] == ["hosted.trust_missing"]

    unready = await stripe_preflight(
        _config(),
        {
            "marketplace_signer": FakeSigner(),
            "preflight_client": ObservationalClient(account_ready=False),
        },
        "seller",
    )
    assert [blocker.code for blocker in unready.blockers] == ["hosted.account_unready"]


@pytest.mark.asyncio
async def test_hosted_preflight_is_sanitized_and_never_calls_mutations() -> None:
    client = ObservationalClient(fail=True)
    status = await stripe_preflight(
        _config(),
        {"marketplace_signer": FakeSigner(), "preflight_client": client},
        "seller",
    )

    assert [blocker.code for blocker in status.blockers] == ["hosted.preflight_failed"]
    projection = status.model_dump_json()
    assert "secret-host" not in projection
    assert "provider_secret" not in projection
    assert "webhook-secret" not in projection
    assert "seller-main" not in projection
    assert client.mutation_calls == []


@pytest.mark.asyncio
async def test_seller_preflight_uses_account_owner_role() -> None:
    captured = []

    def factory(config):
        captured.append(config)
        return ObservationalClient()

    status = await stripe_preflight(
        _config(),
        {"marketplace_signer": FakeSigner(), "hosted_client_factory": factory},
        "seller",
    )
    assert status.ready is True
    assert captured[0].caller_role == "account_owner"


@pytest.mark.asyncio
async def test_preflight_reads_use_fresh_request_identities() -> None:
    client = ObservationalClient()
    resources = {"marketplace_signer": FakeSigner(), "preflight_client": client}

    await stripe_preflight(_config(), resources, "seller")
    await stripe_preflight(_config(), resources, "seller")

    assert len(client.request_ids) == 4
    assert len(set(client.request_ids)) == 4
    assert client.request_ids[0].startswith("settlement-preflight:health:")
    assert client.request_ids[1].startswith("settlement-preflight:account:")


def test_stripe_registration_and_factory_are_exact() -> None:
    registration = create_stripe_registration()
    assert registration.mechanism_id == MECHANISM
    assert registration.config_key == "stripe"
    assert registration.roles == frozenset({"buyer", "seller"})

    raw = ObservationalClient()
    captured = []

    def factory(config):
        captured.append(config)
        return raw

    client = registration.client_factory(
        _config(),
        {"marketplace_signer": FakeSigner(), "hosted_client_factory": factory},
        "seller",
    )
    assert type(client) is HostedConditionalEscrowClient
    assert captured[0].caller_role == "storefront"
    assert captured[0].timeout_seconds == 10.0


@pytest.mark.asyncio
async def test_stripe_option_builder_is_deterministic_and_buyer_compatible() -> None:
    config = _config()
    registration = create_stripe_registration()
    readiness = await registration.preflight(
        config,
        {
            "marketplace_signer": FakeSigner(),
            "preflight_client": ObservationalClient(),
        },
        "seller",
    )
    resources = {
        "claimant_principal": _identity(8),
        "rate_minor_units": 125,
    }

    first = registration.option_builder(config, readiness, resources, "seller")
    second = registration.option_builder(config, readiness, resources, "seller")

    assert first == second
    assert first["accepted_escrows"] == []
    option = first["settlement_options"][0]
    assert option["mechanism"] == MECHANISM
    assert option["asset"] == "usd"
    assert option["rates"] == [{"field": "amount", "per": "hour", "value": "125"}]
    assert registration.buyer_compatibility(config, option, {"currencies": {"usd"}})
