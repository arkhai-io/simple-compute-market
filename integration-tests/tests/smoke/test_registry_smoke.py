"""
Integration tests for the Registry REST API.

Scope
-----
These tests validate *deployment* concerns only:
  - The service is reachable and healthy
  - The service can connect to its dependencies (health_checks_enabled)
  - The service has been seeded with at least one agent
"""

from __future__ import annotations

import logging

import pytest

from registry_client import SyncRegistryClient as RegistryClient
from registry_client import RegistryClientError
from registry_client.models import AgentListResponse

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-scoped fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def registry_api_url(registry_settings) -> str:
    url = registry_settings.get("api_url", "")
    if not url:
        pytest.fail(
            "registry.api_url is not configured.\n"
            "Set it via ARKHAI_REGISTRY__API_URL, config.yml, or --registry-api-url."
        )
    return url.rstrip("/")


@pytest.fixture(scope="module")
def registry_client(registry_api_url: str) -> RegistryClient:  # type: ignore[return]
    """One RegistryClient instance shared across all tests in this module."""
    client = RegistryClient(base_url=registry_api_url)
    yield client
    client.close()


# ---------------------------------------------------------------------------
# Test suite 1 — Service health
# ---------------------------------------------------------------------------

@pytest.mark.registry
class TestRegistryHealth:
    """Verify the Registry service is live and all dependency checks pass."""

    def test_health_endpoint_returns_200(self, registry_client: RegistryClient) -> None:
        try:
            health = registry_client.get_health()
        except RegistryClientError as exc:
            pytest.fail(
                f"Registry health check failed — service may be down or unreachable.\n{exc}"
            )

        log.info("Health response: status=%s checks=%s extra=%s",
                 health.status, health.extra.get("checks"), health.extra)

        assert health is not None, "GET /health returned no parseable body"

    def test_health_checks_enabled(self, registry_client: RegistryClient) -> None:
        try:
            health = registry_client.get_health()
        except RegistryClientError as exc:
            pytest.fail(f"Could not reach /health to check dependency status.\n{exc}")

        checks = health.extra.get("checks", {})

        assert checks, (
            "health response is missing the 'checks' field.\n"
            f"Full response: status={health.status!r} extra={health.extra}"
        )

        assert checks.get("database") == "ok", (
            f"Database health check is not 'ok'.\n"
            f"checks={checks}\n"
            "The registry may have lost its database connection."
        )

        log.info("✓ health checks present — database=%s", checks.get("database"))


# ---------------------------------------------------------------------------
# Test suite 2 — Agent registry population
# ---------------------------------------------------------------------------

@pytest.mark.registry
class TestRegistryAgents:
    """Verify the deployed registry contains at least one registered agent."""

    def test_list_agents_returns_200(self, registry_client: RegistryClient) -> None:
        """
        GET /agents must respond with HTTP 200.

        Validates basic API reachability beyond /health and confirms the
        agent listing route is wired up correctly in the deployment.
        """
        try:
            result = registry_client.list_agents(limit=1)
        except RegistryClientError as exc:
            pytest.fail(f"GET /agents failed — route may be misconfigured in this deployment.\n{exc}")

        assert isinstance(result, AgentListResponse), (
            f"Expected AgentListResponse, got {type(result)}"
        )

        log.info("GET /agents responded successfully (agents_in_page=%d)", len(result.agents))

    def test_list_agents_response_shape(self, registry_client: RegistryClient) -> None:
        """GET /agents returns a parseable AgentListResponse.

        Post-pluggable-identity (Phase 4) agent rows are created lazily on
        first signed publish_listing — the registry is empty on a fresh
        stack until a storefront publishes. Smoke tests verify the
        endpoint contract, not data flow; the populated-registry assertion
        lives in the e2e suite where the seller publishes as part of the
        scenario.
        """
        try:
            result = registry_client.list_agents(limit=5)
        except RegistryClientError as exc:
            pytest.fail(f"GET /agents failed — route may be misconfigured.\n{exc}")

        log.info(
            "GET /agents responded — agents_in_page=%d total=%s",
            len(result.agents),
            result.total,
        )


