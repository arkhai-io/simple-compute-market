"""Alkahest claim hooks: trusted-oracle conditions request once and poll.

The oracle is always a third party — the hooks never arbitrate; they
ask (once per fulfillment) and watch for ``ArbitrationMade``.
"""

from __future__ import annotations

from typing import Any

import pytest

from core_storefront.settlement_lifecycle import ClaimRecord
from domains.vms.settlement.claims import AlkahestClaimHooks
from market_alkahest.alkahest import get_trusted_oracle_arbiter
from market_alkahest.claims import TrustedOracleArbiterCodec

ORACLE = "0x" + "cd" * 20


class FakeOracle:
    def __init__(self) -> None:
        self.requested: list[tuple] = []
        self.arbitrated: list[tuple] = []
        self.event: Any = None

    async def request_arbitration(self, fulfillment, oracle, demand):
        self.requested.append((fulfillment, oracle))
        return "0xreq"

    async def arbitrate(self, obligation, demand, decision):  # pragma: no cover
        self.arbitrated.append((obligation, decision))
        return "0xarb"

    async def wait_for_arbitration(self, obligation, demand, oracle, from_block):
        if self.event is None:
            import asyncio
            await asyncio.sleep(3600)  # probe times out → None
        return self.event


class FakeClient:
    def __init__(self) -> None:
        self.oracle = FakeOracle()


def _claim() -> ClaimRecord:
    arbiter = get_trusted_oracle_arbiter("base_sepolia")
    demand = TrustedOracleArbiterCodec().encode_demand_data(
        {"oracle": ORACLE, "data": b""}
    )
    return ClaimRecord(
        claim_ref="0x" + "ee" * 32,
        obligation={
            "mechanism": "alkahest.v1",
            "expiration_unix": 4_102_444_800,
            "params": {
                "chain_name": "base_sepolia",
                "escrow_contract": "0x" + "11" * 20,
                "obligation_data": {
                    "arbiter": arbiter,
                    "demand": "0x" + demand.hex(),
                },
            },
        },
        fulfillment_ref="0xfulfill",
    )


def _hooks(client):
    return AlkahestClaimHooks(
        get_client=lambda chain: client,
        default_chain="base_sepolia",
        arbitration_probe_timeout=0.05,
    )


@pytest.mark.asyncio
async def test_requests_arbitration_once_then_polls():
    client = FakeClient()
    hooks = _hooks(client)
    claim = _claim()

    # No arbitration yet → pending; the request went out exactly once
    # and the hooks never arbitrate on the oracle's behalf.
    assert await hooks.check_conditions(claim) == "pending"
    assert await hooks.check_conditions(claim) == "pending"
    assert client.oracle.requested == [("0xfulfill", ORACLE)]
    assert client.oracle.arbitrated == []
    assert claim.mechanism_state["arbitration_requested_for"] == "0xfulfill"


@pytest.mark.asyncio
async def test_arbitration_made_true_reports_ready():
    client = FakeClient()
    hooks = _hooks(client)
    claim = _claim()

    class Made:
        decision = True

    client.oracle.event = Made()
    assert await hooks.check_conditions(claim) == "ready"


@pytest.mark.asyncio
async def test_arbitration_made_false_stays_pending():
    """A false decision isn't terminal — the oracle may re-arbitrate
    (dispute resolved, lease end reached); expiration grace bounds it."""
    client = FakeClient()
    hooks = _hooks(client)
    claim = _claim()

    class Made:
        decision = False

    client.oracle.event = Made()
    assert await hooks.check_conditions(claim) == "pending"
