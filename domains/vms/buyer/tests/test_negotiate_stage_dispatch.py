"""Fresh standalone negotiation preserves stage-owned prices and prerequisites."""

from types import SimpleNamespace

import pytest
from core_buyer.registry_config import RegistryAuthority
from market_config.config_loader import ChainConfig
from market_core.schemas import RateValue, derive_settlement_option_id
from typer.testing import CliRunner

from arkhai_vms_buyer.cli import app
from arkhai_vms_buyer.buyer_client import NegotiationOutcome
from identity_helpers import seller_principals
from test_buy_resume_cli import _RESOLVED


@pytest.fixture
def negotiation(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    monkeypatch.setattr("arkhai_vms_buyer.common.resolve_fresh_buyer_identity", lambda: _RESOLVED)
    monkeypatch.setattr("arkhai_vms_buyer.common.resolve_registry_authorities", lambda urls: {
        url: RegistryAuthority(authority="registry", principals=seller_principals()) for url in urls
    })
    monkeypatch.setattr("arkhai_vms_buyer.common.resolve_indexer_urls_for_schema", lambda _schema, **kw: list(kw["registry_authorities"]))
    monkeypatch.setattr("arkhai_vms_buyer.common.resolve_registry_api_keys", lambda: {})
    monkeypatch.setattr("arkhai_vms_buyer.common.resolve_negotiation_config", lambda: (None, None))
    monkeypatch.setattr("arkhai_vms_buyer.negotiate_cli.resolve_negotiation_config", lambda: (None, None))
    captured = {}

    def negotiate(**fields):
        captured.update(fields)
        return NegotiationOutcome(
            status="exited", negotiation_id="neg-1",
            reason="controlled stop after opening", rounds=0,
        )

    monkeypatch.setattr("arkhai_vms_buyer.negotiate_cli.negotiate_with_seller", negotiate)
    return captured


def _listing(mechanism):
    entry = {
        "chain_name": "anvil", "escrow_address": "0x" + "aa" * 20,
        "literal_fields": {"token": "0x" + "bb" * 20},
        "rates": [{"field": "amount", "per": "hour", "value": "100"}],
    }
    params = {"accepted_escrow": entry} if mechanism == "alkahest.v1" else {
        "payee_account": "22222222-2222-4222-8222-222222222222", "asset": "USD",
    }
    asset = "0x" + "bb" * 20 if mechanism == "alkahest.v1" else "USD"
    rates = [RateValue(field="amount", per="hour", value=100)]
    return {
        "listing_id": "L-1", "storefront_url": "http://seller", "publisher_id": "publisher",
        "publisher_principals": seller_principals().model_dump(mode="json"),
        "accepted_escrows": [entry], "settlement_options": [{
            "mechanism": mechanism, "option_id": derive_settlement_option_id(
                mechanism=mechanism, asset=asset, rates=rates, params=params,
            ), "asset": asset, "rates": rates, "params": params,
        }],
    }


def _configure(monkeypatch, mechanism, wallet=True):
    listing = _listing(mechanism)
    monkeypatch.setattr("arkhai_vms_buyer.negotiate_cli.fetch_listing_dict", lambda *a, **kw: listing)
    monkeypatch.setattr("arkhai_vms_buyer.settlement_composition.load_user_config", lambda: {
        "Settlement": {
            "schema_version": 1, "priority": [mechanism],
            "alkahest": {"enabled": mechanism == "alkahest.v1"},
            "arkhai_payments": {"enabled": mechanism == "arkhai.payments.v1"},
        }
    })
    monkeypatch.setattr("arkhai_vms_buyer.common.chain_by_name", lambda name: ChainConfig(
        name=name, rpc_url="http://rpc", chain_id=31337,
    ))
    monkeypatch.setattr("arkhai_vms_buyer.common.resolve_buyer_wallet", lambda: ("address", "key") if wallet else (None, None))
    monkeypatch.setattr("arkhai_vms_buyer.settlement_stages.resolve_token", lambda *a, **kw: SimpleNamespace(decimals=2))
    monkeypatch.setattr("arkhai_vms_buyer.arkhai_payments.load_user_config", lambda: {
        "vms": {"payer_account": "11111111-1111-4111-8111-111111111111"},
    })
    return listing


def _run(*prices):
    return CliRunner().invoke(app, [
        "negotiate", "--listing-id", "L-1", "--registry-urls", "http://registry",
        "--duration-hours", "1", "--ssh-public-key", "ssh-ed25519 AAAA", "--yes", *prices,
    ])


@pytest.mark.parametrize("mechanism,expected", [("alkahest.v1", 200), ("arkhai.payments.v1", 2)])
def test_selected_stage_controls_fresh_prices_and_proposal(negotiation, monkeypatch, mechanism, expected):
    _configure(monkeypatch, mechanism)
    result = _run("--initial-price", "2", "--max-price", "3")
    assert result.exit_code == 4, (result.output, result.exception)
    assert negotiation["initial_price"] == expected
    assert negotiation["max_price"] == expected * 1.5
    assert negotiation["escrow_proposal"] is None
    assert negotiation["settlement_selection"].mechanism == mechanism
    if mechanism == "arkhai.payments.v1":
        assert negotiation["settlement_selection"].params == {"payer_account": "11111111-1111-4111-8111-111111111111"}


def test_alkahest_wallet_guard_stops_before_negotiation(negotiation, monkeypatch):
    _configure(monkeypatch, "alkahest.v1", wallet=False)
    result = _run("--initial-price", "2", "--max-price", "3")
    assert result.exit_code != 0
    assert "requires [Wallet] credentials" in result.output
    assert not negotiation


def test_alkahest_derived_price_is_not_scaled_twice(negotiation, monkeypatch):
    _configure(monkeypatch, "alkahest.v1")
    result = _run()
    assert result.exit_code == 4, (result.output, result.exception)
    assert negotiation["initial_price"] == 100
    assert negotiation["max_price"] == 100
