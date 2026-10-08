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


class FakeViews:
    """An inventory projection claiming the given views and attributes."""

    def __init__(self, *, resource=(), pool=(), consumed=()):
        self.resource_view_ids = frozenset(resource)
        self.pool_view_ids = frozenset(pool)
        self.consumed_attributes = frozenset(consumed)

    def resource_views(self, declaration, *, pool_id):
        return {view_id: {"pool_id": pool_id} for view_id in self.resource_view_ids}

    def pool_views(self, db, *, pool_id, provider):
        return {}


def _compose_views(first, second):
    return compose_adapter_bundles(
        [
            ExecutorAdapterBundle(
                name="vm",
                executors=(contribution("vm", "create"),),
                inventory_views=(first,),
            ),
            ExecutorAdapterBundle(
                name="bare-metal",
                executors=(contribution("bare_metal", "grant_access"),),
                inventory_views=(second,),
            ),
        ],
        host_requirement={},
        job_executors=JobExecutorTable(),
    )


@pytest.mark.parametrize(
    ("first", "second", "claim"),
    [
        (FakeViews(resource=["x.v1"]), FakeViews(resource=["x.v1"]), "resource view 'x.v1'"),
        (FakeViews(pool=["p.v1"]), FakeViews(pool=["p.v1"]), "pool view 'p.v1'"),
        (FakeViews(consumed=["cfg"]), FakeViews(consumed=["cfg"]), "consumed attribute 'cfg'"),
    ],
)
def test_an_inventory_view_claimed_twice_is_refused(first, second, claim):
    with pytest.raises(ValueError, match=f"duplicate inventory {claim}"):
        _compose_views(first, second)


def test_one_identifier_at_both_attachment_points_is_not_a_conflict():
    composed = _compose_views(FakeViews(resource=["x.v1"]), FakeViews(pool=["x.v1"]))

    assert len(composed.inventory_views.projections) == 2


def test_composed_views_merge_and_refuse_an_undeclared_view():
    composed = _compose_views(
        FakeViews(resource=["a.v1"], consumed=["a"]),
        FakeViews(resource=["b.v1"], consumed=["b"]),
    )
    views = composed.inventory_views

    assert views.consumed_attributes == {"a", "b"}
    assert views.resource_views({}, pool_id="p") == {
        "a.v1": {"pool_id": "p"},
        "b.v1": {"pool_id": "p"},
    }

    class Overreaching(FakeViews):
        def resource_views(self, declaration, *, pool_id):
            return {"other.v1": {}}

    overreaching = _compose_views(Overreaching(resource=["c.v1"]), FakeViews())
    with pytest.raises(ValueError, match="undeclared view"):
        overreaching.inventory_views.resource_views({}, pool_id="p")


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


# ---------------------------------------------------------------------------
# Terminal hooks, definition documents, and background tasks
# ---------------------------------------------------------------------------

from compute_provisioning import (  # noqa: E402
    ComputeProvisioningBackgroundTask,
    DefinitionDocumentContribution,
    ReleaseEffects,
)


def _hook(db, capacity_reservation_id, state):
    return None


def _document(kind: str) -> DefinitionDocumentContribution:
    return DefinitionDocumentContribution(
        kind=kind, label=kind, path=None, apply=lambda db, text: ""
    )


def _task(name: str) -> ComputeProvisioningBackgroundTask:
    async def run():
        return None

    return ComputeProvisioningBackgroundTask(name, run)


def _compose_contributions(*bundles, release_effects=None):
    return compose_adapter_bundles(
        list(bundles),
        host_requirement={},
        job_executors=JobExecutorTable(),
        release_effects=release_effects,
    )


def _bundle(name, mode, **contributions):
    return ExecutorAdapterBundle(
        name=name, executors=(contribution(mode, "act"),), **contributions
    )


def test_contributed_effects_are_registered_and_the_registry_frozen():
    calls = []
    effects = ReleaseEffects()

    def recording(db, capacity_reservation_id, state):
        calls.append(capacity_reservation_id)

    _compose_contributions(
        _bundle("vm", "vm", release_effects=(recording,)),
        release_effects=effects,
    )
    effects(object(), "cr-1", "released")

    assert effects.frozen
    assert calls == ["cr-1"]


def test_a_contributed_effect_with_no_registry_is_refused_rather_than_dropped():
    with pytest.raises(ValueError, match="no registry"):
        _compose_contributions(_bundle("vm", "vm", release_effects=(_hook,)))


def test_documents_and_tasks_are_carried_in_bundle_order():
    composed = _compose_contributions(
        _bundle("vm", "vm", definition_documents=(_document("relays"),),
                background_tasks=(_task("relay-port-reconciliation"),)),
        _bundle("bare-metal", "bare_metal", definition_documents=(_document("machines"),)),
    )

    assert [d.kind for d in composed.definition_documents] == ["relays", "machines"]
    assert [t.name for t in composed.background_tasks] == ["relay-port-reconciliation"]


@pytest.mark.parametrize("kind", ["pools", "capacity"])
def test_a_document_kind_the_service_imports_itself_is_refused(kind):
    with pytest.raises(ValueError, match="service's own definition document kind"):
        _compose_contributions(_bundle("vm", "vm", definition_documents=(_document(kind),)))


def test_a_document_kind_declared_twice_is_refused():
    with pytest.raises(ValueError, match="duplicate definition document kind 'relays'"):
        _compose_contributions(
            _bundle("vm", "vm", definition_documents=(_document("relays"),)),
            _bundle("bare-metal", "bare_metal", definition_documents=(_document("relays"),)),
        )


def test_a_background_task_declared_twice_is_refused():
    with pytest.raises(ValueError, match="duplicate background task 'reconcile'"):
        _compose_contributions(
            _bundle("vm", "vm", background_tasks=(_task("reconcile"),)),
            _bundle("bare-metal", "bare_metal", background_tasks=(_task("reconcile"),)),
        )
