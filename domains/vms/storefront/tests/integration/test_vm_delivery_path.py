"""VM deals delivered through the compute family's delivery path, and their
credentials read live by the settle routes, never stored or replayed.

SQLite persistence, the domain registry, VM's fulfillment hook and delivery
ports, the delivery path, end service and the deal lifecycle are real
throughout; the site and the provisioning service are replaced at the
aggregate clients the storefront wraps them in (``tests.delivery_fakes``).
Payment deals settle through the canonical typed clients against the real app
and its authentication middleware, with the payments kit's fake behind
``PaymentsClient``. The Alkahest deals, whose escrow verification and claim
publication read and write a chain, enter the same hook through core's
``fulfill_domain`` with the settlement already verified and the stage's chain
submission and claim binding replaced at its own parameters. The
fulfillment-request tests call VM's delivery port directly. The settle routes'
credential tests read the replay store and the upgrade's clearing of every
stored copy from the same database. An end is recorded through end service's
journal directly, since the end route would also drive a physical end this
rig's site does not serve.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from functools import partial
from types import SimpleNamespace

import httpx
import pytest
import pytest_asyncio
from core_storefront.stage_log import set_stage_event_db_path
from core_storefront.domain_lifecycle import (
    StorefrontFulfillmentContext,
    StorefrontFulfillmentPorts,
    fulfill_domain,
)
from fastapi import FastAPI
from market_arkhai_payments import PaymentSellerStage
from market_arkhai_payments.fixtures import FakePaymentsClient, build_signed_receipt
from market_capacity_publication import CapacityEffects
from market_deal_lifecycle_client import LifecycleClient
from market_deal_lifecycle_contracts.models import CommitMessage
from market_deal_servicing import Classification, EndSession, FinalRequest, create_lifecycle_router
from market_deal_servicing.evidence import transaction
from market_identity import TrustedIdentitySet
from market_storefront_kit.dispute_configuration import RegistryDisputePolicy
from storefront_client import StorefrontClientError
from storefront_client.client import StorefrontClient

import market_storefront.container as _container
from market_storefront.controllers.settle_controller import (
    admin_settle_router,
    router,
    settlements_router,
)
from market_storefront.deal_lifecycle import VmDealLifecycle
from market_storefront.delivery_ports import VmDeliveryDomain
from market_storefront.domain_runtime import build_vm_storefront_domain, build_vm_storefront_registry
from market_storefront.middleware.admin_identity import (
    administrator_identity_middleware,
    initialize_administrator_identities,
)
from market_storefront.middleware.seller_auth import listing_lifecycle_middleware
from market_storefront.payment_settlement import VmPaymentsCoordinator
from market_storefront.services.fulfillment_resume_runtime import resume_incomplete_fulfillments_once
from market_storefront.utils.sqlite_client import SQLiteClient
from tests.delivery_fakes import DeliveryProvisioning, DeliverySite
from tests.fulfillment_fixtures import BUYER_PRINCIPAL, make_vm_lifecycle_fixture
from tests.integration.test_payment_settlement import (
    BUYER,
    NEGOTIATION,
    SELLER,
    SERVICE,
    _client,
    _config,
    _seed,
)
from tests.integration.test_settle_controller import ADMIN_SIGNER, ADMINISTRATORS


def _instant(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _row(db: SQLiteClient, negotiation_id: str) -> dict:
    with sqlite3.connect(db.db_path) as conn:
        conn.row_factory = sqlite3.Row
        return dict(conn.execute(
            "SELECT * FROM vm_delivery_records WHERE negotiation_id=?", (negotiation_id,),
        ).fetchone())


def _servicing(db: SQLiteClient, negotiation_id: str):
    with transaction(db.db_path) as conn:
        session = EndSession(conn)
        return session.read(negotiation_id), session.intents(negotiation_id)


class PaymentRig(SimpleNamespace):
    async def settle(self):
        return await self.buyer.settle_agreement(NEGOTIATION)

    async def delivered(self):
        task = self.coordinator.tasks.get(NEGOTIATION)
        if task is not None:
            await task


@pytest_asyncio.fixture
async def payment_rig(tmp_path):
    rigs = []

    async def build(*, start: datetime | None = None, hold: bool = False):
        domain = build_vm_storefront_domain()
        registry = build_vm_storefront_registry(domain)
        db = SQLiteClient(str(tmp_path / "storefront.db"), registry=registry)
        payments = FakePaymentsClient()
        stage = PaymentSellerStage(_config(), client_for_owner=payments)
        data = await _seed(db, stage, deposit=False, start=start)
        site = DeliverySite("site-test")
        provisioning = DeliveryProvisioning(site)
        coordinator = VmPaymentsCoordinator(
            domain=domain, db=db, stage=stage, capacity=CapacityEffects(site), fulfillment=provisioning,
        )
        lifecycle = VmDealLifecycle(
            db, SELLER, coordinator, RegistryDisputePolicy.from_document({}), fulfillment=provisioning,
        )
        coordinator.lifecycle = lifecycle
        composition = SimpleNamespace(
            payments_coordinator=coordinator, seller_stages=domain.settlement.seller_stages,
            local_principal=SELLER.identity, arkhai_payments_stage=stage, lifecycle=lifecycle,
        )
        _container.resolved_sqlite_client = db
        _container.resolved_domain_registry = registry
        _container.resolved_marketplace_signer = SELLER
        _container.resolved_settlement_composition = composition
        set_stage_event_db_path(db.db_path)
        app = FastAPI()
        app.include_router(router)
        app.include_router(settlements_router)
        app.include_router(create_lifecycle_router(lambda _: lifecycle.routes(
            TrustedIdentitySet(identities=(SELLER.identity,))
        )))
        app.middleware("http")(listing_lifecycle_middleware)
        transport = httpx.ASGITransport(app=app)
        payments.serve(build_signed_receipt(signer=SERVICE, mandate=data.mandate))
        rig = PaymentRig(
            db=db, data=data, site=site, provisioning=provisioning, coordinator=coordinator,
            lifecycle=lifecycle, composition=composition, transport=transport,
            buyer=_client(BUYER, "buyer", transport),
        )
        rigs.append(rig)
        return rig

    yield build
    for rig in rigs:
        await rig.coordinator.stop()
        await rig.buyer.close()
        await rig.lifecycle.close()
    set_stage_event_db_path(None)
    _container.resolved_sqlite_client = None
    _container.resolved_domain_registry = None
    _container.resolved_marketplace_signer = None
    _container.resolved_settlement_composition = None


@pytest.mark.asyncio
async def test_a_payment_deal_is_activated_before_billing_and_available_without_a_read(payment_rig):
    rig = await payment_rig()
    await rig.settle()
    await rig.delivered()

    row = _row(rig.db, NEGOTIATION)
    reservation = row["capacity_reservation_id"]
    assert row["status"] == "ready"
    assert row["activated_at_utc"] is not None
    assert row["tenant_credentials"] is None
    assert json.loads(row["connection_details"])["host"] == "203.0.113.10"
    assert rig.site.rows[reservation]["activated_at_utc"] is not None
    assert list(rig.site.rows) == [reservation]
    # The reservation is held under the deal's negotiation and its settlement
    # placement, and names no settlement reference.
    deal_ref = rig.site.rows[reservation]["deal_ref"]
    assert deal_ref["negotiation_id"] == NEGOTIATION
    assert deal_ref["placement_key"] == f"{NEGOTIATION}:settlement"
    assert "escrow_uid" not in deal_ref
    # The reservation, the accepted fulfillment and the delivery are each
    # reported once.
    with sqlite3.connect(rig.db.db_path) as conn:
        events = conn.execute(
            "SELECT event, data FROM stage_events WHERE stage='provision' AND negotiation_id=?",
            (NEGOTIATION,),
        ).fetchall()
    assert [event for event, _ in events] == ["reserved", "job_submitted", "fulfilled"]
    assert json.loads(events[0][1])["capacity_reservation_id"] == reservation
    assert json.loads(events[1][1])["fulfillment_id"] == row["fulfillment_id"]
    assert rig.provisioning.scheduled == [reservation]
    record, intents = _servicing(rig.db, NEGOTIATION)
    assert record.available_at is not None
    billing = next(intent for intent in intents if intent.kind == "billing")
    assert billing.payload["activated_delivery"] == {
        "version": 1, "record_ref": reservation, "activated_at": row["activated_at_utc"],
    }
    assert row["fulfillment_phase"] == "activated"


def _recorded_bodies(db: SQLiteClient) -> list[dict]:
    with sqlite3.connect(db.db_path) as conn:
        return [
            json.loads(row[0]) for row in conn.execute(
                "SELECT response_body FROM auth_replay_reservations WHERE response_body IS NOT NULL"
            )
        ]


def _end_now(rig) -> None:
    """Record an end due now, as the buyer's end route records one."""
    now = rig.lifecycle.clock()
    with transaction(rig.db.db_path) as conn:
        EndSession(conn).record_end(FinalRequest(
            negotiation_id=NEGOTIATION, source_ref="buyer-end", ended_at=now, observed_at=now,
            actor=BUYER.identity, cause="buyer_surrender", source="end_delivery",
        ), now=now, classification=Classification(kind="buyer_surrender", evidence_refs=["buyer-end"]))


@pytest.mark.asyncio
async def test_settle_status_reads_credentials_live_and_records_none(payment_rig):
    rig = await payment_rig()
    await rig.settle()
    await rig.delivered()

    status = await rig.buyer.get_settle_status(NEGOTIATION)

    assert status.status == "ready"
    assert status.tenant_credentials == {"password": "tenant-pw", "key_type": "generated"}
    assert _row(rig.db, NEGOTIATION)["tenant_credentials"] is None
    with sqlite3.connect(rig.db.db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM credentials").fetchone()[0] == 0
    assert all("tenant_credentials" not in body for body in _recorded_bodies(rig.db))


@asynccontextmanager
async def _administrator(rig, monkeypatch):
    """The storefront's administrator, through the admin settle routes and
    their identity authentication, over the rig's database."""
    monkeypatch.setattr(
        "market_storefront.middleware.admin_identity.get_administrator_configs",
        lambda: {"integration-admin": ADMINISTRATORS},
    )
    monkeypatch.setattr(_container, "resolved_alkahest_clients", {})
    initialize_administrator_identities(rig.db.db_path)
    app = FastAPI()
    app.include_router(admin_settle_router)
    app.middleware("http")(administrator_identity_middleware)
    async with StorefrontClient(
        "http://test", signer=ADMIN_SIGNER, caller_role="admin",
        expected_publishers=TrustedIdentitySet(identities=(SELLER.identity,)),
        transport=httpx.ASGITransport(app=app),
    ) as client:
        yield client


@pytest.mark.asyncio
async def test_a_settlement_wait_returns_once_delivery_has_ended(payment_rig, monkeypatch):
    """A deal whose delivery ended is terminal to the settlement wait, which
    answers at once rather than waiting out its timeout."""
    # A deal that waits for its start, ended while it waits, ends undelivered
    # on its next drive.
    rig = await payment_rig(start=(datetime.now(timezone.utc) + timedelta(hours=2)).replace(microsecond=0))
    await rig.settle()
    await rig.delivered()
    _end_now(rig)
    await resume_incomplete_fulfillments_once(
        sqlite_client=rig.db, capacity=CapacityEffects(rig.site), fulfillment_client=rig.provisioning,
        composition=rig.composition,
    )
    async with _administrator(rig, monkeypatch) as administrator:
        waited = await administrator.wait_for_settlement(NEGOTIATION, timeout=5.0)

    assert waited.ready is True
    assert waited.status == "ended"


@pytest.mark.asyncio
async def test_an_exact_settle_status_retry_after_an_end_is_refused(payment_rig):
    rig = await payment_rig()
    await rig.settle()
    await rig.delivered()
    first = await rig.buyer.get_settle_status(NEGOTIATION, request_id="status-1")
    assert first.tenant_credentials
    _end_now(rig)

    with pytest.raises(StorefrontClientError) as refused:
        await rig.buyer.get_settle_status(NEGOTIATION, request_id="status-1")

    assert refused.value.status_code == 410
    assert "tenant-pw" not in str(refused.value)
    # The request's reservation stays in force: its recorded outcome is kept.
    with sqlite3.connect(rig.db.db_path) as conn:
        assert conn.execute(
            "SELECT response_status FROM auth_replay_reservations WHERE request_id='status-1'"
        ).fetchone() == (200,)
    # A first request after the end answers without credentials.
    later = await rig.buyer.get_settle_status(NEGOTIATION)
    assert later.tenant_credentials is None


@pytest.mark.asyncio
async def test_an_exact_settle_retry_resumes_and_rebuilds_only_its_access_part(payment_rig):
    rig = await payment_rig()
    await rig.settle()
    await rig.delivered()
    first = await rig.buyer.settle_agreement(NEGOTIATION, request_id="settle-1")
    retried = await rig.buyer.settle_agreement(NEGOTIATION, request_id="settle-1")

    credentials = {"password": "tenant-pw", "key_type": "generated"}
    assert first.extra["tenant_credentials"] == retried.extra["tenant_credentials"] == credentials
    assert len(rig.provisioning.begins) == 1
    assert all("tenant_credentials" not in body for body in _recorded_bodies(rig.db))

    # After an end the retry still resumes the same operation, now with no
    # access part to give.
    _end_now(rig)
    ended = await rig.buyer.settle_agreement(NEGOTIATION, request_id="settle-1")
    assert "tenant_credentials" not in ended.extra
    assert len(rig.provisioning.begins) == 1


@pytest.mark.asyncio
async def test_a_storefront_upgrading_with_recorded_credentials_clears_every_copy(payment_rig):
    rig = await payment_rig()
    await rig.settle()
    await rig.delivered()
    await rig.buyer.get_settle_status(NEGOTIATION, request_id="recorded-1")
    recorded = {"status": "ready", "tenant_credentials": {"password": "kept-at-rest"}}
    with sqlite3.connect(rig.db.db_path) as conn:
        conn.execute(
            "UPDATE auth_replay_reservations SET response_body=? WHERE request_id='recorded-1'",
            (json.dumps(recorded),),
        )
        conn.execute(
            "UPDATE vm_delivery_records SET tenant_credentials=? WHERE negotiation_id=?",
            (json.dumps({"password": "kept-at-rest"}), NEGOTIATION),
        )
        conn.execute(
            "INSERT INTO credentials (id, listing_id, role, granted_to, password, created_at) "
            "VALUES ('c-1', 'vm-payment-listing', 'tenant', 'self', 'kept-at-rest', '2026-01-01')"
        )
        conn.execute("DELETE FROM schema_migrations WHERE id='20261106_002_vm_credentials_cleared'")

    SQLiteClient(rig.db.db_path, registry=rig.db.domain_registry)

    with sqlite3.connect(rig.db.db_path) as conn:
        status, body = conn.execute(
            "SELECT response_status, response_body FROM auth_replay_reservations WHERE request_id='recorded-1'"
        ).fetchone()
        assert conn.execute("SELECT COUNT(*) FROM credentials").fetchone()[0] == 0
    assert status == 200
    assert json.loads(body) == {"status": "ready"}
    assert _row(rig.db, NEGOTIATION)["tenant_credentials"] is None


@pytest.mark.asyncio
async def test_a_commit_reaches_available_without_a_settlement_status_poll(payment_rig):
    rig = await payment_rig()
    async with LifecycleClient(
        "http://test", BUYER, TrustedIdentitySet(identities=(SELLER.identity,)), transport=rig.transport,
    ) as buyer:
        committed = await buyer.commit(CommitMessage(
            negotiation_id=NEGOTIATION, commitment_ref=rig.data.transaction_id, operation_key="commit",
        ))
        assert committed.outcome.status == "accepted"
        await rig.delivered()
        assert (await buyer.read(NEGOTIATION)).delivery.progress == "active"
    assert len(rig.provisioning.begins) == 1


@pytest.mark.asyncio
async def test_late_settlement_commits_the_agreement_window(payment_rig):
    start = (datetime.now(timezone.utc) - timedelta(minutes=30)).replace(microsecond=0)
    rig = await payment_rig(start=start)
    await rig.settle()
    await rig.delivered()

    reservation = _row(rig.db, NEGOTIATION)["capacity_reservation_id"]
    commits = {
        (_instant(lease_start), _instant(lease_end))
        for rid, lease_start, lease_end in rig.site.commits if rid == reservation
    }
    assert commits == {(start, start + timedelta(hours=1))}
    assert _row(rig.db, NEGOTIATION)["status"] == "ready"


@pytest.mark.asyncio
async def test_a_forward_deal_is_committed_at_settlement_and_waits_for_its_start(payment_rig, tmp_path):
    start = (datetime.now(timezone.utc) + timedelta(hours=2)).replace(microsecond=0)
    rig = await payment_rig(start=start)
    await rig.settle()
    await rig.delivered()

    row = _row(rig.db, NEGOTIATION)
    reservation = row["capacity_reservation_id"]
    assert rig.site.rows[reservation]["state"] == "leased"
    assert _instant(rig.site.rows[reservation]["lease_start_utc"]) == start
    assert row["status"] == "provisioning"
    assert row["processing_owner"] is None
    assert rig.provisioning.begins == []
    assert rig.site.rows[reservation]["activated_at_utc"] is None

    # The resume pass brings it back and, before its start, still dispatches nothing.
    await resume_incomplete_fulfillments_once(
        sqlite_client=rig.db, capacity=CapacityEffects(rig.site), fulfillment_client=rig.provisioning,
        composition=rig.composition,
    )
    assert rig.provisioning.begins == []
    assert list(rig.site.rows) == [reservation]


@pytest.mark.asyncio
async def test_a_live_acceptance_hold_is_committed_and_no_second_reservation_placed(payment_rig):
    rig = await payment_rig()
    thread = await rig.db.load_negotiation_thread_row(negotiation_id=NEGOTIATION)
    agreement = json.loads(thread["agreement_bytes"])
    placement = {
        "claim": {"gpu_count": 1}, "deal_ref": {"listing_id": "vm-payment-listing", "negotiation_id": NEGOTIATION},
        "ttl_seconds": 600.0, "lease_start_utc": agreement["start_utc"],
        "lease_duration_seconds": agreement["duration_seconds"],
    }
    rig.site.hold("hold-1", placement_key=f"{NEGOTIATION}:hold", request={
        "claim": placement["claim"], "start": placement["lease_start_utc"],
        "duration": placement["lease_duration_seconds"],
    })
    await rig.db.save_capacity_hold(
        negotiation_id=NEGOTIATION, listing_id="vm-payment-listing", capacity_reservation_id="hold-1",
        payload={"capacity_reservation_id": "hold-1", "placement": placement},
    )
    await rig.settle()
    await rig.delivered()

    row = _row(rig.db, NEGOTIATION)
    assert row["capacity_reservation_id"] == "hold-1"
    assert list(rig.site.rows) == ["hold-1"]
    assert rig.site.rows["hold-1"]["state"] == "leased"
    assert row["status"] == "ready"


@pytest.mark.asyncio
async def test_a_lost_reserve_acknowledgement_is_replayed_by_its_placement_key(payment_rig):
    rig = await payment_rig()
    rig.site.lose["reserve"] = 1
    await rig.settle()
    await rig.delivered()
    row = _row(rig.db, NEGOTIATION)
    assert row["capacity_reservation_id"] is None
    assert row["status"] == "provisioning"
    assert len(rig.site.rows) == 1

    await resume_incomplete_fulfillments_once(
        sqlite_client=rig.db, capacity=CapacityEffects(rig.site), fulfillment_client=rig.provisioning,
        composition=rig.composition,
    )

    row = _row(rig.db, NEGOTIATION)
    assert list(rig.site.rows) == [row["capacity_reservation_id"]]
    assert row["status"] == "ready"
    assert len(rig.provisioning.by_reservation) == 1


class AlkahestRig(SimpleNamespace):
    async def fulfil(self):
        return await fulfill_domain(self.domain, StorefrontFulfillmentContext(
            thread_binding=self.fixture.thread_binding,
            settlement_evidence=self.fixture.evidence,
            buyer_principal=BUYER_PRINCIPAL,
            ports=StorefrontFulfillmentPorts(
                repository=self.db, capacity_client=CapacityEffects(self.site),
                fulfillment_client=self.provisioning,
            ),
            domain_input={},
        ))


@pytest_asyncio.fixture
async def alkahest_rig(tmp_path):
    """An Alkahest VM deal whose escrow is verified; its chain submission and
    claim binding are replaced at the stage's own seams."""
    fixture = await make_vm_lifecycle_fixture(tmp_path / "storefront.db", with_context=False)
    domain = build_vm_storefront_domain()
    site = DeliverySite("site-1")
    lifecycle = VmDealLifecycle(fixture.db, SELLER, None, RegistryDisputePolicy.from_document({}))
    rig = AlkahestRig(
        fixture=fixture, db=fixture.db, domain=domain, site=site,
        provisioning=DeliveryProvisioning(site), submitted=[], bound=[], submit_failures=[0],
    )

    async def submit(*, client, escrow_uid, connection_details, allow_submit):
        if rig.submit_failures[0]:
            rig.submit_failures[0] -= 1
            raise RuntimeError("chain unavailable")
        rig.submitted.append(connection_details)
        return "onchain-fulfillment-1"

    async def bind(*, obligation_ref, fulfillment_ref):
        rig.bound.append((obligation_ref, fulfillment_ref))

    alkahest = domain.settlement.seller_stages["alkahest.v1"]
    stages = {
        "alkahest.v1": SimpleNamespace(
            continue_delivery=partial(alkahest.continue_delivery, submit=submit, bind=bind),
        ),
    }
    _container.resolved_settlement_composition = SimpleNamespace(
        seller_stages=stages, lifecycle=lifecycle, evidence_clients={},
    )
    yield rig
    _container.resolved_settlement_composition = None
    await lifecycle.close()


@pytest.mark.asyncio
async def test_an_alkahest_deal_starts_billing_as_a_no_op_and_converges_on_its_claim(alkahest_rig):
    rig = alkahest_rig
    db = rig.db
    submitted, bound = rig.submitted, rig.bound
    result = await rig.fulfil()

    assert result.state == "fulfilled"
    assert result.domain_result["outcome"] == "converged"
    row = _row(db, "neg-1")
    assert row["status"] == "ready"
    assert row["fulfillment_uid"] == "onchain-fulfillment-1"
    assert row["activated_at_utc"] is not None
    assert bound == [("obligation-1", "onchain-fulfillment-1")]
    assert json.loads(submitted[0]) == json.loads(row["connection_details"])
    assert "tenant-pw" not in submitted[0]
    record, intents = _servicing(db, "neg-1")
    assert record.available_at is not None
    billing = next(intent for intent in intents if intent.kind == "billing")
    assert billing.payload["activated_delivery"]["record_ref"] == row["capacity_reservation_id"]


@pytest.mark.asyncio
async def test_evidence_publication_failing_after_provisioning_defers_and_the_next_drive_publishes(
    alkahest_rig,
):
    rig = alkahest_rig
    rig.submit_failures[0] = 1

    first = await rig.fulfil()

    assert first.domain_result["outcome"] == "available"
    row = _row(rig.db, "neg-1")
    assert row["status"] == "provisioning"
    assert row["fulfillment_uid"] is None
    assert len(rig.provisioning.begins) == 1

    second = await rig.fulfil()

    assert second.domain_result["outcome"] == "converged"
    assert _row(rig.db, "neg-1")["fulfillment_uid"] == "onchain-fulfillment-1"
    assert len(rig.provisioning.begins) == 1
    assert len(rig.site.rows) == 1


def _request_domain(db) -> VmDeliveryDomain:
    return VmDeliveryDomain(db, stages={}, payments=None, fulfillment=SimpleNamespace(), composition=None)


@pytest.mark.asyncio
async def test_the_request_names_no_guest_and_is_stored_before_it_is_sent(tmp_path):
    """Provisioning names the guest from the capacity reservation, so the
    request carries only the buyer's key; the context it is built from is
    stored with the deal, and a second build sends the same request."""
    fixture = await make_vm_lifecycle_fixture(tmp_path / "request.db", with_context=False)
    domain = _request_domain(fixture.db)

    first = await domain.fulfillment_request("neg-1", capacity_reservation_id="reservation-1", window=None)
    again = await domain.fulfillment_request("neg-1", capacity_reservation_id="reservation-1", window=None)

    assert first == again
    assert (first.market, first.capacity_reservation_id) == ("vms", "reservation-1")
    assert first.fulfillment_request.payload == {"ssh_pubkey": "ssh-ed25519 test"}
    stored = json.loads(_row(fixture.db, "neg-1")["fulfillment_context"])
    assert stored["payload"]["fulfillment_request"]["payload"] == {"ssh_pubkey": "ssh-ed25519 test"}


@pytest.mark.asyncio
async def test_a_stored_request_for_other_evidence_is_refused(tmp_path):
    fixture = await make_vm_lifecycle_fixture(tmp_path / "stale.db", with_context=False)
    domain = _request_domain(fixture.db)
    await domain.fulfillment_request("neg-1", capacity_reservation_id="reservation-1", window=None)
    stored = json.loads(_row(fixture.db, "neg-1")["fulfillment_context"])
    stored["payload"]["fulfillment_request"]["payload"]["ssh_pubkey"] = "ssh-ed25519 other"
    with sqlite3.connect(fixture.db.db_path) as conn:
        conn.execute(
            "UPDATE vm_delivery_records SET fulfillment_context=? WHERE negotiation_id='neg-1'",
            (json.dumps(stored),),
        )

    with pytest.raises(ValueError, match="differs from verified evidence"):
        await domain.fulfillment_request("neg-1", capacity_reservation_id="reservation-1", window=None)
