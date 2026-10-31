from functools import partial
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from compute_provisioning_contracts import FulfillmentStatusResponse
from market_alkahest import RELEASE_MODELS
from market_fulfillment import CREATE_COMPENSATION

from market_storefront.services.fulfillment_resume_runtime import (
    converge_delivery_once,
    converge_post_physical_delivery,
)
from market_storefront.settlement_stages import VmAlkahestSellerStage
from tests.fulfillment_fixtures import (
    make_vm_lifecycle_fixture,
    vm_delivery_evidence,
    vm_fulfillment_result,
)


@pytest.mark.asyncio
async def test_known_fulfillment_resumes_without_schedule_or_begin(tmp_path):
    lifecycle = await make_vm_lifecycle_fixture(tmp_path / "known.db")
    delivery = lifecycle.db
    await delivery.update_vm_delivery(
        negotiation_id="neg-1",
        capacity_reservation_id="reservation-1",
        settlement_resource_id="resource-1",
        fulfillment_id="fulfillment-1",
    )
    db = lifecycle.reopen()
    remote = SimpleNamespace(
        schedule_resource=AsyncMock(),
        begin_fulfillment=AsyncMock(),
        get_fulfillment_status=AsyncMock(
            return_value=SimpleNamespace(
                state="active", failure_reason=None, failure_message=None
            )
        ),
        get_fulfillment_result=AsyncMock(
            return_value=vm_fulfillment_result(
                provisioned_resource_id="vm-1",
            )
        ),
    )
    escrow = await db.load_vm_delivery(negotiation_id="neg-1")
    assert escrow is not None

    assert (
        await converge_delivery_once(
            escrow,
            evidence=lifecycle.evidence,
            sqlite_client=db,
            fulfillment_client=remote,
        )
        is True
    )
    remote.schedule_resource.assert_not_awaited()
    remote.begin_fulfillment.assert_not_awaited()
    remote.get_fulfillment_status.assert_awaited_once_with(
        "fulfillment-1",
        capacity_reservation_id="reservation-1",
        site_id="site-1",
    )
    remote.get_fulfillment_result.assert_awaited_once_with(
        "fulfillment-1",
        capacity_reservation_id="reservation-1",
        site_id="site-1",
    )
    persisted = await db.load_vm_delivery(negotiation_id="neg-1")
    assert persisted is not None
    assert persisted["fulfillment_phase"] == "physical_result_recorded"


async def _converge_known_fulfillment(tmp_path, status: FulfillmentStatusResponse):
    """One resume pass over a delivery whose fulfillment is known, reading
    ``status``, with the failure policy recorded."""
    lifecycle = await make_vm_lifecycle_fixture(tmp_path / f"{status.state}.db")
    await lifecycle.db.update_vm_delivery(
        negotiation_id="neg-1",
        capacity_reservation_id="reservation-1",
        settlement_resource_id="resource-1",
        fulfillment_id="fulfillment-1",
    )
    db = lifecycle.reopen()
    remote = SimpleNamespace(
        schedule_resource=AsyncMock(),
        begin_fulfillment=AsyncMock(),
        get_fulfillment_status=AsyncMock(return_value=status),
        get_fulfillment_result=AsyncMock(),
    )
    failure_policy = AsyncMock()
    delivery = await db.load_vm_delivery(negotiation_id="neg-1")
    assert delivery is not None
    progressed = await converge_delivery_once(
        delivery,
        evidence=lifecycle.evidence,
        sqlite_client=db,
        fulfillment_client=remote,
        failure_policy=failure_policy,
    )
    persisted = await db.load_vm_delivery(negotiation_id="neg-1")
    assert persisted is not None
    return progressed, persisted, remote, failure_policy


def _status(state: str, failure_reason: str | None) -> FulfillmentStatusResponse:
    return FulfillmentStatusResponse(
        fulfillment_id="fulfillment-1",
        capacity_reservation_id="reservation-1",
        state=state,
        failure_reason=failure_reason,
        failure_message="grant reported no delivery evidence",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "state",
    ["teardown_dispatch_pending", "tearing_down", "teardown_failed", "torn_down"],
)
async def test_a_compensating_fulfillment_is_a_failed_delivery_in_every_state(
    tmp_path, state
):
    """Compensation moves a failed create on from ``failed``; a delivery first
    read after that has failed, as one read ``failed`` has, and is not left
    waiting for an ``active`` it will never reach."""
    progressed, persisted, remote, failure_policy = await _converge_known_fulfillment(
        tmp_path, _status(state, CREATE_COMPENSATION)
    )

    assert progressed is True
    assert persisted["status"] == "failed"
    assert persisted["fulfillment_phase"] == "physical_failed"
    remote.get_fulfillment_result.assert_not_awaited()
    remote.begin_fulfillment.assert_not_awaited()
    failure_policy.assert_awaited_once()
    assert failure_policy.await_args.kwargs["reason"] == "provisioning_failed"
    assert failure_policy.await_args.kwargs["capacity_reservation_id"] == (
        "reservation-1"
    )
    assert failure_policy.await_args.kwargs["message"] == (
        "grant reported no delivery evidence"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("state", "failure_reason"),
    [
        ("torn_down", None),
        ("torn_down", "provider_reported_failure"),
        ("teardown_failed", "provider_reported_failure"),
        ("tearing_down", None),
    ],
)
async def test_a_delivered_fulfillments_teardown_is_not_a_failed_delivery(
    tmp_path, state, failure_reason
):
    """A teardown that began from ``active`` carries no compensation marker,
    whatever reason a failed attempt left, so it is never read as a failed
    delivery."""
    progressed, persisted, remote, failure_policy = await _converge_known_fulfillment(
        tmp_path, _status(state, failure_reason)
    )

    assert progressed is False
    assert persisted["status"] != "failed"
    assert persisted["fulfillment_phase"] != "physical_failed"
    failure_policy.assert_not_awaited()
    remote.get_fulfillment_result.assert_not_awaited()


@pytest.mark.asyncio
async def test_active_result_must_match_persisted_fulfillment_identity(tmp_path):
    lifecycle = await make_vm_lifecycle_fixture(tmp_path / "mismatched-result.db")
    await lifecycle.db.update_vm_delivery(
        negotiation_id="neg-1",
        capacity_reservation_id="reservation-1",
        settlement_resource_id="resource-1",
        fulfillment_id="fulfillment-1",
    )
    db = lifecycle.reopen()
    remote = SimpleNamespace(
        get_fulfillment_status=AsyncMock(
            return_value=SimpleNamespace(
                state="active", failure_reason=None, failure_message=None
            )
        ),
        get_fulfillment_result=AsyncMock(
            return_value=vm_fulfillment_result(
                capacity_reservation_id="different-reservation",
            )
        ),
    )
    escrow = await db.load_vm_delivery(negotiation_id="neg-1")
    assert escrow is not None

    with pytest.raises(RuntimeError, match="disagrees with active lifecycle"):
        await converge_delivery_once(
            escrow,
            evidence=lifecycle.evidence,
            sqlite_client=db,
            fulfillment_client=remote,
        )


@pytest.mark.asyncio
async def test_missing_identifiers_replay_exact_persisted_request(tmp_path):
    request = {
        "kind": "vm.fulfillment.request",
        "schema_version": 1,
        "payload": {"ssh_pubkey": "ssh-ed25519 test"},
    }
    lifecycle = await make_vm_lifecycle_fixture(
        tmp_path / "replay.db",
        context_payload={
            "duration_seconds": 7200,
            "required_attributes": {"gpu_count": 1},
            "fulfillment_request": request,
        },
    )
    db = lifecycle.reopen()
    order: list[str] = []
    capacity = SimpleNamespace(
        site_names=["site-1"],
        commit=AsyncMock(side_effect=lambda **_: order.append("commit") or _RECORDED),
        reserve=AsyncMock(
            return_value={
                "capacity_reservation_id": "reservation-1",
                "resource_id": "resource-1",
                "site": "site-1",
            }
        ),
    )
    remote = SimpleNamespace(
        schedule_resource=AsyncMock(
            return_value=SimpleNamespace(settlement_resource_id="resource-1")
        ),
        begin_fulfillment=AsyncMock(
            side_effect=lambda *_, **__: order.append("begin")
            or SimpleNamespace(fulfillment_id="fulfillment-1")
        ),
        get_fulfillment_status=AsyncMock(
            return_value=SimpleNamespace(
                state="dispatching", failure_reason=None, failure_message=None
            )
        ),
    )
    escrow = await db.load_vm_delivery(negotiation_id="neg-1")
    assert escrow is not None

    assert (
        await converge_delivery_once(
            escrow,
            evidence=lifecycle.evidence,
            sqlite_client=db,
            fulfillment_client=remote,
            capacity_client=capacity,
        )
        is False
    )

    capacity.reserve.assert_awaited_once_with(
        claim={"gpu_count": 1, "offering_mode": "vm"},
        deal_ref={"listing_id": "listing-1", "negotiation_id": "neg-1"},
        ttl_seconds=None,
        lease_start_utc="2026-01-01T00:00:00+00:00",
        lease_duration_seconds=7200,
        site="site-1",
    )
    # The recovered reservation is committed, beginning the lease and naming
    # the deal, before its fulfillment begins.
    assert order == ["commit", "begin"]
    committed = capacity.commit.await_args.kwargs
    assert committed["capacity_reservation_id"] == "reservation-1"
    assert committed["deal_ref"] == {"negotiation_id": "neg-1"}
    assert committed["site_id"] == "site-1"
    remote.schedule_resource.assert_awaited_once()
    scheduled_body = remote.schedule_resource.await_args.args[0]
    assert scheduled_body.market == "vms"
    assert scheduled_body.capacity_reservation_id == "reservation-1"
    assert remote.schedule_resource.await_args.kwargs == {"site_id": "site-1"}
    accepted_body = remote.begin_fulfillment.await_args.args[0]
    assert accepted_body.fulfillment_request.model_dump() == request
    assert accepted_body.capacity_reservation_id == "reservation-1"
    assert remote.begin_fulfillment.await_args.kwargs == {"site_id": "site-1"}
    assert accepted_body.market == "vms"
    remote.get_fulfillment_status.assert_awaited_once_with(
        "fulfillment-1",
        capacity_reservation_id="reservation-1",
        site_id="site-1",
    )
    persisted = await db.load_vm_delivery(negotiation_id="neg-1")
    assert persisted is not None
    assert persisted["capacity_reservation_id"] == "reservation-1"
    assert persisted["settlement_resource_id"] == "resource-1"
    assert persisted["fulfillment_id"] == "fulfillment-1"
    assert persisted["fulfillment_phase"] == "fulfillment_accepted"


@pytest.mark.asyncio
async def test_post_physical_convergence_records_ready_and_claim():
    db = SimpleNamespace(
        update_vm_delivery=AsyncMock(),
        update_escrow=AsyncMock(),
        store_credential=AsyncMock(),
        update_listing=AsyncMock(),
    )
    capacity = SimpleNamespace(commit=AsyncMock())
    submit = AsyncMock(return_value="attestation-1")
    bind_fulfillment = AsyncMock()
    escrow = {
        "negotiation_id": "neg-1",
        "obligation_ref": "obligation-1",
        "chain_name": "base-sepolia",
        "escrow_address": "0xabc",
        "capacity_reservation_id": "reservation-1",
        "settlement_resource_id": "resource-1",
        "fulfillment_phase": "physical_result_recorded",
    }
    context = {
        "listing_id": "listing-1",
        "seller_order_id": "order-1",
        "duration_seconds": 3600,
        "fulfillment_request": {
            "payload": {"ssh_pubkey": "ssh-ed25519 AAA"},
        },
    }
    assert (
        await converge_post_physical_delivery(
            delivery=escrow,
            context=context,
            sqlite_client=db,
            capacity_client=capacity,
            connection_details={"host": "203.0.113.1", "port": 2222, "user": "tenant"},
            authentication={"tenant": {"password": "secret", "key_type": "ed25519"}},
            continuation=partial(
                VmAlkahestSellerStage(
                    None,
                    fulfils_through_capacity=True,
                    completes_outside_settlement=False,
                    release_models=RELEASE_MODELS,
                ).continue_delivery,
                evidence=vm_delivery_evidence(),
                db=db,
                submit=submit,
                bind=bind_fulfillment,
                client=object(),
            ),
        )
        is True
    )
    submit.assert_awaited_once()
    assert submit.await_args.kwargs["allow_submit"] is True
    # The lease was written at commit, before the fulfillment began, and its
    # target at activation: nothing after delivery writes it.
    capacity.commit.assert_not_awaited()
    assert any(
        call.kwargs.get("status") == "ready"
        and call.kwargs.get("fulfillment_phase") == "complete"
        for call in db.update_vm_delivery.await_args_list
    )
    bind_fulfillment.assert_awaited_once_with(
        obligation_ref="obligation-1",
        fulfillment_ref="attestation-1",
    )


@pytest.mark.asyncio
async def test_ambiguous_onchain_recovery_never_blindly_resubmits():
    db = SimpleNamespace(
        update_vm_delivery=AsyncMock(),
        store_credential=AsyncMock(),
        update_listing=AsyncMock(),
    )
    submit = AsyncMock(side_effect=RuntimeError("query unavailable"))
    escrow = {
        "negotiation_id": "neg-1",
        "capacity_reservation_id": "reservation-1",
        "settlement_resource_id": "resource-1",
        "fulfillment_phase": "onchain_submission_started",
    }
    with pytest.raises(RuntimeError, match="query unavailable"):
        await converge_post_physical_delivery(
            delivery=escrow,
            context={"fulfillment_request": {"payload": {}}},
            sqlite_client=db,
            capacity_client=SimpleNamespace(commit=AsyncMock(return_value=_RECORDED)),
            connection_details={},
            authentication=None,
            continuation=partial(
                VmAlkahestSellerStage(
                    None,
                    fulfils_through_capacity=True,
                    completes_outside_settlement=False,
                    release_models=RELEASE_MODELS,
                ).continue_delivery,
                evidence=vm_delivery_evidence(),
                db=db,
                submit=submit,
                client=object(),
            ),
        )
    assert submit.await_args.kwargs["allow_submit"] is False


_RECORDED = {
    "capacity_reservation_id": "reservation-1",
    "state": "leased",
    "lease_start_utc": "2026-01-01T00:00:00+00:00",
    "lease_end_utc": "2026-01-01 01:00",
}
