"""The double's transport faults, as the mediation kit's client meets them over a real server.

The app runs under uvicorn on loopback, plain HTTP, which the kit's client
accepts on loopback, so a fault reaches ``MediationClient`` as it would in a lane:
a connection closed mid-response, which the client raises as
``MediationTransportError``, never an HTTP status. Rules are installed and removed
through the typed control client against the same server; the payments peer is
the payments kit's engine, in process (``support``).
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

import pytest
from pydantic import SecretStr

from lane_double_controls import ControlClient, Rule
from market_arkhai_mediation.client import (
    MediationClient,
    MediationCredential,
    MediationTransportError,
)
from market_arkhai_mediation.contract import wire
from market_arkhai_mediation.models import RespondentAfter
from market_deal_lifecycle.terms import DisputeAuthority

from loopback import serving
from support import Lane, filing, run


@dataclass
class Served:
    lane: Lane
    origin: str
    controls: ControlClient

    def client(self, role: str) -> MediationClient:
        authority = DisputeAuthority.model_validate(
            self.lane.dispute.model_dump(mode="json") | {"origin": self.origin})
        return MediationClient(authority, MediationCredential(
            authority.identity, token=SecretStr(self.lane.token(role))))


@pytest.fixture
def served() -> Iterator[Served]:
    lane = Lane()
    with serving(lane.app) as origin:
        with ControlClient(origin, token=lane.authority.control_token) as controls:
            yield Served(lane, origin, controls)


def test_unavailable_abandons_every_api_response_while_controls_answer(served: Served) -> None:
    transaction = served.lane.approve()
    served.controls.install_rule(Rule.model_validate(
        {"rule_id": "down", "match": {}, "unavailable": True}))

    async def calls() -> None:
        async with served.client("seller") as seller:
            with pytest.raises(MediationTransportError):
                await seller.respondent(RespondentAfter(after=""))
            with pytest.raises(MediationTransportError):
                await seller.file(filing(transaction), idempotency_key="filing-1")

    run(calls())

    assert served.controls.status().offset_seconds == 0
    assert served.controls.rules().rules[0].matched == 2
    assert served.lane.events(transaction, "extend") == []
    served.controls.delete_rule("down")

    async def restored() -> dict:
        async with served.client("seller") as seller:
            return wire(await seller.respondent(RespondentAfter(after="")))

    assert run(restored())["cases"] == []


def test_a_lost_filing_response_is_adopted_under_the_same_key(served: Served) -> None:
    transaction = served.lane.approve()
    served.controls.install_rule(Rule.model_validate({
        "rule_id": "lose-filing", "match": {"operation": "file", "filer": "payee"},
        "drop_response_after_commit": True}))

    async def lose() -> None:
        async with served.client("seller") as seller:
            with pytest.raises(MediationTransportError):
                await seller.file(filing(transaction), idempotency_key="filing-1")

    run(lose())
    assert served.controls.rules().rules[0].matched == 1
    [case] = served.controls.cases(transaction).cases
    served.controls.delete_rule("lose-filing")

    async def retry() -> dict:
        async with served.client("seller") as seller:
            return wire(await seller.file(filing(transaction), idempotency_key="filing-1"))

    adopted = run(retry())

    assert adopted["status"] == "accepted"
    assert adopted["case"]["case_ref"] == case.case_ref
    assert len(served.controls.cases(transaction).cases) == 1
    assert len(served.lane.events(transaction, "extend")) == 1
