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
    assert vm.job_submitter._engine is job_engine
    assert bare_metal.operations_service._jobs is job_engine
    assert bare_metal.operations_service._host_service is host_authority
    # The engine resolves each job's host through the same authority.
    assert job_engine._host_lookup == host_authority.lookup


def test_the_host_authority_carries_every_adapter_s_pool_change_hooks():
    host_authority = _container().host_authority()

    assert set(HOST_POOL_CHANGE_HOOKS) <= set(host_authority._pool_change_hooks)


def test_the_bare_metal_release_status_reads_the_one_engine():
    container = _container()

    dispatcher = container.release_job_dispatcher()

    assert dispatcher._jobs["bare_metal"] is container.job_engine()
