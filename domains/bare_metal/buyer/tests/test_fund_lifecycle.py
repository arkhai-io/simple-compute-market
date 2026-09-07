"""`fund` carries an accepted Alkahest agreement into physical fulfillment.

A negotiated agreement is not a purchase. This drives the real `fund_alkahest`
command through the three steps that make it one — create the escrow the seller
accepted, have the seller verify it on chain, then begin fulfillment — with the
chain call and the signed transport as the controlled dependencies.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
import typer
from arkhai_bare_metal_buyer import cli as buy_cli
from arkhai_bare_metal_buyer import escrow as buyer_escrow
from arkhai_bare_metal_buyer.escrow import BareMetalEscrowError
from eth_account import Account

CHAIN = "base_sepolia"
ESCROW_CONTRACT = "0x0000000000000000000000000000000000000001"
TOKEN = "0x00000000000000000000000000000000000000aa"
NEGOTIATION_ID = "neg-1"
ESCROW_UID = "0xescrowuid"
FIXTURE_KEY = "0x" + "11" * 32
# The address that key controls. `fund` refuses a mismatch, because the seller
# would otherwise record a payer that did not fund the escrow.
BUYER_EVM = Account.from_key(FIXTURE_KEY).address
KEY_ENV = "FIXTURE_BUYER_KEY"


def _obligation(**overrides: Any) -> dict[str, Any]:
    obligation = {
        "payer": "buyer",
        "claimant": "seller",
        "amount": "1000",
        "asset": TOKEN,
        "expiration_unix": 2_000_000_000,
        "mechanism": "alkahest.v1",
        "params": {
            "chain_name": CHAIN,
            "escrow_contract": ESCROW_CONTRACT,
            "obligation_data": {"token": TOKEN, "amount": "1000"},
        },
    }
    obligation.update(overrides)
    return obligation


@pytest.fixture()
def world(monkeypatch):
    events: list[tuple[str, dict[str, Any]]] = []
    calls: list[tuple[str, dict[str, Any]]] = []

    class _Fulfillment:
        def settle(self, **kwargs):
            calls.append(("settle", kwargs))
            return {"obligation_ref": "obl-1", "escrow_uid": kwargs["escrow_uid"]}

        def begin(self, **kwargs):
            calls.append(("begin", kwargs))
            return {"state": "reserved"}

    deal = SimpleNamespace(
        negotiation_id=NEGOTIATION_ID,
        settlement_plan={"obligations": [_obligation()]},
        # No prior escrow: this run has not funded anything yet.
        escrow_uid=None,
    )
    identity = SimpleNamespace(signer=object(), profile_id="fixture-profile")

    monkeypatch.setattr(
        buy_cli,
        "_recovered_transports",
        lambda run_id, config: (deal, identity, object(), _Fulfillment()),
    )
    monkeypatch.setattr(
        buy_cli,
        "open_run_log",
        lambda run_id, **kw: SimpleNamespace(
            event=lambda name, **fields: events.append((name, fields))
        ),
    )
    monkeypatch.setattr(
        buy_cli,
        "fund_accepted_obligation",
        lambda obligation, private_key: ESCROW_UID,
    )
    monkeypatch.setenv(KEY_ENV, FIXTURE_KEY)

    return SimpleNamespace(events=events, calls=calls, deal=deal)


def _fund(**overrides: Any) -> None:
    kwargs: dict[str, Any] = {
        "run_id": "run-1",
        "buyer_evm_address": BUYER_EVM,
        "private_key_env": KEY_ENV,
        "escrow_uid": None,
        "config": None,
    }
    kwargs.update(overrides)
    buy_cli.fund_alkahest(**kwargs)


def test_funding_verifies_then_begins_in_that_order(world) -> None:
    """Beginning before verification would reserve capacity for unfunded terms."""
    _fund()

    assert [name for name, _ in world.calls] == ["settle", "begin"]
    settle_kwargs = world.calls[0][1]
    assert settle_kwargs["escrow_uid"] == ESCROW_UID
    assert settle_kwargs["negotiation_id"] == NEGOTIATION_ID
    assert settle_kwargs["buyer_evm_address"] == BUYER_EVM
    assert world.calls[1][1] == {
        "negotiation_id": NEGOTIATION_ID,
        "escrow_uid": ESCROW_UID,
    }


def test_the_escrow_is_recorded_before_it_is_verified(world) -> None:
    """An escrow funded but unverified must still be reclaimable.

    If the reference were only written after verification, a failure in between
    would strand the buyer's funds with nothing naming the escrow.
    """
    _fund()

    names = [name for name, _ in world.events]
    assert names.index("escrow_created") < names.index("settlement_verified")
    created = dict(world.events[0][1])
    assert created["escrow_uid"] == ESCROW_UID
    assert created["chain_name"] == CHAIN


def _must_not_fund(*_args: Any, **_kwargs: Any) -> str:
    raise AssertionError("a resumed run must not create a second escrow")


def test_an_existing_escrow_is_adopted_rather_than_funded_twice(world, monkeypatch) -> None:
    monkeypatch.setattr(buy_cli, "fund_accepted_obligation", _must_not_fund)

    _fund(escrow_uid="0xalready")

    assert world.calls[0][1]["escrow_uid"] == "0xalready"
    assert [name for name, _ in world.events] == [
        "settlement_verified",
        "fulfillment_begun",
    ]


def test_a_missing_funding_key_is_refused_before_any_call(world, monkeypatch) -> None:
    monkeypatch.delenv(KEY_ENV, raising=False)

    with pytest.raises(typer.BadParameter):
        _fund()

    assert world.calls == []


def test_a_hosted_obligation_is_not_funded_as_alkahest(world) -> None:
    world.deal.settlement_plan = {
        "obligations": [_obligation(mechanism="fiat.stripe.v1")]
    }

    with pytest.raises(typer.BadParameter):
        _fund()

    assert world.calls == []


# --------------------------------------------------------------------------
# The obligation reader, which decides what gets funded
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"mechanism": "fiat.stripe.v1"}, "another mechanism"),
        ({"params": {"escrow_contract": ESCROW_CONTRACT}}, "no chain"),
        ({"params": {"chain_name": CHAIN}}, "no escrow contract"),
        (
            {"params": {
                "chain_name": CHAIN,
                "escrow_contract": ESCROW_CONTRACT,
                "obligation_data": {},
            }},
            "empty obligation data",
        ),
        (
            {
                "expiration_unix": True,
                "params": {
                    "chain_name": CHAIN,
                    "escrow_contract": ESCROW_CONTRACT,
                    "obligation_data": {"token": TOKEN},
                },
            },
            "a boolean expiry",
        ),
    ],
)
def test_an_unfundable_obligation_is_refused(overrides, reason) -> None:
    """Refused before a chain client is built, so nothing is signed or sent."""
    with pytest.raises(BareMetalEscrowError):
        buyer_escrow._obligation_parts(_obligation(**overrides))


def test_an_unconfigured_chain_is_named_in_the_refusal(monkeypatch) -> None:
    monkeypatch.setattr(buyer_escrow, "chains_from_config", lambda: {})

    with pytest.raises(BareMetalEscrowError) as exc:
        buyer_escrow.resolve_buyer_chain(CHAIN)

    assert CHAIN in str(exc.value)


def test_a_chain_without_an_rpc_url_is_refused(monkeypatch) -> None:
    monkeypatch.setattr(
        buyer_escrow,
        "chains_from_config",
        lambda: {CHAIN: SimpleNamespace(rpc_url="")},
    )

    with pytest.raises(BareMetalEscrowError):
        buyer_escrow.resolve_buyer_chain(CHAIN)


def test_a_rerun_adopts_the_escrow_its_own_run_log_records(world, monkeypatch) -> None:
    """A crash between funding and verification must not pay twice.

    The run log already records `escrow_created`, and the shared deal context
    recovers it, so a rerun without `--escrow-uid` has the evidence it needs to
    resume rather than spend again.
    """
    monkeypatch.setattr(buy_cli, "fund_accepted_obligation", _must_not_fund)
    world.deal.escrow_uid = "0xfrom-run-log"

    _fund()

    assert world.calls[0][1]["escrow_uid"] == "0xfrom-run-log"
    assert [name for name, _ in world.events] == [
        "settlement_verified",
        "fulfillment_begun",
    ]


def test_a_payer_address_that_the_key_does_not_control_is_refused(world) -> None:
    with pytest.raises(typer.BadParameter) as exc:
        _fund(buyer_evm_address="0x000000000000000000000000000000000000dEaD")

    assert "funding key" in str(exc.value)
    assert world.calls == []
