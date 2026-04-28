"""Tests for container path translation in market_buyer.common."""

from market_buyer.common import container_db_to_host, REPO_ROOT


def test_container_db_to_host_strips_dot_slash():
    p = container_db_to_host("./src/market_storefront/data/buy-agent/agent.db")
    assert p == REPO_ROOT / "src" / "market_storefront" / "data" / "buy-agent" / "agent.db"


def test_container_db_to_host_strips_app_prefix():
    p = container_db_to_host("/app/src/market_storefront/data/buy-agent/agent.db")
    assert p == REPO_ROOT / "src" / "market_storefront" / "data" / "buy-agent" / "agent.db"
