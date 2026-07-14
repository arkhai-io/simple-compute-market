"""
tests/conftest.py
-----------------
Shared pytest fixtures and session-level setup for arkhai-e2e-tests.
"""

from __future__ import annotations

import logging
from decimal import Decimal

import pytest
from web3 import Web3

from src.settings import active_profiles, config_directory, settings
from src.web3_client import OWNABLE_ABI, get_web3

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Session-scoped: one Web3 connection for the entire test run
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def w3() -> Web3:
    """Connected Web3 instance."""
    return get_web3()


# ---------------------------------------------------------------------------
# Configuration fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def rpc_settings() -> dict:
    return {
        "url": settings.RPC.URL,
        "chain_id": int(settings.RPC.CHAIN_ID),
    }


@pytest.fixture(scope="session")
def registry_settings() -> dict:
    return {
        "api_url": settings.REGISTRY.API_URL,
    }


@pytest.fixture(scope="session")
def buyer_settings() -> dict:
    """Buyer wallet config. The buyer is a pure HTTP client (domains.vms.buyer
    CLI / library) — there is no buyer api_url because no buyer-side
    server runs. Only the wallet keys are exposed: they sign negotiation
    requests against the seller's storefront and on-chain escrow calls.
    """
    return {
        "private_key": settings.BUYER.PRIVATE_KEY,
        "wallet_address": settings.BUYER.WALLET_ADDRESS,
    }


@pytest.fixture(scope="session")
def seller_settings() -> dict:
    return {
        "api_url": settings.SELLER.API_URL,
        "base_url_override": settings.SELLER.BASE_URL_OVERRIDE,
        "private_key": settings.SELLER.PRIVATE_KEY,
        "wallet_address": settings.SELLER.WALLET_ADDRESS,
        "admin_api_key": str(getattr(settings.SELLER, "ADMIN_API_KEY", None) or "").strip(),
        "agent_id": str(getattr(settings.SELLER, "AGENT_ID", None) or ""),
    }


@pytest.fixture(scope="session")
def min_eth_balance() -> Decimal:
    return Decimal(str(settings.get("TESTS__MINIMUM_ETH_BALANCE", "0.01")))


@pytest.fixture(scope="session")
def provisioning_settings() -> dict:
    return {
        "api_url": settings.PROVISIONING.API_URL,
    }


# ---------------------------------------------------------------------------
# Helper fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def checksum_address(w3: Web3):
    """Return a callable that converts an address to checksum form."""
    def _checksum(addr: str) -> str:
        return w3.to_checksum_address(addr)
    return _checksum


@pytest.fixture(scope="session")
def ownable_contract(w3: Web3):
    """Factory: return a minimal Ownable contract instance for a given address."""
    def _contract(address: str):
        checksummed = w3.to_checksum_address(address)
        return w3.eth.contract(address=checksummed, abi=OWNABLE_ABI)
    return _contract


# ---------------------------------------------------------------------------
# Session-level info log
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session", autouse=True)
def log_test_session_info() -> None:
    log.info("=" * 60)
    log.info("Arkhai E2E Test Session")
    log.info("  Config directory : %s", config_directory())
    log.info("  Active profiles  : %s", active_profiles() or ["(none)"])
    log.info("=" * 60)
