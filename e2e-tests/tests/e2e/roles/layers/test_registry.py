"""Registry layer: what a marketplace operator runs.

A marketplace operator runs the registry service — nothing else. They
provide the discovery surface that lets independent buyers and sellers
find each other. They do NOT run agents.

Produces the ``registry_layer`` fixture for downstream tests.
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
def registry_layer(external_world: dict) -> dict:
    """The registry/indexer service operated by a marketplace operator.

    Builds on top of ``external_world``. Consumed by any test that needs
    to talk to the registry (which is most stage tests).
    """
    url = settings.get("REGISTRY.API_URL")
    if not url:
        pytest.skip("REGISTRY.API_URL not configured — skipping registry-dependent tests")
    return {
        "external": external_world,
        "url": url,
    }


@pytest.mark.roles_layer_registry
class TestRegistryLayer:
    """Verify the marketplace operator's registry service is up."""

    def test_registry_reachable(self, registry_layer: dict):
        """Registry service responds to /health."""
        status, body = _http_get(f"{registry_layer['url']}/health")
        assert status == 200, (
            f"Registry at {registry_layer['url']} not healthy: "
            f"status={status} body={body[:200]}"
        )

    def test_registry_has_orders_endpoint(self, registry_layer: dict):
        """Registry exposes /listings for querying."""
        status, body = _http_get(f"{registry_layer['url']}/listings")
        assert status == 200, (
            f"GET {registry_layer['url']}/listings failed: status={status}"
        )
        data = json.loads(body)
        # Response shape: {"items": [...], "count": N} or similar
        assert isinstance(data, dict), f"Unexpected /listings response: {data!r}"

    def test_registry_has_agents_endpoint(self, registry_layer: dict):
        """Registry exposes /agents for querying."""
        status, body = _http_get(f"{registry_layer['url']}/agents")
        assert status == 200, (
            f"GET {registry_layer['url']}/agents failed: status={status}"
        )
