"""Publish a terms fixture through an invocation-owned in-process registry."""

from __future__ import annotations

import asyncio
import base64
import json
import sys
from pathlib import Path

import httpx
from core_registry.db.database import get_db
from core_registry.db.models import Base
from core_registry.main import app
from market_deal_lifecycle.terms import decode_terms, encode_terms
from market_identity import Ed25519Signer, TrustedIdentitySet, verify_request
from registry_client import ListingRequest, RegistryClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool


async def main(fixture: Path) -> None:
    publication = json.loads(fixture.read_text())
    # Deterministic development identities; never use on a public network.
    seller = Ed25519Signer(bytes(range(32)))
    authority = Ed25519Signer(bytes(range(1, 33)))
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    transport = httpx.ASGITransport(app=app)
    try:
        with Session(engine) as session:
            app.dependency_overrides[get_db] = lambda: session
            app.state.registry_authority_signer = authority
            try:
                async with httpx.AsyncClient(transport=transport, base_url="http://test") as raw:
                    (await raw.get("/health")).raise_for_status()
                async with RegistryClient(
                    "http://test", transport=transport, signer=seller, caller_role="seller",
                    expected_registries=TrustedIdentitySet(identities=(authority.identity,)),
                    registry_authority="example-registry",
                ) as client:
                    await client.publish_listing(ListingRequest(**publication))
                    listing = (await client.get_listing(publication["listing_id"])).to_dict()
                    evidence = listing["publisher_publication"]
                    signed = json.loads(base64.b64decode(evidence["body_base64"]))
                    envelope = evidence["request"]
                    verified = verify_request(
                        envelope, body=signed, now=envelope["timestamp"], max_skew=0,
                        expected_role="seller", expected_method="POST",
                        expected_operation="listing.publish", expected_resource="listings",
                        expected_principals=TrustedIdentitySet(identities=(seller.identity,)),
                    )
                    assert verified.verified, verified.code
                    assert signed["settlement_options"] == publication["settlement_options"]
                    assert listing["settlement_options"] == signed["settlement_options"]
                    for option in listing["settlement_options"]:
                        assert encode_terms(decode_terms(option["lifecycle"])) == option["lifecycle"]
                    print("registry health, typed publication/read, seller proof, shared codec: PASS")
            finally:
                app.dependency_overrides.clear()
                del app.state.registry_authority_signer
    finally:
        engine.dispose()


if __name__ == "__main__":
    asyncio.run(main(Path(sys.argv[1])))
