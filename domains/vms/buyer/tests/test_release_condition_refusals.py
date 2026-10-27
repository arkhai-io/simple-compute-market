"""A resumed run funds only the escrow it derives, held to the seller's plan.

The escrow is derived from the run's accepted proposal and the release
conditions its listing advertised at acceptance, as the run-log recorded them,
and must equal the seller's recorded plan. A run-log recording no accepted
proposal, or none of those conditions, or a plan the derivation does not
match, is refused by name before anything reaches the chain.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
import typer
from arkhai_vms import make_vm_provision_terms
from core_buyer.buyer_config import ResolvedBuyerIdentity
from market_alkahest.alkahest import get_recipient_arbiter
from market_alkahest.dev_chain import anvil_address_book_path
from market_alkahest.plans import (
    escrow_terms_from_settlement_plan,
    materialize_settlement_plan_from_proposal,
)
from market_alkahest.release_authorization import release_conditions_record
from market_alkahest.schemas import EscrowProposal
from market_identity import Ed25519Signer

from arkhai_vms_buyer import common, deal_helpers, escrow_cli
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
        "listing_record": None,
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

    monkeypatch.setattr(escrow_cli, "make_create_escrow_fn", create)
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
# condition, but recording no release conditions for its listing: a run
# accepted before they were recorded.
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
        (_PROPOSAL, "release_conditions_unrecorded"),
        (_SELECTING_PROPOSAL, "release_conditions_unrecorded"),
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


_BOOK = str(anvil_address_book_path())


def _recipient_condition(recipient: str) -> dict:
    return {
        "chain_name": "anvil",
        "arbiter": get_recipient_arbiter("anvil", config_path=_BOOK),
        "demand_data": {"recipient": recipient},
    }


def _seller_plan(recipient: str) -> dict:
    """The seller's plan for the accepted proposal, released to ``recipient``."""
    condition = _recipient_condition(recipient)
    return materialize_settlement_plan_from_proposal(
        proposal=EscrowProposal.model_validate({**_PROPOSAL, "demand": condition}),
        listing={"demands": [condition]},
        agreed_amount=25,
        duration_seconds=3600,
        addr_config_path=_BOOK,
    ).model_dump(mode="json")


def _recorded_deal(plan: dict) -> SimpleNamespace:
    """A run that recorded its listing's conditions and the seller's plan."""
    return _deal(
        accepted_escrow_proposal={
            **_PROPOSAL, "demand": _recipient_condition(_SELLER_WALLET)
        },
        listing_record=release_conditions_record(
            {"demands": [_recipient_condition(_SELLER_WALLET)]}
        ),
        settlement_plan=plan,
    )


def _create_from_recorded_conditions(monkeypatch, *, plan: dict, log: _Log, funded: list):
    """Run escrow creation for a run that recorded its listing's conditions."""
    monkeypatch.setattr(common, "resolve_recovery_buyer_identity", lambda _run: _identity())
    monkeypatch.setattr(
        deal_helpers, "load_deal_context", lambda *_a, **_k: _recorded_deal(plan)
    )
    monkeypatch.setattr(deal_helpers, "open_run_log", lambda *_a, **_k: log)
    monkeypatch.setattr(
        common,
        "chain_by_name",
        lambda _name: SimpleNamespace(
            name="anvil", rpc_url="http://rpc", alkahest_address_config_path=_BOOK
        ),
    )
    monkeypatch.setattr(
        common, "resolve_buyer_wallet", lambda **_kw: ("0x" + "66" * 20, "0x" + "77" * 32)
    )
    monkeypatch.setattr(
        escrow_cli,
        "make_create_escrow_fn",
        lambda **_kwargs: lambda terms: funded.extend(terms) or ["0x" + "ee" * 32],
    )
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


def test_escrow_create_funds_what_it_derives_from_the_recorded_conditions(monkeypatch):
    plan = _seller_plan(_SELLER_WALLET)
    funded: list = []

    _create_from_recorded_conditions(monkeypatch, plan=plan, log=_Log(), funded=funded)

    assert funded == escrow_terms_from_settlement_plan(plan)


def test_escrow_create_refuses_a_seller_plan_paying_another_recipient(monkeypatch):
    log, funded = _Log(), []
    with pytest.raises(typer.Exit) as refused:
        _create_from_recorded_conditions(
            monkeypatch, plan=_seller_plan("0x" + "99" * 20), log=log, funded=funded
        )

    assert refused.value.exit_code == 3
    (missing,) = [
        fields for name, fields in log.events if name == "escrow_release_condition_missing"
    ]
    assert "seller_plan_mismatch" in missing["error"]
    assert funded == []


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


def test_settle_refuses_a_seller_plan_paying_another_recipient(monkeypatch):
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
    deal = _recorded_deal(_seller_plan("0x" + "99" * 20))
    deal.accepted_provision_terms = make_vm_provision_terms(
        duration_seconds=3600, ssh_public_key="ssh-ed25519 accepted-key"
    ).model_dump(mode="json")
    monkeypatch.setattr(settle_cli, "load_deal_context", lambda *_a, **_k: deal)
    monkeypatch.setattr(
        settle_cli, "make_deal_publisher_trust_resolver", lambda *_a, **_k: lambda: None
    )
    monkeypatch.setattr(settle_cli, "open_run_log", lambda *_a, **_k: log)
    monkeypatch.setattr(settle_cli, "resolve_alkahest_address_config_path", lambda: _BOOK)
    _no_escrow_is_created(monkeypatch)

    with pytest.raises(typer.Exit) as refused:
        settle_cli.run_settle_from_log(
            run_id="run-1", poll_interval=0, settlement_timeout=1
        )

    assert refused.value.exit_code == 3
    (missing,) = [
        fields for name, fields in log.events if name == "escrow_release_condition_missing"
    ]
    assert "seller_plan_mismatch" in missing["error"]
