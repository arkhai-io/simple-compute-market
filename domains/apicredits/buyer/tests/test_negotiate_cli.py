"""Standalone credits negotiation drives the real signed buyer transport."""

from __future__ import annotations

import base64
import json
import re
import uuid
from types import SimpleNamespace

import pytest
from core_buyer.buyer_config import ResolvedBuyerIdentity
from core_buyer.orchestrator import BuyResult
from core_buyer.registry_config import RegistryAuthority
from core_buyer.run_log import read_run
from market_config.config_loader import ChainConfig
from market_core.schemas import Agreement, RateValue, SettlementOption, derive_settlement_option_id
from market_identity import Ed25519Signer, ResponseEnvelope, TrustedIdentitySet, canonical_body_hash, sign_response
from typer.testing import CliRunner

from arkhai_api_buying import buy as buy_cli
from arkhai_api_buying import common, settlement_composition
from arkhai_api_buying import negotiate as negotiate_cli
from arkhai_api_buying_alkahest import stage as settlement_stages
from arkhai_api_buying_arkhai_payments import payments
from arkhai_apicredits_buyer.cli import app
from test_negotiation_flow import _MockResponse, _request_header

_BUYER = Ed25519Signer(bytes.fromhex("11" * 32))
_SELLER = Ed25519Signer(bytes.fromhex("22" * 32))
_IDENTITY = ResolvedBuyerIdentity(
    profile_id=uuid.UUID("11111111-1111-4111-8111-111111111111"),
    principal=_BUYER.identity, signer=_BUYER, source="primary",
)
_PAYER = "11111111-1111-4111-8111-111111111111"
_TOKEN = "0x" + "ab" * 20
_ENTRY = {
    "chain_name": "anvil", "escrow_address": "0x" + "cd" * 20,
    "literal_fields": {"token": _TOKEN},
    "rates": [{"field": "amount", "per": "token", "value": "100"}],
}
#: The release condition the Alkahest listing advertises, which the buyer selects.
_CONDITION = {
    "chain_name": "anvil", "arbiter": "0x" + "ef" * 20,
    "demand_data": {"recipient": "0x" + "33" * 20},
}


@pytest.fixture
def surface(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    trust = TrustedIdentitySet(identities=(_SELLER.identity,))
    monkeypatch.setattr(common, "resolve_fresh_buyer_identity", lambda: _IDENTITY)
    monkeypatch.setattr(common, "resolve_recovery_buyer_identity", lambda run: _IDENTITY)
    monkeypatch.setattr(common, "resolve_indexer_urls", lambda **kw: ["http://registry"])
    monkeypatch.setattr(common, "resolve_registry_authorities", lambda urls: {
        url: RegistryAuthority(authority="registry", principals=trust) for url in urls
    })
    monkeypatch.setattr(common, "resolve_registry_api_keys", lambda: {})
    monkeypatch.setattr(common, "resolve_indexer_urls_for_schema", lambda *a, **kw: ["http://registry"])
    monkeypatch.setattr(common, "resolve_negotiation_config", lambda: (None, None))
    for name in (
        "resolve_fresh_buyer_identity", "resolve_recovery_buyer_identity",
        "resolve_indexer_urls", "resolve_registry_authorities",
        "resolve_registry_api_keys", "resolve_indexer_urls_for_schema",
        "resolve_negotiation_config",
    ):
        monkeypatch.setattr(negotiate_cli, name, getattr(common, name))
    config = {
        "Settlement": {
            "schema_version": 1,
            "priority": ["arkhai.payments.v1", "alkahest.v1"],
            "alkahest": {"enabled": True},
            "arkhai_payments": {"enabled": True},
        },
        "apicredits": {"payer_account": _PAYER},
    }
    monkeypatch.setattr(settlement_composition, "load_user_config", lambda: config)
    monkeypatch.setattr(payments, "load_user_config", lambda: config)
    state = SimpleNamespace(config=config, requests=[], opening=None)

    def configure(mechanism):
        params = {"accepted_escrow": _ENTRY} if mechanism == "alkahest.v1" else {
            "payee_account": "22222222-2222-4222-8222-222222222222", "asset": "USD",
        }
        asset = _TOKEN if mechanism == "alkahest.v1" else "USD"
        rates = [RateValue(field="amount", per="token", value=100)]
        option = SettlementOption(
            mechanism=mechanism, asset=asset, rates=rates, params=params,
            option_id=derive_settlement_option_id(
                mechanism=mechanism, asset=asset, rates=rates, params=params,
            ),
        )
        listing = {
            "listing_id": "credits-1", "storefront_url": "http://seller",
            "publisher_id": "publisher", "publisher_principals": trust.model_dump(mode="json"),
            "settlement_options": [option.model_dump(mode="json")],
            "accepted_escrows": [_ENTRY] if mechanism == "alkahest.v1" else [],
            "demands": [_CONDITION] if mechanism == "alkahest.v1" else [],
        }
        monkeypatch.setattr(common, "fetch_listing_dict", lambda *a, **kw: dict(listing))
        monkeypatch.setattr("core_buyer.orchestration.fetch_listing_dict", lambda *a, **kw: dict(listing))
        monkeypatch.setattr("arkhai_api_buying.negotiate.fetch_listing_dict", lambda *a, **kw: dict(listing))
        state.option = option
        return state

    state.configure = configure
    return state


def _transport(monkeypatch, state, actions):
    actions = iter(actions)

    def send(req, timeout=None):
        body = json.loads(req.data)
        state.requests.append((req.full_url, body))
        opening = req.full_url.endswith("/negotiate/new")
        if opening:
            state.opening = body
        action = next(actions)
        if action == "crash":
            raise RuntimeError("controlled connection loss")
        proposal = body.get("proposal") or state.opening["proposal"]
        payload = {
            "negotiation_id": "neg-1", "action": action, "proposal": proposal,
            "buyer_principal": _BUYER.identity.model_dump(mode="json"),
            "seller_principal": _SELLER.identity.model_dump(mode="json"),
            "accepted_provision_terms": state.opening["provision_terms"],
        }
        selection = proposal.get("settlement_selection")
        if selection:
            payload["settlement_selection"] = selection
        if action == "accept":
            agreement = Agreement(
                negotiation_id="neg-1", listing_id="credits-1", listing_hash="0" * 64,
                buyer=payload["buyer_principal"], seller=payload["seller_principal"],
                settlement=state.option, settlement_params=selection["params"],
                amount=proposal["fields"]["amount"], asset=state.option.asset,
                duration_seconds=0, start_utc="2025-01-01T00:00:00Z",
                accepted_at="2025-01-01T00:00:00Z",
                provision_terms=payload["accepted_provision_terms"],
            )
            payload["agreement"] = agreement.model_dump(mode="json", exclude_none=True)
            payload["agreement_bytes"] = base64.b64encode(
                agreement.model_dump_json(exclude_none=True).encode(),
            ).decode()
            payload["settlement_data"] = {"mandate": {"controlled": True}}
        signed = sign_response(
            signer=_SELLER,
            envelope=ResponseEnvelope(
                role="seller", principal=_SELLER.identity,
                method="POST", operation="negotiate_new" if opening else "negotiate_continue",
                resource="credits-1" if opening else "neg-1",
                request_id=_request_header(req, "X-Market-Request-ID"),
                timestamp=int(_request_header(req, "X-Market-Timestamp")),
                status=200, body_hash=canonical_body_hash(payload),
            ),
        )
        return _MockResponse(200, json.dumps(payload), {
            "X-Market-Signature-Version": signed.protocol,
            "X-Market-Identity-Scheme": signed.principal.scheme.value,
            "X-Market-Identity-Identifier": signed.principal.identifier,
            "X-Market-Role": signed.role,
            "X-Market-Request-ID": signed.request_id,
            "X-Market-Timestamp": str(signed.timestamp),
            "X-Market-Signature": signed.proof.value,
        })

    monkeypatch.setattr("core_buyer.negotiation_client.urllib.request.urlopen", send)


def _fresh(*prices):
    result = CliRunner().invoke(app, [
        "credits", "negotiate", "--listing-id", "credits-1", "--quantity", "4", "--yes", *prices,
    ])
    print(result.output)
    return result


def _run_id(result):
    match = re.search(r"\b[0-9a-f]{32}\b", result.output)
    assert match is not None, result.output
    return match.group()


@pytest.mark.parametrize("prices,amount", [
    (("--initial-price", "2", "--max-price", "3"), 8),
    ((), 400),
])
def test_payment_only_cli_is_wallet_free_and_preserves_accepted_state(surface, monkeypatch, prices, amount):
    state = surface.configure("arkhai.payments.v1")
    _transport(monkeypatch, state, ["accept"])
    result = _fresh(*prices)
    assert result.exit_code == 0, (result.output, result.exception)
    opening = state.opening
    assert opening["proposal"]["fields"]["amount"] == str(amount)
    assert opening["proposal"]["settlement_selection"]["params"] == {"payer_account": _PAYER}
    events = read_run(_run_id(result), signer=_BUYER)
    accepted = events[-1]
    assert accepted["settlement_selection"] == opening["proposal"]["settlement_selection"]
    assert json.loads(base64.b64decode(accepted["agreement_bytes"]))["amount"] == str(amount)
    assert accepted["settlement_data"] == {"mandate": {"controlled": True}}


def test_payment_cli_resume_uses_recorded_selection_without_fresh_admission(surface, monkeypatch):
    state = surface.configure("arkhai.payments.v1")
    _transport(monkeypatch, state, ["counter", "crash"])
    interrupted = _fresh("--initial-price", "2", "--max-price", "3")
    assert interrupted.exit_code == 3, (interrupted.output, interrupted.exception)
    run_id = _run_id(interrupted)
    state.config["Settlement"]["arkhai_payments"]["enabled"] = False
    _transport(monkeypatch, state, ["accept"])
    resumed = CliRunner().invoke(app, ["credits", "negotiate", "--from", run_id, "--yes"])
    print(resumed.output)
    assert resumed.exit_code == 0, resumed.output
    assert state.requests[-1][0].endswith("/negotiate/neg-1")
    assert state.requests[-1][1]["proposal"] == state.opening["proposal"]
    assert state.requests[-1][1]["proposal"]["fields"]["amount"] == "8"


@pytest.mark.parametrize("prices,amount", [
    (("--initial-price", "2", "--max-price", "3"), 800),
    ((), 400),
])
def test_alkahest_cli_scales_explicit_prices_by_the_selected_token(surface, monkeypatch, prices, amount):
    state = surface.configure("alkahest.v1")
    chain = ChainConfig(name="anvil", rpc_url="http://rpc", chain_id=31337)
    monkeypatch.setattr(settlement_stages, "buyer_chains", lambda: {"anvil": chain})
    monkeypatch.setattr(settlement_stages, "resolve_buyer_wallet", lambda: ("0x" + "11" * 20, None))
    read = []

    def resolve_token(token, **kw):
        read.append((token, kw["chain_id"]))
        return SimpleNamespace(decimals=2)

    monkeypatch.setattr(settlement_stages, "resolve_token", resolve_token)
    _transport(monkeypatch, state, ["exit"])
    result = _fresh(*prices)
    assert result.exit_code == 4, (result.output, result.exception)
    proposal = state.opening["proposal"]
    assert proposal["fields"]["amount"] == str(amount)
    assert proposal["chain_name"] == "anvil"
    assert proposal["escrow_address"] == _ENTRY["escrow_address"]
    assert proposal["fields"]["token"] == _TOKEN
    assert read == ([(_TOKEN, 31337)] if prices else [])


def test_selected_alkahest_refuses_missing_wallet_before_seller_request(surface, monkeypatch):
    state = surface.configure("alkahest.v1")
    _transport(monkeypatch, state, ["exit"])
    result = _fresh("--initial-price", "2", "--max-price", "3")
    assert result.exit_code == 2, (result.output, result.exception)
    assert "Missing EVM address" in result.output
    assert state.requests == []


def test_negotiate_refuses_a_listing_on_several_configured_chains_under_yes(surface, monkeypatch):
    state = surface.configure("alkahest.v1")
    anvil = ChainConfig(name="anvil", rpc_url="http://rpc", chain_id=31337)
    other = ChainConfig(name="base", rpc_url="http://rpc-base", chain_id=8453)
    monkeypatch.setattr(settlement_stages, "buyer_chains", lambda: {"anvil": anvil, "base": other})
    monkeypatch.setattr(settlement_stages, "resolve_buyer_wallet", lambda: ("0x" + "11" * 20, None))
    listing = common.fetch_listing_dict()
    second = {**_ENTRY, "chain_name": "base"}
    option = state.option.model_copy(update={
        "params": {"accepted_escrow": second},
        "option_id": derive_settlement_option_id(
            mechanism="alkahest.v1", asset=_TOKEN, rates=state.option.rates,
            params={"accepted_escrow": second},
        ),
    })
    listing["settlement_options"].append(option.model_dump(mode="json"))
    listing["accepted_escrows"].append(second)
    monkeypatch.setattr("arkhai_api_buying.negotiate.fetch_listing_dict", lambda *a, **kw: dict(listing))
    _transport(monkeypatch, state, ["exit"])

    result = _fresh()

    assert result.exit_code == 2, (result.output, result.exception)
    output = " ".join(result.output.split())
    assert "'credits-1'" in output and "['anvil', 'base']" in output
    assert state.requests == []


def test_buy_scales_explicit_prices_by_the_selected_listings_token(surface, monkeypatch):
    surface.configure("alkahest.v1")
    chain = ChainConfig(name="anvil", rpc_url="http://rpc", chain_id=31337)
    monkeypatch.setattr(settlement_stages, "buyer_chains", lambda: {"anvil": chain})
    # A deterministic development key for this test only; never used on any network.
    monkeypatch.setattr(settlement_stages, "resolve_buyer_wallet", lambda: ("0x" + "11" * 20, "0x" + "77" * 32))
    monkeypatch.setattr(
        settlement_stages, "resolve_token", lambda token, **_kw: SimpleNamespace(decimals=2),
    )
    for name in (
        "resolve_fresh_buyer_identity", "resolve_indexer_urls", "resolve_registry_authorities",
        "resolve_registry_api_keys", "resolve_indexer_urls_for_schema", "resolve_negotiation_config",
    ):
        monkeypatch.setattr(buy_cli, name, getattr(common, name))
    monkeypatch.setattr(buy_cli, "resolve_discovery_timeout", lambda **_kw: 1.0)
    monkeypatch.setattr(
        buy_cli, "query_registry_for_matches_multi",
        lambda *a, **kw: [common.fetch_listing_dict("http://registry", "credits-1")],
    )
    monkeypatch.setattr(buy_cli, "load_buyer_chain", lambda *a, **kw: None)
    seen = {}

    def run_buy(*, constraints, matches, **_kw):
        seen.update(initial=constraints.initial_price, maximum=constraints.max_price, matches=matches)
        return BuyResult(status="exited", reason="stopped by the test")

    monkeypatch.setattr(buy_cli, "run_buy", run_buy)

    result = CliRunner().invoke(app, [
        "credits", "buy", "--quantity", "4", "--initial-price", "2", "--max-price", "3", "--yes",
    ])

    assert result.exit_code == 4, (result.output, result.exception)
    assert (seen["initial"], seen["maximum"]) == (200, 300)
    assert [match["listing_id"] for match in seen["matches"]] == ["credits-1"]


def test_buy_refuses_explicit_prices_across_mechanisms_of_different_units(surface, monkeypatch):
    surface.configure("arkhai.payments.v1")
    payment_listing = {**common.fetch_listing_dict(), "listing_id": "credits-2"}
    surface.configure("alkahest.v1")
    escrow_listing = common.fetch_listing_dict()
    chain = ChainConfig(name="anvil", rpc_url="http://rpc", chain_id=31337)
    monkeypatch.setattr(settlement_stages, "buyer_chains", lambda: {"anvil": chain})
    # A deterministic development key for this test only; never used on any network.
    monkeypatch.setattr(settlement_stages, "resolve_buyer_wallet", lambda: ("0x" + "11" * 20, "0x" + "77" * 32))
    monkeypatch.setattr(
        settlement_stages, "resolve_token", lambda token, **_kw: SimpleNamespace(decimals=2),
    )
    for name in (
        "resolve_fresh_buyer_identity", "resolve_indexer_urls", "resolve_registry_authorities",
        "resolve_registry_api_keys", "resolve_indexer_urls_for_schema", "resolve_negotiation_config",
    ):
        monkeypatch.setattr(buy_cli, name, getattr(common, name))
    monkeypatch.setattr(buy_cli, "resolve_discovery_timeout", lambda **_kw: 1.0)
    monkeypatch.setattr(
        buy_cli, "query_registry_for_matches_multi",
        lambda *a, **kw: [dict(payment_listing), dict(escrow_listing)],
    )
    monkeypatch.setattr(buy_cli, "load_buyer_chain", lambda *a, **kw: None)

    def run_buy(**_kw):
        raise AssertionError("a buy across units was negotiated")

    monkeypatch.setattr(buy_cli, "run_buy", run_buy)

    result = CliRunner().invoke(app, [
        "credits", "buy", "--quantity", "4", "--initial-price", "2", "--max-price", "3", "--yes",
    ])

    assert result.exit_code == 2, (result.output, result.exception)
    output = " ".join(result.output.split())
    assert "alkahest.v1" in output and "arkhai.payments.v1" in output


@pytest.mark.parametrize("command", ["buy", "negotiate", "settle"])
@pytest.mark.parametrize(
    "flag",
    ["--evm-private-key", "--evm-address", "--chain", "--token-contract", "--token-decimals", "--escrow-uid"],
)
def test_a_mechanism_override_flag_is_refused(command, flag):
    # A deterministic development key for this test only; never used on any network.
    result = CliRunner().invoke(app, ["credits", command, flag, "0x" + "77" * 32])
    assert result.exit_code == 2
    assert "No such option" in result.output
