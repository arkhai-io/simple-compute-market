"""Tests for AGENT_MODE detection and register no-op behaviour."""

from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from market.cli import app
from market.common import read_env_value, container_db_to_host, REPO_ROOT


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
# market register
# ---------------------------------------------------------------------------

runner = CliRunner()


def test_register_is_noop_when_container_mode(tmp_path: Path):
    env = tmp_path / ".env"
    env.write_text("AGENT_MODE=container\n")
    with patch("market.cli.run_step") as mock_run:
        result = runner.invoke(app, ["register", "--env", str(env)])
    assert result.exit_code == 0
    mock_run.assert_not_called()
    assert "container" in result.output


def test_register_runs_make_when_host_mode(tmp_path: Path):
    env = tmp_path / ".env"
    env.write_text("AGENT_MODE=host\n")
    with patch("market.cli.run_step") as mock_run:
        result = runner.invoke(app, ["register", "--env", str(env)])
    assert result.exit_code == 0
    mock_run.assert_called_once()
    cmd = mock_run.call_args[0][1]
    assert cmd[0] == "make"
    assert "register" in cmd


def test_register_defaults_to_host_when_mode_absent(tmp_path: Path):
    env = tmp_path / ".env"
    env.write_text("PORT=8000\n")
    with patch("market.cli.run_step") as mock_run:
        result = runner.invoke(app, ["register", "--env", str(env)])
    assert result.exit_code == 0
    mock_run.assert_called_once()


# ---------------------------------------------------------------------------
# market start
# ---------------------------------------------------------------------------

def test_start_runs_docker_when_container_mode(tmp_path: Path):
    env = tmp_path / ".env"
    env.write_text("AGENT_MODE=container\nPORT=8001\n")
    with patch("market.cli.run_step") as mock_run:
        result = runner.invoke(app, ["start", "--env", str(env)])
    assert result.exit_code == 0
    mock_run.assert_called_once()
    cmd = mock_run.call_args[0][1]
    assert cmd[0] == "docker"
    assert "run" in cmd
    assert "arkhai:core" in cmd
    assert "-p" in cmd
    assert "8001:8001" in cmd
    assert "--env-file" in cmd


def test_start_runs_make_when_host_mode(tmp_path: Path):
    env = tmp_path / ".env"
    env.write_text("AGENT_MODE=host\n")
    with patch("market.cli.run_step") as mock_run:
        result = runner.invoke(app, ["start", "--env", str(env)])
    assert result.exit_code == 0
    mock_run.assert_called_once()
    cmd = mock_run.call_args[0][1]
    assert cmd[0] == "make"
    assert "serve-a2a" in cmd


def test_start_defaults_to_host_when_mode_absent(tmp_path: Path):
    env = tmp_path / ".env"
    env.write_text("PORT=8000\n")
    with patch("market.cli.run_step") as mock_run:
        result = runner.invoke(app, ["start", "--env", str(env)])
    assert result.exit_code == 0
    cmd = mock_run.call_args[0][1]
    assert cmd[0] == "make"


def test_start_includes_volume_mount_when_db_path_set(tmp_path: Path):
    env = tmp_path / ".env"
    env.write_text("AGENT_MODE=container\nPORT=8000\nAGENT_DB_PATH=./core/agent/app/data/buy-agent/agent.db\n")
    with patch("market.cli.run_step") as mock_run:
        result = runner.invoke(app, ["start", "--env", str(env)])
    assert result.exit_code == 0
    cmd = mock_run.call_args[0][1]
    assert "-v" in cmd
    v_index = cmd.index("-v")
    mount = cmd[v_index + 1]
    host_part, container_part = mount.split(":")
    assert host_part == str(REPO_ROOT / "core" / "agent" / "app" / "data" / "buy-agent")
    assert container_part == "/app/core/agent/app/data/buy-agent"


def test_start_no_volume_mount_when_db_path_absent(tmp_path: Path):
    env = tmp_path / ".env"
    env.write_text("AGENT_MODE=container\nPORT=8000\n")
    with patch("market.cli.run_step") as mock_run:
        result = runner.invoke(app, ["start", "--env", str(env)])
    assert result.exit_code == 0
    cmd = mock_run.call_args[0][1]
    assert "-v" not in cmd


# ---------------------------------------------------------------------------
# container_db_to_host
# ---------------------------------------------------------------------------

def test_container_db_to_host_strips_dot_slash():
    p = container_db_to_host("./core/agent/app/data/buy-agent/agent.db")
    assert p == REPO_ROOT / "core" / "agent" / "app" / "data" / "buy-agent" / "agent.db"


def test_container_db_to_host_strips_app_prefix():
    p = container_db_to_host("/app/core/agent/app/data/buy-agent/agent.db")
    assert p == REPO_ROOT / "core" / "agent" / "app" / "data" / "buy-agent" / "agent.db"


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
    env.write_text(f"AGENT_MODE=container\nAGENT_DB_PATH=./core/agent/app/data/buy-agent/agent.db\n")

    with patch("market.groups.order.container_db_to_host", return_value=db_file):
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
    env.write_text("AGENT_MODE=container\nAGENT_DB_PATH=./core/agent/app/data/buy-agent/agent.db\n")

    with patch("market.groups.order.container_db_to_host", return_value=db_file):
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
