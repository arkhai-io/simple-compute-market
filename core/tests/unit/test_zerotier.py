import asyncio
from unittest.mock import AsyncMock

import pytest

from core.agent.app.utils.zerotier import (
    BaseUrlResolutionError,
    await_base_url_resolution,
    resolve_base_url_best_effort,
)


def test_resolve_base_url_without_token_normalizes_url():
    resolved = resolve_base_url_best_effort("http://agent.example:8000/", None)

    assert resolved == "http://agent.example:8000"


def test_resolve_base_url_with_token_and_available_ip(monkeypatch):
    monkeypatch.setattr(
        "core.agent.app.utils.zerotier.get_zerotier_ip",
        lambda network_id: "100.64.0.9",
    )

    resolved = resolve_base_url_best_effort(
        "http://{ZEROTIER_IP}:8000/",
        "8056c2e21c000001",
    )

    assert resolved == "http://100.64.0.9:8000"


def test_resolve_base_url_with_token_returns_placeholder_when_ip_not_ready(monkeypatch):
    monkeypatch.setattr(
        "core.agent.app.utils.zerotier.get_zerotier_ip",
        lambda network_id: None,
    )

    resolved = resolve_base_url_best_effort(
        "http://{ZEROTIER_IP}:8000/",
        "8056c2e21c000001",
    )

    assert resolved == "http://{ZEROTIER_IP}:8000/"


def test_resolve_base_url_requires_network_when_placeholder_present():
    with pytest.raises(BaseUrlResolutionError, match="ZEROTIER_NETWORK is not set"):
        resolve_base_url_best_effort("http://{ZEROTIER_IP}:8000/", None)


def test_await_base_url_resolution_resolves_after_retry(monkeypatch):
    sleep = AsyncMock()

    ips = iter([None, "100.64.0.9"])
    monkeypatch.setattr(
        "core.agent.app.utils.zerotier.get_zerotier_ip",
        lambda network_id: next(ips),
    )
    monkeypatch.setattr("core.agent.app.utils.zerotier.asyncio.sleep", sleep)

    resolved = asyncio.run(
        await_base_url_resolution(
            "http://{ZEROTIER_IP}:8000/",
            "8056c2e21c000001",
            wait_timeout=1.0,
            initial_interval=0.01,
            max_interval=0.01,
        )
    )

    assert resolved == "http://100.64.0.9:8000"
    sleep.assert_awaited_once()


def test_await_base_url_resolution_times_out_when_ip_never_arrives(monkeypatch):
    monkeypatch.setattr(
        "core.agent.app.utils.zerotier.get_zerotier_ip",
        lambda network_id: None,
    )

    with pytest.raises(BaseUrlResolutionError, match="ZeroTier IP not available"):
        asyncio.run(
            await_base_url_resolution(
                "http://{ZEROTIER_IP}:8000/",
                "8056c2e21c000001",
                wait_timeout=0.0,
            )
        )
