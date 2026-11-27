"""A resumed Alkahest settlement reports a seller's refusal once and does not retry it."""

from __future__ import annotations

import io
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest
import typer
from arkhai_api_buying.stages import SettlementResume
from market_identity import Eip191Signer
from rich.console import Console

from arkhai_api_buying_alkahest.stage import AlkahestBuyerStage

# Deterministic development keys for these tests only; never used on any network.
_SIGNER = Eip191Signer(bytes.fromhex("11" * 32))
_WALLET = ("0x" + "cc" * 20, "0x" + "11" * 32)
_CHAIN = SimpleNamespace(name="anvil", rpc_url="http://anvil:8545", chain_id=31337, alkahest_address_config_path=None)
_ESCROW_UID = "0x" + "ee" * 32
_REFUSAL = "key_out_of_scope"

# What finishing a settlement reads of a domain's buying contributions.
CONTRIBUTIONS = SimpleNamespace(command_path="market example", rendering=SimpleNamespace(summary_header="Product"))


@dataclass(frozen=True)
class _Resume(SettlementResume):
    """A recovered deal whose run log, buy configuration, and seller trust are doubles."""

    log: Any = None

    def open_log(self) -> Any:
        return self.log

    def buy_config(self) -> Any:
        return SimpleNamespace()

    def seller_principals(self, log: Any, config: Any) -> Any:
        return MagicMock(name="seller_principals")


@pytest.fixture
def config_home(tmp_path, monkeypatch):
    """An empty user configuration, so the chain names no Alkahest address book."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))


def _resume(log: Any, console: Console) -> _Resume:
    deal = SimpleNamespace(
        accepted_escrow_proposal={"chain_name": "anvil"},
        escrow_uid=_ESCROW_UID,
        seller_url="http://seller:8002",
        listing_id="lst-1",
        negotiation_id="neg-1",
        agreed_amount=300,
        buyer_principal=_SIGNER.identity,
    )
    return _Resume(
        contributions=CONTRIBUTIONS,
        run_id="run-topup-1",
        deal=deal,
        identity=SimpleNamespace(signer=_SIGNER),
        settlement_config=lambda: None,
        options={},
        poll_interval=0.0,
        settlement_timeout=1.0,
        console=console,
        credential_store=MagicMock(name="credential_store"),
        log=log,
    )


def test_a_settlement_the_seller_refuses_is_reported_once_and_not_retried(config_home):
    submit = MagicMock(return_value={"status": "queued"})
    wait = MagicMock(return_value={"status": "failed", "reason": _REFUSAL})
    resolve_chain = MagicMock(return_value=_CHAIN)
    stage = AlkahestBuyerStage(
        wallet=MagicMock(return_value=_WALLET), submit_settlement=submit, wait_settlement=wait, resolve_chain=resolve_chain,
    )
    log = MagicMock(name="log", run_id="run-topup-1", secrets=frozenset())
    output = io.StringIO()

    with pytest.raises(typer.Exit) as exited:
        stage.resume(_resume(log, Console(file=output, width=200)))

    assert exited.value.exit_code == 7
    assert output.getvalue().count(_REFUSAL) == 1
    assert (submit.call_count, wait.call_count) == (1, 1)
    resolve_chain.assert_called_once_with("anvil")
    assert submit.call_args.kwargs["escrow_uid"] == _ESCROW_UID
    assert submit.call_args.kwargs["payload"]["chain_name"] == "anvil"
    log.end.assert_called_once()
    assert log.end.call_args.args == ("failed",)
