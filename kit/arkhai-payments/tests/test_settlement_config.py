from __future__ import annotations

import asyncio
import json
import tomllib
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
    resolve_payments_api_key,
)
from market_identity import Ed25519Signer, Eip191Signer
from market_deal_lifecycle.configuration import DisputeEntry
from market_arkhai_payments.fixtures import dispute_lifecycle
from market_settlement_runtime import SettlementPublicationClause

BUYER = "00000000-0000-4000-8000-000000000011"
PAYEE = "00000000-0000-4000-8000-000000000012"
DISPUTE_AUTHORITY = "00000000-0000-4000-8000-000000000013"
API_KEY_ENV = "ARKHAI_PAYMENTS_TEST_API_KEY"
# A public test-only key that authenticates to nothing; never use it on a public
# network.
OVERLAY_KEY = "sk_test_secret_overlay_canary"
SERVICE_IDENTIFIER = Ed25519Signer(bytes(range(32))).identity.identifier


def _resources(clause):
    authority = DisputeEntry.model_validate({
        **dispute_lifecycle(DISPUTE_AUTHORITY)["adjudication"]["dispute"],
        "advertisement": {"mechanisms": [ARKHAI_PAYMENTS_MECHANISM],
                          "minimum_dispute_window_seconds": 0,
                          "minimum_case_hold_seconds": None},
    })
    return {"publication_clause": clause, "dispute_authorities": (authority,),
            "dispute_interfaces": frozenset({authority.interface})}


def _config(**overrides: Any) -> ArkhaiPaymentsConfig:
    values: dict[str, Any] = {
        "enabled": True,
        "service_url": "https://payments.example",
        "service_identity": Ed25519Signer(bytes(range(32))).identity,
        "fee_bps": 250,
        "api_key_env": API_KEY_ENV,
    }
    values.update(overrides)
    return ArkhaiPaymentsConfig.model_validate(values)


def test_config_requires_tls_for_non_loopback_and_pins_ed25519_identity() -> None:
    for retired in (DISPUTE_AUTHORITY, None):
        with pytest.raises(ValueError, match=r"\[\[Dispute\]\]"):
            _config(dispute_authority=retired)
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


@pytest.mark.parametrize(
    "overrides, named",
    [
        ({"api_key": OVERLAY_KEY}, ("api_key", "api_key_env")),
        ({"api_key_env": None, "api_key": OVERLAY_KEY, "development_auth": True,
          "service_url": "http://127.0.0.1:3180"}, ("development_auth", "api_key")),
        ({"development_auth": True, "service_url": "http://127.0.0.1:3180"},
         ("development_auth", "api_key_env")),
        ({"enabled": False, "api_key": OVERLAY_KEY}, ("api_key", "api_key_env")),
    ],
    ids=["both-key-forms", "key-with-development-auth", "variable-with-development-auth",
         "both-key-forms-disabled"],
)
def test_conflicting_key_forms_are_refused_naming_both(overrides, named) -> None:
    with pytest.raises(ValueError) as refused:
        _config(**overrides)
    message = str(refused.value)
    assert all(form in message for form in named)
    assert OVERLAY_KEY not in message


def test_a_validation_error_never_shows_a_stated_key() -> None:
    # Short enough that an error would print it whole if it showed its input.
    with pytest.raises(ValueError) as refused:
        _config(api_key="tok")
    assert "tok" not in str(refused.value)


@pytest.mark.parametrize("key", ["", "   ", "two\nlines"], ids=["empty", "blank", "multi-line"])
def test_an_unusable_api_key_is_refused_without_echoing_it(key) -> None:
    with pytest.raises(ValueError, match="api_key must be a nonempty single-line key") as refused:
        _config(api_key_env=None, api_key=key)
    if key.strip():
        assert key not in str(refused.value)


@pytest.mark.parametrize("path", ["", "  "], ids=["empty", "blank"])
def test_an_empty_ca_bundle_path_is_refused(path) -> None:
    with pytest.raises(ValueError, match="ca_bundle_path must name a file"):
        _config(ca_bundle_path=path)


def test_api_key_from_toml_text_validates_strictly_and_never_shows() -> None:
    document = tomllib.loads(
        f"""
        enabled = true
        service_url = "https://payments.example"
        service_identity = {{ scheme = "ed25519", identifier = "{SERVICE_IDENTIFIER}" }}
        fee_bps = 250
        api_key = "{OVERLAY_KEY}"
        ca_bundle_path = "/run/payments-lane-double/lane-ca.pem"
        """
    )
    config = ArkhaiPaymentsConfig.model_validate(document)

    assert config.api_key is not None
    assert config.api_key.get_secret_value() == OVERLAY_KEY
    assert config.ca_bundle_path == "/run/payments-lane-double/lane-ca.pem"
    assert OVERLAY_KEY not in repr(config)
    assert OVERLAY_KEY not in config.model_dump_json()
    assert OVERLAY_KEY not in json.dumps(config.model_dump(mode="json"))
    assert ArkhaiPaymentsConfig.model_fields["api_key"].json_schema_extra == {"secret": True}


def test_the_key_resolves_from_whichever_form_is_stated() -> None:
    stated = _config(api_key_env=None, api_key=OVERLAY_KEY)
    assert resolve_payments_api_key(
        stated, environment={API_KEY_ENV: "unread"}
    ).get_secret_value() == OVERLAY_KEY
    named = _config()
    assert resolve_payments_api_key(
        named, environment={API_KEY_ENV: "from-variable"}
    ).get_secret_value() == "from-variable"

    with pytest.raises(ArkhaiPaymentsConfigurationError, match=API_KEY_ENV):
        resolve_payments_api_key(named, environment={})
    with pytest.raises(ArkhaiPaymentsConfigurationError, match=API_KEY_ENV):
        resolve_payments_api_key(named, environment={API_KEY_ENV: "two\nlines"})
    with pytest.raises(ArkhaiPaymentsConfigurationError, match="api_key or api_key_env"):
        resolve_payments_api_key(_config(api_key_env=None), environment={})


def test_the_key_resolves_from_the_process_environment_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(API_KEY_ENV, "from-process")
    assert resolve_payments_api_key(_config()).get_secret_value() == "from-process"


def test_preflight_reads_a_stated_key_and_no_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(API_KEY_ENV, raising=False)
    ready = asyncio.run(arkhai_payments_preflight(
        _config(api_key_env=None, api_key=OVERLAY_KEY), {}, "seller"))
    assert ready.ready
    assert OVERLAY_KEY not in repr(ready)


def test_preflight_names_both_key_forms_when_neither_is_stated() -> None:
    readiness = asyncio.run(arkhai_payments_preflight(_config(api_key_env=None), {}, "seller"))
    assert [(blocker.code, blocker.kind) for blocker in readiness.blockers] == [
        ("arkhai_payments.api_key_missing", "configuration")
    ]
    message = readiness.blockers[0].message
    assert "api_key" in message and "api_key_env" in message


def test_preflight_checks_configured_environment_name_without_exposing_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(API_KEY_ENV, raising=False)
    config = _config()
    readiness = asyncio.run(arkhai_payments_preflight(config, {}, "seller"))

    assert not readiness.ready
    assert [(blocker.code, blocker.kind) for blocker in readiness.blockers] == [
        ("arkhai_payments.credential_missing", "configuration")
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
                "dispute_window_seconds": 604800,
            },
        }
    )

    built = arkhai_payments_option_builder(
        config,
        readiness,
        _resources(clause),
        "seller",
    )
    unselected = {key: value for key, value in _resources(clause).items()
                  if key != "publication_clause"}
    assert arkhai_payments_option_builder(config, readiness, unselected, "seller") == {
        "accepted_escrows": [], "settlement_options": [],
    }
    registration = create_arkhai_payments_registration()
    option = built["settlement_options"][0]

    assert built["accepted_escrows"] == []
    assert option["settlement"]["schema"] == ARKHAI_PAYMENTS_MECHANISM
    assert option.get("price", {}).get("rates", []) == [
        {"field": "amount", "per": "hour", "value": "125"}
    ]
    assert option["option_id"]
    for unit in ("unit", "item"):
        unit_clause = clause.model_copy(update={"rate": "125", "per": unit})
        unit_option = arkhai_payments_option_builder(
            config, readiness, _resources(unit_clause), "seller"
        )["settlement_options"][0]
        assert unit_option.get("price", {}).get("rates", []) == [
            {"field": "amount", "per": unit, "value": "125"}
        ]
        assert unit_option["settlement"] == option["settlement"]
    assert registration.client_factory is None
    assert registration.accepted_obligation_builder is None
    assert registration.settlement_verifier is None
    assert registration.buyer_compatibility(config, option, {})
    assert not registration.buyer_compatibility(
        config,
        {**option, "price": {**option["price"], "asset": "not-an-asset"}},
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
        "dispute_window_seconds": 604800,
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
                _resources(clause),
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
        "ca_bundle": None,
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
        "ca_bundle": None,
        "development_account": BUYER,
    }
    stated = payments_client_for_owner(
        _config(api_key_env=None, api_key=OVERLAY_KEY, ca_bundle_path="/run/ca/lane-ca.pem"),
        PAYEE,
        environment={},
    )
    assert stated == {
        "timeout": 10.0,
        "transport": None,
        "ca_bundle": "/run/ca/lane-ca.pem",
        "api_key": OVERLAY_KEY,
    }
    assert calls == [
        ("https://payments.example", prod),
        ("http://localhost:3180", dev),
        ("https://payments.example", stated),
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
    assert [(blocker.code, blocker.kind) for blocker in seller.blockers] == [
        ("arkhai_payments.attach_agreement_buyer_only", "configuration")
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
