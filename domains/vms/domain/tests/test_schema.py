from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from arkhai_vms import (
    VM_PROVISION_KIND,
    VmListing,
    VmMaterialization,
    VmMessage,
    VmReceipt,
    VmResult,
    VmTerms,
    make_vm_provision_terms,
    normalize_vm_provision_terms,
    vm_listing_resource_shape,
)


def test_vm_schema_models_validate_current_payload_shapes() -> None:
    lease_start = datetime.now(UTC)
    lease_end = lease_start + timedelta(hours=1)

    listing = VmListing.model_validate({
        "gpu_model": "H200",
        "gpu_count": 1,
        "sla": 0.99,
        "region": "California, US",
    })
    message = VmMessage.model_validate(make_vm_provision_terms(
        duration_seconds=3600,
        ssh_public_key="ssh-ed25519 AAAA test",
        compute_resource=listing.listing_resource,
    ))
    terms = VmTerms.model_validate({
        "duration_seconds": 3600,
        "ssh_public_key": "ssh-ed25519 AAAA test",
        "compute_resource": listing.listing_resource,
    })
    materialization = VmMaterialization.model_validate({
        "escrow_uid": "escrow-1",
        "duration_seconds": 3600,
        "ssh_public_key": "ssh-ed25519 AAAA test",
        "compute_resource": listing.listing_resource,
        "lease_start_utc": lease_start,
        "lease_end_utc": lease_end,
    })
    receipt = VmReceipt.model_validate({
        "vm_name": "vm-1",
        "status": "leased",
    })
    result = VmResult.model_validate({
        "action": "vm_create",
        "vm_name": "vm-1",
    })

    assert listing.kind == VM_PROVISION_KIND
    assert message.kind == VM_PROVISION_KIND
    assert terms.kind == VM_PROVISION_KIND
    assert materialization.kind == VM_PROVISION_KIND
    assert receipt.kind == VM_PROVISION_KIND
    assert result.kind == VM_PROVISION_KIND


def test_a_vm_listing_without_gpus_validates() -> None:
    listing = VmListing.model_validate({
        "vcpu_count": 8,
        "ram_gb": 32,
        "sla": 0.99,
        "region": "California, US",
    })

    assert "gpu_count" not in listing.listing_resource
    assert vm_listing_resource_shape(listing.listing_resource) == {
        "cpu": {"count": 8},
        "memory": {"gib": 32},
    }


def test_a_gpu_field_stated_as_none_states_nothing() -> None:
    listing = VmListing.model_validate({
        "gpu_count": None,
        "gpu_model": None,
        "vcpu_count": 8,
        "region": "California, US",
    })

    assert vm_listing_resource_shape(listing.listing_resource) == {"cpu": {"count": 8}}


@pytest.mark.parametrize(
    ("resource", "reason"),
    [
        ({"gpu_model": "H200", "vcpu_count": 8}, "gpu.count: is required"),
        ({"gpu_count": 1, "vcpu_count": 8}, "gpu.model: is required"),
        ({"sla": 0.99, "region": "California, US"}, "a shape must name at least one family"),
        ({"gpu_count": 0, "gpu_model": "H200"}, "gpu.count: must be a positive integer"),
    ],
    ids=["model-alone", "count-alone", "no-quantity", "zero-gpus"],
)
def test_a_vm_listing_whose_fields_form_no_shape_is_refused(resource, reason) -> None:
    with pytest.raises(ValidationError, match=reason):
        VmListing.model_validate(resource)


def test_vm_message_accepts_provision_terms_carrier() -> None:
    message = VmMessage.model_validate({
        "kind": VM_PROVISION_KIND,
        "payload": {
            "duration_seconds": 3600,
            "ssh_public_key": "ssh-ed25519 AAAA test",
        },
    })

    assert message.duration_seconds == 3600
    assert message.ssh_public_key == "ssh-ed25519 AAAA test"

def test_vm_provision_normalization_accepts_wire_and_durable_shapes() -> None:
    payload = {
        "duration_seconds": 3600,
        "ssh_public_key": "ssh-ed25519 AAAA test",
    }

    assert normalize_vm_provision_terms(payload).payload == payload
    assert normalize_vm_provision_terms(
        {"kind": "compute.v1", "version": 1, "payload": payload}
    ).payload == payload
    assert normalize_vm_provision_terms(
        {
            "kind": "compute.v1",
            **payload,
            "settlement_selection": None,
        }
    ).payload == payload

