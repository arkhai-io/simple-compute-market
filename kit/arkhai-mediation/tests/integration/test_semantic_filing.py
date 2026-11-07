"""Delivery-end callers converge on signed authority cases, never caller-key duplicates."""

import asyncio

import httpx

from market_deal_lifecycle.adapters import DeliveryEndIntent
from market_arkhai_mediation.fixtures.authority import MediationContractFake
from test_adapter import Scenario


def test_online_recovery_and_reconstructed_caller_adopt_one_semantic_case():
    async def drive():
        peer = MediationContractFake()
        def handle(request):
            if request.url.path == "/record" and not peer.cases:
                return httpx.Response(404, json={
                    "status": "error", "code": "invalid_request", "message": "Agreement not found",
                })
            return peer.handle(request)
        s = Scenario(peer=peer, transport=httpx.MockTransport(handle))
        intent = DeliveryEndIntent(ended_at=1800000000, delivered=False, cause="payee")
        try:
            assert (await s.adapter.read()).outcome.status == "rejected"
            first = await s.submit("delivery_end", "online", intent.model_dump(mode="json"))
            second = await s.submit("delivery_end", "operator", intent.model_dump(mode="json"))
            assert first.status == second.status == "accepted"
            assert (await s.adapter.read()).outcome.status == "accepted"
            assert first.filing.case_ref == second.filing.case_ref
            assert len(s.peer.cases) == 1
            assert len([r for r in s.peer.requests if r.method == "POST"]) == 1
        finally:
            await s.client.close()
    asyncio.run(drive())


def test_uncertain_original_refuses_revision_and_allows_equivalent_adoption():
    async def drive():
        s = Scenario()
        intent = DeliveryEndIntent(ended_at=1800000000, delivered=False, cause="payee")
        try:
            s.peer.lose_next_response = True
            assert (await s.submit("delivery_end", "online", intent.model_dump(mode="json"))).status == "unknown"
            revised = intent.model_copy(update={"ended_at": 1800000001})
            refusal = await s.submit("delivery_end", "operator-revision", revised.model_dump(mode="json"))
            assert refusal.status == "rejected" and "repair required" in refusal.reason
            adopted = await s.submit("delivery_end", "operator", intent.model_dump(mode="json"))
            assert adopted.status == "accepted" and len(s.peer.cases) == 1
        finally:
            await s.client.close()
    asyncio.run(drive())


def test_existing_case_pending_protection_is_not_refiled():
    async def drive():
        peer = MediationContractFake()
        def handle(request):
            if request.url.path.startswith("/cases/"):
                return httpx.Response(200, json={
                    "status": "pending", "case_ref": next(iter(peer.cases)),
                })
            return peer.handle(request)
        s = Scenario(peer=peer, transport=httpx.MockTransport(handle))
        intent = DeliveryEndIntent(ended_at=1800000000, delivered=False, cause="payee")
        try:
            first = await s.submit("delivery_end", "online", intent.model_dump(mode="json"))
            assert first.status == "accepted"
            recovered = await s.submit("delivery_end", "recovery", intent.model_dump(mode="json"))
            assert recovered.status == "pending" and "protection pending" in recovered.reason
            assert len(peer.cases) == 1
            assert len([r for r in peer.requests if r.method == "POST"]) == 1
        finally:
            await s.client.close()
    asyncio.run(drive())


def test_concurrent_callers_coordinate_before_authority_write():
    async def drive():
        entered, proceed = asyncio.Event(), asyncio.Event()
        peer = MediationContractFake()
        async def handle(request):
            if request.method == "POST":
                entered.set()
                await proceed.wait()
            return peer.handle(request)
        s = Scenario(peer=peer, transport=httpx.MockTransport(handle))
        intent = DeliveryEndIntent(ended_at=1800000000, delivered=False, cause="payee").model_dump(mode="json")
        try:
            first = asyncio.create_task(s.submit("delivery_end", "online", intent))
            await entered.wait()
            second = await asyncio.wait_for(s.submit("delivery_end", "recovery", intent), timeout=1)
            assert second.status == "pending" and "resolve" in second.reason
            proceed.set()
            assert (await first).status == "accepted"
            assert (await s.submit("delivery_end", "recovery", intent)).status == "accepted"
            assert len(peer.cases) == 1
        finally:
            proceed.set()
            if not first.done():
                first.cancel()
            await asyncio.gather(first, return_exceptions=True)
            await s.client.close()
    asyncio.run(drive())
