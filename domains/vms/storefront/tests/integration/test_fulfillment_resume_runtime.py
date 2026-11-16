"""The resume pass drives each unfinished VM delivery through the delivery path.

Real SQLite persistence and the real path, end service and deal lifecycle;
the pass is called directly with the site and provisioning fakes at the
storefront's aggregate clients, which the loop's own step would build from the
configured sites. The Alkahest deal's stage
has its chain reads replaced at the stage; the payment deal is settled through
the typed buyer client against the payment rig's app, with the payments kit's
fake behind ``PaymentsClient``, and is re-checked by the real payments stage.
"""

import logging
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from functools import partial
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from compute_provisioning_contracts import FulfillmentStatusResponse
from market_arkhai_payments import PaymentSellerStage
from market_capacity_publication import CapacityEffects
from market_storefront_kit.dispute_configuration import RegistryDisputePolicy

from market_storefront.deal_lifecycle import VmDealLifecycle
from market_storefront.domain_runtime import build_vm_storefront_domain
from market_storefront.services.fulfillment_resume_runtime import resume_incomplete_fulfillments_once
from tests.delivery_fakes import DeliveryProvisioning, DeliverySite
from tests.fulfillment_fixtures import SELLER_PRINCIPAL, make_vm_lifecycle_fixture
from tests.integration.test_payment_settlement import IMPOSTOR, NEGOTIATION, _config
from tests.integration.test_vm_delivery_path import _row, payment_rig  # noqa: F401 - the rig's fixture

_SELLER = SimpleNamespace(identity=SELLER_PRINCIPAL)


async def _recorded_fulfillment(tmp_path):
    """An Alkahest deal interrupted after its fulfillment was accepted."""
    fixture = await make_vm_lifecycle_fixture(tmp_path / "storefront.db", with_context=False)
    site = DeliverySite("site-1")
    site.rows["reservation-1"] = {
        "capacity_reservation_id": "reservation-1", "state": "leased", "deal_ref": {},
        "lease_start_utc": None, "lease_end_utc": None, "activated_at_utc": None,
    }
    await fixture.db.update_vm_delivery(
        negotiation_id="neg-1", capacity_reservation_id="reservation-1", fulfillment_id="fulfillment-1",
    )
    provisioning = DeliveryProvisioning(site)
    provisioning.by_reservation["reservation-1"] = "fulfillment-1"
    lifecycle = VmDealLifecycle(fixture.db, _SELLER, None, RegistryDisputePolicy.from_document({}))
    alkahest = build_vm_storefront_domain().settlement.seller_stages["alkahest.v1"]
    stage = SimpleNamespace(
        recover_evidence=AsyncMock(),
        continue_delivery=partial(
            alkahest.continue_delivery, submit=AsyncMock(return_value="onchain-1"), bind=AsyncMock(),
        ),
        delivery_failed=AsyncMock(),
    )
    composition = SimpleNamespace(
        seller_stages={"alkahest.v1": stage}, lifecycle=lifecycle, evidence_clients={},
    )
    return fixture, site, provisioning, stage, composition


async def _resume(fixture, site, provisioning, composition):
    return await resume_incomplete_fulfillments_once(
        sqlite_client=fixture.db, capacity=CapacityEffects(site), fulfillment_client=provisioning,
        composition=composition,
    )


@pytest.mark.asyncio
async def test_a_recorded_fulfillment_resumes_without_schedule_or_begin(tmp_path):
    fixture, site, provisioning, stage, composition = await _recorded_fulfillment(tmp_path)
    provisioning.schedule_resource = AsyncMock()
    provisioning.begin_fulfillment = AsyncMock()

    assert await _resume(fixture, site, provisioning, composition) == 1

    provisioning.schedule_resource.assert_not_awaited()
    provisioning.begin_fulfillment.assert_not_awaited()
    stage.recover_evidence.assert_awaited_once()
    persisted = await fixture.db.load_vm_delivery(negotiation_id="neg-1")
    assert persisted["status"] == "ready"
    assert persisted["fulfillment_uid"] == "onchain-1"
    assert site.rows["reservation-1"]["activated_at_utc"] is not None
    await composition.lifecycle.close()


@pytest.mark.asyncio
async def test_a_failed_fulfillment_is_handed_to_the_end_and_its_policy_runs_once(tmp_path):
    fixture, site, provisioning, stage, composition = await _recorded_fulfillment(tmp_path)

    async def failed(fulfillment_id, *, capacity_reservation_id=None, site_id=None):
        return FulfillmentStatusResponse(
            fulfillment_id=fulfillment_id, capacity_reservation_id=capacity_reservation_id,
            state="failed", failure_reason="create_failed",
        )

    provisioning.get_fulfillment_status = failed
    composition.lifecycle.end.physical = SimpleNamespace(apply_end=AsyncMock(return_value=SimpleNamespace(
        progress="tearing_down", done=False,
    )))

    await _resume(fixture, site, provisioning, composition)
    await _resume(fixture, site, provisioning, composition)

    persisted = await fixture.db.load_vm_delivery(negotiation_id="neg-1")
    assert persisted["status"] == "ended"
    stage.delivery_failed.assert_awaited_once()
    assert stage.delivery_failed.await_args.kwargs["source"] == "compute_delivery"
    await composition.lifecycle.close()


@pytest.mark.asyncio
async def test_an_active_result_for_another_fulfillment_is_never_made_available(tmp_path):
    fixture, site, provisioning, stage, composition = await _recorded_fulfillment(tmp_path)
    read = provisioning.get_fulfillment_result

    async def another(fulfillment_id, *, capacity_reservation_id=None, site_id=None):
        return await read("fulfillment-other", capacity_reservation_id=capacity_reservation_id)

    provisioning.get_fulfillment_result = another

    await _resume(fixture, site, provisioning, composition)

    persisted = await fixture.db.load_vm_delivery(negotiation_id="neg-1")
    assert persisted["status"] == "provisioning"
    assert persisted["activated_at_utc"] is None
    assert site.rows["reservation-1"]["activated_at_utc"] is None
    await composition.lifecycle.close()


@pytest.mark.asyncio
async def test_a_phase_this_storefront_never_writes_is_unreadable(tmp_path):
    fixture, site, provisioning, stage, composition = await _recorded_fulfillment(tmp_path)
    with sqlite3.connect(fixture.db.db_path) as conn:
        conn.execute("UPDATE vm_delivery_records SET fulfillment_phase='mystery' WHERE negotiation_id='neg-1'")

    await _resume(fixture, site, provisioning, composition)

    persisted = await fixture.db.load_vm_delivery(negotiation_id="neg-1")
    assert persisted["status"] == "provisioning"
    assert site.rows["reservation-1"]["activated_at_utc"] is None
    await composition.lifecycle.close()


class _RecordedStage:
    """A seller stage as composed, its evidence re-checks recorded."""

    def __init__(self, stage, rechecks: list[str]) -> None:
        self._stage = stage
        self._rechecks = rechecks

    async def recover_evidence(self, *, evidence, **kwargs):
        self._rechecks.append(evidence.negotiation_id)
        return await self._stage.recover_evidence(evidence=evidence, **kwargs)

    def __getattr__(self, name):
        return getattr(self._stage, name)


async def _waiting_payment_deal(payment_rig):
    """A payment deal settled an hour before its Agreement start, committed and waiting.

    The lifecycle's clock runs an hour behind wall time until ``offset`` is set
    to zero, which brings the deal to its start; the site stamps activation in
    wall time, so the start is never after it.
    """
    offset = [-3600]
    start = datetime.now(timezone.utc).replace(microsecond=0)
    rig = await payment_rig(start=start, clock=lambda: int(time.time()) + offset[0])
    rechecks: list[str] = []
    rig.composition.seller_stages = {
        mechanism: _RecordedStage(stage, rechecks)
        for mechanism, stage in rig.composition.seller_stages.items()
    }
    await rig.settle()
    await rig.delivered()
    row = _row(rig.db, NEGOTIATION)
    assert row["status"] == "provisioning" and row["capacity_reservation_id"] is not None
    assert rig.provisioning.begins == [] and row["processing_owner"] is None
    return rig, offset, rechecks


async def _resume_payment(rig):
    return await resume_incomplete_fulfillments_once(
        sqlite_client=rig.db, capacity=CapacityEffects(rig.site), fulfillment_client=rig.provisioning,
        composition=rig.composition, owner="resume-pass",
    )


@pytest.mark.asyncio
async def test_a_deal_waiting_for_its_start_is_claimed_re_checked_and_driven_at_its_start(payment_rig):
    rig, offset, rechecks = await _waiting_payment_deal(payment_rig)
    owners_at_begin: list[str | None] = []
    begin = rig.provisioning.begin_fulfillment

    async def observed_begin(body, *args, **kwargs):
        owners_at_begin.append(_row(rig.db, NEGOTIATION)["processing_owner"])
        return await begin(body, *args, **kwargs)

    rig.provisioning.begin_fulfillment = observed_begin
    offset[0] = 0

    assert await _resume_payment(rig) == 1

    assert rechecks == [NEGOTIATION]
    # The pass held the deal's claim while it drove, and released it after.
    assert owners_at_begin == ["resume-pass"]
    row = _row(rig.db, NEGOTIATION)
    assert row["processing_owner"] is None
    assert row["status"] == "ready"
    assert rig.site.rows[row["capacity_reservation_id"]]["activated_at_utc"] is not None


@pytest.mark.asyncio
async def test_a_deal_another_worker_holds_is_skipped(payment_rig):
    rig, offset, rechecks = await _waiting_payment_deal(payment_rig)
    offset[0] = 0
    assert await rig.db.claim_vm_delivery(
        negotiation_id=NEGOTIATION, owner="another-worker",
        lease_until=(datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat(),
    )

    assert await _resume_payment(rig) == 0

    assert rechecks == []
    assert rig.provisioning.begins == []
    row = _row(rig.db, NEGOTIATION)
    assert row["processing_owner"] == "another-worker"
    assert row["status"] == "provisioning"


@pytest.mark.asyncio
async def test_a_deal_whose_evidence_fails_its_re_check_is_not_driven(payment_rig, caplog):
    rig, offset, rechecks = await _waiting_payment_deal(payment_rig)
    offset[0] = 0
    # The receipt identity pin has moved: the stored receipt does not verify under it.
    rig.composition.arkhai_payments_stage = PaymentSellerStage(_config(service_identity=IMPOSTOR.identity))

    with caplog.at_level(logging.WARNING):
        assert await _resume_payment(rig) == 0

    assert rechecks == [NEGOTIATION]
    assert [
        record.getMessage() for record in caplog.records
        if record.name == "market_storefront.services.fulfillment_resume_runtime"
    ] == [
        f"[DELIVERY] {NEGOTIATION} does not re-check for recovery: "
        "payment evidence does not match accepted Agreement",
    ]
    assert not [record for record in caplog.records if record.name == "compute_delivery.recovery"]
    assert rig.provisioning.begins == []
    row = _row(rig.db, NEGOTIATION)
    assert row["processing_owner"] is None
    assert row["status"] == "provisioning"
