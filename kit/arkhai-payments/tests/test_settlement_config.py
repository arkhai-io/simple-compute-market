from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any

import market_arkhai_payments.settlement_config as settlement_config
import pytest
from market_arkhai_payments import PaymentsClient
from market_arkhai_payments.settlement_config import (
    ARKHAI_PAYMENTS_MECHANISM,
    ArkhaiPaymentsConfig,
    ArkhaiPaymentsConfigurationError,
    arkhai_payments_option_builder,
    arkhai_payments_preflight,
    create_arkhai_payments_registration,
    payments_client_for_owner,
)
from market_identity import Ed25519Signer, Eip191Signer
from market_settlement_runtime import SettlementPublicationClause

BUYER = "00000000-0000-4000-8000-000000000011"
PAYEE = "00000000-0000-4000-8000-000000000012"
DISPUTE_AUTHORITY = "00000000-0000-4000-8000-000000000013"
API_KEY_ENV = "ARKHAI_PAYMENTS_TEST_API_KEY"


def _config(**overrides: Any) -> ArkhaiPaymentsConfig:
    values: dict[str, Any] = {
        "enabled": True,
        "service_url": "https://payments.example",
        "service_identity": Ed25519Signer(bytes(range(32))).identity,
        "fee_bps": 250,
        "dispute_authority": DISPUTE_AUTHORITY,
        "api_key_env": API_KEY_ENV,
    }
    values.update(overrides)
    return ArkhaiPaymentsConfig.model_validate(values)


def test_config_requires_tls_for_non_loopback_and_pins_ed25519_identity() -> None:
    with pytest.raises(ValueError, match="HTTPS"):
        _config(service_url="http://payments.example")
    with pytest.raises(ValueError, match="Ed25519"):
        _config(service_identity=Eip191Signer("0x" + "01" * 32).identity)


def test_development_auth_is_explicit_and_loopback_only() -> None:
    with pytest.raises(ValueError, match="loopback"):
        _config(
            service_url="https://payments.example",
            api_key_env=None,
            development_auth=True,
        )

    config = _config(
        service_url="http://127.0.0.1:3180",
        api_key_env=None,
        development_auth=True,
    )
    assert config.development_auth


def test_preflight_checks_configured_environment_name_without_exposing_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(API_KEY_ENV, raising=False)
    config = _config()
    readiness = asyncio.run(arkhai_payments_preflight(config, {}, "seller"))

    assert not readiness.ready
    assert [blocker.code for blocker in readiness.blockers] == [
        "arkhai_payments.credential_missing"
    ]
    assert "secret" not in repr(readiness).lower()

    monkeypatch.setenv(API_KEY_ENV, "never-print-this")
    ready = asyncio.run(arkhai_payments_preflight(config, {}, "seller"))
    assert ready.ready
    assert "never-print-this" not in repr(ready)


def test_publication_builder_preserves_option_identity_and_rate_units(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(API_KEY_ENV, "test-secret")
    config = _config()
    readiness = asyncio.run(arkhai_payments_preflight(config, {}, "seller"))
    clause = SettlementPublicationClause.model_validate(
        {
            "mechanism": ARKHAI_PAYMENTS_MECHANISM,
            "asset": "USD/2",
            "rate": "1.25",
            "per": "hour",
            "mechanism_input": {
                "payee_account": PAYEE,
                "asset": "USD/2",
                "window": "P7D",
                "deposit_agreement": True,
            },
        }
    )

    built = arkhai_payments_option_builder(
        config,
        readiness,
        {"publication_clause": clause},
        "seller",
    )
    registration = create_arkhai_payments_registration()
    option = built["settlement_options"][0]

    assert built["accepted_escrows"] == []
    assert option["mechanism"] == ARKHAI_PAYMENTS_MECHANISM
    assert option["rates"] == [{"field": "amount", "per": "hour", "value": "125"}]
    assert option["option_id"]
    for unit in ("unit", "item"):
        unit_clause = clause.model_copy(update={"rate": "125", "per": unit})
        unit_option = arkhai_payments_option_builder(
            config, readiness, {"publication_clause": unit_clause}, "seller"
        )["settlement_options"][0]
        assert unit_option["rates"] == [
            {"field": "amount", "per": unit, "value": "125"}
        ]
        assert unit_option["params"] == option["params"]
    assert registration.client_factory is None
    assert registration.accepted_obligation_builder is None
    assert registration.settlement_verifier is None
    assert registration.buyer_compatibility(config, option, {})
    assert not registration.buyer_compatibility(
        config,
        {**option, "asset": "EUR/2"},
        {},
    )

    descriptors = {field.descriptor.name for field in registration.clause_fields}
    assert descriptors == {
        "arkhai_payments.payee_account",
        "arkhai_payments.window",
        "arkhai_payments.deposit_agreement",
    }


def test_publication_builder_rejects_precision_loss_and_fractional_base_units(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(API_KEY_ENV, "test-secret")
    config = _config()
    readiness = asyncio.run(arkhai_payments_preflight(config, {}, "seller"))
    input_data = {
        "payee_account": PAYEE,
        "asset": "USD/2",
        "window": "P7D",
        "deposit_agreement": False,
    }

    for rate, unit in (("1.001", "hour"), ("1.25", "day"), ("1.25", "unit")):
        clause = SettlementPublicationClause.model_validate(
            {
                "mechanism": ARKHAI_PAYMENTS_MECHANISM,
                "asset": "USD/2",
                "rate": rate,
                "per": unit,
                "mechanism_input": input_data,
            }
        )
        with pytest.raises(ValueError):
            arkhai_payments_option_builder(
                config,
                readiness,
                {"publication_clause": clause},
                "seller",
            )


def test_owner_client_provider_uses_configured_key_or_development_account(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, Mapping[str, Any]]] = []

    def capture_client(service_url: str, **kwargs: Any) -> PaymentsClient:
        calls.append((service_url, kwargs))
        return kwargs  # type: ignore[return-value]

    monkeypatch.setattr(settlement_config, "PaymentsClient", capture_client)
    prod = payments_client_for_owner(
        _config(),
        PAYEE,
        environment={API_KEY_ENV: "owner-scoped-key"},
    )
    assert prod == {
        "timeout": 10.0,
        "transport": None,
        "api_key": "owner-scoped-key",
    }

    dev_config = _config(
        service_url="http://localhost:3180",
        api_key_env=None,
        development_auth=True,
    )
    dev = payments_client_for_owner(dev_config, BUYER, environment={})
    assert dev == {
        "timeout": 10.0,
        "transport": None,
        "development_account": BUYER,
    }
    assert calls == [
        ("https://payments.example", prod),
        ("http://localhost:3180", dev),
    ]

    with pytest.raises(ArkhaiPaymentsConfigurationError, match="environment variable"):
        payments_client_for_owner(_config(), PAYEE, environment={})


def test_registration_has_no_client_factory_or_settlement_lifecycle() -> None:
    registration = create_arkhai_payments_registration()
    assert registration.client_factory is None
    assert registration.accepted_obligation_builder is None
    assert registration.settlement_verifier is None


def test_attach_agreement_is_a_buyer_setting(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(API_KEY_ENV, "present")
    config = _config(attach_agreement=True)

    seller = asyncio.run(arkhai_payments_preflight(config, {}, "seller"))
    assert [blocker.code for blocker in seller.blockers] == [
        "arkhai_payments.attach_agreement_buyer_only"
    ]
    buyer = asyncio.run(arkhai_payments_preflight(config, {}, "buyer"))
    assert buyer.ready
    assert not _config().attach_agreement


def test_client_factory_serves_a_disabled_mechanism() -> None:
    from market_arkhai_payments import payments_client_for_owner

    config = _config(
        enabled=False, development_auth=True, service_url="http://127.0.0.1:9", api_key_env=None
    )
    with payments_client_for_owner(config, "11111111-1111-4111-8111-111111111111") as client:
        assert client is not None
