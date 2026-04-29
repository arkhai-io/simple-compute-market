"""Smoke tests for a deployed seller storefront.

Replaces the legacy test_agents.py, which tested the symmetric two-
storefront flow (one "buyer" storefront posting buy-shaped orders, one
"seller" posting sell-shaped). Buyers no longer host a storefront —
they're a pure HTTP client surfaced via the `market` CLI / market_buyer
library — so what the helm smoke pod actually wants to confirm is "the
seller storefront is reachable and on-chain registered".

Tagged ``@pytest.mark.storefront`` so the helm test pod's
``pytest -m storefront`` selector still picks them up.
"""

from __future__ import annotations

import logging

import pytest

from src.agent_client import AgentClient
from registry_client import RegistryClientError

log = logging.getLogger(__name__)


@pytest.fixture(scope="module")
def seller_api_url(seller_settings) -> str:
    url = seller_settings.get("api_url", "")
    if not url:
        pytest.fail(
            "seller.api_url is not configured.\n"
            "Set it via ARKHAI_SELLER__API_URL, config.yml, or --seller-api-url."
        )
    return url.rstrip("/")


@pytest.fixture(scope="module")
def seller_client(seller_api_url: str, seller_settings: dict) -> AgentClient:
    client = AgentClient(
        base_url=seller_api_url,
        private_key=seller_settings["private_key"],
        agent_wallet_address=seller_settings["wallet_address"],
    )
    yield client
    client.close()


@pytest.mark.storefront
class TestStorefrontRegistration:
    """Verify the deployed seller storefront is reachable and on-chain registered."""

    def test_storefront_is_on_chain_registered(self, seller_client: AgentClient) -> None:
        """The registration file must contain at least one record with a
        non-zero agentId. Confirms the agent has been indexed by the
        registry and its on-chain identity is live.
        """
        try:
            reg = seller_client.get_registration_file()
        except RegistryClientError as exc:
            pytest.fail(f"Could not fetch seller registration file.\n{exc}")

        assert reg.registrations, (
            "Seller has no registration records in its ERC-8004 file.\n"
            "The agent may not have completed on-chain registration."
        )
        assert reg.is_registered, (
            f"Seller registration records all have agentId == 0.\n"
            f"Registrations: {reg.registrations}\n"
            "The agent has not been indexed by the registry yet."
        )
        log.info(
            "✓ Seller is registered — agentId(s): %s",
            [r.agent_id for r in reg.registrations],
        )

    def test_storefront_registry_address_matches_config(
        self,
        seller_client: AgentClient,
        registry_settings: dict,
    ) -> None:
        """The agentRegistry field in the registration file must contain
        the identity_address from configuration.

        Guards against the agent being registered against a different
        registry contract than the one this test suite is configured to
        use (e.g., wrong chain or stale deployment).
        """
        expected_address = registry_settings["identity_address"].lower()
        try:
            reg = seller_client.get_registration_file()
        except RegistryClientError as exc:
            pytest.fail(f"Could not fetch seller registration file.\n{exc}")

        assert reg.registrations, "Seller has no registration records."

        actual_addresses = [
            (r.registry_address or "").lower()
            for r in reg.registrations
        ]
        assert any(addr == expected_address for addr in actual_addresses), (
            f"Seller is not registered against the expected identity registry.\n"
            f"  Expected : {expected_address}\n"
            f"  Got      : {actual_addresses}\n"
            "Check registry.identity_address in config and the agent's "
            "registry.identity_registry_address in config.toml."
        )
        log.info(
            "✓ Seller registry address matches config: %s", expected_address
        )
