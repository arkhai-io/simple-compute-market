"""A resumed Alkahest settlement reports a seller's refusal once and does not retry it.

The seller calls are doubled at the stage's injected submit and status-poll
collaborators; the chain configuration, the wallet, the registry trust, and the
run log are the buyer's real ones.
"""

from __future__ import annotations

import io
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import typer
from arkhai_api_buying.credentials import FileCredentialStore
from arkhai_api_buying.stages import SettlementResume
from core_buyer.buyer_config import ResolvedBuyerIdentity
from core_buyer.run_log import RunLog, read_run
from market_identity import Ed25519Signer, Eip191Signer, TrustedIdentitySet
from rich.console import Console

from arkhai_api_buying_alkahest.stage import AlkahestBuyerStage

# Deterministic development keys for these tests only; never used on any network.
_PRIVATE_KEY = "0x" + "11" * 32
_SIGNER = Eip191Signer(bytes.fromhex("11" * 32))
_REGISTRY = Ed25519Signer(b"\x05" * 32)
_SELLER = Ed25519Signer(b"\x07" * 32)
_REGISTRY_URL = "http://registry:8000"
_ESCROW_UID = "0x" + "ee" * 32
_REFUSAL = "key_out_of_scope"

# What finishing a settlement reads of a domain's buying contributions.
CONTRIBUTIONS = SimpleNamespace(command_path="market example", rendering=SimpleNamespace(summary_header="Product"))


@pytest.fixture
def buyer_home(tmp_path, monkeypatch):
    """A buyer configuration naming the anvil chain, the wallet, and the pinned registry, and an empty state directory."""
    config = tmp_path / "config" / "arkhai"
    config.mkdir(parents=True)
    registry = _REGISTRY.identity.model_dump(mode="json")
    (config / "buyer.toml").write_text(
        '[chains.anvil]\nrpc_url = "http://anvil:8545"\nchain_id = 31337\n\n'
        f'[wallet]\nprivate_key = "{_PRIVATE_KEY}"\n\n'
        f'[registry]\nurls = ["{_REGISTRY_URL}"]\n\n'
        f'[registry.authorities."{_REGISTRY_URL}"]\nauthority = "registry"\n'
        f'identities = [{{ scheme = "{registry['scheme']}", identifier = "{registry['identifier']}" }}]\n'
    )
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))


def _resume(identity: ResolvedBuyerIdentity, run_id: str, console: Console) -> SettlementResume:
    deal = SimpleNamespace(
        accepted_escrow_proposal={"chain_name": "anvil"},
        escrow_uid=_ESCROW_UID,
        seller_url="http://seller:8002",
        listing_id="lst-1",
        publisher_id="pub-1",
        publisher_principals=TrustedIdentitySet(identities=(_SELLER.identity,)),
        source_registry_url=_REGISTRY_URL,
        source_registry_authority="registry",
        negotiation_id="neg-1",
        agreed_amount=300,
        buyer_principal=_SIGNER.identity,
    )
    return SettlementResume(
        contributions=CONTRIBUTIONS,
        run_id=run_id,
        deal=deal,
        identity=identity,
        settlement_config=lambda: None,
        options={},
        poll_interval=0.0,
        settlement_timeout=1.0,
        console=console,
        credential_store=FileCredentialStore(),
    )


def test_a_settlement_the_seller_refuses_is_reported_once_and_not_retried(buyer_home):
    identity = ResolvedBuyerIdentity(
        profile_id=uuid.uuid4(), principal=_SIGNER.identity, signer=_SIGNER, source="recovery",
    )
    run_id = RunLog.start(profile_id=identity.profile_id, principal=identity.principal).run_id
    submit = MagicMock(return_value={"status": "queued"})
    wait = MagicMock(return_value={"status": "failed", "reason": _REFUSAL})
    stage = AlkahestBuyerStage(submit_settlement=submit, wait_settlement=wait)
    output = io.StringIO()

    with pytest.raises(typer.Exit) as exited:
        stage.resume(_resume(identity, run_id, Console(file=output, width=200)))

    assert exited.value.exit_code == 7
    assert output.getvalue().count(_REFUSAL) == 1
    assert (submit.call_count, wait.call_count) == (1, 1)
    assert submit.call_args.kwargs["escrow_uid"] == _ESCROW_UID
    assert submit.call_args.kwargs["payload"]["chain_name"] == "anvil"
    events = read_run(run_id, signer=_SIGNER, profile_id=identity.profile_id)
    names = [event["event"] for event in events]
    assert names.index("settle_resumed") < names.index("settle_submitted") < names.index("settle_terminal")
    assert events[-1]["event"] == "run_ended"
    assert events[-1]["status"] == "failed"
