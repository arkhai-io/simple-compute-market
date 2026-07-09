from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

pytest.importorskip("core_storefront.domain_runtime")

from arkhai_bare_metal import (
    BARE_METAL_SCHEMA_KIND,
    NODE_GRANT_ACCESS_ACTION,
    BareMetalAccessResult,
    BareMetalListing,
    BareMetalMaterialization,
    BareMetalMessage,
    BareMetalReceipt,
    BareMetalTerms,
)
from arkhai_bare_metal.domain_runtime import storefront_runtime


def test_storefront_runtime_normalizes_bare_metal_schema_slots() -> None:
    runtime = storefront_runtime()
    lease_end = datetime.now(UTC) + timedelta(hours=1)

    listing = runtime.listing({
        "machine_id": "node-1",
        "physical_host_id": "host-1",
    })
    message = runtime.message({
        "duration_seconds": 3600,
        "ssh_public_key": "ssh-ed25519 AAAA test",
    })
    terms = runtime.terms({
        "machine_id": "node-1",
        "physical_host_id": "host-1",
        "duration_seconds": 3600,
        "ssh_public_key": "ssh-ed25519 AAAA test",
    })
    materialization = runtime.materialization({
        "escrow_uid": "escrow-1",
        "machine_id": "node-1",
        "physical_host_id": "host-1",
        "lease_end_utc": lease_end,
        "ssh_public_key": "ssh-ed25519 AAAA test",
    })
    receipt = runtime.receipt({
        "machine_id": "node-1",
        "physical_host_id": "host-1",
        "status": "active",
    })
    result = runtime.result({
        "action": NODE_GRANT_ACCESS_ACTION,
        "machine_id": "node-1",
    })

    assert runtime.schema_id == BARE_METAL_SCHEMA_KIND
    assert isinstance(listing, BareMetalListing)
    assert isinstance(message, BareMetalMessage)
    assert isinstance(terms, BareMetalTerms)
    assert isinstance(materialization, BareMetalMaterialization)
    assert isinstance(receipt, BareMetalReceipt)
    assert isinstance(result, BareMetalAccessResult)


def test_storefront_runtime_surfaces_bare_metal_validation_errors() -> None:
    runtime = storefront_runtime()

    with pytest.raises(ValidationError, match="machine_id must be non-empty"):
        runtime.listing({
            "machine_id": "",
            "physical_host_id": "host-1",
        })
