"""VM fulfillment planning from verified settlement delivery facts."""

from __future__ import annotations

from arkhai_vms import normalize_vm_provision_terms
from market_core import SettlementEvidence

from market_storefront.models.vm_fulfillment_models import VmFulfillmentPlan


def build_vm_fulfillment_plan(*, evidence: SettlementEvidence) -> VmFulfillmentPlan:
    if evidence.status != "verified" or not evidence.settlement_ref:
        raise ValueError("VM delivery requires verified settlement evidence")
    payload = evidence.evidence
    delivery = payload.get("delivery") or {}
    if (
        payload.get("schema") != "vm.settlement-evidence.v1"
        or delivery.get("kind") != "vm.delivery-facts"
        or delivery.get("schema_version") != 1
    ):
        raise ValueError("VM delivery requires supported delivery facts")
    facts = delivery.get("payload") or {}
    order = facts.get("order")
    if not isinstance(order, dict) or not order:
        raise ValueError(
            "VM fulfillment requires a valid, non-empty settlement order object."
        )
    return VmFulfillmentPlan(
        order_dict=dict(order),
        order_id=facts["listing_id"],
        order_bytes=bytes.fromhex(facts["lease_bytes_hex"]),
        required_attributes=dict(facts["required_attributes"]),
        provision_terms=normalize_vm_provision_terms(facts["provision_terms"]),
        duration_seconds=int(facts["duration_seconds"]),
        start_utc=facts["start_utc"],
        lease_end_utc=facts["lease_end_utc"],
        funding_expiration_unix=facts.get("funding_expiration_unix"),
        condition_anchor=facts.get("condition_anchor"),
    )
