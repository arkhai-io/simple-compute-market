"""Case GETs preserve protection outcomes at the HTTP contract boundary."""

import asyncio
from copy import deepcopy

import httpx
import pytest

from market_arkhai_mediation.client import MediationProtocolError
from market_arkhai_mediation.contract import wire
from .test_adapter import Scenario


def test_case_read_accepts_the_authority_outcome_envelope():
    async def drive():
        s = Scenario()
        case = deepcopy(s.peer.data["filing"]["answer"]["case"])
        expected = {"status": "accepted", "case": case}
        await s.client.close()
        s = Scenario(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=expected)))
        try:
            result = await s.client.case(case["case_ref"], agreement=case["agreement"], transaction=case["transaction"])
            assert wire(result) == expected
        finally:
            await s.client.close()
    asyncio.run(drive())


@pytest.mark.parametrize("status,mismatch", [
    ("accepted", None), ("accepted", "case_ref"),
    ("accepted", "agreement"), ("accepted", "transaction"),
    ("pending", None), ("pending", "case_ref"),
])
def test_case_read_preserves_pending_and_checks_bindings(status, mismatch):
    async def drive():
        seed = Scenario()
        case = deepcopy(seed.peer.data["filing"]["answer"]["case"])
        await seed.client.close()
        answer = {"status": status, "case": deepcopy(case)} if status == "accepted" else {
            "status": "pending", "case_ref": case["case_ref"],
        }
        if mismatch:
            target = answer["case"] if status == "accepted" else answer
            target[mismatch] = "different-case" if mismatch == "case_ref" else "f" * 64
        s = Scenario(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=answer)))
        try:
            if mismatch:
                with pytest.raises(MediationProtocolError, match="another"):
                    await s.client.case(case["case_ref"], agreement=case["agreement"], transaction=case["transaction"])
            else:
                result = await s.client.case(case["case_ref"], agreement=case["agreement"], transaction=case["transaction"])
                assert wire(result) == answer
        finally:
            await s.client.close()
    asyncio.run(drive())


@pytest.mark.parametrize("malformation", ["bare", "extra", "unknown_status"])
def test_case_read_rejects_malformed_outcomes(malformation):
    async def drive():
        seed = Scenario()
        case = deepcopy(seed.peer.data["filing"]["answer"]["case"])
        await seed.client.close()
        answer = {"status": "accepted", "case": case}
        if malformation == "bare":
            answer = case
        elif malformation == "extra":
            answer["unexpected"] = True
        else:
            answer["status"] = "ready"
        s = Scenario(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=answer)))
        try:
            with pytest.raises(MediationProtocolError, match="violates its contract"):
                await s.client.case(case["case_ref"], agreement=case["agreement"], transaction=case["transaction"])
        finally:
            await s.client.close()
    asyncio.run(drive())
