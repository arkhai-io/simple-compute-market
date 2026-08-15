from __future__ import annotations

from types import SimpleNamespace

import pytest

import apicredits_storefront.server as server
from apicredits_storefront.domain_runtime import get_market_domain_contract
from apicredits_storefront.startup import _negotiation_watchdog_policy
from tests._settings_overrides import settings_overrides


def test_api_credit_routes_use_shared_storefront_shell():
    app = server.app

    assert app.title == "Arkhai API-Credits Storefront"
    assert app.state.storefront_binding.offering_mode == "api_credits"
    paths = {route.path for route in app.routes}
    assert "/health" in paths
    assert "/api/v1/listings" in paths
    assert "/api/v1/negotiate/new" in paths
    assert "/api/v1/settle/{escrow_uid}" in paths


@pytest.mark.asyncio
async def test_api_credit_lifespan_carries_exact_domain_container(monkeypatch):
    domain = get_market_domain_contract()
    container = SimpleNamespace(domain=domain)
    events: list[str] = []

    monkeypatch.setattr(server, "_build_api_credit_services", lambda selected: container)

    async def start(selected):
        assert selected is container
        events.append("start")

    async def stop(selected):
        assert selected is container
        events.append("stop")

    monkeypatch.setattr(server, "_start_api_credit_services", start)
    monkeypatch.setattr(server, "_stop_api_credit_services", stop)
    app = server.build_api_credits_storefront_app(
        registry=server.build_api_credits_storefront_registry(domain=domain)
    )

    async with app.router.lifespan_context(app):
        assert app.state.storefront_container is container
        assert app.state.storefront_container.domain is domain
    assert app.state.storefront_container is None
    assert events == ["start", "stop"]


def test_api_credit_chain_values_are_contributed_to_shared_factory(monkeypatch):
    captured = []
    chain = SimpleNamespace(
        rpc_url="http://rpc",
        alkahest_address_config_path="addresses.json",
    )
    monkeypatch.setattr(server, "CHAINS", {"anvil": chain})
    monkeypatch.setattr(
        server,
        "build_alkahest_clients",
        lambda policy, **_kwargs: captured.append(policy) or {"anvil": object()},
    )

    with settings_overrides(**{"wallet.private_key": "secret"}):
        clients = server._build_alkahest_clients()

    assert tuple(clients) == ("anvil",)
    assert captured[0].chains[0].name == "anvil"
    assert captured[0].chains[0].rpc_url == "http://rpc"


def test_api_credit_watchdog_preserves_configured_schedule():
    with settings_overrides(
        negotiation_timeout_seconds=1800,
        negotiation_watchdog_interval=60,
    ):
        policy = _negotiation_watchdog_policy()

    assert policy.timeout_seconds == 1800
    assert policy.interval_seconds == 60
    assert policy.log_loop_start is False
    assert policy.log_cutoff is False
