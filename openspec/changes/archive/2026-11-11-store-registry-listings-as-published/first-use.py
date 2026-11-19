"""Print a local publication, its seller proof, and a replacement for review."""

from __future__ import annotations

import asyncio
import base64
import json
from pathlib import Path
from tempfile import TemporaryDirectory

import httpx
from market_identity import Ed25519Signer, TrustedIdentitySet, verify_request
from registry_client import ListingRequest, RegistryClient, UpdateListingRequest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from core_registry.db.database import get_db
from core_registry.db.migrations import migrate_database
from core_registry.main import app


async def main() -> None:
    # Deterministic development identities; never use on a public network.
    seller = Ed25519Signer(bytes(range(32)))
    authority = Ed25519Signer(bytes(range(1, 33)))
    directory = TemporaryDirectory()
    database_url = f"sqlite:///{Path(directory.name) / 'registry.db'}"
    migrate_database(database_url)
    engine = create_engine(database_url, connect_args={"check_same_thread": False})
    transport = httpx.ASGITransport(app=app)
    with Session(engine) as session:
        app.dependency_overrides[get_db] = lambda: session
        app.state.registry_authority_signer = authority
        try:
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as raw:
                ready = await raw.get("/health")
                ready.raise_for_status()
            async with RegistryClient(
                "http://test", transport=transport, signer=seller, caller_role="seller",
                expected_registries=TrustedIdentitySet(identities=(authority.identity,)),
                registry_authority="example-registry",
            ) as client:
                request = ListingRequest(
                    listing_id="example-retained", storefront_url="https://seller.example/",
                    listing_resource={"region": "example"}, accepted_escrows=[],
                    settlement_options=[{
                        "option_id": "a" * 64,
                        "settlement": {"schema": "example.payment.v1"},
                    }],
                    extra={
                        "pricing": {
                            "asking_rate": {"amount": "0.40", "asset": "usd", "period": "hour"},
                            "rate_structure": {
                                "cpu": [{"asset": "usd", "rate": "0.05", "per": "hour"}],
                            },
                        },
                        "arbitrary_term": {"value": None},
                    },
                )
                await client.publish_listing(request)
                published = (await client.get_listing(request.listing_id)).to_dict()
                evidence = published["publisher_publication"]
                original = json.loads(base64.b64decode(evidence["body_base64"]))
                envelope = evidence["request"]
                verification = verify_request(
                    envelope, body=original, now=envelope["timestamp"], max_skew=0,
                    expected_role="seller", expected_method="POST",
                    expected_operation="listing.publish", expected_resource="listings",
                    expected_principals=TrustedIdentitySet(identities=(seller.identity,)),
                )
                found = await client.list_listings()
                await client.update_listing(
                    request.listing_id, UpdateListingRequest({"status": "closed"})
                )
                request.extra = {"replacement_term": "present"}
                await client.publish_listing(request)
                replaced = (await client.get_listing(request.listing_id)).to_dict()
                print(json.dumps({
                    "readiness": ready.json(), "seller_verification": verification.code.value,
                    "published": published, "search_count": len(found.listings),
                    "replacement": replaced,
                }, indent=2))
        finally:
            app.dependency_overrides.clear()
            del app.state.registry_authority_signer
    engine.dispose()
    directory.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
