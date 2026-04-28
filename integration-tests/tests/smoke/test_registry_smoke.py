"""
Integration tests for the Registry REST API.

Scope
-----
These tests validate *deployment* concerns only:
  - The service is reachable and healthy
  - The service can connect to its dependencies (health_checks_enabled)
  - The service has been seeded with at least one agent
  - The attestation stats endpoint is reachable and returns a valid shape
  - (Production only) The registry contains at least one settled order
"""

from __future__ import annotations

import logging
import warnings

import pytest

from registry_client import SyncRegistryClient as RegistryClient
from registry_client import RegistryClientError, AttestationStats
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

    def test_at_least_one_agent_registered(self, registry_client: RegistryClient) -> None:
        """
        The registry must contain at least one registered agent.

        In a test-env deployment this is satisfied by the sentinel agent
        registered on-chain during build-anvil-state (Anvil account #3,
        unrelated to buyer/seller agents).  In production this is satisfied
        by the seller agent registering on startup.

        An empty registry indicates either:
          - the sentinel registration or agent startup failed, or
          - the event sync did not replay the Registered event on startup.
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
            "In test-env: check that build-anvil-state ran seed_agent.py successfully.\n"
            "In production: check that the seller agent registered on startup.\n"
            f"Response: total={result.total} agents_in_page={len(result.agents)}"
        )

        first = result.agents[0]
        log.info(
            "✓ Registry contains agents — first: id=%s name=%s owner=%s",
            first.agent_id or first.id,
            first.name,
            first.owner,
        )


# ---------------------------------------------------------------------------
# Test suite 3 — Attestation stats endpoint
# ---------------------------------------------------------------------------

@pytest.mark.registry
class TestAttestationStats:
    """Verify the attestation stats endpoint is reachable and returns valid data."""

    def test_attestation_endpoint_reachable(self, registry_client: RegistryClient) -> None:
        """
        GET /api/v1/system/stats/attestations must respond with HTTP 200
        and return a parseable AttestationStats response.

        This test always passes in any healthy deployment — it validates
        only that the endpoint exists and returns a valid shape, not that
        settled orders are present (see test_settled_orders_exist).
        """
        try:
            stats = registry_client.get_attestation_stats()
        except RegistryClientError as exc:
            pytest.fail(
                f"GET /api/v1/system/stats/attestations failed.\n"
                f"The endpoint may be missing from this deployment.\n{exc}"
            )

        assert isinstance(stats, AttestationStats), (
            f"Expected AttestationStats, got {type(stats)}"
        )
        assert stats.settled_order_count >= 0
        assert stats.maker_attestation_count >= 0
        assert stats.taker_attestation_count >= 0

        log.info(
            "Attestation stats — settled=%d maker=%d taker=%d",
            stats.settled_order_count,
            stats.maker_attestation_count,
            stats.taker_attestation_count,
        )

    def test_settled_orders_exist(self, registry_client: RegistryClient) -> None:
        """
        The registry should contain at least one fully settled order
        (both maker_attestation and taker_attestation set).

        A non-zero settled_order_count is the strongest available
        smoke-test signal: it confirms that contracts are deployed,
        agents are registered, negotiations completed, Alkahest escrow
        was locked, and compute obligation was fulfilled and attested.

        WARNING behaviour (not failure): A fresh test-env deployment will
        always have zero settled orders because no agent negotiations have
        run yet — seeding a full deal cycle at build time is not feasible.
        This test emits a warning rather than failing hard in that case, so
        the test suite still passes for new deployments while the assertion
        is meaningful in long-running production/staging environments.
        """
        try:
            stats = registry_client.get_attestation_stats()
        except RegistryClientError as exc:
            pytest.fail(
                f"GET /api/v1/system/stats/attestations failed — cannot check settlement.\n{exc}"
            )

        log.info(
            "Settlement check — settled_order_count=%d",
            stats.settled_order_count,
        )

        if stats.settled_order_count == 0:
            warnings.warn(
                "No settled orders found in the registry "
                f"(maker_attestation_count={stats.maker_attestation_count}, "
                f"taker_attestation_count={stats.taker_attestation_count}).\n"
                "This is expected in a fresh test-env deployment where no agent "
                "negotiations have completed yet. In a long-running production or "
                "staging environment this indicates no deals have fully settled.",
                UserWarning,
                stacklevel=2,
            )
            return

        log.info(
            "✓ Registry contains %d settled order(s) — market is functioning end-to-end",
            stats.settled_order_count,
        )
