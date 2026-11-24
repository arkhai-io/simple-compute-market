"""The administrator interrupt route through the composed bare-metal application.

The route mounts the seller half's classification, so these tests prove its
binding: the canonical storefront client reaches it, each kind sends its
command, and a refusal leaves nothing recorded. The identities are the
harness's deterministic development fixtures; never use them on a public
network.
"""

import httpx
import pytest
from market_deal_servicing import EndSession
from market_deal_servicing.evidence import EvidenceSession, transaction
from market_identity import TrustedIdentitySet
from storefront_client import StorefrontClient, StorefrontClientError

from integration.test_payment_settlement_client import ADMIN, SELLER, harness, enabled  # noqa: F401 - fixtures
from integration.test_spot_notice import approve_rate


def administrator(h):
    return StorefrontClient(
        "http://test", signer=ADMIN, caller_role="admin",
        expected_publishers=TrustedIdentitySet(identities=(SELLER.identity,)),
        transport=httpx.ASGITransport(app=h.app),
    )


def recorded(h):
    with transaction(h.runtime.lifecycle.path) as conn:
        end = EndSession(conn)
        evidence = [item.evidence_id for item in EvidenceSession(conn).read(h.negotiation_id).items]
        return end.requests(h.negotiation_id), end.intents(h.negotiation_id), evidence


@pytest.mark.asyncio
async def test_preemption_sends_the_sellers_notice_and_records_no_end(harness):
    h = harness
    _, _, now = approve_rate(h)
    before = recorded(h)
    async with administrator(h) as admin:
        body = {"reason": "host reclaimed", "operation_key": "reclaim", "interruption_kind": "preemption"}
        preview = await admin.admin_interrupt_deal(h.negotiation_id, dry_run=True, **body)
        assert (preview["status"], preview["settlement_action"]) == ("dry_run", "notice_stop")
        assert recorded(h) == before
        response = await admin.admin_interrupt_deal(h.negotiation_id, **body)
        # The operation's key binds its administrator and reason.
        with pytest.raises(StorefrontClientError) as changed:
            await admin.admin_interrupt_deal(h.negotiation_id, **(body | {"reason": "another reason"}))
        assert changed.value.status_code == 409
    assert (response["status"], response["settlement_action"]) == ("accepted", "notice_stop")
    assert response["delivery"]["recorded_end"] is None
    read = await h.runtime.lifecycle.seller.read(h.negotiation_id)
    assert read.authority.parts[0].pending_stop.at == now + 600
    requests, intents, evidence = recorded(h)
    assert requests == [] and intents == []
    assert "administrator-interrupt:reclaim" in evidence


@pytest.mark.asyncio
async def test_failure_ends_delivery_and_journals_a_delivery_end_filing(harness):
    h = harness
    approve_rate(h, payee=False)
    async with administrator(h) as admin:
        response = await admin.admin_interrupt_deal(
            h.negotiation_id, reason="hardware failure", operation_key="failed", interruption_kind="failure",
        )
    assert response["settlement_action"] == "delivery_end_filing"
    assert response["delivery"]["recorded_end"] is not None
    requests, intents, _ = recorded(h)
    assert [(request.cause, request.administrator_reason) for request in requests] == [
        ("operator_end", "hardware failure"),
    ]
    filings = [intent for intent in intents if intent.kind == "filing"]
    assert len(filings) == 1 and filings[0].payload["payload"]["cause"] == "payee"


@pytest.mark.asyncio
async def test_an_interruption_takes_effect_at_receipt_and_accepts_no_time(harness):
    h = harness
    approve_rate(h)
    before = recorded(h)
    async with administrator(h) as admin:
        with pytest.raises(StorefrontClientError) as refused:
            await admin.admin_interrupt_deal(
                h.negotiation_id, reason="reclaim", operation_key="timed", interruption_kind="preemption",
                interrupted_at_utc="2026-01-01T00:00:00Z",
            )
    assert refused.value.status_code == 400
    assert recorded(h) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("payee,kind", [(False, "preemption"), (True, None)])
async def test_an_unclassifiable_interruption_is_refused_before_any_effect(harness, payee, kind):
    h = harness
    approve_rate(h, payee=payee)
    before = recorded(h)
    async with administrator(h) as admin:
        with pytest.raises(StorefrontClientError) as refused:
            await admin.admin_interrupt_deal(
                h.negotiation_id, reason="reclaim", operation_key="refused", interruption_kind=kind,
            )
    assert refused.value.status_code == 409
    assert recorded(h) == before
