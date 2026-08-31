from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from market_storefront.services.fulfillment_resume_runtime import converge_escrow_once
from tests.fulfillment_fixtures import (
    make_vm_lifecycle_fixture,
    vm_fulfillment_result,
)


@pytest.mark.asyncio
async def test_known_fulfillment_resumes_without_schedule_or_begin(tmp_path):
    lifecycle = await make_vm_lifecycle_fixture(tmp_path / "known.db")
    await lifecycle.db.update_escrow(
        escrow_uid="escrow-1",
        capacity_reservation_id="reservation-1",
        settlement_resource_id="resource-1",
        fulfillment_id="fulfillment-1",
    )
    db = lifecycle.reopen()
    remote = SimpleNamespace(
        schedule_resource=AsyncMock(),
        begin_fulfillment=AsyncMock(),
        get_fulfillment_status=AsyncMock(
            return_value=SimpleNamespace(state="active", failure_message=None)
        ),
        get_fulfillment_result=AsyncMock(
            return_value=vm_fulfillment_result(
                provisioned_resource_id="vm-1",
                connection_info={"vm_name": "tenant-1", "host": "kvm1"},
            )
        ),
    )
    escrow = await db.load_escrow(escrow_uid="escrow-1")
    assert escrow is not None

    assert (
        await converge_escrow_once(escrow, sqlite_client=db, fulfillment_client=remote)
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
    persisted = await db.load_escrow(escrow_uid="escrow-1")
    assert persisted is not None
    assert persisted["fulfillment_phase"] == "physical_result_recorded"


@pytest.mark.asyncio
async def test_active_result_must_match_persisted_fulfillment_identity(tmp_path):
    lifecycle = await make_vm_lifecycle_fixture(tmp_path / "mismatched-result.db")
    await lifecycle.db.update_escrow(
        escrow_uid="escrow-1",
        capacity_reservation_id="reservation-1",
        settlement_resource_id="resource-1",
        fulfillment_id="fulfillment-1",
    )
    db = lifecycle.reopen()
    remote = SimpleNamespace(
        get_fulfillment_status=AsyncMock(
            return_value=SimpleNamespace(state="active", failure_message=None)
        ),
        get_fulfillment_result=AsyncMock(
            return_value=vm_fulfillment_result(
                capacity_reservation_id="different-reservation",
            )
        ),
    )
    escrow = await db.load_escrow(escrow_uid="escrow-1")
    assert escrow is not None

    with pytest.raises(RuntimeError, match="disagrees with active lifecycle"):
        await converge_escrow_once(
            escrow,
            sqlite_client=db,
            fulfillment_client=remote,
        )


@pytest.mark.asyncio
async def test_missing_identifiers_replay_exact_persisted_request(tmp_path):
    request = {
        "kind": "vm.fulfillment.request",
        "schema_version": 1,
        "payload": {"vm_target": "tenant-fixed", "ssh_pubkey": "ssh-ed25519 AAA"},
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
    capacity = SimpleNamespace(
        reserve=AsyncMock(
            return_value={
                "capacity_reservation_id": "reservation-1",
                "resource_id": "resource-1",
                "site": "site-1",
            }
        )
    )
    remote = SimpleNamespace(
        schedule_resource=AsyncMock(
            return_value=SimpleNamespace(settlement_resource_id="resource-1")
        ),
        begin_fulfillment=AsyncMock(
            return_value=SimpleNamespace(fulfillment_id="fulfillment-1")
        ),
        get_fulfillment_status=AsyncMock(
            return_value=SimpleNamespace(state="dispatching", failure_message=None)
        ),
    )
    escrow = await db.load_escrow(escrow_uid="escrow-1")
    assert escrow is not None

    assert (
        await converge_escrow_once(
            escrow,
            sqlite_client=db,
            fulfillment_client=remote,
            capacity_client=capacity,
        )
        is False
    )

    capacity.reserve.assert_awaited_once_with(
        claim={"gpu_count": 1, "executor_kind": "vm"},
        deal_ref={"listing_id": "listing-1", "escrow_uid": "escrow-1"},
        lease_start_utc=None,
        lease_duration_seconds=7200,
        site="site-1",
    )
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
    persisted = await db.load_escrow(escrow_uid="escrow-1")
    assert persisted is not None
    assert persisted["capacity_reservation_id"] == "reservation-1"
    assert persisted["settlement_resource_id"] == "resource-1"
    assert persisted["fulfillment_id"] == "fulfillment-1"
    assert persisted["fulfillment_phase"] == "fulfillment_accepted"


@pytest.mark.asyncio
async def test_post_physical_convergence_records_ready_and_claim():
    from market_storefront.services.fulfillment_resume_runtime import (
        converge_post_physical_delivery,
    )

    db = SimpleNamespace(
        update_escrow=AsyncMock(),
        store_credential=AsyncMock(),
        update_listing=AsyncMock(),
    )
    capacity = SimpleNamespace(commit=AsyncMock())
    register = AsyncMock()
    submit = AsyncMock(return_value="attestation-1")
    bind_fulfillment = AsyncMock()
    escrow = {
        "escrow_uid": "escrow-1",
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
            "payload": {"vm_target": "tenant-1"},
        },
    }
    assert (
        await converge_post_physical_delivery(
            escrow=escrow,
            context=context,
            sqlite_client=db,
            capacity_client=capacity,
            connection_details={"host": "kvm-1", "vm_name": "tenant-1"},
            authentication={"tenant": {"password": "secret", "key_type": "ed25519"}},
            register_lease=register,
            submit_fulfillment=submit,
            bind_fulfillment_fn=bind_fulfillment,
            alkahest_client=object(),
            site_id="site-1",
        )
        is True
    )
    submit.assert_awaited_once()
    assert submit.await_args.kwargs["allow_submit"] is True
    capacity.commit.assert_awaited_once()
    assert capacity.commit.await_args.kwargs["capacity_reservation_id"] == (
        "reservation-1"
    )
    assert capacity.commit.await_args.kwargs["site_id"] == "site-1"
    register.assert_awaited_once_with(
        resource_id="resource-1",
        capacity_reservation_id="reservation-1",
        escrow_uid="escrow-1",
        vm_host="kvm-1",
        vm_target="tenant-1",
        lease_start_utc=capacity.commit.await_args.kwargs["lease_start_utc"],
        lease_end_utc=capacity.commit.await_args.kwargs["lease_end_utc"],
    )
    assert any(
        call.kwargs.get("status") == "ready"
        and call.kwargs.get("fulfillment_phase") == "complete"
        for call in db.update_escrow.await_args_list
    )
    bind_fulfillment.assert_awaited_once_with(
        obligation_ref="obligation-1",
        fulfillment_ref="attestation-1",
    )


@pytest.mark.asyncio
async def test_ambiguous_onchain_recovery_never_blindly_resubmits():
    from market_storefront.services.fulfillment_resume_runtime import (
        converge_post_physical_delivery,
    )

    db = SimpleNamespace(
        update_escrow=AsyncMock(),
        store_credential=AsyncMock(),
        update_listing=AsyncMock(),
    )
    submit = AsyncMock(side_effect=RuntimeError("query unavailable"))
    escrow = {
        "escrow_uid": "escrow-1",
        "capacity_reservation_id": "reservation-1",
        "settlement_resource_id": "resource-1",
        "fulfillment_phase": "onchain_submission_started",
    }
    with pytest.raises(RuntimeError, match="query unavailable"):
        await converge_post_physical_delivery(
            escrow=escrow,
            context={"fulfillment_request": {"payload": {}}},
            sqlite_client=db,
            capacity_client=SimpleNamespace(commit=AsyncMock()),
            connection_details={},
            authentication=None,
            submit_fulfillment=submit,
            alkahest_client=object(),
            site_id="site-1",
        )
    assert submit.await_args.kwargs["allow_submit"] is False


@pytest.mark.asyncio
async def test_hosted_deal_is_not_swept_by_the_chain_convergence_loop(tmp_path):
    """A hosted deal already has a convergence owner and must keep only one.

    The settlement runtime reserves fulfillment before it provisions. This
    sweep takes no such reservation, so converging a hosted escrow here puts
    two owners on one capacity reservation -- observed as a second provisioning
    two seconds behind the first, rejected as ``fulfillment_conflict``.
    """

    lifecycle = await make_vm_lifecycle_fixture(tmp_path / "hosted.db")
    db = lifecycle.reopen()
    escrow = await db.load_escrow(escrow_uid="escrow-1")
    assert escrow is not None
    hosted = {**escrow, "chain_name": None}
    remote = SimpleNamespace(
        schedule_resource=AsyncMock(),
        begin_fulfillment=AsyncMock(),
        get_fulfillment_status=AsyncMock(),
        get_fulfillment_result=AsyncMock(),
    )

    assert (
        await converge_escrow_once(hosted, sqlite_client=db, fulfillment_client=remote)
        is False
    )
    remote.schedule_resource.assert_not_awaited()
    remote.begin_fulfillment.assert_not_awaited()
    remote.get_fulfillment_status.assert_not_awaited()
