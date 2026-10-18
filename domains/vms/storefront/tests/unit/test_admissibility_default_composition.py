"""The VM composition root parses the configured admissibility default once.

A default it cannot read stops composition before any collaborator is built;
a readable one is the single value the lifespan publishes to its consumers.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

import market_storefront.container as container
from market_storefront import server
from tests._settings_overrides import settings_overrides


def _registration():
    domain = MagicMock(name="domain")
    registry = MagicMock(name="registry")
    registry.resolve_registration.return_value.contract = domain
    return registry, MagicMock(name="binding"), domain


def test_an_unreadable_default_stops_composition_before_anything_is_built():
    registry, binding, domain = _registration()
    with (
        settings_overrides(**{"admissibility.defaults.vm": {"gpu": {"count": {"min": 8, "max": 4}}}}),
        patch.object(server, "get_sqlite_client") as sqlite_client,
        patch.object(server, "resolve_marketplace_signer") as signer,
        patch.object(server, "build_pool_override_service") as overrides,
    ):
        with pytest.raises(RuntimeError, match="admissibility.defaults.vm.gpu.count"):
            server._build_vm_services(registry=registry, binding=binding, domain=domain)

    sqlite_client.assert_not_called()
    signer.assert_not_called()
    overrides.assert_not_called()


async def test_the_lifespan_publishes_the_composed_default_to_the_container():
    declaration = object()
    services = MagicMock(name="services", admissibility_default=declaration)
    seen: list[object] = []

    async def startup_tasks(**_kwargs):
        seen.append(container.resolved_admissibility_default)

    previous_registry = container.resolved_domain_registry
    container.resolved_domain_registry = None
    try:
        with (
            patch.object(server, "initialize_administrator_identities"),
            patch.object(server, "_run_startup_tasks", startup_tasks),
        ):
            await server._start_vm_services(services)
        assert seen == [declaration]
    finally:
        container.clear_lifespan_state(registry=services.registry)
        container.resolved_domain_registry = previous_registry
    assert container.resolved_admissibility_default is None
