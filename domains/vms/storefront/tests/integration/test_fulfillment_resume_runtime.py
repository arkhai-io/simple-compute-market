"""The resume pass drives each unfinished VM delivery through the delivery path.

Real SQLite persistence and the real path, end service and deal lifecycle;
the site and provisioning service are the fakes at the storefront's aggregate
clients, and the Alkahest stage's chain reads are replaced at the stage.
"""

import sqlite3
from functools import partial
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from compute_provisioning_contracts import FulfillmentStatusResponse
from market_capacity_publication import CapacityEffects
from market_storefront_kit.dispute_configuration import RegistryDisputePolicy

from market_storefront.deal_lifecycle import VmDealLifecycle
from market_storefront.domain_runtime import build_vm_storefront_domain
from market_storefront.services.fulfillment_resume_runtime import resume_incomplete_fulfillments_once
from tests.delivery_fakes import DeliveryProvisioning, DeliverySite
from tests.fulfillment_fixtures import SELLER_PRINCIPAL, make_vm_lifecycle_fixture

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
