"""The composition root builds one job engine and one host authority.

Both domain runtimes, and everything they build that submits or reads jobs or
looks up hosts, must hold those same instances: a second engine would keep its
own terminal signals and retry schedule, and a second host authority would miss
the other domain's pool-change hooks. Asserted by identity on a real container
whose persistence is an in-memory database.
"""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from market_identity import Ed25519Signer
from compute_provisioning_service.identity import ProvisioningIdentityContext

from compute_provisioning.release import (
    FulfillmentReleaseExecutor,
    FulfillmentReleaseGuard,
    FulfillmentReleaseStatusPort,
)

from compute_provisioning.relays import release_reservation_ports
from compute_provisioning.relays.rebinding import relay_host_pool_change

from compute_provisioning_service.container import Container


def _container() -> Container:
    container = Container()
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    container.session_factory.override(sessionmaker(bind=engine))
    # Public deterministic development principals; never use on a public network.
    container.identity_context.override(ProvisioningIdentityContext(
        signer=Ed25519Signer(bytes([1]) * 32),
        storefront_principal=Ed25519Signer(bytes([2]) * 32).identity,
        admin_principal=Ed25519Signer(bytes([3]) * 32).identity,
        storefront_site_id="fixture-site",
    ))
    return container


def test_one_engine_and_one_host_authority_reach_both_runtimes():
    container = _container()
    job_engine = container.job_engine()
    host_authority = container.host_authority()

    vm = container.vm_runtime()
    bare_metal = container.bare_metal_runtime()

    assert vm.job_engine is job_engine
    assert vm.host_authority is host_authority
    assert vm.job_submission is container.job_submission()
    submission = container.job_submission()
    assert submission._engine is job_engine
    assert submission._hosts is host_authority
    # Both domains' job-backed providers submit through it and read the engine.
    assert vm.fulfillment_provider()._submission is submission
    assert vm.fulfillment_provider()._jobs is job_engine
    assert bare_metal.fulfillment_provider._submission is submission
    assert bare_metal.fulfillment_provider._jobs is job_engine
    # The engine resolves each job's host through the same authority.
    assert job_engine._host_lookup == host_authority.lookup


def test_the_host_authority_carries_the_relays_pool_change_hooks():
    """Both relay checks, the rebinding rule and the management route, over
    the codecs the authority and the relay service share."""
    container = _container()
    host_authority = container.host_authority()

    assert relay_host_pool_change in host_authority._pool_change_hooks
    assert len(host_authority._pool_change_hooks) == 2
    assert len(host_authority._connection_change_hooks) == 1
    assert host_authority._codecs is container.connection_codecs()
    assert container.relay_service()._connection_codecs is container.connection_codecs()


def test_both_pool_configurations_check_hosts_through_the_authoritys_codecs():
    """Pointing a pool at a relay checks its hosts' management routes, so each
    domain's pool configuration holds the codecs the host authority stores
    connections with."""
    container = _container()
    codecs = container.connection_codecs()

    assert container.vm_runtime().pool_config_handler._connection_codecs is codecs
    assert container.bare_metal_runtime().pool_config_handler._connection_codecs is codecs


def test_the_allocator_reads_the_grant_grace_and_the_reuse_margin():
    container = _container()
    container.config.override(
        SimpleNamespace(relay_grant_expiry_grace_seconds=120, relay_port_reuse_margin_seconds=45)
    )
    allocator = container.relay_port_allocator()

    assert allocator._grant_expiry_grace == timedelta(seconds=120)
    assert allocator._reuse_margin == timedelta(seconds=45)


@pytest.mark.parametrize(
    ("grace", "margin", "setting"),
    [
        (-1, 300, "relay_grant_expiry_grace_seconds"),
        (3600, 0, "relay_port_reuse_margin_seconds"),
        (3600, -60, "relay_port_reuse_margin_seconds"),
    ],
)
def test_the_allocator_refuses_a_timing_setting_that_defeats_its_protection(
    grace, margin, setting
):
    container = _container()
    container.config.override(
        SimpleNamespace(
            relay_grant_expiry_grace_seconds=grace, relay_port_reuse_margin_seconds=margin
        )
    )

    with pytest.raises(ValueError, match=setting):
        container.relay_port_allocator()


def test_the_allocator_accepts_no_grace_and_the_smallest_margin():
    """A zero grace still expires a grant no earlier than its lease's end, and
    any positive margin can exceed some skew; both are the operator's call."""
    container = _container()
    container.config.override(
        SimpleNamespace(relay_grant_expiry_grace_seconds=0, relay_port_reuse_margin_seconds=1)
    )
    allocator = container.relay_port_allocator()

    assert allocator._grant_expiry_grace == timedelta(0)
    assert allocator._reuse_margin == timedelta(seconds=1)


def test_the_relays_are_composed_once_for_every_domain():
    """VM's runtime holds the container's one allocator and one execution
    resolver, and the relay release effect, definitions document, and
    reconciliation are each registered once, by the relays rather than by a
    domain."""
    container = _container()
    composed = container.composed_adapters()

    assert container.vm_runtime().relay_port_allocator is container.relay_port_allocator()
    assert container.vm_runtime().codec._relay_resolver is container.relay_execution_resolver()
    bare_metal = container.bare_metal_runtime()
    assert bare_metal.fulfillment_provider._plan._port_allocator is container.relay_port_allocator()
    assert bare_metal.job_executor()._codec._relay_resolver is container.relay_execution_resolver()
    assert container.release_effects()._effects.count(release_reservation_ports) == 1
    assert [d.kind for d in composed.definition_documents] == ["relays"]
    assert [t.name for t in composed.background_tasks] == ["relay-port-reconciliation"]
    assert container.vm_adapter_bundle().release_effects == ()
    assert container.vm_adapter_bundle().definition_documents == ()


def test_both_pool_configuration_handlers_hold_the_services_settings():
    """Each provider's execution read decrypts a relay's token with the
    service's key, so each handler is built over the service's settings."""
    container = _container()
    config = container.config()

    assert container.vm_runtime().pool_config_handler._settings is config
    assert container.bare_metal_runtime().pool_config_handler._settings is config


def test_release_is_composed_once_for_every_offering_mode():
    """The ledger is held to the fulfillment release guard, and the one lease
    lifecycle releases every mode through the fulfillment executor and status
    port, which share the container's teardown port."""
    container = _container()

    ledger = container.capacity_ledger_service()
    executor = container.release_executor()
    status = container.release_status()
    # The lifecycle itself needs the service's signing identity to build, so
    # its wiring is read from its provider rather than resolved here.
    lifecycle_inputs = container.lease_lifecycle_service.kwargs

    assert isinstance(ledger._release_guard, FulfillmentReleaseGuard)
    assert isinstance(executor, FulfillmentReleaseExecutor)
    assert isinstance(status, FulfillmentReleaseStatusPort)
    assert lifecycle_inputs["release_executor"] is container.release_executor
    assert lifecycle_inputs["release_status"] is container.release_status
    assert executor._teardown_port is container.fulfillment_teardown_port()


def test_the_ledger_and_the_scheduler_read_the_host_authoritys_report():
    """Admission, the site's offered read, and scheduling all judge a
    declaration's host by one report of the hosts taking new delivery: the
    host authority, with the same host requirement beside it. A ledger or
    unit of work built without it would accept any named host."""
    container = _container()
    host_authority = container.host_authority()

    ledger = container.capacity_ledger_service()
    unit_of_work = container.scheduling_unit_of_work()
    scheduler = container.physical_settlement_scheduler()

    assert ledger._deliverable_hosts is host_authority
    assert unit_of_work.deliverable_hosts is host_authority
    assert scheduler._unit_of_work is unit_of_work
    assert ledger._host_requirement is scheduler._host_requirement
    assert ledger._host_requirement == container.host_requirement()


def test_the_release_effect_registry_is_the_ledgers_and_composition_fills_it():
    """The ledger runs the registry composition fills; a second registry would
    never be frozen, or would miss the bundles' effects."""
    container = _container()
    effects = container.release_effects()

    ledger = container.capacity_ledger_service()
    container.composed_adapters()

    assert ledger._release_effect is effects
    assert effects.frozen
