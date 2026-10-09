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


def test_api_credit_app_serves_the_lifecycle_routes():
    paths = {route.path for route in server.app.routes}
    assert {
        "/api/v1/admin/lifecycle/pause",
        "/api/v1/admin/lifecycle/resume",
        "/api/v1/admin/lifecycle/{loop}/run-cycle",
        "/api/v1/admin/lifecycle/{loop}/dry-run",
    } <= paths


@pytest.mark.asyncio
async def test_startup_registers_exactly_the_loops_it_starts_each_with_a_step(monkeypatch):
    import asyncio

    import apicredits_storefront.container as container
    import market_policy.negotiation_thread as negotiation_thread
    from apicredits_storefront import startup
    from apicredits_storefront.lifecycle_steps import register_api_credit_lifecycle_steps
    from apicredits_storefront.services import capacity_client
    from market_storefront_kit import StorefrontLoopController

    domain = get_market_domain_contract()
    loops = StorefrontLoopController()
    register_api_credit_lifecycle_steps(loops)

    class _Worker:
        async def run(self, *, paused=None, wait=None):
            await asyncio.Event().wait()

    async def _noop():
        return None

    async def _poller(controller):
        await asyncio.Event().wait()

    monkeypatch.setattr(container, "resolved_market_domain", domain)
    monkeypatch.setattr(container, "resolved_sqlite_client", object())
    monkeypatch.setattr(container, "resolved_settlement_runtime", None)
    monkeypatch.setattr(container, "resolved_settlement_worker", _Worker())
    monkeypatch.setattr(container, "resolved_loop_controller", loops)
    monkeypatch.setattr(negotiation_thread, "get_thread_store", lambda **_kwargs: None)
    monkeypatch.setattr(startup, "_preflight_credits_service", _noop)
    monkeypatch.setattr(startup, "_seed_demo_listing", _noop)
    monkeypatch.setattr(capacity_client, "capacity_events_poller_loop", _poller)

    try:
        await startup._startup_tasks(domain=domain)
        assert loops.registered_loop_names() == [
            "capacity_events_poller",
            "negotiation_watchdog",
            "settlement_servicing",
        ]
        assert set(loops.step_routes().values()) == set(loops.registered_loop_names())
    finally:
        handles = list(loops._handles.values())
        loops.clear_loops()
        await asyncio.gather(*handles, return_exceptions=True)

def test_every_settlement_route_contract_is_mounted() -> None:
    """The settle, status, and refund routes are mounted where the contract declares them."""
    from storefront_client.settlement_routes import unmounted_settlement_routes

    mounted = [
        (method, route.path)
        for route in server.app.routes
        if getattr(route, "path", None)
        for method in (getattr(route, "methods", None) or ())
    ]

    assert unmounted_settlement_routes(mounted) == []

