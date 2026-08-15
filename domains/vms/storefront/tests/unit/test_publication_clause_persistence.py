from __future__ import annotations

from datetime import datetime

import pytest

from market_storefront.domain_runtime import build_vm_storefront_domain
from market_storefront.utils.sqlite_client import SQLiteClient
from tests.fake_site import TEST_MARKETPLACE_SIGNER


@pytest.mark.asyncio
async def test_listing_round_trips_canonical_publication_clauses(tmp_path) -> None:
    db = SQLiteClient(db_path=str(tmp_path / "storefront.db"), domain=build_vm_storefront_domain())
    now = datetime.now().isoformat()
    clauses = [
        {
            "mechanism": "fiat.stripe.v1",
            "asset": "usd",
            "rate": "2",
            "per": "hour",
            "mechanism_input": {
                "funding_profile": "card.v1",
                "interaction": "interactive",
                "funds_flow": "separate_charges_transfers",
            },
        }
    ]

    await db.upsert_listing(
        listing_id="listing-with-publication-clauses",
        status="open",
        created_at=now,
        updated_at=now,
        offer_resource={
            "resource_type": "compute",
            "resource_id": "resource-1",
            "gpu_model": "H200",
            "gpu_count": 1,
            "region": "California, US",
            "sla": 99.0,
        },
        fulfillment_resource=None,
        max_duration_seconds=3600,
        storefront_url="http://seller.test",
        seller_principal=TEST_MARKETPLACE_SIGNER.identity,
        accepted_escrows=[],
        settlement_options=[],
        publication_clauses=clauses,
        demands=[],
    )

    stored = await db.load_listing(listing_id="listing-with-publication-clauses")

    assert stored is not None
    assert stored["publication_clauses"] == clauses
