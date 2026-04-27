"""
Integration tests for the Registry REST API.

Scope
-----
These tests validate *deployment* concerns only:
  - The service is reachable and healthy
  - The service can connect to its dependencies (health_checks_enabled)
  - The service has been seeded with at least one agent
  - The service has at least one order visible in the order book
"""

from __future__ import annotations

import logging

import pytest

from registry_client import SyncRegistryClient as RegistryClient
from registry_client import RegistryClientError
from registry_client.models import AgentListResponse, OrderListResponse

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

        # Kept as a separate assertion so the log line above always runs
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

    def test_at_least_one_agent_registered(self, registry_client: RegistryClient) -> None:
        """
        The registry must contain at least one registered agent.

        An empty registry indicates either:
          - the deployment seed / migration did not run, or
          - agents failed to register on startup due to a credential or
            connectivity issue.

        This test uses limit=1 so it is fast regardless of registry size.
        """
        try:
            result = registry_client.list_agents(limit=1)
        except RegistryClientError as exc:
            pytest.fail(f"GET /agents failed — cannot verify agent population.\n{exc}")

        log.info(
            "Agent registry population — agents_in_page=%d total=%s",
            len(result.agents),
            result.total,
        )

        assert len(result.agents) >= 1, (
            "No agents found in the registry.\n"
            "Expected at least one registered agent in a healthy deployment.\n"
            f"Response: total={result.total} agents_in_page={len(result.agents)}"
        )

        # Log the first agent for diagnostic visibility in CI reports
        first = result.agents[0]
        log.info(
            "✓ Registry contains agents — first: id=%s name=%s owner=%s",
            first.agent_id or first.id,
            first.name,
            first.owner,
        )


# ---------------------------------------------------------------------------
# Test suite 3 — Order book population
# ---------------------------------------------------------------------------

@pytest.mark.registry
class TestRegistryOrders:
    """Verify the deployed registry has at least one order in the order book."""

    def test_list_orders_returns_200(self, registry_client: RegistryClient) -> None:
        """
        GET /orders must respond with HTTP 200.

        Confirms the orders route is reachable and the underlying data store
        is queryable.
        """
        try:
            result = registry_client.list_orders(limit=1, status=None)
        except RegistryClientError as exc:
            pytest.fail(
                f"GET /orders failed — route may be misconfigured in this deployment.\n{exc}"
            )

        assert isinstance(result, OrderListResponse), (
            f"Expected OrderListResponse, got {type(result)}"
        )

        log.info("GET /orders responded successfully (orders_in_page=%d)", len(result.orders))

    def test_at_least_one_order_exists(self, registry_client: RegistryClient) -> None:
        """
        The order book must contain at least one order (any status).

        An empty order book in a deployed environment suggests that:
          - agent startup routines failed to publish initial orders, or
          - the orders table was not migrated / seeded correctly.

        We query with status=None to include all statuses (open, matched,
        expired) so a recently-deployed environment with no live orders but
        historical ones still passes.
        """
        try:
            # A null status filter only returns open orders. Here we use closed to try to capture historical data.
            result = registry_client.list_orders(limit=1, status="closed")
            if len(result.orders) == 0:
                result = registry_client.list_orders(limit=1, status=None)
        except RegistryClientError as exc:
            pytest.fail(f"GET /orders failed — cannot verify order book population.\n{exc}")

        assert len(result.orders) >= 1, (
            "No orders found in the registry (queried with closed and null status filter).\n"
            "Expected at least one order in a healthy deployment.\n"
            f"Response: total={result.total} orders_in_page={len(result.orders)}"
        )

        first = result.orders[0]
        log.info(
            "✓ Order book contains orders — first: id=%s status=%s maker=%s",
            first.id,
            first.status,
            first.maker_agent_id,
        )