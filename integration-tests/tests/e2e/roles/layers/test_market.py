"""Market layer: what a marketplace operator runs.

A marketplace operator runs the registry service — nothing else. They
provide the discovery surface that lets independent buyers and sellers
find each other. They do NOT run agents.

Produces the ``market_registry`` fixture for downstream tests.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request

import pytest

from src.settings import settings

log = logging.getLogger(__name__)


def _http_get(url: str, timeout: float = 5) -> tuple[int, str]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return resp.status, resp.read().decode(errors="replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode(errors="replace")
    except urllib.error.URLError as exc:
        return 0, str(exc)


@pytest.fixture(scope="session")
def market_registry(external_world: dict) -> dict:
    """The marketplace registry: an indexer service operated by a market operator.

    Builds on top of ``external_world``. Consumed by any test that needs
    to talk to the registry (which is most stage tests).
    """
    url = settings.get("AGENTS.REGISTRY_URL")
    if not url:
        pytest.skip("AGENTS.REGISTRY_URL not configured — skipping market-dependent tests")
    return {
        "external": external_world,
        "url": url,
    }


@pytest.mark.roles_layer_market
class TestMarketRegistry:
    """Verify the market operator's registry service is up."""

    def test_registry_reachable(self, market_registry: dict):
        """Registry service responds to /health."""
        status, body = _http_get(f"{market_registry['url']}/health")
        assert status == 200, (
            f"Registry at {market_registry['url']} not healthy: "
            f"status={status} body={body[:200]}"
        )

    def test_registry_has_orders_endpoint(self, market_registry: dict):
        """Registry exposes /listings for querying."""
        status, body = _http_get(f"{market_registry['url']}/listings")
        assert status == 200, (
            f"GET {market_registry['url']}/listings failed: status={status}"
        )
        data = json.loads(body)
        # Response shape: {"items": [...], "count": N} or similar
        assert isinstance(data, dict), f"Unexpected /listings response: {data!r}"

    def test_registry_has_agents_endpoint(self, market_registry: dict):
        """Registry exposes /agents for querying."""
        status, body = _http_get(f"{market_registry['url']}/agents")
        assert status == 200, (
            f"GET {market_registry['url']}/agents failed: status={status}"
        )
