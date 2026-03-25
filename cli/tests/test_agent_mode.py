"""Tests for AGENT_MODE detection and register no-op behaviour."""

from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from market.cli import app
from market.common import read_env_value


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
