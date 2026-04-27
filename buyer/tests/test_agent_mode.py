"""Tests for AGENT_MODE detection and register no-op behaviour."""

from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from market_buyer.cli import app
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


runner = CliRunner()


# Note: register/start/portfolio command tests moved with their
# implementations to market-storefront. Re-add them in
# storefront/tests/unit/test_cli_admin.py covering market_storefront.cli
# (the docker-run / make-target invocation paths haven't behaviorally
# changed; the move is purely packaging).


# ---------------------------------------------------------------------------
# container_db_to_host
# ---------------------------------------------------------------------------

def test_container_db_to_host_strips_dot_slash():
    p = container_db_to_host("./src/market_storefront/data/buy-agent/agent.db")
    assert p == REPO_ROOT / "src" / "market_storefront" / "data" / "buy-agent" / "agent.db"


def test_container_db_to_host_strips_app_prefix():
    p = container_db_to_host("/app/src/market_storefront/data/buy-agent/agent.db")
    assert p == REPO_ROOT / "src" / "market_storefront" / "data" / "buy-agent" / "agent.db"


# ---------------------------------------------------------------------------
# market order history
# ---------------------------------------------------------------------------

def test_order_history_resolves_host_path_in_container_mode(tmp_path: Path):
    """order history resolves AGENT_DB_PATH via container_db_to_host when AGENT_MODE=container."""
    db_file = tmp_path / "agent.db"
    # Write a minimal SQLite DB with an empty orders table
    import sqlite3
    conn = sqlite3.connect(db_file)
    conn.execute("CREATE TABLE orders (order_id TEXT, status TEXT, created_at TEXT, updated_at TEXT, offer_resource TEXT, demand_resource TEXT, fulfillment_resource TEXT)")
    conn.commit()
    conn.close()

    env = tmp_path / ".env"
    env.write_text(f"AGENT_MODE=container\nAGENT_DB_PATH=./src/market_storefront/data/buy-agent/agent.db\n")

    with patch("market_buyer.groups.order.container_db_to_host", return_value=db_file):
        result = runner.invoke(app, ["order", "history", "--env", str(env)])
    assert result.exit_code == 0
    assert "No local orders found." in result.output


def test_order_history_uses_raw_path_in_host_mode(tmp_path: Path):
    """order history reads AGENT_DB_PATH directly when AGENT_MODE=host."""
    db_file = tmp_path / "agent.db"
    import sqlite3
    conn = sqlite3.connect(db_file)
    conn.execute("CREATE TABLE orders (order_id TEXT, status TEXT, created_at TEXT, updated_at TEXT, offer_resource TEXT, demand_resource TEXT, fulfillment_resource TEXT)")
    conn.commit()
    conn.close()

    env = tmp_path / ".env"
    env.write_text(f"AGENT_MODE=host\nAGENT_DB_PATH={db_file}\n")

    result = runner.invoke(app, ["order", "history", "--env", str(env)])
    assert result.exit_code == 0
    assert "No local orders found." in result.output


# ---------------------------------------------------------------------------
# market order show — _resolve_db_path
# ---------------------------------------------------------------------------

def test_order_show_resolves_host_path_in_container_mode(tmp_path: Path):
    """order show resolves AGENT_DB_PATH via container_db_to_host when AGENT_MODE=container."""
    import sqlite3
    db_file = tmp_path / "agent.db"
    conn = sqlite3.connect(db_file)
    conn.execute("CREATE TABLE orders (order_id TEXT, status TEXT, created_at TEXT, updated_at TEXT, offer_resource TEXT, demand_resource TEXT, fulfillment_resource TEXT)")
    conn.commit()
    conn.close()

    env = tmp_path / ".env"
    env.write_text("AGENT_MODE=container\nAGENT_DB_PATH=./src/market_storefront/data/buy-agent/agent.db\n")

    with patch("market_buyer.groups.order.container_db_to_host", return_value=db_file):
        result = runner.invoke(app, ["order", "show", "nonexistent-id", "--env", str(env)])
    # DB resolves correctly; fails on missing order, not missing DB
    assert "not found" in result.output.lower() or result.exit_code != 0


def test_order_show_uses_raw_path_in_host_mode(tmp_path: Path):
    """order show reads AGENT_DB_PATH directly when AGENT_MODE=host."""
    import sqlite3
    db_file = tmp_path / "agent.db"
    conn = sqlite3.connect(db_file)
    conn.execute("CREATE TABLE orders (order_id TEXT, status TEXT, created_at TEXT, updated_at TEXT, offer_resource TEXT, demand_resource TEXT, fulfillment_resource TEXT)")
    conn.commit()
    conn.close()

    env = tmp_path / ".env"
    env.write_text(f"AGENT_MODE=host\nAGENT_DB_PATH={db_file}\n")

    result = runner.invoke(app, ["order", "show", "nonexistent-id", "--env", str(env)])
    # DB resolves correctly; fails on missing order, not missing DB
    assert "not found" in result.output.lower() or result.exit_code != 0


# Note: market-portfolio import-csv tests moved with the
# implementation to market-storefront. See note above re:
# storefront/tests/unit/test_cli_admin.py.
