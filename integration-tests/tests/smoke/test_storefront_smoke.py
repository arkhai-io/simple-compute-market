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

    def test_storefront_registry_connectivity(
        self,
        seller_api_url: str,
        seller_settings: dict,
    ) -> None:
        """GET /api/v1/system/status must report checks.registry == 'ok'.

        Guards against misconfigured registry.url in config.toml — this
        failure would cause resume_listing to silently return
        registry_status='error' and the e2e deal test to fail at stage 05.
        """
        import httpx
        admin_key = seller_settings.get("admin_api_key", "")
        headers = {"X-Admin-Key": admin_key} if admin_key else {}
        try:
            resp = httpx.get(
                f"{seller_api_url}/api/v1/system/status",
                headers=headers,
                timeout=5.0,
            )
        except Exception as exc:
            pytest.fail(f"Could not reach /api/v1/system/status: {exc}")

        assert resp.status_code == 200, (
            f"GET /api/v1/system/status returned {resp.status_code}: {resp.text[:200]}"
        )
        body = resp.json()
        registry_check = body.get("checks", {}).get("registry", "absent")
        assert registry_check == "ok", (
            f"Storefront cannot reach registry. checks.registry={registry_check!r}.\n"
            f"Verify registry.url in the storefront's config.toml points to a reachable\n"
            f"indexer endpoint from inside the storefront container.\n"
            f"Full status response: {body}"
        )
        log.info("✓ Storefront registry connectivity ok")

    def test_negotiation_strategy_viable(
        self,
        seller_api_url: str,
        seller_settings: dict,
    ) -> None:
        """GET /api/v1/system/status must report a viable negotiation strategy.

        Guards against the rl strategy being configured but torch being
        unavailable in the container — in that case every /negotiate/new call
        returns exit_negotiation at round 0, causing stage 10 of the e2e test
        to fail with a 409 on force-accept.  Catching this here saves the entire
        multi-stage e2e run.
        """
        import httpx
        admin_key = seller_settings.get("admin_api_key", "")
        headers = {"X-Admin-Key": admin_key} if admin_key else {}
        try:
            resp = httpx.get(
                f"{seller_api_url}/api/v1/system/status",
                headers=headers,
                timeout=5.0,
            )
        except Exception as exc:
            pytest.fail(f"Could not reach /api/v1/system/status: {exc}")

        assert resp.status_code in (200, 503), (
            f"Unexpected status {resp.status_code}: {resp.text[:200]}"
        )
        body = resp.json()
        strat = body.get("checks", {}).get("negotiation_strategy", "absent")
        assert strat != "absent", (
            "checks.negotiation_strategy absent from status response. "
            "Ensure the storefront image includes the updated system_controller.py."
        )
        assert "exit_on_probe" not in strat, (
            f"Negotiation strategy would exit on every round: {strat!r}\n"
            "Fix: set [seller.negotiation] policy_mode = 'bisection' in config.toml,\n"
            "or install torch in the container if rl is required."
        )
        log.info("✓ Negotiation strategy viable: %s", strat)
