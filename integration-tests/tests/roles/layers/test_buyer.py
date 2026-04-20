"""Buyer layer: what a buyer runs on their own machine.

A buyer (someone who wants to rent compute) runs only the buyer agent.
They depend on an external chain and a marketplace registry, but are
otherwise independent of any seller or the market operator.

Produces the ``buyer_node`` fixture: an identifier for the buyer's
running agent.
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
def buyer_node(external_world: dict, market_registry: dict) -> dict:
    """A buyer's running machine: their agent.

    Represents "a buyer has launched their node and is ready to discover
    offers". Depends on the external chain (to sign attestations and
    create escrows) and the market registry (to discover sellers through).
    """
    def _require(key: str) -> str:
        value = settings.get(key)
        if not value:
            pytest.skip(f"Setting {key} not configured — skipping buyer-dependent tests")
        return value

    def _resolve(path: str) -> str:
        p = Path(path)
        return str(p if p.is_absolute() else _REPO_ROOT / p)

    return {
        "external": external_world,
        "market": market_registry,
        "agent_url": _require("AGENTS.BUYER_URL"),
        "agent_db_path": _resolve(_require("AGENTS.BUYER_DB")),
        "agent_env_file": _resolve(_require("AGENTS.BUYER_ENV")),
        "wallet_address": external_world["buyer"]["wallet_address"],
        "private_key": external_world["buyer"]["private_key"],
    }


@pytest.mark.roles_layer_buyer
class TestBuyerNode:
    """Verify a buyer's node (agent) is running."""

    def test_agent_reachable(self, buyer_node: dict):
        """Buyer agent responds on its HTTP port."""
        status, body = _http_get(f"{buyer_node['agent_url']}/.well-known/agent.json")
        assert status == 200, (
            f"Buyer agent at {buyer_node['agent_url']} not reachable: "
            f"status={status} body={body[:200]}"
        )

    def test_agent_db_exists(self, buyer_node: dict):
        """Buyer's local SQLite DB has been created."""
        db_path = Path(buyer_node["agent_db_path"])
        assert db_path.exists(), (
            f"Buyer agent DB {db_path} does not exist. "
            f"Agent runtime has not initialized."
        )
