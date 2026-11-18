"""The real storefront app and lifespan, composed from a seller's configuration.

Only the quota site's capacity runtime and the startup tasks are stubbed. Every
address and key here is a deterministic development value, never used on a
public network.
"""

from __future__ import annotations

import base64
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import patch

import httpx
import pytest
from arkhai_api_selling.migrations import migrate_storefront_database
from arkhai_api_selling.publication import RegistryPublication
from arkhai_api_selling.publish_route import ListingClient
from core_storefront.multi_registry_client import RegistryListings
from market_alkahest.dev_chain import anvil_address_book_path
from market_config.config_loader import ChainConfig
from market_identity import Ed25519Signer, TrustedIdentitySet
from registry_client.models import ListingSummary
from storefront_client import StorefrontClient

from inference_storefront import container, server
from inference_storefront.domain_runtime import get_market_domain_contract
from inference_storefront.migrate import CHAIN
from inference_storefront.model_card import PublishFromQuotaRequest
from inference_storefront.utils import config as storefront_config

SEED = b"\x22" * 32
SELLER_SIGNER = Ed25519Signer(SEED)
ADMIN_SIGNER = Ed25519Signer(b"\x44" * 32)
AUTHORITY_SIGNER = Ed25519Signer(b"\x66" * 32)
AUTHORITY_URL = "http://inference-authority.test"
# Anvil's well-known development account 0; never use it on a public network.
SELLER_WALLET = "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266"
SELLER_WALLET_KEY = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
SITE = "tokens"
ESCROW = {
    "chain_name": "anvil",
    "escrow_address": "0x" + "11" * 20,
    "literal_fields": {"token": "0x" + "01" * 20},
    "rates": [{"field": "amount", "per": "credit", "value": "1"}],
}
ANVIL = ChainConfig(name="anvil", rpc_url="http://anvil.test", chain_id=31337)


@contextmanager
def replaced(**roots: Any) -> Iterator[None]:
    """Replace whole settings roots; an override would merge into existing tables."""
    settings = storefront_config.settings
    saved = {name: deepcopy(settings.get(name)) for name in roots}
    try:
        for name, value in roots.items():
            settings.unset(name, force=True)
            settings.set(name, value)
        yield
    finally:
        for name, value in saved.items():
            settings.unset(name, force=True)
            if value is not None:
                settings.set(name, value)


def settlement(*priority: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "priority": list(priority or ("alkahest.v1",)),
        "alkahest": {
            "enabled": True,
            "address_books": {"anvil": str(anvil_address_book_path())},
        },
    }


class QuotaSite:
    """The quota site: its availability and its pool projection, set by the test."""

    def __init__(self, units: dict[str, int]) -> None:
        self.units = units

    def site_client(self, site_id: str) -> "QuotaSite":
        assert site_id == SITE
        return self

    async def resource_pool_projection(self) -> dict[str, Any]:
        return {
            "resource_pools": [
                {
                    "pool_id": "default",
                    "resources": [{"physical_resource_id": rid} for rid in self.units],
                    "pool_metadata": {
                        "enabled": True,
                        "policy_tags": {
                            "deliverable_modes": ["inference"],
                            "advertisable_modes": ["inference"],
                            "capacity_backing": "backed",
                        },
                    },
                }
            ]
        }

    async def availability(self) -> dict[tuple[str, str], int]:
        return {(SITE, rid): units for rid, units in self.units.items()}


class Registries:
    """The registries a publication pass sends to, recording each listing it
    publishes and holding the open listings a test planted."""

    urls = ("http://registry.test",)

    def __init__(self) -> None:
        self.published: list[Any] = []
        self.open: list[ListingSummary] = []
        self.publisher_reads: list[Any] = []

    def plant(self, listing_id: str, offering_mode: str) -> None:
        self.open.append(
            ListingSummary(
                id=listing_id, status="open", listing_resource={"offering_mode": offering_mode}
            )
        )

    async def __aenter__(self) -> "Registries":
        return self

    async def __aexit__(self, *exc: Any) -> bool:
        return False

    def _results(self, payloads: dict[str, Any]) -> list[dict[str, Any]]:
        return [
            {"registry_url": url, "success": True, "response": {"ok": True}, "error": None}
            for url in payloads
        ]

    async def publish_listing_per_registry(self, *, payloads: dict[str, Any]) -> list[dict[str, Any]]:
        self.published.extend(payloads.values())
        return self._results(payloads)

    async def list_publisher_listings_per_registry(self, principal: Any) -> list[RegistryListings]:
        self.publisher_reads.append(principal)
        return [RegistryListings(url, tuple(self.open)) for url in self.urls]

    async def update_listing_per_registry(
        self, *, listing_id: str, payloads: dict[str, Any]
    ) -> list[dict[str, Any]]:
        self.published.extend(payloads.values())
        if any(request.updates.get("status") == "closed" for request in payloads.values()):
            self.open = [item for item in self.open if item.id != listing_id]
        return self._results(payloads)


@pytest.fixture
def storefront(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """The configuration a seller's storefront starts from, and its database path."""
    db_path = tmp_path / "inference-storefront.db"
    monkeypatch.setenv(
        "ARKHAI_IDENTITY_CREDENTIAL", base64.urlsafe_b64encode(SEED).rstrip(b"=").decode()
    )
    # The process's database client is created by the first startup; each test
    # starts from none and leaves none behind.
    monkeypatch.setattr(container, "_sqlite_client", None)
    identity = SELLER_SIGNER.identity
    with replaced(
        identity={
            "scheme": identity.scheme.value,
            "identifier": identity.identifier,
            "admin_principals": {"identities": [ADMIN_SIGNER.identity.model_dump(mode="json")]},
        },
        wallet={"address": SELLER_WALLET, "private_key": SELLER_WALLET_KEY},
        credits={
            "service_url": AUTHORITY_URL,
            "expected_authorities": {
                "identities": [AUTHORITY_SIGNER.identity.model_dump(mode="json")]
            },
        },
        db_path=str(db_path),
        # A quota site the startup refusal can read; its runtime is the test's.
        capacity={
            "placement": "fill_first",
            "sites": {
                SITE: {
                    "url": "http://quota-site.invalid:8086",
                    "expected_authorities": {
                        "identities": [ADMIN_SIGNER.identity.model_dump(mode="json")]
                    },
                }
            },
        },
        settlement=settlement(),
    ), patch.dict(storefront_config.CHAINS, {"anvil": ANVIL}, clear=True):
        yield db_path


@pytest.fixture
def quota_site(monkeypatch: pytest.MonkeyPatch) -> QuotaSite:
    site = QuotaSite({"svc-quota": 42})
    monkeypatch.setattr(container.QUOTA_CAPACITY, "runtime", lambda factory: site)
    return site


@pytest.fixture
def registries(monkeypatch: pytest.MonkeyPatch) -> Registries:
    recorded = Registries()
    monkeypatch.setattr(
        container.QUOTA_PUBLICATION,
        "_registry",
        lambda: RegistryPublication(
            enabled=True,
            registry_urls=recorded.urls,
            storefront_url=storefront_config.BASE_URL_OVERRIDE,
            client_factory=lambda: recorded,
            publisher=container._registry_publisher,
        ),
    )
    return recorded


def deployed_chain(rpc_url: str, method: str, params: Any, timeout: float) -> str:
    """The chain's JSON-RPC endpoint, answering as the deployed development chain."""
    return hex(31337) if method == "eth_chainId" else "0x6080"


def app(seams: server.InferenceCompositionSeams | None = None) -> Any:
    # The probe's JSON-RPC transport is the composition's seam to the chain; the
    # SDK builds its clients over the HTTP rpc_url without calling it.
    return server.build_inference_storefront_app(
        registry=server.build_inference_storefront_registry(domain=get_market_domain_contract()),
        seams=seams or server.InferenceCompositionSeams(alkahest_json_rpc=deployed_chain),
    )


@dataclass
class Clients:
    seller: ListingClient
    public: StorefrontClient


@asynccontextmanager
async def running(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Clients]:
    """The app through its lifespan on the database its migration command built,
    with the seller's typed listing client and a public one."""

    async def no_startup_tasks(*, domain: Any) -> None:
        return None

    monkeypatch.setattr(server, "_startup_tasks", no_startup_tasks)
    migrate_storefront_database(CHAIN, storefront_config.settings.get("db_path"))
    served = app()
    async with served.router.lifespan_context(served):
        # Publishing waits for a reached chain, so the probe steps once.
        await container.resolved_alkahest_chain_probe.step()
        transport = httpx.ASGITransport(app=served)
        publishers = TrustedIdentitySet(identities=(SELLER_SIGNER.identity,))
        async with StorefrontClient(
            "http://seller",
            signer=SELLER_SIGNER,
            caller_role="seller",
            expected_publishers=publishers,
            transport=transport,
        ) as seller, StorefrontClient("http://seller", transport=transport) as public:
            yield Clients(
                seller=ListingClient(
                    seller, seller=SELLER_SIGNER.identity, request_model=PublishFromQuotaRequest
                ),
                public=public,
            )
