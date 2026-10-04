from __future__ import annotations

import pytest
from compute_provisioning import (
    ExecutorAdapterBundle,
    ExecutorAdapterContribution,
    JobExecutorTable,
    compose_adapter_bundles,
)
from market_fulfillment import (
    FulfillmentProvider,
    FulfillmentResult,
    ProviderNotFoundError,
    ProviderOperationState,
    ProviderStatus,
)
from market_core import VersionedEnvelope


class FakeJobExecutor:
    async def execute(self, run):
        raise NotImplementedError

    async def cancel(self, handle):
        return None


class FakeReleaseExecutor:
    async def submit_release(self, reservation):
        return f"release-{reservation['capacity_reservation_id']}"


class FakeProvider(FulfillmentProvider):
    needs_host = True

    def prepare_create(self, *, capacity_reservation_id, request, resource, pool_config):
        return VersionedEnvelope(kind="fake.create", schema_version=1, payload={})

    async def dispatch_create(self, prepared):
        return FulfillmentResult(provider_metadata={})

    def prepare_teardown(self, settlement_result, pool_config):
        return VersionedEnvelope(kind="fake.teardown", schema_version=1, payload={})

    async def dispatch_teardown(self, prepared):
        return FulfillmentResult(provider_metadata={})

    async def get_status(self, capacity_reservation_id, resource, provider_metadata):
        return ProviderStatus(state=ProviderOperationState.succeeded)

    def resolve_provisioned_resources(self, provider_metadata):
        return ()

    async def fetch_credentials(self, provider_metadata, provisioned_resources):
        return VersionedEnvelope(kind="vm.fulfillment.result.v1", schema_version=1, payload={"credentials": []})


class FakePoolConfigHandler:
    def __init__(self, provider: str) -> None:
        self.provider = provider

    def validate_config(self, config):
        return dict(config)

    def validate_config_problems(self, config):
        return dict(config), ()

    def read_config(self, unit_of_work, pool_id):
        return {}

    def read_config_for_execution(self, db, pool_id):
        # No secrets in this fake, so both reads agree. Implemented anyway: the
        # split is part of the protocol, and a fake that provides only half of
        # it would let a caller reach the wrong read without the suite noticing.
        return self.read_config(db, pool_id)

    def replace_config(self, unit_of_work, pool_id, config):
        return None

    def delete_config(self, unit_of_work, pool_id):
        return None


#: The host requirement matching one registered ``FakeProvider`` as ``ansible``.
ANSIBLE_NEEDS_HOST = {"ansible": True}


def contribution(kind: str, *actions: str) -> ExecutorAdapterContribution:
    return ExecutorAdapterContribution(
        offering_mode=kind,
        release_executor=FakeReleaseExecutor(),
        job_executors={action: FakeJobExecutor() for action in actions},
    )


def test_composes_executor_and_provider_namespaces_independently():
    provider = FakeProvider()
    handler = FakePoolConfigHandler("ansible")
    composed = compose_adapter_bundles([
        ExecutorAdapterBundle(
            name="vm",
            executors=(contribution("vm", "create"),),
            fulfillment_providers={"ansible": provider},
            pool_config_handlers={"ansible": handler},
        ),
        ExecutorAdapterBundle(
            name="bare-metal",
            executors=(contribution("bare_metal", "grant_access"),),
        ),
    ], host_requirement=ANSIBLE_NEEDS_HOST, job_executors=JobExecutorTable())

    assert composed.job_executors.resolve("vm", "create")
    assert composed.job_executors.resolve("bare_metal", "grant_access")
    assert composed.provider_registry.require("ansible") is provider
    assert composed.pool_config_handlers["ansible"] is handler
    with pytest.raises(ProviderNotFoundError):
        composed.provider_registry.require("vm")


def test_duplicate_executor_identifies_both_bundles():
    with pytest.raises(ValueError, match="duplicate offering mode 'vm'.*'first'.*'second'"):
        compose_adapter_bundles(
            [
                ExecutorAdapterBundle(
                    name="first",
                    executors=(contribution("vm", "create"),),
                ),
                ExecutorAdapterBundle(
                    name="second",
                    executors=(contribution("vm", "delete"),),
                ),
            ],
            host_requirement=ANSIBLE_NEEDS_HOST,
            job_executors=JobExecutorTable(),
        )


def test_duplicate_provider_identifies_both_bundles_independently_of_executors():
    provider = FakeProvider()
    handler = FakePoolConfigHandler("ansible")
    with pytest.raises(
        ValueError,
        match="duplicate fulfillment provider 'ansible'.*'vm'.*'bare-metal'",
    ):
        compose_adapter_bundles(
            [
                ExecutorAdapterBundle(
                    name="vm",
                    executors=(contribution("vm", "create"),),
                    fulfillment_providers={"ansible": provider},
                    pool_config_handlers={"ansible": handler},
                ),
                ExecutorAdapterBundle(
                    name="bare-metal",
                    executors=(contribution("bare_metal", "grant_access"),),
                    fulfillment_providers={"ansible": provider},
                    pool_config_handlers={"ansible": handler},
                ),
            ],
            host_requirement=ANSIBLE_NEEDS_HOST,
            job_executors=JobExecutorTable(),
        )


def test_provider_without_pool_config_handler_is_rejected_before_startup():
    with pytest.raises(
        ValueError,
        match="missing pool config handler.*'ansible'",
    ):
        compose_adapter_bundles(
            [
                ExecutorAdapterBundle(
                    name="vm",
                    executors=(contribution("vm", "create"),),
                    fulfillment_providers={"ansible": FakeProvider()},
                )
            ],
            host_requirement=ANSIBLE_NEEDS_HOST,
            job_executors=JobExecutorTable(),
        )


def test_handler_identity_must_match_provider_identity():
    with pytest.raises(
        ValueError,
        match="declares provider 'other'",
    ):
        compose_adapter_bundles(
            [
                ExecutorAdapterBundle(
                    name="vm",
                    executors=(contribution("vm", "create"),),
                    fulfillment_providers={"ansible": FakeProvider()},
                    pool_config_handlers={
                        "ansible": FakePoolConfigHandler("other"),
                    },
                )
            ],
            host_requirement=ANSIBLE_NEEDS_HOST,
            job_executors=JobExecutorTable(),
        )


def test_incomplete_executor_contribution_is_rejected_before_startup():
    with pytest.raises(ValueError, match="contributes no job executors"):
        compose_adapter_bundles(
            [
                ExecutorAdapterBundle(
                    name="vm",
                    executors=(contribution("vm"),),
                )
            ],
            host_requirement=ANSIBLE_NEEDS_HOST,
            job_executors=JobExecutorTable(),
        )


def test_duplicate_readiness_check_is_rejected():
    with pytest.raises(ValueError, match="duplicate readiness check 'controller'"):
        compose_adapter_bundles(
            [
                ExecutorAdapterBundle(
                    name="vm",
                    executors=(contribution("vm", "create"),),
                    readiness_checks={"controller": lambda: True},
                ),
                ExecutorAdapterBundle(
                    name="bare-metal",
                    executors=(contribution("bare_metal", "grant_access"),),
                    readiness_checks={"controller": lambda: True},
                ),
            ],
            host_requirement=ANSIBLE_NEEDS_HOST,
            job_executors=JobExecutorTable(),
        )


class UndeclaredProvider(FakeProvider):
    """A provider whose host need is not a bool, so it declares nothing usable."""

    needs_host = None


def _one_provider_bundle(provider) -> ExecutorAdapterBundle:
    return ExecutorAdapterBundle(
        name="vm",
        executors=(contribution("vm", "create"),),
        fulfillment_providers={"ansible": provider},
        pool_config_handlers={"ansible": FakePoolConfigHandler("ansible")},
    )


@pytest.mark.parametrize(
    ("host_requirement", "problem"),
    [
        ({}, "omits registered provider.*'ansible'"),
        (
            {"ansible": True, "k8s": False},
            "names unregistered provider.*'k8s'",
        ),
        ({"ansible": False}, "disagrees with the declaration.*'ansible'"),
    ],
)
def test_a_host_requirement_disagreeing_with_registered_providers_is_refused(
    host_requirement, problem
):
    with pytest.raises(ValueError, match=problem):
        compose_adapter_bundles(
            [_one_provider_bundle(FakeProvider())],
            host_requirement=host_requirement,
            job_executors=JobExecutorTable(),
        )


def test_a_provider_that_declares_no_host_need_is_refused():
    with pytest.raises(ValueError, match="does not declare needs_host"):
        compose_adapter_bundles(
            [_one_provider_bundle(UndeclaredProvider())],
            host_requirement=ANSIBLE_NEEDS_HOST,
            job_executors=JobExecutorTable(),
        )


def _with_jobs(kind: str, actions: tuple[str, ...], executor):
    return ExecutorAdapterContribution(
        offering_mode=kind,
        release_executor=FakeReleaseExecutor(),
        job_executors={action: executor for action in actions},
    )


def test_composition_registers_job_executors_by_mode_and_action_and_freezes():
    vm_executor, bm_executor = FakeJobExecutor(), FakeJobExecutor()
    table = JobExecutorTable()
    composed = compose_adapter_bundles([
        ExecutorAdapterBundle(
            name="vm",
            executors=(_with_jobs("vm", ("create", "destroy"), vm_executor),),
        ),
        ExecutorAdapterBundle(
            name="bare-metal",
            executors=(
                _with_jobs(
                    "bare_metal",
                    ("node_grant_access", "node_reclaim_access"),
                    bm_executor,
                ),
            ),
        ),
    ], host_requirement={}, job_executors=table)

    assert composed.job_executors is table
    assert table.frozen
    assert table.resolve("vm", "destroy") is vm_executor
    assert table.resolve("bare_metal", "node_reclaim_access") is bm_executor


def test_a_non_canonical_offering_mode_is_refused():
    with pytest.raises(ValueError, match="is not canonical"):
        compose_adapter_bundles(
            [ExecutorAdapterBundle(name="vm", executors=(contribution(" vm", "create"),))],
            host_requirement={},
            job_executors=JobExecutorTable(),
        )


def test_a_duplicate_job_executor_names_the_bundle():
    table = JobExecutorTable()
    table.register("vm", "create", FakeJobExecutor())
    with pytest.raises(ValueError, match="adapter bundle 'vm'.*duplicate job executor"):
        compose_adapter_bundles([
            ExecutorAdapterBundle(
                name="vm",
                executors=(_with_jobs("vm", ("create",), FakeJobExecutor()),),
            ),
        ], host_requirement={}, job_executors=table)
