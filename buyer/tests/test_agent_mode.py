"""Tests for env-file parsing + container path translation in market_buyer.common."""

from pathlib import Path

from market_buyer.common import read_env_value, container_db_to_host, REPO_ROOT


# ---------------------------------------------------------------------------
# read_env_value
# ---------------------------------------------------------------------------

def test_read_env_value_returns_default_when_no_file():
    assert read_env_value(None, "AGENT_MODE", default="host") == "host"


def test_read_env_value_returns_default_when_file_missing():
    assert read_env_value("/nonexistent/.env", "AGENT_MODE", default="host") == "host"


def test_read_env_value_reads_plain_value(tmp_path: Path):
    env = tmp_path / ".env"
    env.write_text("AGENT_MODE=container\n")
    assert read_env_value(env, "AGENT_MODE", default="host") == "container"


def test_read_env_value_returns_default_when_key_absent(tmp_path: Path):
    env = tmp_path / ".env"
    env.write_text("PORT=8000\n")
    assert read_env_value(env, "AGENT_MODE", default="host") == "host"


def test_read_env_value_strips_quotes(tmp_path: Path):
    env = tmp_path / ".env"
    env.write_text('AGENT_MODE="container"\n')
    assert read_env_value(env, "AGENT_MODE", default="host") == "container"


def test_read_env_value_ignores_comments(tmp_path: Path):
    env = tmp_path / ".env"
    env.write_text("# AGENT_MODE=container\nAGENT_MODE=host\n")
    assert read_env_value(env, "AGENT_MODE", default="host") == "host"


# ---------------------------------------------------------------------------
# container_db_to_host
# ---------------------------------------------------------------------------

def test_container_db_to_host_strips_dot_slash():
    p = container_db_to_host("./src/market_storefront/data/buy-agent/agent.db")
    assert p == REPO_ROOT / "src" / "market_storefront" / "data" / "buy-agent" / "agent.db"


def test_container_db_to_host_strips_app_prefix():
    p = container_db_to_host("/app/src/market_storefront/data/buy-agent/agent.db")
    assert p == REPO_ROOT / "src" / "market_storefront" / "data" / "buy-agent" / "agent.db"
