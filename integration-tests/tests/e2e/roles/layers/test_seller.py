"""Seller layer: what a seller runs on their own machine.

A seller (someone with compute to sell) runs the seller agent and a
provisioning service on their machine. They depend on an external chain
and a marketplace registry, but are otherwise independent of any other
seller or the market operator.

Produces the ``seller_node`` fixture: an identifier for the seller's
running agent and provisioning service. "Node" here means "one seller's
machine", not blockchain node.
"""

from __future__ import annotations

import logging
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from src.settings import settings

log = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[4]


def _http_get(url: str, timeout: float = 5) -> tuple[int, str]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return resp.status, resp.read().decode(errors="replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode(errors="replace")
    except urllib.error.URLError as exc:
        return 0, str(exc)


@pytest.fixture(scope="session")
def seller_node(external_world: dict, market_registry: dict) -> dict:
    """A seller's running machine: agent + provisioning service.

    This fixture represents "a seller has launched their node and is
    ready to publish offers". Depends on the external chain (to sign
    attestations) and the market registry (to publish into).
    """
    def _require(key: str) -> str:
        value = settings.get(key)
        if not value:
            pytest.skip(f"Setting {key} not configured — skipping seller-dependent tests")
        return value

    def _resolve(path: str) -> str:
        p = Path(path)
        return str(p if p.is_absolute() else _REPO_ROOT / p)

    return {
        "external": external_world,
        "market": market_registry,
        "agent_url": _require("AGENTS.SELLER_URL"),
        "agent_db_path": _resolve(_require("AGENTS.SELLER_DB")),
        "agent_env_file": _resolve(_require("AGENTS.SELLER_ENV")),
        "wallet_address": external_world["seller"]["wallet_address"],
        "private_key": external_world["seller"]["private_key"],
    }


@pytest.mark.roles_layer_seller
class TestSellerNode:
    """Verify a seller's node (agent + provisioning) is running."""

    def test_agent_reachable(self, seller_node: dict):
        """Seller agent responds on its HTTP port."""
        status, body = _http_get(f"{seller_node['agent_url']}/.well-known/agent.json")
        assert status == 200, (
            f"Seller agent at {seller_node['agent_url']} not reachable: "
            f"status={status} body={body[:200]}"
        )

    def test_agent_db_exists(self, seller_node: dict):
        """Seller's local SQLite DB has been created (agent is initialized)."""
        db_path = Path(seller_node["agent_db_path"])
        assert db_path.exists(), (
            f"Seller agent DB {db_path} does not exist. "
            f"Agent runtime has not initialized."
        )
