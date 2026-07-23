from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from arkhai_bare_metal import (
    BARE_METAL_ACCESS_ACTIONS,
    BARE_METAL_PROVISION_VERSION,
    BARE_METAL_SCHEMA_KIND,
    NODE_GRANT_ACCESS_ACTION,
    NODE_RECLAIM_ACCESS_ACTION,
    PHYSICAL_HOST_ID_REF_KEY,
    SSH_ACCESS_METHOD,
    BareMetalAccessResult,
    BareMetalLeaseCreate,
    BareMetalLeaseView,
    BareMetalListing,
    BareMetalMaterialization,
    BareMetalMessage,
    BareMetalProvisionTerms,
    BareMetalReceipt,
    BareMetalTerms,
    bare_metal_executor_ref,
    make_bare_metal_provision_terms,
    materialization_to_lease_create,
    receipt_from_lease_view,
)


def test_bare_metal_listing_is_domain_payload_not_registry_row():
    listing = BareMetalListing(
        machine_id="bm-node-1",
        physical_host_id="host-physical-1",
        min_duration_seconds=3600,
        max_duration_seconds=7200,
        site={"region": "us-west"},
        capabilities={"gpu_model": "L40S", "ram_gb": 256},
    )

    assert listing.kind == BARE_METAL_SCHEMA_KIND
    assert listing.machine_id == "bm-node-1"
    assert listing.physical_host_id == "host-physical-1"
    assert listing.access_methods == [SSH_ACCESS_METHOD]
    assert "publisher" not in listing.model_dump()
    assert "storefront_url" not in listing.model_dump()


def test_bare_metal_listing_keeps_machine_and_physical_ids_separate():
    listing = BareMetalListing(
        machine_id="executor-local-node",
        physical_host_id="site-physical-host",
    )

    assert listing.machine_id != listing.physical_host_id


def test_bare_metal_listing_rejects_invalid_duration_bounds():
    with pytest.raises(ValidationError):
        BareMetalListing(
            machine_id="bm-node-1",
            physical_host_id="host-physical-1",
            min_duration_seconds=7200,
            max_duration_seconds=3600,
        )


def test_bare_metal_message_requires_access_material_for_ssh():
    with pytest.raises(ValidationError):
        BareMetalMessage(duration_seconds=3600)


def test_bare_metal_message_accepts_ssh_public_key():
    message = BareMetalMessage(
        duration_seconds=3600,
        ssh_public_key="ssh-ed25519 AAAA buyer",
    )

    assert message.kind == BARE_METAL_SCHEMA_KIND
    assert message.access_method == SSH_ACCESS_METHOD
    assert message.ssh_public_key == "ssh-ed25519 AAAA buyer"


def test_bare_metal_message_unwraps_versioned_provision_terms():
    envelope = make_bare_metal_provision_terms(
        duration_seconds=3600,
        ssh_public_key="ssh-ed25519 AAAA buyer",
    )
    original = envelope.model_dump(mode="json")

    message = BareMetalMessage.model_validate(envelope)

    assert envelope.version == BARE_METAL_PROVISION_VERSION
    assert message.duration_seconds == 3600
    assert message.ssh_public_key == "ssh-ed25519 AAAA buyer"
    assert envelope.model_dump(mode="json") == original


@pytest.mark.parametrize(
    "value",
    [
        {"kind": "compute.v1", "version": 1, "payload": {"duration_seconds": 1, "access_method": "ssh", "ssh_public_key": "key"}},
        {"kind": "bare_metal.v1", "version": 2, "payload": {"duration_seconds": 1, "access_method": "ssh", "ssh_public_key": "key"}},
        {"kind": "bare_metal.v1", "version": 1, "payload": {"duration_seconds": 1, "access_method": "ssh", "ssh_public_key": "key", "unknown": True}},
        {"kind": "bare_metal.v1", "version": 1, "payload": {"duration_seconds": 1, "access_method": "ssh", "ssh_public_key": "   "}},
    ],
)
def test_bare_metal_provision_terms_reject_invalid_envelopes(value):
    with pytest.raises(ValidationError):
        BareMetalProvisionTerms.model_validate(value)


def test_bare_metal_terms_are_canonical_negotiation_handoff():
    terms = BareMetalTerms(
        machine_id="bm-node-1",
        physical_host_id="host-physical-1",
        duration_seconds=3600,
        ssh_public_key="ssh-ed25519 AAAA buyer",
        listing_ref="listing-1",
    )

    assert terms.kind == BARE_METAL_SCHEMA_KIND
    assert terms.duration_seconds == 3600
    assert terms.listing_ref == "listing-1"
    assert "executor_action" not in terms.model_dump()
    assert "playbook" not in terms.model_dump()


def test_bare_metal_materialization_is_settlement_handoff():
    materialization = BareMetalMaterialization(
        escrow_uid="0xbm",
        machine_id="bm-node-1",
        physical_host_id="host-physical-1",
        lease_start_utc=datetime(2099, 1, 1, tzinfo=timezone.utc),
        lease_end_utc=datetime(2099, 1, 1, 1, tzinfo=timezone.utc),
        ssh_public_key="ssh-ed25519 AAAA buyer",
        listing_ref="listing-1",
        settlement_ref={"chain": "anvil"},
    )

    assert materialization.kind == BARE_METAL_SCHEMA_KIND
    assert materialization.access_method == SSH_ACCESS_METHOD
    assert materialization.settlement_ref == {"chain": "anvil"}
    assert "playbook" not in materialization.model_dump()


def test_bare_metal_materialization_rejects_invalid_window():
    with pytest.raises(ValidationError):
        BareMetalMaterialization(
            escrow_uid="0xbm",
            machine_id="bm-node-1",
            physical_host_id="host-physical-1",
            lease_start_utc=datetime(2099, 1, 1, 1, tzinfo=timezone.utc),
            lease_end_utc=datetime(2099, 1, 1, tzinfo=timezone.utc),
            ssh_public_key="ssh-ed25519 AAAA buyer",
        )


def test_materialization_to_lease_create_adapts_current_api_request():
    materialization = BareMetalMaterialization(
        escrow_uid="0xbm",
        machine_id="bm-node-1",
        physical_host_id="host-physical-1",
        lease_end_utc=datetime(2099, 1, 1, 1, tzinfo=timezone.utc),
        ssh_public_key="ssh-ed25519 AAAA buyer",
        access_ref={"ssh_user": "tenant-a"},
    )

    request = materialization_to_lease_create(
        materialization,
        capacity_reservation_id="alloc-1",
        create_job_id="job-1",
    )

    assert request.capacity_reservation_id == "alloc-1"
    assert request.escrow_uid == "0xbm"
    assert request.machine_id == "bm-node-1"
    assert request.physical_host_id == "host-physical-1"
    assert request.lease_end_utc == materialization.lease_end_utc
    assert request.create_job_id == "job-1"
    assert request.access_ref == {
        "ssh_user": "tenant-a",
        "ssh_public_key": "ssh-ed25519 AAAA buyer",
        "access_method": SSH_ACCESS_METHOD,
    }


def test_bare_metal_receipt_is_domain_view_not_executor_result():
    receipt = BareMetalReceipt(
        escrow_uid="0xbm",
        machine_id="bm-node-1",
        physical_host_id="host-physical-1",
        lease_start_utc=datetime(2099, 1, 1, tzinfo=timezone.utc),
        lease_end_utc=datetime(2099, 1, 1, 1, tzinfo=timezone.utc),
        status="leased",
        access_ref={"ssh_user": "tenant-a"},
        result_ref={"grant_job_id": "job-1"},
    )

    assert receipt.kind == BARE_METAL_SCHEMA_KIND
    assert receipt.status == "leased"
    assert "executor_action" not in receipt.model_dump()


def test_receipt_from_lease_view_adapts_current_api_view():
    lease = BareMetalLeaseView(
        capacity_reservation_id="alloc-1",
        escrow_uid="0xbm",
        machine_id="bm-node-1",
        physical_host_id="host-physical-1",
        lease_start_utc="2099-01-01T00:00:00+00:00",
        lease_end_utc="2099-01-01T01:00:00+00:00",
        state="leased",
        release_job_id=None,
        access_ref={"ssh_user": "tenant-a"},
    )

    receipt = receipt_from_lease_view(
        lease,
        result_ref={"capacity_reservation_id": "alloc-1"},
    )

    assert receipt.escrow_uid == "0xbm"
    assert receipt.machine_id == "bm-node-1"
    assert receipt.status == "leased"
    assert receipt.lease_start_utc == datetime(
        2099, 1, 1, tzinfo=timezone.utc,
    )
    assert receipt.result_ref == {"capacity_reservation_id": "alloc-1"}


def test_bare_metal_lease_create_keeps_machine_and_physical_ids_separate():
    body = BareMetalLeaseCreate(
        capacity_reservation_id="alloc-1",
        escrow_uid="0xbm",
        machine_id="bm-node-1",
        physical_host_id="host-physical-1",
        lease_end_utc=datetime(2099, 1, 1, 1, 0, tzinfo=timezone.utc),
    )

    assert body.machine_id == "bm-node-1"
    assert body.physical_host_id == "host-physical-1"


def test_bare_metal_executor_ref_uses_reserved_physical_host_key():
    ref = bare_metal_executor_ref(
        "host-physical-1",
        access_ref={"ssh_user": "tenant-a"},
    )

    assert ref == {
        PHYSICAL_HOST_ID_REF_KEY: "host-physical-1",
        "ssh_user": "tenant-a",
    }


def test_bare_metal_lease_create_rejects_blank_identity_fields():
    with pytest.raises(ValidationError):
        BareMetalLeaseCreate(
            escrow_uid="0xbm",
            machine_id=" ",
            physical_host_id="host-physical-1",
            lease_end_utc=datetime(2099, 1, 1, 1, 0, tzinfo=timezone.utc),
        )


def test_bare_metal_access_actions_are_domain_owned():
    assert BARE_METAL_ACCESS_ACTIONS == (
        NODE_GRANT_ACCESS_ACTION,
        NODE_RECLAIM_ACCESS_ACTION,
    )


def test_bare_metal_access_result_accepts_contract_action():
    result = BareMetalAccessResult(
        action=NODE_GRANT_ACCESS_ACTION,
        machine_id="bm-node-1",
        physical_host_id="host-physical-1",
        ssh_user="tenant-a",
        escrow_uid="0xbm",
    )

    assert result.action == NODE_GRANT_ACCESS_ACTION
    assert result.machine_id == "bm-node-1"
    assert result.status == "success"


def test_bare_metal_access_result_rejects_unknown_action():
    with pytest.raises(ValidationError):
        BareMetalAccessResult(
            action="delete_everything",
            machine_id="bm-node-1",
        )
