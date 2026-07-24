"""Integration tests for the durable fulfillment-acceptance HTTP surface.

Exercises ``POST /api/v1/fulfillment/{validate,begin}`` end to end: a real
FastAPI app, a real SQLite-backed ``FulfillmentUnitOfWork``, a real
``AnsibleFulfillmentProvider``, and a real ``AsyncJobQueue``-backed
``AnsibleJobService`` (only ``AnsibleService`` itself is mocked, per this
suite's usual boundary). Unlike the unit suites (``kit/fulfillment``'s
orchestration tests, and this service's ``AnsibleFulfillmentProvider`` unit
tests), nothing here is a fake or a mock of the persistence/dispatch path
itself: assertions read the actual persisted ``prepared_create_operation``
and ``provider_metadata`` columns back out of the database after a real
HTTP round trip.

Coverage:
  - ``begin`` persists a versioned, typed prepared-create envelope before
    dispatch, containing every VM create field and the pool's provider
    configuration snapshot.
  - The dispatched Ansible job carries an empty ``deal_ref`` and the
    deterministic ``{capacity_reservation_id}:create`` idempotency key.
  - ``begin`` is idempotent for an equivalent retry: no second job.
  - ``validate`` performs the identical preparation/validation path but
    persists nothing and dispatches nothing.
  - Teardown preparation produces the same shape of typed, versioned input,
    with exact teardown identity derived from the durable create metadata.

What is deliberately NOT covered here: there is no ``/fulfillment/teardown``
HTTP endpoint yet. Dispatching teardown through the durable orchestrator is
Section 10 scope (see ``design.md``, "Section 5 (fulfillment acceptance and
provider preparation) -- resolved design decisions", scope boundary note).
The teardown test below instead drives ``AnsibleFulfillmentProvider``
directly against this fixture's real ``job_service``/session -- the actual
provider-level contract Section 10 will call into -- rather than a
placeholder for HTTP coverage that cannot exist until that endpoint does.
"""

from __future__ import annotations

from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from compute_provisioning_service import container as _container_module
from compute_provisioning_service.main import app
from market_fulfillment import (
    PhysicalSettlementRequest,
    SettlementRepository,
    SettlementResult,
    VersionedEnvelope,
)
from market_resource_pools import PoolCreate, PoolUpdate

_PLAYBOOK_PATH = "playbooks/vm-operations.yaml"
_PROVIDER_CONFIG = {"playbook_path": _PLAYBOOK_PATH, "extra_vars": {"region": "eu"}}


class FulfillmentApi:
    """Typed helper over the fulfillment endpoints (no raw HTTP in tests)."""

    def __init__(self, client: AsyncClient) -> None:
        self._client = client

    async def validate(
        self, capacity_reservation_id: str, market: str, fulfillment_request: dict
    ) -> dict:
        resp = await self._client.post(
            "/api/v1/fulfillment/validate",
            json={
                "capacity_reservation_id": capacity_reservation_id,
                "market": market,
                "fulfillment_request": fulfillment_request,
            },
        )
        assert resp.status_code == 200, resp.text
        return resp.json()

    async def begin(
        self, capacity_reservation_id: str, market: str, fulfillment_request: dict
    ) -> dict:
        resp = await self._client.post(
            "/api/v1/fulfillment/begin",
            json={
                "capacity_reservation_id": capacity_reservation_id,
                "market": market,
                "fulfillment_request": fulfillment_request,
            },
        )
        assert resp.status_code == 200, resp.text
        return resp.json()

    async def get_job(self, job_id: str) -> dict:
        resp = await self._client.get(f"/api/v1/jobs/{job_id}/contract")
        assert resp.status_code == 200, resp.text
        return resp.json()


@pytest.fixture
async def fulfillment(client_and_queue) -> FulfillmentApi:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        yield FulfillmentApi(http)


def _fulfillment_request(**overrides: Any) -> dict:
    payload = {
        "vm_target": "vm-fulfillment-1",
        "vm_ram": 8192,
        "vm_vcpus": 4,
        "vm_disk_size": "80G",
        "vm_os_variant": "ubuntu22.04",
        "ssh_pubkey": "ssh-ed25519 AAAAtest",
    }
    payload.update(overrides)
    return {"kind": "vm.fulfillment.request", "schema_version": 1, "payload": payload}


async def _scheduled_reservation(pool_id: str = "pool-fulfillment-a") -> str:
    """Register a pool + VM resource, reserve capacity, and schedule it.

    Direct service calls, not HTTP: scheduling has no storefront-facing HTTP
    endpoint yet (Section 9 scope), so preconditions this section's task
    list does not own are set up the same way kit/fulfillment's own
    scheduler tests do.
    """
    resource_pool_service = _container_module.resolved_resource_pool_service
    capacity_ledger_service = _container_module.resolved_capacity_ledger_service
    physical_settlement_scheduler = (
        _container_module.resolved_physical_settlement_scheduler
    )

    resource_pool_service.create_pool(
        PoolCreate(
            id=pool_id,
            label=pool_id,
            provider="ansible",
            provider_config=_PROVIDER_CONFIG,
        )
    )
    capacity_ledger_service.register_resource(
        resource_id=f"{pool_id}-r1",
        resource_type="compute.gpu",
        total_units=4,
        pool_id=pool_id,
        attributes={"vm_host": "kvm-fulfillment-1"},
    )
    reserved = capacity_ledger_service.reserve(
        claim={"gpu_count": 1},
        deal_ref={"agreement_id": "agreement-fulfillment-1", "market": "vms"},
    )
    assert reserved is not None
    capacity_reservation_id = reserved["capacity_reservation_id"]

    physical_settlement_scheduler.schedule_resource(
        PhysicalSettlementRequest(
            capacity_reservation_id=capacity_reservation_id, market="vms"
        )
    )
    return capacity_reservation_id


class TestBeginPersistsPreparedCreateInput:
    async def test_persisted_prepared_operation_contains_every_create_field(
        self, fulfillment: FulfillmentApi
    ):
        capacity_reservation_id = await _scheduled_reservation()

        result = await fulfillment.begin(
            capacity_reservation_id, "vms", _fulfillment_request()
        )
        assert result["state"] == "dispatching"

        session_factory = _container_module.resolved_session_factory
        with session_factory() as db:
            record = SettlementRepository().get(db, capacity_reservation_id)
            assert record is not None
            prepared = record.prepared_create_operation
            assert prepared["kind"] == "vm.ansible.create.v1"
            assert prepared["schema_version"] == 1

            operation = prepared["payload"]
            assert operation["capacity_reservation_id"] == capacity_reservation_id
            assert operation["action"] == "create"

            params = operation["parameters"]
            assert params["vm_host"] == "kvm-fulfillment-1"
            assert params["vm_target"] == "vm-fulfillment-1"
            assert params["vm_ram"] == 8192
            assert params["vm_vcpus"] == 4
            assert params["vm_disk_size"] == "80G"
            assert params["vm_os_variant"] == "ubuntu22.04"
            assert params["ssh_pubkey"] == "ssh-ed25519 AAAAtest"
            assert params["escrow_uid"] == capacity_reservation_id
            assert params["playbook_path"] == _PLAYBOOK_PATH
            assert params["provider_extra_vars"] == {"region": "eu"}

            metadata = record.provider_metadata
            assert metadata["vm_host"] == "kvm-fulfillment-1"
            assert metadata["vm_target"] == "vm-fulfillment-1"
            assert metadata["operation"] == "create"
            assert metadata["create_job_id"]

    async def test_dispatched_job_has_empty_deal_ref_and_deterministic_key(
        self, fulfillment: FulfillmentApi
    ):
        capacity_reservation_id = await _scheduled_reservation()

        result = await fulfillment.begin(
            capacity_reservation_id, "vms", _fulfillment_request()
        )

        session_factory = _container_module.resolved_session_factory
        with session_factory() as db:
            record = SettlementRepository().get(db, capacity_reservation_id)
            job_id = record.provider_metadata["create_job_id"]

        job = await fulfillment.get_job(job_id)
        assert job["deal_ref"] == {}
        assert job["idempotency_key"] == f"{capacity_reservation_id}:create"
        assert job["capacity_reservation_id"] == capacity_reservation_id
        assert result["fulfillment_id"]

    async def test_equivalent_retry_does_not_dispatch_a_second_job(
        self, fulfillment: FulfillmentApi
    ):
        capacity_reservation_id = await _scheduled_reservation()
        request = _fulfillment_request()

        first = await fulfillment.begin(capacity_reservation_id, "vms", request)
        second = await fulfillment.begin(capacity_reservation_id, "vms", request)

        assert first["fulfillment_id"] == second["fulfillment_id"]

        session_factory = _container_module.resolved_session_factory
        with session_factory() as db:
            record = SettlementRepository().get(db, capacity_reservation_id)
            first_job_id = record.provider_metadata["create_job_id"]

        # A conflicting retry (different requirements) is rejected rather
        # than silently redispatched or overwriting the accepted request.
        with pytest.raises(AssertionError):
            await fulfillment.begin(
                capacity_reservation_id, "vms", _fulfillment_request(vm_ram=16384)
            )

        with session_factory() as db:
            record = SettlementRepository().get(db, capacity_reservation_id)
            assert record.provider_metadata["create_job_id"] == first_job_id


class TestValidateIsSideEffectFree:
    async def test_validate_persists_and_dispatches_nothing(
        self, fulfillment: FulfillmentApi
    ):
        capacity_reservation_id = await _scheduled_reservation()

        result = await fulfillment.validate(
            capacity_reservation_id, "vms", _fulfillment_request()
        )
        assert result["valid"] is True

        session_factory = _container_module.resolved_session_factory
        with session_factory() as db:
            record = SettlementRepository().get(db, capacity_reservation_id)
            assert record.prepared_create_operation is None
            assert record.fulfillment_id is None
            assert record.state == "assigned"

    async def test_validate_reports_invalid_requirements_without_raising(
        self, fulfillment: FulfillmentApi
    ):
        capacity_reservation_id = await _scheduled_reservation()

        result = await fulfillment.validate(
            capacity_reservation_id,
            "vms",
            _fulfillment_request(vm_ram=-1),
        )
        assert result["valid"] is False
        assert result["issues"]


class TestTeardownPreparation:
    """AnsibleFulfillmentProvider.prepare_teardown/dispatch_teardown, driven
    directly against this fixture's real job_service/session -- see module
    docstring for why there is no HTTP path to exercise yet.
    """

    async def test_prepared_teardown_derives_exact_identity_from_create_metadata(
        self, fulfillment: FulfillmentApi
    ):
        capacity_reservation_id = await _scheduled_reservation("pool-fulfillment-b")
        begin_result = await fulfillment.begin(
            capacity_reservation_id, "vms", _fulfillment_request()
        )

        session_factory = _container_module.resolved_session_factory
        with session_factory() as db:
            record = SettlementRepository().get(db, capacity_reservation_id)
            provider_metadata = dict(record.provider_metadata)
            pool_id = record.pool_id
            settlement_resource_id = record.settlement_resource_id

        resource_pool_service = _container_module.resolved_resource_pool_service
        with session_factory() as db:
            pool = resource_pool_service.get_pool_in_session(db, pool_id)
            pool_config = dict(pool.provider_config)

        from market_fulfillment import SettlementResource
        from vm_provisioning_adapter.services.ansible_fulfillment_provider import (
            AnsibleFulfillmentProvider,
        )

        provider = AnsibleFulfillmentProvider(
            job_service=_container_module.resolved_job_service,
            job_queue_provider=lambda: _container_module.resolved_job_queue,
        )
        settlement_result = SettlementResult(
            capacity_reservation_id=capacity_reservation_id,
            fulfillment_id=begin_result["fulfillment_id"],
            resource=SettlementResource(
                settlement_resource_id=settlement_resource_id,
                pool_id=pool_id,
                resource_kind="compute.gpu",
                provider="ansible",
                attributes={"vm_host": "kvm-fulfillment-1"},
            ),
            provisioned_resources=(),
            provider_metadata=provider_metadata,
        )

        prepared = provider.prepare_teardown(settlement_result, pool_config)
        assert prepared.kind == "vm.ansible.teardown.v1"
        assert prepared.schema_version == 1
        assert prepared.payload["capacity_reservation_id"] == capacity_reservation_id
        assert prepared.payload["action"] == "teardown"
        teardown_params = prepared.payload["parameters"]
        assert teardown_params["vm_host"] == "kvm-fulfillment-1"
        assert teardown_params["vm_target"] == "vm-fulfillment-1"
        assert teardown_params["vm_action"] == "vm_remove"
        assert teardown_params["escrow_uid"] == capacity_reservation_id
        assert teardown_params["playbook_path"] == _PLAYBOOK_PATH

        result = await provider.dispatch_teardown(
            VersionedEnvelope.model_validate(prepared.model_dump(mode="json"))
        )
        teardown_job_id = result.provider_metadata["teardown_job_id"]
        assert teardown_job_id
        assert teardown_job_id != provider_metadata["create_job_id"]

        job = await fulfillment.get_job(teardown_job_id)
        assert job["deal_ref"] == {}
        assert job["idempotency_key"] == f"{capacity_reservation_id}:teardown"


class TestPoolConfigFrozenAtAcceptance:
    """Proves the guarantee `get_pool_in_session` exists to provide: pool
    configuration is frozen into the prepared envelope at acceptance time,
    not re-read live. Without this, a pool edit after acceptance could
    silently change what an already-accepted, already-dispatched fulfillment
    would redispatch with on crash recovery.
    """

    async def test_pool_config_mutation_after_acceptance_does_not_change_persisted_input(
        self, fulfillment: FulfillmentApi
    ):
        pool_id = "pool-fulfillment-mutation"
        capacity_reservation_id = await _scheduled_reservation(pool_id)

        await fulfillment.begin(capacity_reservation_id, "vms", _fulfillment_request())

        session_factory = _container_module.resolved_session_factory
        with session_factory() as db:
            record = SettlementRepository().get(db, capacity_reservation_id)
            frozen_params = record.prepared_create_operation["payload"]["parameters"]
            assert frozen_params["playbook_path"] == _PLAYBOOK_PATH
            assert frozen_params["provider_extra_vars"] == {"region": "eu"}

        # Mutate the pool's live provider configuration after acceptance.
        resource_pool_service = _container_module.resolved_resource_pool_service
        resource_pool_service.update_pool(
            pool_id,
            PoolUpdate(
                provider_config={
                    "playbook_path": "playbooks/mutated-after-acceptance.yaml",
                    "extra_vars": {"region": "us"},
                }
            ),
        )

        # The live pool now shows the mutation...
        with session_factory() as db:
            pool = resource_pool_service.get_pool_in_session(db, pool_id)
            assert pool.provider_config["playbook_path"] == (
                "playbooks/mutated-after-acceptance.yaml"
            )

        # ...but the already-persisted prepared operation does not, because
        # it was frozen into the row at acceptance time rather than kept as
        # a live reference to the pool.
        with session_factory() as db:
            record = SettlementRepository().get(db, capacity_reservation_id)
            unchanged_params = record.prepared_create_operation["payload"]["parameters"]
            assert unchanged_params["playbook_path"] == _PLAYBOOK_PATH
            assert unchanged_params["provider_extra_vars"] == {"region": "eu"}


class TestAcknowledgementFailureRecovery:
    """Proves that if the provider accepts a job but the acknowledgement
    transaction (transaction 2) fails before recording it, a subsequent
    retry rediscovers the same job through the deterministic idempotency
    key rather than dispatching a duplicate -- the crash window this
    section's two-transaction design deliberately accepts, per design.md's
    "Accepted Section 5 lifecycle clarifications".
    """

    async def test_retry_after_failed_acknowledgement_reuses_the_same_job(
        self, fulfillment: FulfillmentApi
    ):
        from market_fulfillment import FulfillmentOrchestrator, ProviderRegistry
        from market_fulfillment.fulfillment_persistence import (
            SqlAlchemyFulfillmentTransaction,
            SqlAlchemyFulfillmentUnitOfWork,
        )

        capacity_reservation_id = await _scheduled_reservation(
            "pool-fulfillment-ack-failure"
        )

        attempts = {"count": 0}

        class FaultyOnceTransaction(SqlAlchemyFulfillmentTransaction):
            def acknowledge_create(self, *args, **kwargs):
                attempts["count"] += 1
                if attempts["count"] == 1:
                    raise RuntimeError("simulated acknowledgement failure")
                return super().acknowledge_create(*args, **kwargs)

        from vm_provisioning_adapter.services.ansible_fulfillment_provider import (
            AnsibleFulfillmentProvider,
        )

        session_factory = _container_module.resolved_session_factory
        resource_pool_service = _container_module.resolved_resource_pool_service
        provider = AnsibleFulfillmentProvider(
            job_service=_container_module.resolved_job_service,
            job_queue_provider=lambda: _container_module.resolved_job_queue,
        )
        faulty_orchestrator = FulfillmentOrchestrator(
            provider_registry=ProviderRegistry({"ansible": provider}),
            unit_of_work=SqlAlchemyFulfillmentUnitOfWork(
                session_factory=session_factory,
                pool_service=resource_pool_service,
                transaction_type=FaultyOnceTransaction,
            ),
        )
        request = VersionedEnvelope.model_validate(_fulfillment_request())

        with pytest.raises(RuntimeError, match="simulated acknowledgement failure"):
            await faulty_orchestrator.begin_fulfillment(
                capacity_reservation_id, "vms", request
            )

        with session_factory() as db:
            record = SettlementRepository().get(db, capacity_reservation_id)
            assert record.state == "dispatch_pending"
            assert dict(record.provider_metadata or {}) == {}
            assert record.prepared_create_operation is not None

        # Retry: acknowledgement now succeeds, and the provider redispatches
        # the persisted prepared operation with the same idempotency key.
        result = await faulty_orchestrator.begin_fulfillment(
            capacity_reservation_id, "vms", request
        )
        assert result.state == "dispatching"

        with session_factory() as db:
            record = SettlementRepository().get(db, capacity_reservation_id)
            job_id = record.provider_metadata["create_job_id"]

            from compute_provisioning_service.db.models import AnsibleJob

            jobs = (
                db.query(AnsibleJob)
                .filter(
                    AnsibleJob.capacity_reservation_id == capacity_reservation_id,
                    AnsibleJob.action_kind == "create",
                )
                .all()
            )
            assert len(jobs) == 1
            assert jobs[0].id == job_id
