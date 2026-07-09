from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

pytest.importorskip("core_storefront.domain_runtime")

from arkhai_vms import (  # noqa: E402
    VM_PROVISION_KIND,
    VmListing,
    VmMaterialization,
    VmMessage,
    VmReceipt,
    VmResult,
    VmTerms,
)
from arkhai_vms.domain_runtime import storefront_runtime  # noqa: E402


def test_storefront_runtime_normalizes_vm_schema_slots() -> None:
    runtime = storefront_runtime()
    lease_end = datetime.now(UTC) + timedelta(hours=1)

    listing = runtime.listing({
        "gpu_model": "H200",
        "gpu_count": 1,
        "sla": 0.99,
        "region": "California, US",
    })
    message = runtime.message({
        "duration_seconds": 3600,
        "ssh_public_key": "ssh-ed25519 AAAA test",
    })
    terms = runtime.terms({
        "duration_seconds": 3600,
        "ssh_public_key": "ssh-ed25519 AAAA test",
    })
    materialization = runtime.materialization({
        "escrow_uid": "escrow-1",
        "duration_seconds": 3600,
        "ssh_public_key": "ssh-ed25519 AAAA test",
        "lease_end_utc": lease_end,
    })
    receipt = runtime.receipt({
        "status": "leased",
        "vm_name": "vm-1",
    })
    result = runtime.result({
        "action": "vm_create",
        "vm_name": "vm-1",
    })

    assert runtime.schema_id == VM_PROVISION_KIND
    assert isinstance(listing, VmListing)
    assert isinstance(message, VmMessage)
    assert isinstance(terms, VmTerms)
    assert isinstance(materialization, VmMaterialization)
    assert isinstance(receipt, VmReceipt)
    assert isinstance(result, VmResult)


def test_storefront_runtime_surfaces_vm_validation_errors() -> None:
    runtime = storefront_runtime()

    with pytest.raises(ValidationError, match="ssh_public_key must be non-empty"):
        runtime.message({
            "duration_seconds": 3600,
            "ssh_public_key": "",
        })

