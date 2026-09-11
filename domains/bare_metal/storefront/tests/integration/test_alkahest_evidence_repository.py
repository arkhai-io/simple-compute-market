from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from arkhai_bare_metal import (
    BareMetalLeaseReadyResult,
    CanonicalPrincipal,
    build_bare_metal_alkahest_lease_ready_evidence,
)
from market_identity import Ed25519Signer

from arkhai_bare_metal_storefront.sqlite_client import SQLiteClient


BUYER = Ed25519Signer(bytes.fromhex("11" * 32)).identity
SELLER = Ed25519Signer(bytes.fromhex("22" * 32)).identity


@pytest.mark.asyncio
async def test_publication_intent_has_one_atomic_submission_winner(tmp_path) -> None:
    db = SQLiteClient(str(tmp_path / "storefront.db"))
    obligation_ref = "a" * 64
    escrow_uid = "0x" + "33" * 32
    digest = "sha256:" + "b" * 64
    await db.ensure_bare_metal_alkahest_evidence_binding(
        obligation_ref=obligation_ref,
        agreement_ref="agreement-a",
        escrow_uid=escrow_uid,
        accepted_plan_digest=digest,
        seller_recipient="0x" + "44" * 20,
    )
    now = datetime(2030, 1, 1, tzinfo=timezone.utc)
    evidence = build_bare_metal_alkahest_lease_ready_evidence(
        agreement_ref="agreement-a",
        obligation_ref=obligation_ref,
        obligation_hash="c" * 64,
        accepted_plan_digest=digest,
        escrow_uid=escrow_uid,
        buyer_principal=CanonicalPrincipal.model_validate(
            BUYER.model_dump(mode="json")
        ),
        seller_principal=CanonicalPrincipal.model_validate(
            SELLER.model_dump(mode="json")
        ),
        seller_recipient="0x" + "44" * 20,
        result=BareMetalLeaseReadyResult(
            site_id="site-a",
            resource_selection="specific",
            physical_resource_id="resource-a",
            capacity_reservation_ref="reservation-a",
            settlement_resource_ref="settlement-resource-a",
            fulfillment_ref="provisioning-a",
            access_grant_ref="grant-a",
            access_ready_at=now,
            expires_at=now + timedelta(hours=1),
        ),
    )
    intent = await db.record_bare_metal_alkahest_evidence_intent(
        obligation_ref=obligation_ref,
        evidence=evidence,
    )

    claims = await asyncio.gather(
        *(
            db.claim_bare_metal_alkahest_evidence_submission(
                obligation_ref=obligation_ref,
                evidence_digest=str(intent["evidence_digest"]),
                worker_id=worker,
            )
            for worker in ("worker-a", "worker-b")
        )
    )

    assert sum(claim is not None for claim in claims) == 1
    winner = next(claim for claim in claims if claim is not None)
    assert winner["publication_state"] == "submitting"
    assert winner["publication_owner"] in {"worker-a", "worker-b"}
