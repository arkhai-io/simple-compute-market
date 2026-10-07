"""The composition root builds one job engine and one host authority.

Both domain runtimes, and everything they build that submits or reads jobs or
looks up hosts, must hold those same instances: a second engine would keep its
own terminal signals and retry schedule, and a second host authority would miss
the other domain's pool-change hooks. Asserted by identity on a real container
whose persistence is an in-memory database.
"""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from compute_provisioning.release import (
    FulfillmentReleaseExecutor,
    FulfillmentReleaseGuard,
    FulfillmentReleaseStatusPort,
)

from compute_provisioning_service.container import Container
from vm_provisioning_adapter.runtime import HOST_POOL_CHANGE_HOOKS


def _container() -> Container:
    container = Container()
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    container.session_factory.override(sessionmaker(bind=engine))
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


def test_the_host_authority_carries_every_adapter_s_pool_change_hooks():
    host_authority = _container().host_authority()

    assert set(HOST_POOL_CHANGE_HOOKS) <= set(host_authority._pool_change_hooks)


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


def test_the_release_effect_registry_is_the_ledgers_and_composition_fills_it():
    """The ledger runs the registry composition fills; a second registry would
    never be frozen, or would miss the bundles' effects."""
    container = _container()
    effects = container.release_effects()

    ledger = container.capacity_ledger_service()
    container.composed_adapters()

    assert ledger._release_effect is effects
    assert effects.frozen
