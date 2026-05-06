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
    # Phase 0 — service readiness
    _storefront_healthy: bool = False
    _registry_reachable: bool = False
    _provisioning_healthy: bool = False
    _negotiation_strategy_viable: bool = False
    # Phase 1 — policy pipeline
    _policy_dry_run_passed: bool = False
    _policies_seeded: bool = False
    # Phase 2 — listing creation (paused)
    _evaluate_create_passed: bool = False
    seller_listing_id: Optional[str] = None
    # Phase 3 — registry publication
    _registry_validate_passed: bool = False
    resume_confirmed: bool = False
    # Phase 5 — negotiation
    _evaluate_negotiate_passed: bool = False
    negotiation_id: Optional[str] = None
    negotiation_terminal_state: Optional[str] = None
    agreed_price: Optional[int] = None
    # Phase 7 — mock escrow + provisioning gate
    real_escrow_uid: Optional[str] = None
    provisioning_gate_armed: bool = False
    # Phase 8a — evaluate settle (doWork dry-run)
    _evaluate_settle_vm_host: Optional[str] = None
    _evaluate_settle_vm_target: Optional[str] = None
    _evaluate_settle_passed: bool = False
    # Phase 9a — provisioning job evaluate
    _provision_job_evaluated: bool = False
    # Phase 8 — settlement
    settlement_submitted: bool = False
    provisioning_job_id: Optional[str] = None
    # Phase 9 — provisioning completion
    provisioning_result_injected: bool = False
    settlement_status: Optional[str] = None
    tenant_credentials: Optional[dict[str, Any]] = None
    seller_listing_final_status: Optional[str] = None


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
    # rpc_url for on-chain escrow creation — falls back to the global rpc.url setting
    rpc_url = str(
        getattr(settings.BUYER, "CHAIN_RPC_URL", None) or
        getattr(settings, "RPC", {}).get("URL", "ws://localhost:8545")
    )
    return {
        "private_key": private_key,
        "wallet_address": wallet_address,
        "ssh_public_key": ssh_public_key,
        "rpc_url": rpc_url,
    }


@pytest.fixture(scope="module")
def seller_wallet() -> str:
    """Seller wallet address — passed as agent_wallet_address to create_order."""
    return _require_setting(settings.SELLER.WALLET_ADDRESS, "SELLER.WALLET_ADDRESS")


# ---------------------------------------------------------------------------
# Teardown — ensure global pause is cleared after each test module run
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module", autouse=True)
def ensure_storefront_resumed(storefront_admin_client):
    """Yield to let the module run; then unconditionally clear global pause if set.

    Safety net in case an unexpected error leaves the storefront paused between
    runs. Admin pause/resume is no longer tested in this module (moved to the
    smoke suite), so this fixture should rarely need to act.
    """
    yield
    try:
        status = storefront_admin_client.get_system_status()
        if status.paused:
            storefront_admin_client.admin_resume()
            log.info("[teardown] Cleared residual global pause on storefront")
    except Exception as exc:
        log.warning("[teardown] Could not verify/clear global pause: %s", exc)


# ---------------------------------------------------------------------------
# wait_for_stage_event helper — wraps storefront_admin_client.wait_for_stage_event
# ---------------------------------------------------------------------------

def wait_for_stage_event(
    client,
    stage: str,
    event: str,
    *,
    listing_id: str | None = None,
    negotiation_id: str | None = None,
    timeout: float = 30.0,
):
    """Block until the matching stage event appears in /api/v1/system/events.

    Wraps ``SyncStorefrontClient.wait_for_stage_event`` with a friendlier
    pytest-style timeout error message.

    Parameters
    ----------
    client:
        A ``SyncStorefrontClient`` instance with admin_key configured.
    stage, event:
        Stage and event strings to match (e.g. ``"discovery"``, ``"order_published"``).
    listing_id, negotiation_id:
        Optional filters passed through to the events query.
    timeout:
        Seconds to wait before raising AssertionError.
    """
    try:
        return client.wait_for_stage_event(
            stage, event,
            listing_id=listing_id,
            negotiation_id=negotiation_id,
            timeout=timeout,
        )
    except TimeoutError as exc:
        pytest.fail(str(exc))
