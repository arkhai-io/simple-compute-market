from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from core_storefront.domain_registry import (
    StorefrontListingBinding,
    StorefrontThreadBinding,
)
from market_capacity_publication import CapacityBinding
from market_core import SettlementEvidence
from market_fulfillment import (
    FulfillmentResultPayload,
    ProvisionedResourceOutput,
    VersionedEnvelope,
    build_fulfillment_result_envelope,
)
from market_identity import Ed25519Signer

from market_storefront.domain_runtime import (
    build_vm_storefront_domain,
    build_vm_storefront_registry,
)
from market_storefront.publication_binding import prepare_vm_listing_binding
from market_storefront.services.vm_fulfillment_planner import build_vm_fulfillment_plan
from market_storefront.utils.sqlite_client import SQLiteClient

BUYER_PRINCIPAL = Ed25519Signer(b"\x61" * 32).identity
SELLER_PRINCIPAL = Ed25519Signer(b"\x62" * 32).identity


@dataclass(frozen=True)
class VmLifecycleFixture:
    db: SQLiteClient
    listing_binding: StorefrontListingBinding
    thread_binding: StorefrontThreadBinding
    capacity_binding: CapacityBinding
    evidence: SettlementEvidence

    def reopen(self) -> SQLiteClient:
        return SQLiteClient(
            db_path=self.db.db_path,
            registry=self.db.domain_registry,
        )


async def make_vm_lifecycle_fixture(
    db_path: Path,
    *,
    escrow_uid: str = "escrow-1",
    negotiation_id: str = "neg-1",
    listing_id: str = "listing-1",
    site_id: str = "site-1",
    pool_id: str = "pool-1",
    status: str = "provisioning",
    interruptible: bool = True,
    context_payload: Mapping[str, Any] | None = None,
    with_context: bool = True,
) -> VmLifecycleFixture:
    """Persist the exact VM listing, thread, site, and escrow authority."""

    domain = build_vm_storefront_domain()
    db = SQLiteClient(
        db_path=str(db_path),
        registry=build_vm_storefront_registry(domain),
    )
    registration = db.domain_registry.resolve_mode("vm")
    listing_binding = prepare_vm_listing_binding(
        listing_id=listing_id,
        candidate={
            "site_id": site_id,
            "pool_id": pool_id,
            "gpu_count": (context_payload or {})
            .get("order", {})
            .get("offer_resource", {})
            .get("gpu_count", 1),
        },
    )
    await db.upsert_listing_with_binding(
        binding=listing_binding,
        status="open",
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-01T00:00:00Z",
        offer_resource={
            "pool_id": pool_id,
            "gpu_model": "A100",
            "gpu_count": 1,
            "sla": 99.0,
            "region": "test-region",
            "virtualization_type": "vm",
            "interruptible": interruptible,
        }
        | (context_payload or {}).get("order", {}).get("offer_resource", {}),
        fulfillment_resource=None,
        max_duration_seconds=7_200,
        storefront_url="http://seller.test",
        seller_principal=SELLER_PRINCIPAL,
        accepted_escrows=[],
        demands=[],
    )
    thread_binding = StorefrontThreadBinding(
        negotiation_id=negotiation_id,
        listing_id=listing_id,
        site_id=site_id,
        binding=registration.binding,
    )
    await db.create_negotiation_thread(
        negotiation_id=negotiation_id,
        our_listing_id=listing_id,
        their_listing_id="buyer-listing-1",
        our_agent_id="seller-agent",
        their_agent_id="buyer-agent",
        buyer_principal=BUYER_PRINCIPAL,
        seller_principal=SELLER_PRINCIPAL,
        owner_id="seller-agent",
        binding=thread_binding,
    )
    inserted = await db.insert_escrow(
        escrow_uid=escrow_uid,
        negotiation_id=negotiation_id,
        chain_name="anvil",
        escrow_address="0x" + "11" * 20,
        status=status,
    )
    if not inserted:
        raise RuntimeError(f"duplicate lifecycle escrow {escrow_uid!r}")

    payload = {
        "fulfillment_request": {
            "kind": "vm.fulfillment.request",
            "schema_version": 1,
            "payload": {"vm_target": "tenant-abcd", "ssh_pubkey": "ssh-ed25519 test"},
        },
        **dict(context_payload or {}),
    }
    authoritative = {
        "escrow_uid": escrow_uid,
        "listing_id": listing_id,
    }
    for field, value in authoritative.items():
        if field in payload and payload[field] != value:
            raise ValueError(f"fulfillment context {field} disagrees with fixture")
        payload[field] = value
    context = db.bind_fulfillment_context(
        {
            "kind": "vm.storefront.fulfillment-context",
            "schema_version": 1,
            "payload": payload,
        },
        thread_binding=thread_binding,
    )
    await db.update_escrow(
        escrow_uid=escrow_uid,
        fulfillment_context=json.dumps(context, sort_keys=True),
    )
    evidence = vm_delivery_evidence(
        negotiation_id=negotiation_id,
        listing_id=listing_id,
        settlement_ref=escrow_uid,
        **dict(context_payload or {}),
    )
    await db.save_vm_settlement_evidence(evidence)
    await db.insert_vm_delivery(negotiation_id=negotiation_id)
    plan = build_vm_fulfillment_plan(evidence=evidence)
    payload.update(
        {
            "negotiation_id": negotiation_id,
            "settlement_ref": escrow_uid,
            "agreement_sha256": evidence.evidence["agreement_sha256"],
            "required_attributes": plan.required_attributes,
            "duration_seconds": plan.duration_seconds,
            "start_utc": plan.start_utc,
            "lease_end_utc": plan.lease_end_utc,
        }
    )
    if with_context:
        await db.update_vm_delivery(
            negotiation_id=negotiation_id,
            fulfillment_context=json.dumps(
                db.bind_fulfillment_context(
                    {
                        "kind": "vm.storefront.fulfillment-context",
                        "schema_version": 1,
                        "payload": payload,
                    },
                    thread_binding=thread_binding,
                ),
                sort_keys=True,
                separators=(",", ":"),
            ),
        )
    return VmLifecycleFixture(
        db=db,
        listing_binding=listing_binding,
        thread_binding=thread_binding,
        capacity_binding=CapacityBinding(site_id, "vm", pool_id),
        evidence=evidence,
    )


def vm_delivery_evidence(
    *,
    negotiation_id="neg-1",
    listing_id="listing-1",
    settlement_ref="escrow-1",
    order=None,
    required_attributes=None,
    duration_seconds=3600,
    start_utc="2026-01-01T00:00:00+00:00",
    **_,
):
    return SettlementEvidence(
        negotiation_id=negotiation_id,
        mechanism="alkahest.v1",
        settlement_ref=settlement_ref,
        status="verified",
        evidence={
            "schema": "vm.settlement-evidence.v1",
            "agreement_sha256": "1" * 64,
            "source": {"escrow_uid": settlement_ref, "obligation_ref": "obligation-1"},
            "delivery": {
                "kind": "vm.delivery-facts",
                "schema_version": 1,
                "payload": {
                    "listing_id": listing_id,
                    "order": order if order is not None else {"listing_id": listing_id},
                    "required_attributes": required_attributes or {},
                    "duration_seconds": duration_seconds,
                    "start_utc": start_utc,
                    "lease_end_utc": "2026-01-01T01:00:00+00:00",
                    "lease_bytes_hex": "0102",
                    "provision_terms": {
                        "kind": "compute.v1",
                        "version": 1,
                        "payload": {
                            "ssh_public_key": "ssh-ed25519 test",
                            "duration_seconds": duration_seconds,
                        },
                    },
                },
            },
        },
    )


def vm_fulfillment_result(
    *,
    fulfillment_id: str = "fulfillment-1",
    capacity_reservation_id: str = "reservation-1",
    provisioned_resource_id: str = "resource-1",
    connection_info: Mapping[str, Any] | None = None,
    credentials: tuple[Mapping[str, Any], ...] = (),
) -> VersionedEnvelope[Any]:
    """Build the authoritative generic result with a VM-domain envelope."""

    domain_result = VersionedEnvelope(
        kind="vm.fulfillment.result.v1",
        schema_version=1,
        payload={
            "connection_info": dict(connection_info or {}),
            "credentials": [dict(credential) for credential in credentials],
            "provisioned_resources": [
                {
                    "provisioned_resource_id": provisioned_resource_id,
                    "status": "active",
                }
            ],
        },
    )
    return build_fulfillment_result_envelope(
        FulfillmentResultPayload(
            fulfillment_id=fulfillment_id,
            capacity_reservation_id=capacity_reservation_id,
            state="active",
            provisioned_resources=(
                ProvisionedResourceOutput(
                    provisioned_resource_id=provisioned_resource_id,
                    status="active",
                ),
            ),
            domain_result=domain_result,
        )
    )
