"""The storefront through its lifespan with a buyer, the seller and the administrator.

Beyond the storefront, the chain is scripted at the Alkahest stage's injected
escrow verifier and the attestation client it is handed, and the inference
authority at its HTTP boundary; the quota site and registries are the other
integration tests'. Every key and address is a deterministic development
value, never used on a public network.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

import httpx
from arkhai_api_selling.migrations import migrate_storefront_database
from arkhai_api_selling.publish_route import ListingClient
from arkhai_inference.negotiation.terms import INFERENCE_PROVISION_KIND, INFERENCE_PROVISION_VERSION
from market_identity import Ed25519Signer, TrustedIdentitySet
from storefront_client import StorefrontClient

from inference_storefront import container, server
from inference_storefront.migrate import CHAIN
from inference_storefront.model_card import PublishFromQuotaRequest
from inference_storefront.services import credits_service_client
from inference_storefront.utils import config as storefront_config
from tests.cards import model_card
from tests.integration.conftest import (
    ADMIN_SIGNER,
    ESCROW,
    SELLER_SIGNER,
    QuotaSite,
    app,
    deployed_chain,
)
from tests.integration.issuance_authority import ScriptedAuthority

BUYER_SIGNER = Ed25519Signer(bytes.fromhex("11" * 32))
BUYER_WALLET = "0x" + "55" * 20
ATTESTATION_UID = "0x" + "cd" * 32
QUANTITY = 40


class NegotiableQuotaSite(QuotaSite):
    """The quota site, also read through the client a negotiation's capacity guard holds."""

    def client(self) -> "NegotiableQuotaSite":
        return self

    def site(self, site_id: str) -> "NegotiableQuotaSite":
        return self.site_client(site_id)

    async def snapshot(self) -> list[dict[str, Any]]:
        return [
            {
                "resource_id": rid,
                "resource_type": "inference",
                "available_units": units,
                "total_units": units,
                "state": "available",
            }
            for rid, units in self.units.items()
        ]


class ScriptedChain:
    """An escrow that verifies against the listing it is shown, and an attestation the chain records."""

    def __init__(self) -> None:
        self.verified_against: list[dict[str, Any]] = []
        self.attestations: list[str] = []
        self.client = SimpleNamespace(string_obligation=SimpleNamespace(do_obligation=self._attest))

    async def verify_escrow(self, *, settlement_plan: dict[str, Any], **_escrow: Any) -> int:
        self.verified_against.append(settlement_plan)
        return 0

    async def _attest(self, _data: str, condition_anchor: str) -> str:
        self.attestations.append(condition_anchor)
        return ATTESTATION_UID


@dataclass
class Parties:
    seller: StorefrontClient
    listings: ListingClient
    buyer: StorefrontClient
    admin: StorefrontClient
    public: StorefrontClient
    app: Any


@asynccontextmanager
async def running(monkeypatch, chain: ScriptedChain, authority: ScriptedAuthority) -> AsyncIterator[Parties]:
    """The app through its lifespan, over the scripted chain and authority."""

    async def no_startup_tasks(*, domain: Any) -> None:
        return None

    monkeypatch.setattr(server, "_startup_tasks", no_startup_tasks)
    quota = NegotiableQuotaSite({"svc-quota": 42})
    monkeypatch.setattr(container.QUOTA_CAPACITY, "runtime", lambda factory: quota)
    monkeypatch.setattr(container.ALKAHEST_STAGE, "_verify_escrow", chain.verify_escrow)
    monkeypatch.setattr(credits_service_client, "_client", authority.client())
    migrate_storefront_database(CHAIN, storefront_config.settings.get("db_path"))
    served = app(
        server.InferenceCompositionSeams(
            alkahest_client_constructor=lambda _policy: lambda _chain: chain.client,
            alkahest_json_rpc=deployed_chain,
        )
    )
    async with served.router.lifespan_context(served):
        await container.resolved_alkahest_chain_probe.step()
        transport = httpx.ASGITransport(app=served)
        publishers = TrustedIdentitySet(identities=(SELLER_SIGNER.identity,))

        def signed(signer: Ed25519Signer, role: str) -> StorefrontClient:
            return StorefrontClient(
                "http://seller",
                signer=signer,
                caller_role=role,
                expected_publishers=publishers,
                transport=transport,
            )

        async with signed(SELLER_SIGNER, "seller") as seller, signed(
            BUYER_SIGNER, "buyer"
        ) as buyer, signed(ADMIN_SIGNER, "admin") as admin, StorefrontClient(
            "http://seller", transport=transport
        ) as public:
            yield Parties(
                seller=seller,
                listings=ListingClient(
                    seller, seller=SELLER_SIGNER.identity, request_model=PublishFromQuotaRequest
                ),
                buyer=buyer,
                admin=admin,
                public=public,
                app=served,
            )


def publish_request(request_credits: int) -> dict[str, Any]:
    card = model_card()
    card["rate_card"] = {**card["rate_card"], "request_credits": request_credits}
    return {"resource_id": "svc-quota", "accepted_escrows": [dict(ESCROW)], "model_card": card}


def provision_terms(quantity: int = QUANTITY) -> dict[str, Any]:
    return {
        "kind": INFERENCE_PROVISION_KIND,
        "version": INFERENCE_PROVISION_VERSION,
        "payload": {"quantity": quantity, "key": {"mode": "new"}},
    }


async def open_negotiation(
    parties: Parties, listing: Any, *, amount: int = QUANTITY, buyer: StorefrontClient | None = None
) -> dict[str, Any]:
    """Open a negotiation on a published listing, as a buyer's client does."""
    (release_condition,) = listing.extra["demands"]
    return await (buyer or parties.buyer).negotiate_new(
        listing_id=listing.listing_id,
        initial_amount=amount,
        provision_terms=provision_terms(),
        proposal_fields={"token": ESCROW["literal_fields"]["token"]},
        chain_name="anvil",
        escrow_address=ESCROW["escrow_address"],
        escrow_expiration_unix=1_900_000_000,
        literal_fields=ESCROW["literal_fields"],
        rates=ESCROW["rates"],
        demands=[release_condition],
    )
