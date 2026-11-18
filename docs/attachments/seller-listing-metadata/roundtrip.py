"""Drive a signed publish -> GET round trip through the registry API.

Run from core/registry: uv run --no-sync python ../../docs/attachments/seller-listing-metadata/roundtrip.py

Publishes a VM-, bare-metal-, and API-credits-shaped listing carrying
title/description/metadata plus one carrying none, reads each back,
refuses a limit violation naming the field, and filters on a filter-spec
entry whose path is $.metadata["acme.tier"]. Identity material below is
deterministic development-only key material.
"""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from pathlib import Path

import httpx
from market_identity import Ed25519Signer, TrustedIdentitySet
from registry_client import ListingRequest, RegistryClient
from registry_client.models import ValidatePublishRequest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "core" / "registry" / "src"))

from core_registry.api.filter_spec import reset_cache
from core_registry.config import Settings
from core_registry.main import app

PUBLISHER_SECRET = bytes.fromhex(
    "5de4111afa1a4b94908f83103eb1f1706367c2e68ca870fc3fb9a804cdab365a"
)
AUTHORITY_SECRET = bytes(range(1, 33))

FILTER_SPEC = """
version: 1
schema:
  id: compute.market
  version: "1"
listing_shape:
  type: object
filters:
  - name: acme_tier
    path: $.metadata["acme.tier"]
    op: in
    value_type: string
    on_missing: pass
"""

VM_RESOURCE = {
    "offering_mode": "vm",
    "capacity_backing": "unbacked",
    "gpu_model": "H100",
    "gpu_count": 8,
    "region": "us-east",
    "sla": 99.9,
}
BARE_METAL_RESOURCE = {
    "kind": "bare_metal.v2",
    "offering_mode": "bare_metal",
    "capacity_backing": "unbacked",
    "region": "us-east",
    "vcpu_count": 192,
    "ram_gb": 2048,
    "disk_gb": 3840,
}
API_CREDITS_RESOURCE = {
    "offering_mode": "api_credits",
    "service_name": "inference",
    "description": "Token-gated inference endpoint",
    "resource_id": "quota-1",
    "capacity_site_id": "site-1",
}
DETAILS = {
    "title": "8x H100 node, ready now",
    "description": "Dedicated H100 hosts, SLA 99.9, us-east.",
    "metadata": {
        "acme.tier": "gold",
        "cooldown_hours": 0,
        "ipv4": True,
    },
}


def _prepare(spec_dir):
    spec_path = spec_dir / "filter-spec.yaml"
    spec_path.write_text(FILTER_SPEC)
    reset_cache(settings=Settings(REGISTRY_FILTER_SPEC_PATH=str(spec_path)))

    signer = Ed25519Signer(AUTHORITY_SECRET)
    from market_core import RegistryDescriptor

    app.state.registry_authority_signer = signer
    app.state.registry_descriptor = RegistryDescriptor.model_validate(
        {
            "access": {"posture": "public"},
            "authority": {
                "name": "evidence-registry",
                "principals": [signer.identity.model_dump(mode="json")],
            },
            "baseUrl": "http://test",
            "displayName": "Evidence Registry",
            "operatorIdentity": "evidence-operator",
            "schema": {"id": "compute.market", "version": "1"},
        }
    )

    from core_registry.db.database import Base, engine, get_db
    from core_registry.db import models  # noqa: F401  (register the mappers)

    Base.metadata.create_all(bind=engine)

    def override_get_db():
        from core_registry.db.database import SessionLocal

        session = SessionLocal()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db


async def _publish(client, listing_id, resource, **fields):
    request = ListingRequest(
        listing_resource=resource,
        accepted_escrows=[
            {
                "chain_name": "anvil",
                "escrow_address": "0x" + "11" * 20,
                "literal_fields": {"token": "0x" + "ab" * 20},
            }
        ],
        listing_id=listing_id,
        storefront_url="http://localhost:8001/",
        **fields,
    )
    await client.publish_listing(request)
    stored = await client.get_listing(listing_id)
    return stored.to_dict()


async def main():
    with tempfile.TemporaryDirectory() as tmp:
        _prepare(Path(tmp))
        signer = Ed25519Signer(PUBLISHER_SECRET)
        authority = Ed25519Signer(AUTHORITY_SECRET)
        findings = []
        transport = httpx.ASGITransport(app=app)
        async with RegistryClient(
            "http://test",
            transport=transport,
            signer=signer,
            caller_role="seller",
            expected_registries=TrustedIdentitySet(identities=(authority.identity,)),
            registry_authority="evidence-registry",
        ) as client:
            for name, resource in (
                ("vm", VM_RESOURCE),
                ("bare_metal", BARE_METAL_RESOURCE),
                ("api_credits", API_CREDITS_RESOURCE),
            ):
                stored = await _publish(client, "evidence-" + name, resource, **DETAILS)
                for field in ("title", "description", "metadata"):
                    assert stored.get(field) == DETAILS[field], (name, field)
                findings.append(name + ": title/description/metadata round-trip unchanged")

            plain = await _publish(client, "evidence-plain", dict(VM_RESOURCE))
            assert not any(
                field in plain for field in ("title", "description", "metadata")
            )
            findings.append("a listing without the fields publishes and reads as before")

            try:
                await _publish(
                    client,
                    "evidence-overflow",
                    dict(VM_RESOURCE),
                    metadata={"acme.tier": "x" * 501},
                )
                raise AssertionError("over-long metadata value was accepted")
            except Exception as exc:
                message = str(exc)
                assert "metadata" in message and "500" in message, message
                findings.append("limit violation refused naming the field: " + message)

            validation = await client.validate_publish_listing(
                ValidatePublishRequest(
                    listing_id="evidence-validate",
                    listing_resource=dict(VM_RESOURCE),
                    accepted_escrows=[],
                    storefront_url="http://localhost:8001/",
                    metadata={"bad key!": "gold"},
                )
            )
            assert not validation.valid and any(
                "metadata" in error for error in validation.errors
            ), validation.errors
            findings.append("dry-run names the field: " + "; ".join(validation.errors))

            bronze = await _publish(
                client,
                "evidence-bronze",
                dict(VM_RESOURCE),
                metadata={"acme.tier": "bronze"},
            )
            assert bronze["metadata"] == {"acme.tier": "bronze"}

            gold_ids = {
                item.id for item in (await client.list_listings(acme_tier="gold")).listings
            }
            # on_missing: pass keeps the plain listing, which states no tier.
            assert gold_ids == {
                "evidence-vm",
                "evidence-bare_metal",
                "evidence-api_credits",
                "evidence-plain",
            }, gold_ids
            findings.append(
                "$.metadata[acme.tier]=gold selects the three gold listings and keeps "
                "the one stating no tier"
            )

            bronze_ids = {
                item.id
                for item in (await client.list_listings(acme_tier="bronze")).listings
            }
            assert bronze_ids == {"evidence-bronze", "evidence-plain"}, bronze_ids
            findings.append(
                "$.metadata[acme.tier]=bronze selects only the bronze listing; the "
                "gold listings are excluded by value"
            )
        print(json.dumps(findings, indent=2))
        return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
