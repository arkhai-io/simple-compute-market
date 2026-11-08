from __future__ import annotations

import json
import hashlib
import sqlite3
import time
from market_deal_servicing import DeliveryRecord, EndSession, create_schema
from datetime import datetime, timezone, timedelta

from market_core.schemas import Agreement, SettlementOption, derive_settlement_option_id
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Mapping

from core_storefront.domain_registry import (
    StorefrontListingBinding,
    StorefrontThreadBinding,
)
from market_capacity_publication import PublicationBinding
from market_resource_pools_contracts.backing import BACKED
from market_core import SettlementEvidence
from market_core import VersionedEnvelope
from market_fulfillment import (
    FulfillmentResultPayload,
    ProvisionedResourceOutput,
    build_fulfillment_result_envelope,
)
from market_identity import Ed25519Signer

from market_storefront.domain_runtime import (
    build_vm_storefront_domain,
    build_vm_storefront_registry,
)
from market_storefront.services.vm_fulfillment_planner import build_vm_fulfillment_plan
from market_storefront.utils.sqlite_client import SQLiteClient

BUYER_PRINCIPAL = Ed25519Signer(b"\x61" * 32).identity
SELLER_PRINCIPAL = Ed25519Signer(b"\x62" * 32).identity


@dataclass(frozen=True)
class VmLifecycleFixture:
    db: SQLiteClient
    listing_binding: StorefrontListingBinding
    thread_binding: StorefrontThreadBinding
    capacity_binding: PublicationBinding
    evidence: SettlementEvidence

    def reopen(self) -> SQLiteClient:
        return SQLiteClient(
            db_path=self.db.db_path,
            registry=self.db.domain_registry,
        )


def seed_delivery_admission(db, *, negotiation_id="neg-1", commitment_ref="escrow-1"):
    """Supply the committed lifecycle boundary to isolated repository tests."""
    now = int(time.time())
    with sqlite3.connect(db.db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        create_schema(conn)
        if conn.execute("SELECT 1 FROM servicing_delivery WHERE negotiation_id=?", (negotiation_id,)).fetchone():
            return
        EndSession(conn).register(DeliveryRecord(
            negotiation_id=negotiation_id, seller=SELLER_PRINCIPAL, commitment_ref=commitment_ref,
            start_at=now - 10, term_end=now + 3600, committed_at=now - 10,
        ))


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
    listing_binding = StorefrontListingBinding.from_source_envelope(
        listing_id=listing_id,
        site_id=site_id,
        pool_id=pool_id,
        physical_resource_id=None,
        binding=registration.binding,
        derivation_key=f"{site_id}:{pool_id}:vm:1",
        source_envelope={
            "kind": "vm.capacity-candidate.v1",
            "schema_version": 1,
            "payload": {
                "site_id": site_id,
                "pool_id": pool_id,
                "offering_mode": "vm",
            },
        },
        last_reconciled_at="2026-01-01T00:00:00Z",
        capacity_backing="backed",
    )
    await db.upsert_listing_with_binding(
        binding=listing_binding,
        status="open",
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-01T00:00:00Z",
        listing_resource={
            "pool_id": pool_id,
            "gpu_model": "A100",
            "gpu_count": 1,
            "sla": 99.0,
            "region": "test-region",
            "offering_mode": "vm",
            "interruptible": interruptible,
        }
        | (context_payload or {}).get("order", {}).get("listing_resource", {}),
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
            "payload": {"ssh_pubkey": "ssh-ed25519 test"},
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
    now = datetime.now(timezone.utc) - timedelta(seconds=10)
    start = (context_payload or {}).get("start_utc", now.isoformat())
    facts = evidence.evidence["delivery"]["payload"]
    facts["start_utc"] = start
    facts["lease_end_utc"] = (
        datetime.fromisoformat(start.replace("Z", "+00:00")) + timedelta(seconds=facts["duration_seconds"])
    ).isoformat()
    body = {"price": {"asset": "USD/2", "rates": []}, "settlement": {"schema": "alkahest.v1"}}
    agreement = Agreement(
        negotiation_id=negotiation_id, listing_id=listing_id, listing_hash="0" * 64,
        buyer=BUYER_PRINCIPAL.model_dump(mode="json"), seller=SELLER_PRINCIPAL.model_dump(mode="json"),
        settlement=SettlementOption(option_id=derive_settlement_option_id(**body), **body),
        settlement_params={}, amount=100, asset="USD/2", start_utc=start,
        accepted_at=now.isoformat(), duration_seconds=facts["duration_seconds"],
        provision_terms=facts["provision_terms"],
    )
    raw = agreement.model_dump_json(exclude_none=True).encode()
    await db.commit_agreed_terms(
        negotiation_id=negotiation_id, agreed_price=100, agreed_duration_seconds=facts["duration_seconds"],
        agreement_bytes=raw, accepted_at=agreement.accepted_at, agreed_start_utc=start,
    )
    evidence = replace(evidence, evidence={**evidence.evidence, "agreement_sha256": hashlib.sha256(raw).hexdigest()})
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
        capacity_binding=PublicationBinding(site_id, "vm", pool_id, BACKED),
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
            "source": {
                "escrow_uid": settlement_ref, "obligation_ref": "obligation-1", "chain_name": "anvil",
            },
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
    endpoint: Mapping[str, Any] | None = None,
    credentials: tuple[Mapping[str, Any], ...] = (),
    ready_at: str = "2030-01-01T00:00:01+00:00",
) -> VersionedEnvelope[Any]:
    """Build the authoritative generic result carrying the family's access delivery."""

    domain_result = VersionedEnvelope(
        kind="compute.access-delivery",
        schema_version=1,
        payload={
            "endpoints": [
                dict(
                    endpoint
                    or {"protocol": "ssh", "host": "203.0.113.10", "port": 2222, "user": "tenant1"}
                )
            ],
            "credentials": [dict(credential) for credential in credentials],
            "ready_at": ready_at,
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
