"""Verified VM authority is validated before it can become immutable storage."""

from dataclasses import replace

import pytest

from market_storefront.domain_runtime import (
    build_vm_storefront_domain,
    build_vm_storefront_registry,
)
from market_storefront.utils.sqlite_client import SQLiteClient
from tests.fulfillment_fixtures import vm_delivery_evidence


@pytest.mark.asyncio
@pytest.mark.parametrize("patch", [
    {"agreement_sha256": "diagnostic-digest"},
    {"agreement_sha256": "g" * 64},
    {"source": None},
    {"source": {}},
    {"delivery": {"kind": "not-a-vm-payload", "schema_version": 1, "payload": {}}},
    {"delivery": {"kind": "vm.delivery-facts", "schema_version": 999, "payload": {}}},
    {"delivery": {"kind": "vm.delivery-facts", "schema_version": True, "payload": {}}},
    {"delivery": {"kind": "vm.delivery-facts", "schema_version": 1}},
])
async def test_invalid_verified_evidence_cannot_poison_pending_or_fresh_state(tmp_path, patch):
    db = SQLiteClient(
        str(tmp_path / "evidence.db"),
        registry=build_vm_storefront_registry(build_vm_storefront_domain()),
    )
    valid = vm_delivery_evidence()
    malformed = replace(valid, evidence={**valid.evidence, **patch})
    with pytest.raises(ValueError):
        await db.save_vm_settlement_evidence(malformed)
    assert await db.load_vm_settlement_evidence(negotiation_id=valid.negotiation_id) is None

    pending = replace(malformed, status="pending")
    await db.save_vm_settlement_evidence(pending)
    with pytest.raises(ValueError):
        await db.save_vm_settlement_evidence(malformed)
    assert await db.load_vm_settlement_evidence(negotiation_id=valid.negotiation_id) == pending

    # The digest is accepted identity even while delivery facts are incomplete.
    if "agreement_sha256" not in patch:
        await db.save_vm_settlement_evidence(valid)
        await db.save_vm_settlement_evidence(valid)
        assert await db.load_vm_settlement_evidence(negotiation_id=valid.negotiation_id) == valid
        assert await db.insert_vm_delivery(negotiation_id=valid.negotiation_id)
