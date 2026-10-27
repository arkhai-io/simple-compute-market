"""The Alkahest buy session derives its wallet, chain, and price scale, and refuses without them."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
import typer
from arkhai_api_buying.stages import BuyRequest, BuyRun
from market_alkahest.schemas import EscrowProposal
from rich.console import Console

import arkhai_api_buying_alkahest.stage as alkahest_stage
from arkhai_api_buying_alkahest.stage import AlkahestBuyerStage

# A deterministic development address and key for these tests only; never used on any network.
ADDRESS = "0x" + "11" * 20
KEY = "0x" + "22" * 32
CHAIN = SimpleNamespace(name="anvil", rpc_url="http://rpc", chain_id=31337, alkahest_address_config_path=None)
BASE = SimpleNamespace(name="base", rpc_url="http://rpc-base", chain_id=8453, alkahest_address_config_path=None)
TOKEN = "0x" + "ab" * 20


def _request(*, enabled=True, assume_yes=True, **options) -> BuyRequest:
    return BuyRequest(
        identity=SimpleNamespace(),
        settlement=SimpleNamespace(),
        policy=SimpleNamespace(compatible=None, prefer_settlement=None),
        enabled=enabled,
        options=options,
        assume_yes=assume_yes,
        console=Console(),
    )


def _session(wallet, *, chains=None, **request):
    stage = AlkahestBuyerStage(
        wallet=lambda: wallet,
        chains=lambda: {"anvil": CHAIN} if chains is None else chains,
    )
    session = stage.open_buy(_request(**request))
    session.prepare()
    return session


def _proposal(chain: str = "anvil", token: str | None = TOKEN) -> EscrowProposal:
    literal = {"token": token} if token else {}
    return EscrowProposal(
        chain_name=chain, escrow_address="0x" + "cd" * 20, fields=dict(literal),
        literal_fields=literal, rates=[], demands=[], expiration_unix=1_800_000_000,
    )


def _listing(*chains: str) -> dict:
    return {"listing_id": "lst-1", "accepted_escrows": [{"chain_name": chain} for chain in chains]}


@pytest.fixture
def decimals(monkeypatch):
    by_token = {TOKEN: 2, "0x" + "ef" * 20: 6}
    monkeypatch.setattr(
        alkahest_stage, "resolve_token",
        lambda token, **_kw: SimpleNamespace(decimals=by_token[token]),
    )


def test_a_disabled_session_resolves_nothing():
    def wallet():
        raise AssertionError("wallet resolved")

    session = AlkahestBuyerStage(wallet=wallet, chains=lambda: {"anvil": CHAIN}).open_buy(
        _request(enabled=False)
    )
    session.prepare()
    assert not session.available
    assert session.run_fields() == {"buyer_evm_address": None}
    assert session.header_rows() == ()
    assert session.propose(_listing("anvil"), expiration_unix=1) is None


def test_a_configured_wallet_and_chain_make_it_available():
    session = _session((ADDRESS, KEY))
    assert session.available
    assert session.run_fields() == {"buyer_evm_address": ADDRESS}
    assert session.header_rows() == (("EVM chain wallet", ADDRESS),)


def test_a_missing_key_names_what_to_set():
    session = _session((ADDRESS, None), chains={})
    assert not session.available
    assert session.missing() == (
        ("buyer_evm_private_key", "wallet.private_key"),
        ("chain configuration", "chains.<name>"),
    )


def test_the_stage_contributes_no_options():
    assert AlkahestBuyerStage.options == ()


def test_a_listing_on_one_configured_chain_settles_there(monkeypatch):
    chosen = {}

    def entry(listing, *, chain_name, token_contract_filter, **_kw):
        chosen.update(chain=chain_name, token=token_contract_filter)
        return {"chain_name": chain_name}

    monkeypatch.setattr(alkahest_stage, "select_escrow_entry", entry)
    monkeypatch.setattr(alkahest_stage, "escrow_proposal_from_accepted_entry", lambda **kw: kw["entry"])
    session = _session((ADDRESS, KEY), chains={"anvil": CHAIN, "base": BASE})

    assert session.propose(_listing("base"), expiration_unix=1) == {"chain_name": "base"}
    assert chosen == {"chain": "base", "token": None}


def test_a_listing_on_no_configured_chain_is_skipped():
    session = _session((ADDRESS, KEY))
    assert session.propose(_listing("base"), expiration_unix=1) is None


def test_a_listing_on_several_configured_chains_refuses_under_yes(capsys):
    session = _session((ADDRESS, KEY), chains={"anvil": CHAIN, "base": BASE})

    with pytest.raises(typer.Exit) as refused:
        session.propose(_listing("anvil", "base"), expiration_unix=1)

    assert refused.value.exit_code == 2
    err = " ".join(capsys.readouterr().err.split())
    assert "'lst-1'" in err and "['anvil', 'base']" in err


def test_explicit_prices_scale_by_the_selected_token(decimals):
    session = _session((ADDRESS, KEY))
    matches = [{"_selected_buyer_proposal": _proposal()}, {"_selected_buyer_proposal": object()}]
    assert session.scale_explicit_prices(2, 3, matches) == (200, 300)


def test_selected_tokens_of_different_decimals_are_refused(decimals):
    session = _session((ADDRESS, KEY))
    matches = [
        {"_selected_buyer_proposal": _proposal()},
        {"_selected_buyer_proposal": _proposal(token="0x" + "ef" * 20)},
    ]
    with pytest.raises(typer.Exit) as refused:
        session.scale_explicit_prices(2, 3, matches)
    assert refused.value.exit_code == 2


def test_a_native_token_escrow_cannot_scale_explicit_prices():
    session = _session((ADDRESS, KEY))
    with pytest.raises(typer.Exit):
        session.scale_explicit_prices(2, 3, [{"_selected_buyer_proposal": _proposal(token=None)}])


def test_no_alkahest_selection_leaves_prices_as_given():
    session = _session((ADDRESS, KEY))
    assert session.scale_explicit_prices(2, 3, [{"_selected_buyer_proposal": object()}]) == (2, 3)


def test_settlement_builds_its_adapters_on_the_accepted_chain(monkeypatch):
    built = {}
    monkeypatch.setattr(
        alkahest_stage, "make_create_escrow_fn", lambda **kw: built.setdefault("create", kw["chain_name"]),
    )
    monkeypatch.setattr(
        alkahest_stage, "make_escrow_settle_hook", lambda **_kw: lambda negotiation, on_event: "settled",
    )
    session = _session((ADDRESS, KEY), chains={"anvil": CHAIN, "base": BASE})
    outcome = SimpleNamespace(accepted_escrow_proposal=_proposal("base"), settlement_plan={"x": 1})
    run = BuyRun(config=None, quantity=1, poll_interval=0, settlement_timeout=0, interactive=False)

    assert session.settle(SimpleNamespace(outcome=outcome), lambda *_a: None, run) == "settled"
    assert built == {"create": "base"}


def test_an_unavailable_session_leaves_prices_and_refuses_to_settle():
    session = _session((None, None), chains={})
    assert session.scale_explicit_prices(2, 3, [{"_selected_buyer_proposal": _proposal()}]) == (2, 3)
    outcome = SimpleNamespace(accepted_escrow_proposal={"x": 1}, settlement_plan={"x": 1})
    run = BuyRun(config=None, quantity=1, poll_interval=0, settlement_timeout=0, interactive=False)
    with pytest.raises(ValueError, match="Alkahest settlement resources are unavailable"):
        session.settle(SimpleNamespace(outcome=outcome), lambda *_a: None, run)


def test_a_negotiation_records_the_selected_chain():
    stage = AlkahestBuyerStage()
    selected = SimpleNamespace(option=SimpleNamespace(params={"accepted_escrow": {"chain_name": "anvil"}}))
    assert stage.negotiation_run_fields({}, selected) == {"chain_name": "anvil"}
    assert stage.negotiation_run_fields({}, None) == {"chain_name": None}
