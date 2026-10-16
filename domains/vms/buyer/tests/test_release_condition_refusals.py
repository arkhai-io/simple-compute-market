"""The buyer creates no escrow without the release condition the seller accepted.

A seller settles an Alkahest escrow only under the condition it authorized, so
an escrow created under any other would never be released to it. Each path
that would create one from a run-log refuses by name instead, before anything
reaches the chain.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
import typer
from arkhai_vms import make_vm_provision_terms
from core_buyer.buyer_config import ResolvedBuyerIdentity
from market_identity import Ed25519Signer

from arkhai_vms_buyer import common, deal_helpers, escrow_cli, escrow_client
from arkhai_vms_buyer import settle_cli, settlement_stages

_BUYER = Ed25519Signer(b"\x35" * 32)
_TOKEN = "0x" + "22" * 20
_SELLER_WALLET = "0x" + "44" * 20


class _Log:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    def event(self, name: str, **fields) -> None:
        self.events.append((name, fields))

    def end(self, *_args, **_kwargs) -> None:
        return None


def _deal(**overrides) -> SimpleNamespace:
    deal = {
        "agreement": None,
        "settlement_selection": None,
        "settlement_plan": None,
        "accepted_provision_terms": None,
        "duration_seconds": 3600,
        "token_contract": _TOKEN,
        "token_decimals": 18,
        "accepted_escrow_proposal": None,
        "accepted_escrow_terms": None,
        "escrow_uid": None,
        "seller_url": "http://seller",
        "negotiation_id": "neg-1",
        "listing_id": "listing-1",
        "agreed_amount": 25,
        "seller_wallet_address": _SELLER_WALLET,
        "buyer_principal": _BUYER.identity,
    }
    deal.update(overrides)
    return SimpleNamespace(**deal)


def _no_escrow_is_created(monkeypatch) -> None:
    def create(**_kwargs):
        def refuse(_terms):
            raise AssertionError("an escrow was created without its release condition")

        return refuse

    monkeypatch.setattr(escrow_client, "make_create_escrow_fn", create)
    monkeypatch.setattr(settlement_stages, "make_create_escrow_fn", create)


def _identity() -> ResolvedBuyerIdentity:
    return ResolvedBuyerIdentity(
        profile_id=uuid.UUID("11111111-1111-4111-8111-111111111111"),
        principal=_BUYER.identity,
        signer=_BUYER,
        source="recovery",
    )


def test_escrow_create_refuses_a_run_log_with_no_accepted_proposal(monkeypatch):
    log = _Log()
    monkeypatch.setattr(common, "resolve_recovery_buyer_identity", lambda _run: _identity())
    monkeypatch.setattr(deal_helpers, "load_deal_context", lambda *_a, **_k: _deal())
    monkeypatch.setattr(deal_helpers, "open_run_log", lambda *_a, **_k: log)
    monkeypatch.setattr(
        common,
        "select_chain_for_listing",
        lambda **_kwargs: SimpleNamespace(name="anvil", rpc_url="http://rpc"),
    )
    monkeypatch.setattr(
        deal_helpers,
        "resolve_chain_settings",
        lambda **_kwargs: SimpleNamespace(
            chain_name="anvil",
            alkahest_addr_config=None,
            token_contract=_TOKEN,
            token_decimals=18,
            buyer_private_key="0x" + "77" * 32,
            rpc_url="http://rpc",
        ),
    )
    _no_escrow_is_created(monkeypatch)

    with pytest.raises(typer.Exit) as refused:
        escrow_cli.create_cmd(
            run_id="run-1",
            duration_hours=None,
            expiration_seconds=3600,
            token_contract=None,
            token_decimals=None,
            chain_name_flag=None,
            private_key=None,
            buyer_address=None,
        )

    assert refused.value.exit_code == 3
    assert [name for name, _ in log.events][-1] == "escrow_release_condition_missing"


_PROPOSAL = {
    "chain_name": "anvil",
    "escrow_address": "0x" + "11" * 20,
    "fields": {"token": _TOKEN},
    "literal_fields": {"token": _TOKEN},
    "expiration_unix": 2_000_000_000,
}
# A run-log holding an accepted proposal that selects the seller's recipient
# condition, but not the listing that authorizes it, nor the seller's terms.
_SELECTING_PROPOSAL = {
    **_PROPOSAL,
    "demand": {
        "chain_name": "anvil",
        "arbiter": "0x" + "55" * 20,
        "demand_data": {"recipient": _SELLER_WALLET},
    },
}
_RESUMED_PROPOSALS = pytest.mark.parametrize(
    ("proposal", "reason"),
    [
        (_PROPOSAL, "release_condition_unselected"),
        (_SELECTING_PROPOSAL, "not the listing that authorizes"),
    ],
    ids=["naming no condition", "selecting a condition"],
)


@_RESUMED_PROPOSALS
def test_escrow_create_refuses_a_run_log_holding_only_an_accepted_proposal(
    monkeypatch, proposal, reason
):
    log = _Log()
    monkeypatch.setattr(common, "resolve_recovery_buyer_identity", lambda _run: _identity())
    monkeypatch.setattr(
        deal_helpers,
        "load_deal_context",
        lambda *_a, **_k: _deal(accepted_escrow_proposal=proposal),
    )
    monkeypatch.setattr(deal_helpers, "open_run_log", lambda *_a, **_k: log)
    monkeypatch.setattr(
        common,
        "chain_by_name",
        lambda _name: SimpleNamespace(
            name="anvil", rpc_url="http://rpc", alkahest_address_config_path=None
        ),
    )
    monkeypatch.setattr(
        common, "resolve_buyer_wallet", lambda **_kw: ("0x" + "66" * 20, "0x" + "77" * 32)
    )
    _no_escrow_is_created(monkeypatch)

    with pytest.raises(typer.Exit) as refused:
        escrow_cli.create_cmd(
            run_id="run-1",
            duration_hours=None,
            expiration_seconds=3600,
            token_contract=None,
            token_decimals=None,
            chain_name_flag=None,
            private_key=None,
            buyer_address=None,
        )

    assert refused.value.exit_code == 3
    (missing,) = [
        fields for name, fields in log.events if name == "escrow_release_condition_missing"
    ]
    assert reason in missing["error"]


@_RESUMED_PROPOSALS
def test_settle_refuses_a_run_log_holding_only_an_accepted_proposal(
    monkeypatch, proposal, reason
):
    log = _Log()
    monkeypatch.setattr(common, "resolve_recovery_buyer_identity", lambda _run: _identity())
    monkeypatch.setattr(
        common, "resolve_buyer_wallet", lambda: ("0x" + "66" * 20, "0x" + "77" * 32)
    )
    monkeypatch.setattr(
        common,
        "chain_by_name",
        lambda _name: SimpleNamespace(name="anvil", rpc_url="http://rpc"),
    )
    monkeypatch.setattr(
        settle_cli,
        "load_deal_context",
        lambda *_a, **_k: _deal(
            accepted_escrow_proposal=proposal,
            accepted_provision_terms=make_vm_provision_terms(
                duration_seconds=3600, ssh_public_key="ssh-ed25519 accepted-key"
            ).model_dump(mode="json"),
            # The accepted plan selects Alkahest, which resumes escrow creation.
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
        ),
    )
    monkeypatch.setattr(
        settle_cli, "make_deal_publisher_trust_resolver", lambda *_a, **_k: lambda: None
    )
    monkeypatch.setattr(settle_cli, "open_run_log", lambda *_a, **_k: log)
    monkeypatch.setattr(settle_cli, "resolve_alkahest_address_config_path", lambda: None)
    _no_escrow_is_created(monkeypatch)

    with pytest.raises(typer.Exit) as refused:
        settle_cli.run_settle_from_log(
            run_id="run-1", poll_interval=0, settlement_timeout=1
        )

    assert refused.value.exit_code == 3
    (missing,) = [
        fields for name, fields in log.events if name == "escrow_release_condition_missing"
    ]
    assert reason in missing["error"]
