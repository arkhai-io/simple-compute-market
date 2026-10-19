from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from types import SimpleNamespace

import pytest
from market_identity import Ed25519Signer

import apicredits_storefront.server as server
from apicredits_storefront.utils import config as storefront_config
from apicredits_storefront.domain_runtime import get_market_domain_contract
from apicredits_storefront.lifecycle_steps import negotiation_watchdog_policy
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
        policy = negotiation_watchdog_policy()

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
@pytest.mark.parametrize("payments", [False, True], ids=["no-payments", "payments"])
async def test_startup_registers_and_starts_every_loop(monkeypatch, payments):
    """Held from the start, so no loop runs a cycle here.

    Startup registers each sweep's timer over the step its route runs and the
    capacity-event pollers' fan-out, and `start_loops` starts them all. Payment
    reconciliation runs only while Arkhai payments is composed.
    """
    import asyncio

    import apicredits_storefront.container as container
    import market_policy.negotiation_thread as negotiation_thread
    from apicredits_storefront import startup
    from apicredits_storefront.lifecycle_steps import (
        api_credit_loop_controller,
        register_api_credit_lifecycle_steps,
    )

    domain = get_market_domain_contract()
    composition = (
        SimpleNamespace(payment_service=lambda _db: object()) if payments else None
    )
    monkeypatch.setattr(container, "resolved_settlement_composition", composition)
    monkeypatch.setattr(container, "resolved_sqlite_client", object())
    loops = api_credit_loop_controller()
    register_api_credit_lifecycle_steps(loops)

    async def _noop():
        return None

    class _HeldFeeds:
        """The quota authority's feeds: one site, held from the start, so its
        poller's one gate read acknowledges the pause."""

        site_ids = ("quota-site",)

        async def poll_events(self, *, interval_seconds, paused=None, wait=None, record=None):
            paused("quota-site")()
            await asyncio.Event().wait()

    monkeypatch.setattr(container, "resolved_market_domain", domain)
    monkeypatch.setattr(container, "resolved_settlement_runtime", None)
    monkeypatch.setattr(container, "resolved_settlement_worker", object())
    monkeypatch.setattr(container, "resolved_loop_controller", loops)
    monkeypatch.setattr(negotiation_thread, "get_thread_store", lambda **_kwargs: None)
    monkeypatch.setattr(startup, "_preflight_credits_service", _noop)
    monkeypatch.setattr(startup, "_seed_demo_listing", _noop)

    timed = {"negotiation_watchdog", "settlement_servicing"}
    if payments:
        timed.add("payment_reconciliation")
    loops.request_pause(True)
    try:
        await startup._startup_tasks(domain=domain, capacity_runtime=_HeldFeeds())
        await asyncio.wait_for(loops.await_quiescence(), timeout=1.0)

        assert set(loops.registered_loop_names()) == {*timed, "capacity_events_poller"}
        assert set(loops.step_routes().values()) == set(loops.registered_loop_names())
        snapshot = loops.snapshot()
        assert {name: snapshot[name].state for name in timed} == dict.fromkeys(
            timed, "paused"
        )
        assert snapshot["capacity_events_poller"].state == "paused"
        assert snapshot["capacity_events_poller:quota-site"].state == "paused"
        assert all(snapshot[name].last_outcome is None for name in timed)
    finally:
        await loops.stop_loops()


def test_the_servicing_interval_is_read_from_its_key():
    """The packaged key sets the worker's interval; the old name is not read."""
    from apicredits_storefront.utils import config

    assert config.settings.get("claims_sweep_interval") is None
    assert config.settlement_servicing_interval() == 30
    with settings_overrides(
        settlement_servicing_interval_seconds=7, claims_sweep_interval=99
    ):
        assert config.settlement_servicing_interval() == 7


@pytest.mark.parametrize("value", [0, -1, "soon", True, 1e11])
def test_an_unusable_servicing_interval_is_refused_by_its_key(value):
    from apicredits_storefront.utils import config

    refusal = r"^\[settlement_servicing_interval_seconds\] "
    with settings_overrides(settlement_servicing_interval_seconds=value):
        with pytest.raises(ValueError, match=refusal) as refused:
            config.settlement_servicing_interval()
    assert refused.value.__context__ is None


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


#: A quota site's principal: a deterministic development key, never used on any
#: network.
_SITE_PRINCIPAL = Ed25519Signer(bytes.fromhex("11" * 32)).identity.model_dump(mode="json")

#: A readable quota site, so a refusal case names only its own problem. A
#: development URL on a reserved domain.
_QUOTA_SITE = {
    "quota-site": {
        "url": "http://quota-site.invalid:8082",
        "expected_authorities": {"identities": [_SITE_PRINCIPAL]},
    }
}


@contextmanager
def _capacity_sites(sites):
    """Replace `[capacity.sites]` whole: an override would merge into the
    configuration's own table, and a restore into the replacement."""
    settings = storefront_config.settings
    saved = deepcopy(settings.get("capacity"))
    try:
        settings.unset("capacity", force=True)
        settings.set("capacity", {**(saved or {}), "sites": sites})
        yield
    finally:
        settings.unset("capacity", force=True)
        if saved is not None:
            settings.set("capacity", saved)


def _refused(monkeypatch, tmp_path, **overrides):
    """The composition's refusal under ``overrides``, and whether it created
    its database file.

    With no signing credential in the environment, resolving the signer -- the
    composition's first collaborator -- would refuse with its own error, so a
    startup refusal comes before it, and so before the database and the
    servicing worker.
    """
    from apicredits_storefront.startup_refusal import StorefrontStartupError

    monkeypatch.delenv("ARKHAI_IDENTITY_CREDENTIAL", raising=False)
    db_path = tmp_path / "agent.db"
    sites = overrides.pop("sites", _QUOTA_SITE)
    with _capacity_sites(sites), settings_overrides(db_path=str(db_path), **overrides):
        with pytest.raises(StorefrontStartupError) as refused:
            server._build_api_credit_services(get_market_domain_contract())
    return refused.value, db_path.exists()


@pytest.mark.parametrize("spelling", ["claims_sweep_interval", "CLAIMS_SWEEP_INTERVAL"])
def test_the_renamed_servicing_interval_refuses_startup_naming_its_replacement(
    monkeypatch, tmp_path, spelling
):
    refusal, created = _refused(monkeypatch, tmp_path, **{spelling: 30})

    assert str(refusal) == (
        "the storefront states retired settings: claims_sweep_interval was renamed "
        "settlement_servicing_interval_seconds; state "
        "settlement_servicing_interval_seconds instead"
    )
    assert not created


def test_authorities_that_are_not_principals_refuse_startup_by_key(monkeypatch, tmp_path):
    """Refused with the other startup refusals, before anything is composed,
    rather than when the capacity pollers first read the site; the refusal
    names the key and not the value, and carries no validation error."""
    unreadable = {
        "quota-site": {
            "url": "http://quota-site.invalid:8082",
            "expected_authorities": {"identities": [{"scheme": "nope", "identifier": "x"}]},
        }
    }
    refusal, created = _refused(monkeypatch, tmp_path, sites=unreadable)

    assert str(refusal) == (
        "the storefront cannot read its capacity configuration: "
        "[capacity.sites.quota-site.expected_authorities] must list one or two valid "
        "principals"
    )
    assert refusal.__context__ is None
    assert not created


def test_no_capacity_site_refuses_startup(monkeypatch, tmp_path):
    refusal, created = _refused(monkeypatch, tmp_path, sites={})

    assert "[capacity.sites]" in str(refusal)
    assert not created


@pytest.mark.parametrize("value", [0, -5, float("nan"), float("inf")])
def test_an_unusable_capacity_poll_interval_refuses_startup_by_key(
    monkeypatch, tmp_path, value
):
    """Refused with the other capacity refusals, before anything is composed,
    rather than handed to the capacity-event pollers; zero is refused, not
    read as the default, and the refusal names the key and not the value."""
    refusal, created = _refused(monkeypatch, tmp_path, capacity__poll_interval=value)

    assert str(refusal) == (
        "the storefront cannot read its capacity configuration: "
        "[capacity.poll_interval] must be a positive, finite number of seconds"
    )
    assert refusal.__context__ is None
    assert not created


def test_the_capacity_poll_interval_is_five_seconds_only_when_unstated():
    from apicredits_storefront.services.capacity_client import capacity_poll_interval

    settings = storefront_config.settings
    saved = deepcopy(settings.get("capacity"))
    try:
        settings.unset("capacity", force=True)
        settings.set("capacity", {key: value for key, value in (saved or {}).items() if key != "poll_interval"})
        assert capacity_poll_interval() == 5
    finally:
        settings.unset("capacity", force=True)
        if saved is not None:
            settings.set("capacity", saved)
    with settings_overrides(capacity__poll_interval=2.5):
        assert capacity_poll_interval() == 2.5


def test_a_configuration_stating_no_renamed_setting_is_not_refused():
    from apicredits_storefront.retired_settings import retired_setting_problems

    assert retired_setting_problems() == []


@pytest.mark.parametrize(
    "key", ["negotiation_timeout_seconds", "negotiation_watchdog_interval"]
)
def test_an_unusable_watchdog_duration_is_refused_by_its_key(key):
    from apicredits_storefront.lifecycle_steps import negotiation_watchdog_policy

    with settings_overrides(**{key: float("nan")}):
        with pytest.raises(ValueError, match=rf"^\[{key}\] "):
            negotiation_watchdog_policy()


def test_an_unusable_payment_reconciliation_interval_refuses_its_registration(monkeypatch):
    import apicredits_storefront.container as container
    from apicredits_storefront.lifecycle_steps import (
        api_credit_loop_controller,
        register_api_credit_loops,
    )

    monkeypatch.setattr(
        container,
        "resolved_settlement_composition",
        SimpleNamespace(payment_service=lambda _db: object()),
    )
    monkeypatch.setattr(container, "resolved_sqlite_client", object())
    with settings_overrides(payment_reconciliation_interval=0):
        with pytest.raises(ValueError, match=r"^\[payment_reconciliation_interval\] "):
            register_api_credit_loops(
                api_credit_loop_controller(), capacity_runtime=SimpleNamespace(site_ids=())
            )
