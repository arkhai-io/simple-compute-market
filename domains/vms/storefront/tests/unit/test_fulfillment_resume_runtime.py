import sqlite3
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from market_fulfillment import VersionedEnvelope

from market_storefront.services.fulfillment_resume_runtime import converge_escrow_once


@pytest.mark.asyncio
async def test_known_fulfillment_resumes_without_schedule_or_begin():
    db = SimpleNamespace(update_escrow=AsyncMock())
    remote = SimpleNamespace(
        get_fulfillment_status=AsyncMock(
            return_value=SimpleNamespace(state="active", failure_message=None)
        ),
        get_fulfillment_result=AsyncMock(
            return_value=VersionedEnvelope(
                kind="fulfillment.result.v1",
                schema_version=1,
                payload={
                    "provisioned_resources": [
                        {"provisioned_resource_id": "vm-1", "status": "active"}
                    ],
                    "domain_result": {
                        "kind": "vm.fulfillment.result.v1",
                        "schema_version": 1,
                        "payload": {
                            "connection_info": {"vm_name": "tenant-1", "host": "kvm1"},
                            "credentials": [],
                        },
                    },
                },
            )
        ),
    )
    escrow = {
        "escrow_uid": "escrow-1",
        "status": "provisioning",
        "capacity_reservation_id": "reservation-1",
        "fulfillment_id": "fulfillment-1",
        "fulfillment_context": '{"kind":"vm.storefront.fulfillment-context",'
        '"schema_version":1,"payload":{"escrow_uid":"escrow-1"}}',
    }

    assert (
        await converge_escrow_once(escrow, sqlite_client=db, fulfillment_client=remote)
        is True
    )
    remote.get_fulfillment_status.assert_awaited_once_with(
        "fulfillment-1", capacity_reservation_id="reservation-1"
    )
    remote.get_fulfillment_result.assert_awaited_once()
    db.update_escrow.assert_awaited_once()
    assert (
        db.update_escrow.await_args.kwargs["fulfillment_phase"]
        == "physical_result_recorded"
    )


@pytest.mark.asyncio
async def test_missing_identifiers_replay_exact_persisted_request(tmp_path):
    db_path = str(tmp_path / "test.db")
    sqlite3.connect(db_path).close()  # a real, valid (if empty) sqlite file
    db = SimpleNamespace(update_escrow=AsyncMock(), db_path=db_path)
    capacity = SimpleNamespace(
        reserve=AsyncMock(
            return_value={
                "capacity_reservation_id": "reservation-1",
                "resource_id": "resource-1",
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
    request = {
        "kind": "vm.fulfillment.request",
        "schema_version": 1,
        "payload": {"vm_target": "tenant-fixed", "ssh_pubkey": "ssh-ed25519 AAA"},
    }
    escrow = {
        "escrow_uid": "escrow-1",
        "status": "provisioning",
        "capacity_reservation_id": None,
        "settlement_resource_id": None,
        "fulfillment_id": None,
        "fulfillment_context": __import__("json").dumps(
            {
                "kind": "vm.storefront.fulfillment-context",
                "schema_version": 1,
                "payload": {
                    "escrow_uid": "escrow-1",
                    "listing_id": "listing-1",
                    "duration_seconds": 7200,
                    "required_attributes": {"gpu_count": 1},
                    "fulfillment_request": request,
                },
            }
        ),
    }

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
        claim={"gpu_count": 1},
        deal_ref={"listing_id": "listing-1", "escrow_uid": "escrow-1"},
        lease_start_utc=None,
        lease_duration_seconds=7200,
        site=None,
    )
    accepted_body = remote.begin_fulfillment.await_args.args[0]
    assert accepted_body.fulfillment_request.model_dump() == request
    remote.get_fulfillment_status.assert_awaited_once_with(
        "fulfillment-1", capacity_reservation_id="reservation-1"
    )
    assert db.update_escrow.await_count == 3


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
        )
        is True
    )
    submit.assert_awaited_once()
    assert submit.await_args.kwargs["allow_submit"] is True
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
        )
    assert submit.await_args.kwargs["allow_submit"] is False
