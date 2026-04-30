"""Fixtures for the full-deal e2e scenario tests.

All fixtures are ``module``-scoped so the ``DealState`` object persists
across the 16 sequential tests in ``test_full_deal.py``.  Each test reads
from and writes to ``DealState``; later tests skip automatically if an
earlier required field was never populated (indicating the earlier test
failed).

Clients
-------
* ``storefront_client``        — canonical ``SyncStorefrontClient``, buyer key
* ``storefront_admin_client``  — same, seller key + admin key
* ``registry_client``          — ``SyncRegistryClient`` from the registry-client wheel
* ``provisioning_client``      — canonical ``SyncProvisioningClient``
* ``provisioning_test_client`` — thin sync wrapper over ``/test/*`` endpoints

Settings access uses the ``settings.SECTION.KEY`` attribute pattern
(uppercase, dot-separated) consistent with the rest of the project's conftest.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional

import pytest

from src.settings import settings
from src.provisioning_test_client import ProvisioningTestClient

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# DealState — mutable carrier shared across all tests in the module
# ---------------------------------------------------------------------------

@dataclass
class DealState:
    """Accumulates IDs and snapshots as the deal progresses."""
    # Stage 00 — policy seeding
    _policies_seeded: bool = False
    _policy_evaluated: bool = False
    # Stage 1 — seller order
    seller_listing_id: Optional[str] = None
    _seller_url: str = ""
    # Stage 2 — registry visibility
    registry_order_confirmed: bool = False
    # Stage 3-4 — pause/resume
    pause_confirmed: bool = False
    resume_confirmed: bool = False
    # Stage 5-8 — negotiation
    negotiation_id: Optional[str] = None
    negotiation_round_count: int = 0
    negotiation_terminal_state: Optional[str] = None
    agreed_price: Optional[int] = None
    # Stage 9 — escrow (mock)
    escrow_uid: Optional[str] = None
    # Stage 10-11 — settlement + provisioning
    settlement_submitted: bool = False
    provisioning_job_id: Optional[str] = None
    # Stage 12-13 — provisioning lifecycle gates
    provisioning_paused_confirmed: bool = False
    provisioning_result_injected: bool = False
    # Stage 14-16 — settlement ready and credentials
    settlement_status: Optional[str] = None
    tenant_credentials: Optional[dict[str, Any]] = None
    seller_order_final_status: Optional[str] = None


def require_state(deal_state: DealState, *fields: str) -> None:
    """Skip the current test if any required DealState field is None/False."""
    for f in fields:
        val = getattr(deal_state, f, None)
        if not val:
            pytest.skip(
                f"Prerequisite not satisfied: DealState.{f} is {val!r}. "
                f"An earlier test likely failed."
            )


# ---------------------------------------------------------------------------
# Settings helpers — use attribute access, consistent with tests/conftest.py
# ---------------------------------------------------------------------------

def _require_setting(value: Any, name: str) -> str:
    """Return value as str, or skip if empty/missing."""
    if not value:
        pytest.skip(f"{name} not configured")
    return str(value)


# ---------------------------------------------------------------------------
# Module-scoped fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def deal_state() -> DealState:
    return DealState()


@pytest.fixture(scope="module")
def storefront_client():
    """Buyer-signed SyncStorefrontClient (no admin key)."""
    from storefront_client import SyncStorefrontClient
    url = _require_setting(settings.SELLER.API_URL, "SELLER.API_URL")
    client = SyncStorefrontClient(
        base_url=url,
        private_key=str(settings.BUYER.PRIVATE_KEY),
    )
    yield client
    client.close()


@pytest.fixture(scope="module")
def storefront_admin_client():
    """Seller-signed SyncStorefrontClient with admin key.

    Uses the seller's private key because /orders/create and similar
    seller-owned endpoints verify EIP-191 signatures against the seller's
    configured wallet address (CONFIG.agent_wallet_address).
    The admin_key is a separate X-Admin-Key header that gates /admin/* routes.
    """
    from storefront_client import SyncStorefrontClient
    url = _require_setting(settings.SELLER.API_URL, "SELLER.API_URL")
    admin_key = _require_setting(settings.SELLER.ADMIN_API_KEY, "SELLER.ADMIN_API_KEY")
    client = SyncStorefrontClient(
        base_url=url,
        private_key=str(settings.SELLER.PRIVATE_KEY),
        admin_key=admin_key,
    )
    yield client
    client.close()


@pytest.fixture(scope="module")
def registry_client():
    """SyncRegistryClient from the canonical registry-client wheel."""
    from registry_client import SyncRegistryClient
    url = _require_setting(settings.REGISTRY.API_URL, "REGISTRY.API_URL")
    client = SyncRegistryClient(base_url=url)
    yield client
    client.close()


@pytest.fixture(scope="module")
def provisioning_client():
    """Canonical SyncProvisioningClient."""
    from client.provisioning_client import SyncProvisioningClient
    url = _require_setting(settings.PROVISIONING.API_URL, "PROVISIONING.API_URL")
    seller_agent_id = str(settings.SELLER.AGENT_ID or "")
    client = SyncProvisioningClient(
        base_url=url,
        agent_id=seller_agent_id or None,
    )
    yield client
    client.close()


@pytest.fixture(scope="module")
def provisioning_test_client():
    """ProvisioningTestClient for /test/* control endpoints.

    Only works when the provisioning service runs with ACTIVE_PROFILES=mock.
    """
    url = _require_setting(settings.PROVISIONING.API_URL, "PROVISIONING.API_URL")
    with ProvisioningTestClient(base_url=url, timeout=20.0) as client:
        yield client


@pytest.fixture(scope="module")
def buyer_config() -> dict[str, str]:
    """Buyer wallet credentials for signing negotiate/settle requests."""
    private_key = str(settings.BUYER.PRIVATE_KEY or "")
    wallet_address = str(settings.BUYER.WALLET_ADDRESS or "")
    if not private_key or not wallet_address:
        pytest.skip("BUYER.PRIVATE_KEY / BUYER.WALLET_ADDRESS not configured")
    ssh_public_key = str(
        getattr(settings.BUYER, "SSH_PUBLIC_KEY", None) or
        "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAITestKeyForE2E test@e2e"
    )
    return {
        "private_key": private_key,
        "wallet_address": wallet_address,
        "ssh_public_key": ssh_public_key,
    }


@pytest.fixture(scope="module")
def seller_wallet() -> str:
    """Seller wallet address — passed as agent_wallet_address to create_order."""
    return _require_setting(settings.SELLER.WALLET_ADDRESS, "SELLER.WALLET_ADDRESS")
