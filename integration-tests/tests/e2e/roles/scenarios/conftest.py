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
    _provisioning_mock_mode: bool = False
    _negotiation_strategy_viable: bool = False
    _resources_seeded: bool = False
    _alkahest_configured: bool = False
    _provisioning_storefront_ok: bool = False
    # Phase 1 — policy pipeline
    _policy_dry_run_passed: bool = False
    _policies_seeded: bool = False
    # Phase 2 — listing creation (paused)
    _evaluate_create_passed: bool = False
    seller_listing_id: Optional[str] = None
    # Phase 3 — registry publication
    _registry_validate_passed: bool = False
    resume_confirmed: bool = False
    _seller_agent_indexed: bool = False
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
    reserved_resource_id: Optional[str] = None
    # Phase 9 — provisioning completion
    provisioning_result_injected: bool = False
    lease_id: Optional[str] = None
    lease_status: Optional[str] = None
    settlement_status: Optional[str] = None
    tenant_credentials: Optional[dict[str, Any]] = None
    seller_listing_final_status: Optional[str] = None
    # Phase 10-11 — lease expiry lifecycle
    _lease_expiry_armed: bool = False
    check_job_id: Optional[str] = None


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
def seller_agent_id(storefront_admin_client) -> str:
    """Discover the seller's live canonical agent ID from /api/v1/system/status.

    Reads the storefront's own agent_id rather than hardcoding it in the test
    config. The hardcoded form (e.g. ``eip155:31337:0x8004A8...:2``) is only
    deterministic on a strictly-fresh anvil where account #2 registers second
    against IdentityRegistry — any prior registration shifts the on-chain ID
    and breaks the auth header used by /admin/* and the provisioning service.

    The storefront exposes its live agent_id at the top level of
    /api/v1/system/status (added in 40b1b9b alongside chain_id and
    resource_count diagnostics). Falls back to the configured ``SELLER.AGENT_ID``
    if the status endpoint doesn't include one (e.g. seller hasn't completed
    registration yet — should be a clear test failure rather than a silent
    skip).
    """
    status = storefront_admin_client.get_system_status()
    live = getattr(status, "agent_id", None)
    if live:
        return str(live)
    fallback = str(settings.SELLER.AGENT_ID or "")
    if not fallback:
        pytest.skip(
            "Storefront has no live agent_id and SELLER.AGENT_ID is not configured. "
            "Either run `market-storefront register` against the storefront, "
            "or set SELLER.AGENT_ID in config-<profile>.yml."
        )
    return fallback


@pytest.fixture(scope="module")
def provisioning_client(seller_agent_id):
    """Canonical SyncProvisioningClient.

    Uses the seller's live agent ID for X-Agent-ID — provisioning jobs created
    by the storefront carry the seller's agent_id, so reads need the same value
    or get a 403.
    """
    from client.provisioning_client import SyncProvisioningClient
    url = _require_setting(settings.PROVISIONING.API_URL, "PROVISIONING.API_URL")
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
    # rpc_url for on-chain escrow creation (AlkahestClient — ws:// only).
    # Resolved from buyer.chain_rpc_url, then rpc.url, then a localhost default.
    # Local/docker profiles set buyer.chain_rpc_url explicitly to a WebSocket
    # endpoint; the helper coerces http(s) fallback values for staging profiles
    # that only define rpc.url.
    rpc_url = (
        str(settings.BUYER.CHAIN_RPC_URL or "").strip()
        or str(settings.RPC.URL or "").strip()
        or "ws://localhost:8545"
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


@pytest.fixture(scope="module", autouse=True)
def release_reserved_resources(storefront_admin_client):
    """Release any leftover reserved compute resources after the module runs.

    Stage 09 reserves a compute VM for the deal but mocked provisioning never
    expires the lease, so the resource stays in ``reserved`` state forever.
    Without this teardown, a second back-to-back e2e_deal run against the
    same stack hits ``no_matching_inventory`` at stage 05b.

    Production storefronts release reservations via ``resource_poller`` once
    the lease expires; this fixture is the test-only equivalent for the
    short-circuited mock flow.
    """
    yield
    try:
        result = storefront_admin_client.admin_release_reservations()
        if result.released_count:
            log.info(
                "[teardown] Released %d reserved resource(s): %s",
                result.released_count, result.resource_ids,
            )
    except Exception as exc:
        log.warning("[teardown] Could not release reserved resources: %s", exc)


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
