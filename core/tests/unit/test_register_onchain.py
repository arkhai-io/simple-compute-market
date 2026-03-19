import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

import core.agent.scripts.register_onchain as register_onchain


IDENTITY_REGISTRY_ADDRESS = "0x0000000000000000000000000000000000000001"
AGENT_WALLET_ADDRESS = "0x0000000000000000000000000000000000000002"


def _set_required_env(monkeypatch):
    monkeypatch.setenv("ZEROTIER_NETWORK", "8056c2e21c000001")
    monkeypatch.setenv("BASE_URL_OVERRIDE", "http://{ZEROTIER_IP}:8000/")
    monkeypatch.setenv("PORT", "8000")
    monkeypatch.setenv("CHAIN_ID", "84532")
    monkeypatch.setenv("IDENTITY_REGISTRY_ADDRESS", IDENTITY_REGISTRY_ADDRESS)
    monkeypatch.setenv("AGENT_WALLET_ADDRESS", AGENT_WALLET_ADDRESS)
    monkeypatch.setenv("CHAIN_RPC_URL", "https://rpc.example")


def test_update_env_file_helpers_round_trip(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("FOO=bar\n")

    assert register_onchain.update_env_file_zerotier_ip(env_file, "100.64.0.9") is True
    assert register_onchain.update_env_file_base_url_override(
        env_file,
        "http://100.64.0.9:8000/",
    ) is True
    assert register_onchain.update_env_file(env_file, 7) is True

    content = env_file.read_text()
    assert "ZEROTIER_IP=100.64.0.9" in content
    assert "BASE_URL_OVERRIDE=http://100.64.0.9:8000/" in content
    assert "ONCHAIN_AGENT_ID=7" in content


def test_main_returns_error_when_zerotier_join_fails(monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("")
    _set_required_env(monkeypatch)

    monkeypatch.setattr(sys, "argv", ["register_onchain.py", "--env-file", str(env_file)])
    monkeypatch.setattr(register_onchain, "join_zerotier_network", lambda network_id: False)
    monkeypatch.setattr(register_onchain, "register_onchain_from_env", AsyncMock())

    result = asyncio.run(register_onchain.main())

    assert result == 1
    register_onchain.register_onchain_from_env.assert_not_called()


def test_main_persists_resolved_zerotier_fields(monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("")
    _set_required_env(monkeypatch)

    monkeypatch.setattr(sys, "argv", ["register_onchain.py", "--env-file", str(env_file)])
    monkeypatch.setattr(register_onchain, "join_zerotier_network", lambda network_id: True)
    monkeypatch.setattr(register_onchain, "get_zerotier_node_id", lambda: "zt-node-123")
    monkeypatch.setattr(
        register_onchain,
        "await_base_url_resolution",
        AsyncMock(return_value="http://100.64.0.9:8000/"),
    )
    monkeypatch.setattr(
        register_onchain,
        "register_onchain_from_env",
        AsyncMock(return_value=("0xabc", 7, {"token_uri_updated": True})),
    )

    result = asyncio.run(register_onchain.main())

    assert result == 0
    content = env_file.read_text()
    assert "ZEROTIER_IP=100.64.0.9" in content
    assert "BASE_URL_OVERRIDE=http://100.64.0.9:8000/" in content
    assert "ONCHAIN_AGENT_ID=7" in content


def test_main_no_update_env_leaves_env_file_untouched(monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    original = "BASE_URL_OVERRIDE=http://{ZEROTIER_IP}:8000/\nKEEP_ME=1\n"
    env_file.write_text(original)
    _set_required_env(monkeypatch)

    monkeypatch.setattr(
        sys,
        "argv",
        ["register_onchain.py", "--env-file", str(env_file), "--no-update-env"],
    )
    monkeypatch.setattr(register_onchain, "join_zerotier_network", lambda network_id: True)
    monkeypatch.setattr(register_onchain, "get_zerotier_node_id", lambda: "zt-node-123")
    monkeypatch.setattr(
        register_onchain,
        "await_base_url_resolution",
        AsyncMock(return_value="http://100.64.0.9:8000/"),
    )
    monkeypatch.setattr(
        register_onchain,
        "register_onchain_from_env",
        AsyncMock(return_value=("0xabc", 7, {"token_uri_updated": True})),
    )

    result = asyncio.run(register_onchain.main())

    assert result == 0
    assert env_file.read_text() == original
