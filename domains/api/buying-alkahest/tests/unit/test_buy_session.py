"""The Alkahest buy session resolves the wallet and chain it settles on, and refuses without them."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
import typer
from arkhai_api_buying.stages import BuyRequest, BuyRun
from rich.console import Console

from arkhai_api_buying_alkahest.stage import AlkahestBuyerStage

# A deterministic development address and key for these tests only; never used on any network.
ADDRESS = "0x" + "11" * 20
KEY = "0x" + "22" * 32
CHAIN = SimpleNamespace(name="anvil", rpc_url="http://rpc", chain_id=31337, alkahest_address_config_path=None)


def _request(*, enabled=True, **options) -> BuyRequest:
    return BuyRequest(
        identity=SimpleNamespace(),
        settlement=SimpleNamespace(),
        policy=SimpleNamespace(compatible=None, prefer_settlement=None),
        enabled=enabled,
        options=options,
        assume_yes=True,
        console=Console(),
    )


def _session(wallet, *, chains=None, **request):
    stage = AlkahestBuyerStage(
        wallet=lambda **_kw: wallet,
        chains=lambda: {"anvil": CHAIN} if chains is None else chains,
    )
    session = stage.open_buy(_request(**request))
    session.prepare()
    return session


def test_a_disabled_session_resolves_nothing():
    def wallet(**_kw):
        raise AssertionError("wallet resolved")

    session = AlkahestBuyerStage(wallet=wallet, chains=lambda: {"anvil": CHAIN}).open_buy(
        _request(enabled=False)
    )
    session.prepare()
    assert not session.available
    assert session.run_fields() == {"buyer_evm_address": None, "chain_name": None}
    assert session.header_rows() == ()
    assert session.propose({}, expiration_unix=1) is None


def test_a_wallet_and_chain_make_it_available():
    session = _session((ADDRESS, KEY))
    assert session.available
    assert session.run_fields() == {"buyer_evm_address": ADDRESS, "chain_name": "anvil"}
    assert session.header_rows() == (("EVM chain wallet", ADDRESS),)


def test_a_missing_key_names_what_to_set():
    session = _session((ADDRESS, None), chains={})
    assert not session.available
    assert session.missing() == (
        ("buyer_evm_private_key", "wallet.private_key"),
        ("chain configuration", "chains.<name>"),
    )


def test_explicit_prices_need_a_token_contract():
    session = _session((ADDRESS, KEY))
    with pytest.raises(typer.Exit) as refused:
        session.scale_explicit_prices(2, 3)
    assert refused.value.exit_code == 2


def test_explicit_prices_scale_by_the_stated_decimals():
    session = _session((ADDRESS, KEY), token_contract="0x" + "ab" * 20, token_decimals=2)
    assert session.scale_explicit_prices(2, 3) == (200, 300)


def test_an_unavailable_session_leaves_prices_and_refuses_to_settle():
    session = _session((None, None), chains={})
    assert session.scale_explicit_prices(2, 3) == (2, 3)
    outcome = SimpleNamespace(accepted_escrow_proposal={"x": 1}, settlement_plan={"x": 1})
    run = BuyRun(config=None, quantity=1, poll_interval=0, settlement_timeout=0, interactive=False)
    with pytest.raises(ValueError, match="Alkahest settlement resources are unavailable"):
        session.settle(SimpleNamespace(outcome=outcome), lambda *_a: None, run)


def test_the_stage_contributes_its_options_to_each_command():
    by_command: dict[str, set[str]] = {}
    for option in AlkahestBuyerStage.options:
        by_command.setdefault(option.command, set()).add(option.name)
    assert by_command == {
        "buy": {"token_contract", "token_decimals", "chain_name", "evm_address", "evm_private_key"},
        "negotiate": {"token_contract", "token_decimals", "chain_name", "evm_address", "evm_private_key"},
        "settle": {"escrow_uid", "chain_name", "evm_address", "evm_private_key"},
    }


def test_a_negotiation_records_the_token_options_and_the_selected_chain():
    stage = AlkahestBuyerStage()
    options = {"token_contract": "0x" + "ab" * 20, "token_decimals": 2}
    selected = SimpleNamespace(option=SimpleNamespace(params={"accepted_escrow": {"chain_name": "anvil"}}))
    assert stage.negotiation_run_fields(options, selected) == {**options, "chain_name": "anvil"}
    assert stage.negotiation_run_fields(options, None)["chain_name"] is None

