"""Bare-metal delivery through core's fulfillment hook and the compute delivery path.

The storefront runtime, its SQLite database, end service, the deal lifecycle
and the delivery path are real; each deal is an accepted Alkahest deal adopted
by settlement verification. The site's capacity client and provisioning client
are doubled at the clients the storefront wraps (``_CapacityClient``,
``_ProvisioningClient``), answering with the provisioning family's typed
contracts. Delivery is entered as settlement enters it, through
``BareMetalFulfillmentService.deliver`` and so core's ``fulfill_domain``; a
waiting deal is re-driven by the served storefront's ``delivery-recovery``
loop, stepped through the typed admin client.
"""

from __future__ import annotations

import logging
import sqlite3
import time
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from core_buyer.negotiation_client import AuthenticatedHTTPError
from core_storefront import StorefrontFulfillmentContext, StorefrontFulfillmentPorts
from loopback import serving
from market_deal_lifecycle_contracts.models import Rejected
from market_deal_servicing import Classification, EndSession, FinalRequest
from market_deal_servicing.evidence import transaction
from market_identity import TrustedIdentitySet
from market_site_client import SiteCapacityClientError
from storefront_client import StorefrontClient
from test_http_settlement import (
    ADMIN_SIGNER,
    BUYER_SIGNER,
    ESCROW_UID,
    SELLER_SIGNER,
    _accepted_runtime,
    _app,
    _CapacityClient,
    _fulfillment_client,
    _ProvisioningClient,
    _settle_body,
)

from arkhai_bare_metal_storefront.fulfillment_service import (
    BareMetalFulfillmentError,
    fulfill_bare_metal,
)
from arkhai_bare_metal_storefront.models import BareMetalSettleRequest

BUYER = BUYER_SIGNER.identity


async def _verified(tmp_path, *, start=None, capacity=None, provisioning=None):
    """An accepted deal whose settlement is verified and adopted, nothing delivered."""

    async def verifier(**_kwargs):
        return 1

    runtime, negotiation_id = await _accepted_runtime(
        str(tmp_path / "storefront.db"), verifier, start=start
    )
    runtime = replace(
        runtime,
        capacity_client=capacity or _CapacityClient(),
        fulfillment_client=provisioning or _ProvisioningClient(),
    )
    await replace(runtime.settlement_service(), service_obligation=None).verify(
        escrow_uid=ESCROW_UID,
        request=BareMetalSettleRequest(**_settle_body(negotiation_id)),
        buyer_principal=BUYER,
    )
    return runtime, negotiation_id


async def _deliver(runtime, negotiation_id):
    return await runtime.fulfillment_service().deliver(
        negotiation_id=negotiation_id, buyer_principal=BUYER
    )


def _record(runtime, negotiation_id):
    with transaction(runtime.db.db_path) as conn:
        return EndSession(conn).read(negotiation_id)


def _intents(runtime, negotiation_id):
    with transaction(runtime.db.db_path) as conn:
        return EndSession(conn).intents(negotiation_id)


async def test_an_alkahest_deal_is_activated_before_it_is_available(tmp_path) -> None:
    runtime, negotiation_id = await _verified(tmp_path)
    capacity, provisioning = runtime.capacity_client, runtime.fulfillment_client

    delivered = await _deliver(runtime, negotiation_id)
    repeated = await _deliver(runtime, negotiation_id)

    # One whole unit of the listing's Physical Resource, under the deal's
    # placement key beside its escrow.
    (reserve,) = capacity.reserve_calls
    assert reserve["claim"]["resource_id"] == "resource-1"
    assert reserve["claim"]["dimensions"] == {"units": 1}
    assert reserve["claim"]["offering_mode"] == "bare_metal"
    assert reserve["deal_ref"] == {
        "escrow_uid": ESCROW_UID,
        "negotiation_id": negotiation_id,
        "placement_key": f"{negotiation_id}:settlement",
    }
    record = _record(runtime, negotiation_id)
    # The commit holds the Agreement window, and the lease is activated once.
    assert {commit["lease_start_utc"] for commit in capacity.commit_calls} == {
        datetime.fromtimestamp(record.start_at, timezone.utc).isoformat()
    }
    assert len(provisioning.begin_calls) == 1
    assert len(capacity.activations) == 1
    row = await runtime.db.load_bare_metal_fulfillment_lifecycle(negotiation_id=negotiation_id)
    activated_at = int(datetime.fromisoformat(capacity.activated_at).timestamp())
    assert row["activated_at_utc"] == activated_at
    # Billing start names the reservation and the site's instant, and the deal
    # is available without any buyer read; its evidence publication, the
    # settlement worker's, is still pending.
    (billing,) = [intent for intent in _intents(runtime, negotiation_id) if intent.kind == "billing"]
    activated = billing.payload["activated_delivery"]
    assert (activated["record_ref"], activated["activated_at"]) == ("reservation-a", activated_at)
    assert record.available_at is not None
    assert delivered.public_result == {
        "outcome": "available", "disposition": "fulfilled", "available": True,
    }
    assert repeated.public_result == delivered.public_result
    assert delivered.settlement_ref == ESCROW_UID
    result = await runtime.db.load_bare_metal_result(negotiation_id=negotiation_id)
    receipt = await runtime.db.load_bare_metal_receipt(negotiation_id=negotiation_id)
    assert result.ssh_user == "tenant-a" and "host" not in result.model_dump()
    assert receipt.status == "ready"


async def test_an_alkahest_deals_lifecycle_read_shows_delivery_with_no_payment_account(tmp_path) -> None:
    """The read resolves the deal's once-only adapter, which names no payment
    account: delivery is shown, and the authority view stays rejected naming
    the mechanism."""
    runtime, negotiation_id = await _verified(tmp_path)
    await _deliver(runtime, negotiation_id)

    read = await runtime.lifecycle.seller.read(negotiation_id)

    assert read.delivery.recorded_end is None
    assert read.delivery.progress == "active"
    assert isinstance(read.authority.outcome, Rejected)
    assert "alkahest.v1" in read.authority.outcome.reason


async def test_settlement_after_the_start_commits_the_agreement_window(tmp_path) -> None:
    start = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(minutes=20)
    runtime, negotiation_id = await _verified(tmp_path, start=start)

    await _deliver(runtime, negotiation_id)

    assert {
        (commit["lease_start_utc"], commit["lease_end_utc"])
        for commit in runtime.capacity_client.commit_calls
    } == {(start.isoformat(), (start + timedelta(hours=1)).isoformat())}
    assert runtime.capacity_client.reserve_calls[0]["lease_start_utc"] == start.isoformat()


async def _waiting(tmp_path):
    """A deal committed two hours before its start, waiting; its end service's
    clock is then set to the start."""
    start = datetime.now(timezone.utc).replace(microsecond=0) + timedelta(hours=2)
    runtime, negotiation_id = await _verified(tmp_path, start=start)
    waiting = await _deliver(runtime, negotiation_id)
    assert waiting.public_result["outcome"] == "waiting"
    assert waiting.public_result["disposition"] == "deferred"
    assert len(runtime.capacity_client.commit_calls) == 1
    assert runtime.fulfillment_client.begin_calls == []
    assert runtime.capacity_client.activations == []
    runtime.lifecycle.end.clock = lambda: int(start.timestamp()) + 1
    return runtime, negotiation_id


@asynccontextmanager
async def _administrator(runtime):
    """The served storefront's administrator, its timers held for the test."""
    app = _app(runtime)
    async with app.router.lifespan_context(app):
        async with StorefrontClient(
            "http://seller", signer=ADMIN_SIGNER, caller_role="admin",
            expected_publishers=TrustedIdentitySet(identities=(SELLER_SIGNER.identity,)),
            transport=httpx.ASGITransport(app=app),
        ) as admin:
            await admin.admin_pause_lifecycle_loops()
            yield admin


async def test_a_deal_waiting_for_its_start_is_claimed_re_checked_and_driven_at_its_start(tmp_path) -> None:
    runtime, negotiation_id = await _waiting(tmp_path)
    provisioning = runtime.fulfillment_client
    lock = runtime.lifecycle.lock(negotiation_id)
    verified = runtime.escrow_verifier
    verifications: list[int] = []
    at_begin: list[tuple[bool, int]] = []

    async def counted(**kwargs):
        verifications.append(1)
        return await verified(**kwargs)

    begin = provisioning.begin_fulfillment

    async def observed_begin(body):
        at_begin.append((lock.locked(), len(verifications)))
        return await begin(body)

    object.__setattr__(runtime, "escrow_verifier", counted)
    provisioning.begin_fulfillment = observed_begin
    async with _administrator(runtime) as admin:
        stepped = await admin.admin_run_lifecycle_cycle("delivery-recovery")

    assert stepped["redriven"] == 1
    # The escrow was read from the chain again before anything was begun —
    # by the routine's re-check and by deliver's own gate — and the drive held
    # the deal's lock, released after.
    assert at_begin == [(True, 2)] and not lock.locked()
    assert len(provisioning.begin_calls) == 1
    assert len(runtime.capacity_client.reserve_calls) == 1
    assert len(runtime.capacity_client.activations) == 1
    assert _record(runtime, negotiation_id).available_at is not None


async def test_a_deal_another_drive_holds_is_skipped(tmp_path) -> None:
    runtime, negotiation_id = await _waiting(tmp_path)

    async with _administrator(runtime) as admin:
        async with runtime.lifecycle.lock(negotiation_id):
            stepped = await admin.admin_run_lifecycle_cycle("delivery-recovery")

    assert stepped["redriven"] == 0
    assert runtime.fulfillment_client.begin_calls == []
    assert _record(runtime, negotiation_id).available_at is None


async def test_a_deal_whose_escrow_does_not_verify_is_not_driven(tmp_path, caplog) -> None:
    runtime, negotiation_id = await _waiting(tmp_path)

    async def reclaimed(**_kwargs):
        raise ValueError("escrow does not match the accepted plan")

    object.__setattr__(runtime, "escrow_verifier", reclaimed)
    with caplog.at_level(logging.WARNING):
        async with _administrator(runtime) as admin:
            stepped = await admin.admin_run_lifecycle_cycle("delivery-recovery")

    assert stepped["redriven"] == 0
    assert [
        record.getMessage() for record in caplog.records
        if record.name == "arkhai_bare_metal_storefront.fulfillment_service"
        and "re-check" in record.getMessage()
    ] == [f"[DELIVERY] {negotiation_id} does not re-check for recovery: stored escrow source is invalid"]
    assert not [record for record in caplog.records if record.name == "compute_delivery.recovery"]
    assert runtime.fulfillment_client.begin_calls == []
    assert runtime.capacity_client.activations == []
    assert _record(runtime, negotiation_id).available_at is None


async def test_an_end_recorded_while_a_deal_waits_is_never_re_driven(tmp_path) -> None:
    """A recorded end moves the deal's physical progress off delivery, so the
    re-drive lists it no more; its end is the servicing cycle's."""
    runtime, negotiation_id = await _waiting(tmp_path)
    _end_recorded(runtime, negotiation_id)
    assert _record(runtime, negotiation_id).progress == "end_recorded"

    async with _administrator(runtime) as admin:
        stepped = await admin.admin_run_lifecycle_cycle("delivery-recovery")

    assert stepped["redriven"] == 0
    assert runtime.fulfillment_client.begin_calls == []
    assert runtime.capacity_client.activations == []
    assert _record(runtime, negotiation_id).available_at is None


async def test_a_lost_reserve_acknowledgement_is_replayed_by_its_placement_key(
    tmp_path,
) -> None:
    class LostAcknowledgement(_CapacityClient):
        async def reserve(self, **request):
            reserved = await super().reserve(**request)
            if len(self.reserve_calls) == 1:
                raise SiteCapacityClientError("connection reset", status_code=None)
            return reserved

    runtime, negotiation_id = await _verified(tmp_path, capacity=LostAcknowledgement())

    # The site reserved, but no answer arrived: the deal stays pending with
    # nothing recorded.
    unanswered = await _deliver(runtime, negotiation_id)
    assert unanswered.public_result["outcome"] == "pending"
    assert unanswered.capacity_reservation_id is None

    await _deliver(runtime, negotiation_id)

    first, replay = runtime.capacity_client.reserve_calls
    assert first["deal_ref"] == replay["deal_ref"]
    assert replay["deal_ref"]["placement_key"] == f"{negotiation_id}:settlement"
    row = await runtime.db.load_bare_metal_fulfillment_lifecycle(negotiation_id=negotiation_id)
    assert row["capacity_reservation_id"] == "reservation-a"
    assert len(runtime.fulfillment_client.begin_calls) == 1


async def test_the_hook_refuses_without_the_storefronts_lifecycle(tmp_path) -> None:
    runtime, negotiation_id = await _verified(tmp_path)
    evidence = await runtime.settlement_service().verified_evidence(
        negotiation_id=negotiation_id, buyer_principal=BUYER
    )

    with pytest.raises(BareMetalFulfillmentError, match="lifecycle"):
        await fulfill_bare_metal(context=StorefrontFulfillmentContext(
            thread_binding=await runtime.db.load_thread_binding(negotiation_id=negotiation_id),
            settlement_evidence=evidence,
            buyer_principal=BUYER,
            ports=StorefrontFulfillmentPorts(
                repository=runtime.db,
                capacity_client=runtime.capacity_client,
                fulfillment_client=runtime.fulfillment_client,
            ),
            domain_input={},
        ))

    assert runtime.capacity_client.reserve_calls == []
    assert runtime.fulfillment_client.begin_calls == []


@pytest.mark.parametrize(
    ("host_id", "physical_host_id"),
    [(None, "host-1"), ("machine-2", "host-1"), ("machine-1", "host-2")],
    ids=["no-host", "another-host", "another-machine"],
)
async def test_a_scheduled_resource_the_terms_did_not_sell_begins_nothing(
    tmp_path, host_id, physical_host_id
) -> None:
    provisioning = _ProvisioningClient(
        scheduled_host_id=host_id, scheduled_physical_host_id=physical_host_id
    )
    runtime, negotiation_id = await _verified(tmp_path, provisioning=provisioning)

    with pytest.raises(BareMetalFulfillmentError, match="scheduled resource conflicts"):
        await _deliver(runtime, negotiation_id)

    assert provisioning.begin_calls == []


async def test_a_failed_begin_is_repeated_with_the_same_materialization(tmp_path) -> None:
    class FailsOnce(_ProvisioningClient):
        async def begin_fulfillment(self, body):
            if not self.begin_calls:
                self.begin_calls.append(body)
                raise RuntimeError("controlled failure after the dispatch was recorded")
            return await super().begin_fulfillment(body)

    runtime, negotiation_id = await _verified(tmp_path, provisioning=FailsOnce())
    provisioning = runtime.fulfillment_client

    with pytest.raises(RuntimeError, match="controlled failure"):
        await _deliver(runtime, negotiation_id)
    recorded = await runtime.db.load_bare_metal_materialization(negotiation_id=negotiation_id)
    await _deliver(runtime, negotiation_id)

    first, retried = provisioning.begin_calls
    assert first == retried
    assert await runtime.db.load_bare_metal_materialization(
        negotiation_id=negotiation_id
    ) == recorded
    assert len(runtime.capacity_client.reserve_calls) == 1
    record = _record(runtime, negotiation_id)
    assert (recorded.lease_start_utc, recorded.lease_end_utc) == (
        datetime.fromtimestamp(record.start_at, timezone.utc),
        datetime.fromtimestamp(record.term_end, timezone.utc),
    )


def _end_recorded(runtime, negotiation_id) -> None:
    """The buyer's end, journaled by end service without driving the physical end."""
    now = int(time.time())
    with transaction(runtime.db.db_path) as conn:
        EndSession(conn).record_end(FinalRequest(
            negotiation_id=negotiation_id, source_ref="buyer-end", ended_at=now,
            observed_at=now, actor=BUYER, cause="buyer", source="buyer",
            evidence_refs=["buyer-end"],
        ), now=now, classification=Classification(kind="terms", evidence_refs=["buyer-end"]))


async def test_an_exact_access_retry_after_an_end_reads_again_and_is_refused(tmp_path) -> None:
    """The buyer's transport repeats one request identity: the exact retry
    reads access again, and once an end is journaled it is refused rather
    than replayed, its recorded outcome keeping no host, port or username."""
    runtime, negotiation_id = await _verified(tmp_path)
    await _deliver(runtime, negotiation_id)
    request_id = "access-retry-1"
    with serving(_app(runtime)) as base_url:
        buyer = _fulfillment_client(base_url)
        first = buyer.access(negotiation_id, request_id=request_id)
        retried = buyer.access(negotiation_id, request_id=request_id)
        _end_recorded(runtime, negotiation_id)
        with pytest.raises(AuthenticatedHTTPError) as refused:
            buyer.access(negotiation_id, request_id=request_id)

    assert first == retried
    assert (first["method"], first["username"]) == ("ssh", "tenant-a")
    assert refused.value.status_code == 410
    with sqlite3.connect(runtime.db.db_path) as conn:
        status, body = conn.execute(
            "SELECT response_status, response_body FROM auth_replay_reservations "
            "WHERE request_id=?",
            (request_id,),
        ).fetchone()
    assert status == 200
    assert '"host"' not in body and '"port"' not in body and '"username"' not in body
    assert '"method":"ssh"' in body
