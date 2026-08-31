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
        compute_resource=listing.offer_resource,
    ))
    terms = VmTerms.model_validate({
        "duration_seconds": 3600,
        "ssh_public_key": "ssh-ed25519 AAAA test",
        "compute_resource": listing.offer_resource,
    })
    materialization = VmMaterialization.model_validate({
        "escrow_uid": "escrow-1",
        "duration_seconds": 3600,
        "ssh_public_key": "ssh-ed25519 AAAA test",
        "compute_resource": listing.offer_resource,
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


def test_vm_listing_requires_compute_identity() -> None:
    with pytest.raises(ValidationError, match="offer_resource must include gpu_model"):
        VmListing.model_validate({"gpu_count": 1})


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

