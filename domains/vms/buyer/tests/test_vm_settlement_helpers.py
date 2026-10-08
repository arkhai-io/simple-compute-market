import uuid
from types import SimpleNamespace

import pytest
import typer
from arkhai_vms import make_vm_provision_terms
from core_buyer.buyer_config import ResolvedBuyerIdentity
from market_identity import (
    Ed25519Signer,
)
from arkhai_vms_buyer import (
    common,
    settle_cli,
    settlement_composition,
)
from arkhai_vms_buyer.escrow_selection import select_escrow_entry
from arkhai_vms_settlement import escrow_proposal_from_accepted_entry

_ESCROW = "0x" + "11" * 20
_TOKEN = "0x" + "22" * 20
_OTHER = "0x" + "33" * 20
_ARBITER = "0x" + "44" * 20


def _resolved(signer: Ed25519Signer) -> ResolvedBuyerIdentity:
    return ResolvedBuyerIdentity(
        profile_id=uuid.UUID("11111111-1111-4111-8111-111111111111"),
        principal=signer.identity,
        signer=signer,
        source="recovery",
    )


def test_select_escrow_entry_filters_by_chain_and_token():
    listing = {
        "accepted_escrows": [
            {
                "chain_name": "other",
                "escrow_address": _OTHER,
                "literal_fields": {"token": _OTHER},
            },
            {
                "chain_name": "anvil",
                "escrow_address": _ESCROW,
                "literal_fields": {"token": _TOKEN},
            },
        ],
    }

    assert (
        select_escrow_entry(
            listing,
            chain_name="anvil",
            token_contract_filter=_TOKEN,
            assume_yes=True,
            rpc_url="http://rpc",
            buyer_address="0x" + "aa" * 20,
        )["escrow_address"]
        == _ESCROW
    )


def test_escrow_proposal_from_accepted_entry_selects_first_matching_demand():
    entry = {
        "chain_name": "anvil",
        "escrow_address": _ESCROW,
        "literal_fields": {"token": _TOKEN},
        "rates": [{"field": "amount", "per": "hour", "value": "100"}],
    }
    listing = {
        "demands": [
            {"chain_name": "other", "arbiter": _OTHER, "demand_data": {}},
            {"chain_name": "anvil", "arbiter": _ARBITER, "demand_data": {"x": 1}},
            {"arbiter": _ARBITER, "demand_data": {"global": True}},
        ],
    }

    proposal = escrow_proposal_from_accepted_entry(
        listing=listing,
        entry=entry,
        expiration_unix=123,
    )

    assert proposal.chain_name == "anvil"
    assert proposal.escrow_address == _ESCROW
    assert proposal.fields == {"token": _TOKEN}
    assert proposal.literal_fields == {"token": _TOKEN}
    assert [rate.model_dump() for rate in proposal.rates] == entry["rates"]
    assert proposal.expiration_unix == 123
    assert proposal.demand is not None
    assert proposal.demand.arbiter == _ARBITER
    assert proposal.demand.demand_data == {"x": 1}
    assert proposal.demands is None


def test_make_vm_provision_terms_uses_compute_compat_shape():
    terms = make_vm_provision_terms(
        duration_seconds=3600,
        ssh_public_key="ssh-ed25519 example",
    )
    assert terms.duration_seconds == 3600
    assert terms.ssh_public_key == "ssh-ed25519 example"
    assert terms.kind == "compute.v1"


def test_alkahest_resume_settles_without_restating_negotiated_terms(monkeypatch):
    """Settlement names the accepted negotiation and the EVM address only.

    The SSH key and chain are the accepted negotiation's, read by the
    storefront; a rotated local SSH key is never consulted.
    """
    buyer = Ed25519Signer(b"\x34" * 32)
    accepted_ssh = "ssh-ed25519 accepted-key"
    deal = SimpleNamespace(
        settlement_selection=None,
        settlement_plan={
            "obligations": [
                {
                    "payer": "buyer",
                    "claimant": "seller",
                    "amount": "25",
                    "asset": _TOKEN,
                    "expiration_unix": 2_000_000_000,
                    "mechanism": "alkahest.v1",
                    "params": {},
                }
            ]
        },
        accepted_provision_terms=make_vm_provision_terms(
            duration_seconds=7200,
            ssh_public_key=accepted_ssh,
        ).model_dump(mode="json"),
        duration_seconds=3600,
        token_contract=_TOKEN,
        token_decimals=18,
        accepted_escrow_proposal={"chain_name": "anvil"},
        accepted_escrow_terms=None,
        escrow_uid="0x" + "55" * 32,
        seller_url="http://seller",
        negotiation_id="neg-accepted-ssh",
        listing_id="listing-1",
        agreed_amount=25,
        seller_wallet_address=None,
        buyer_principal=buyer.identity,
    )
    submitted = {}

    class _Log:
        def event(self, *_args, **_kwargs):
            return None

        def end(self, *_args, **_kwargs):
            return None

    monkeypatch.setattr(
        common,
        "resolve_recovery_buyer_identity",
        lambda _run_id: _resolved(buyer),
    )
    monkeypatch.setattr(
        common,
        "resolve_buyer_wallet",
        lambda: ("0x" + "66" * 20, "0x" + "77" * 32),
    )
    monkeypatch.setattr(
        common,
        "resolve_ssh_public_key",
        lambda: (_ for _ in ()).throw(
            AssertionError("accepted SSH was replaced by rotated config")
        ),
    )
    monkeypatch.setattr(
        common,
        "chain_by_name",
        lambda _name: SimpleNamespace(name="anvil", rpc_url="http://rpc"),
    )
    monkeypatch.setattr(settle_cli, "load_deal_context", lambda *_a, **_k: deal)
    monkeypatch.setattr(
        settle_cli,
        "make_deal_publisher_trust_resolver",
        lambda *_a, **_k: lambda: None,
    )
    monkeypatch.setattr(settle_cli, "open_run_log", lambda *_a, **_k: _Log())
    monkeypatch.setattr(
        settlement_composition,
        "resolve_alkahest_address_config_path",
        lambda: None,
    )
    monkeypatch.setattr(
        settle_cli,
        "submit_settlement_request",
        lambda **kwargs: submitted.update(kwargs) or {"status": "provisioning"},
    )
    monkeypatch.setattr(
        settle_cli,
        "wait_for_settlement",
        lambda **_kwargs: {"status": "ready"},
    )

    result = settle_cli.run_settle_from_log(
        run_id="run-accepted-ssh",
        poll_interval=0,
        settlement_timeout=1,
    )

    assert result == {"status": "ready"}
    assert submitted["payload"] == {
        "negotiation_id": "neg-accepted-ssh",
        "buyer_evm_address": "0x" + "66" * 20,
    }


def test_current_accepted_state_without_provision_terms_never_uses_config():
    deal = SimpleNamespace(
        accepted_provision_terms=None,
        settlement_selection={
            "mechanism": "alkahest.v1",
            "option_id": "a" * 64,
            "expiration_unix": 2_000_000_000,
        },
        settlement_plan={"obligations": []},
        duration_seconds=3600,
    )

    with pytest.raises(
        typer.BadParameter,
        match="current configuration will not reinterpret this run",
    ):
        settle_cli._accepted_provision_inputs(deal)


def test_recovery_never_falls_back_for_uninstalled_accepted_mechanism(
    monkeypatch,
):
    buyer = Ed25519Signer(b"\x31" * 32)
    deal = SimpleNamespace(
        settlement_selection={
            "mechanism": "future.settlement.v1",
            "option_id": "a" * 64,
            "expiration_unix": 2_000_000_000,
        },
        settlement_plan={
            "obligations": [
                {
                    "payer": "buyer",
                    "claimant": "seller",
                    "amount": "1",
                    "asset": "credit",
                    "expiration_unix": 2_000_000_000,
                    "mechanism": "future.settlement.v1",
                    "params": {},
                }
            ]
        },
        negotiation_id="neg-future",
    )

    class _Log:
        def event(self, *_args, **_kwargs):
            return None

    monkeypatch.setattr(
        common,
        "resolve_recovery_buyer_identity",
        lambda _run_id: _resolved(buyer),
    )
    monkeypatch.setattr(
        common,
        "chain_by_name",
        lambda *_args: (_ for _ in ()).throw(
            AssertionError("fallback touched chain config")
        ),
    )
    monkeypatch.setattr(settle_cli, "load_deal_context", lambda *_args, **_kwargs: deal)
    monkeypatch.setattr(
        settle_cli,
        "make_deal_publisher_trust_resolver",
        lambda *_args, **_kwargs: lambda: None,
    )
    monkeypatch.setattr(settle_cli, "open_run_log", lambda *_args, **_kwargs: _Log())

    with pytest.raises(typer.BadParameter, match="will not fall back"):
        settle_cli.run_settle_from_log(
            run_id="run-future",
            poll_interval=0,
            settlement_timeout=1,
        )
