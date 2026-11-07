"""Focused tests for durable fulfillment orchestration."""

from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from market_fulfillment import (
    CREATE_COMPENSATION,
    FULFILLMENT_RESULT_KIND,
    CompensationCandidate,
    CompensationRefusedError,
    CredentialFetchFailedError,
    FulfillmentConflictError,
    FulfillmentCreateFailedError,
    FulfillmentOrchestrator,
    FulfillmentResult,
    ProviderConfigInvalidError,
    ProviderRegistry,
    ProviderUnavailableError,
    SettlementEntityNotFoundError,
    SettlementRecordState,
)
from market_core import VersionedEnvelope
from market_fulfillment.fulfillment_persistence import FulfillmentAcceptanceDecision


def _request() -> VersionedEnvelope[dict]:
    return VersionedEnvelope(
        kind="vm.fulfillment.request",
        schema_version=1,
        payload={"vm_target": "vm-1"},
    )


def _record(**overrides):
    values = {
        "fulfillment_id": "fulfillment-1",
        "capacity_reservation_id": "reservation-1",
        "state": SettlementRecordState.dispatch_pending.value,
        "market": "compute",
        "pool_id": "pool-1",
        "provider": "ansible",
        "settlement_resource_id": "resource-1",
        "resource_attributes": {},
        "resource_host_id": "host-1",
        "scheduling_requirements": {"offering_mode": "vm", "resource_kind": "vm"},
        "prepared_create_operation": None,
        "prepared_teardown_operation": None,
        "provider_metadata": {},
        "failure_reason": None,
        "failure_message": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class FakeTransaction:
    def __init__(self, record, *, dispatch_required=True, provisioned_resources=None):
        self.record = record
        self.db = MagicMock()
        self.db.get.return_value = record
        self.pool = SimpleNamespace(
            provider_config={"playbook_path": "playbook.yml"},
            policy_tags={"advertisable_modes": ["vm"], "capacity_backing": "backed", "deliverable_modes": ["vm"]},
        )
        self.dispatch_required = dispatch_required
        self.persisted = []
        self.acknowledged = []
        self.attached_jobs = []
        self.write_reads = []
        self.provisioned_resources = provisioned_resources or []

    def accept(self, **kwargs):
        return FulfillmentAcceptanceDecision(
            record=self.record,
            newly_accepted=True,
            dispatch_required=self.dispatch_required,
        )

    def get_pool(self, pool_id):
        return self.pool

    def persist_prepared_create(self, capacity_reservation_id, prepared):
        self.persisted.append(prepared)
        self.record.prepared_create_operation = prepared.model_dump(mode="json")
        return self.record

    def acknowledge_create(self, capacity_reservation_id, provider_metadata):
        self.acknowledged.append(provider_metadata)
        self.record.provider_metadata = provider_metadata
        self.record.state = SettlementRecordState.dispatching.value
        return self.record

    def attach_executor_job(self, capacity_reservation_id, job_id):
        self.attached_jobs.append((capacity_reservation_id, job_id))

    def begin_teardown(self, fulfillment_id, prepared):
        self.teardown_prepared = prepared
        self.record.prepared_teardown_operation = prepared.model_dump(mode="json")
        self.record.state = SettlementRecordState.teardown_dispatch_pending.value
        return self.record

    def begin_compensating_teardown(self, fulfillment_id, prepared):
        self.compensation_prepared = prepared
        self.record.prepared_teardown_operation = prepared.model_dump(mode="json")
        self.record.state = SettlementRecordState.teardown_dispatch_pending.value
        self.record.failure_reason = CREATE_COMPENSATION
        return self.record

    def get_by_fulfillment_id(self, fulfillment_id):
        if self.record.fulfillment_id == fulfillment_id:
            return self.record
        return None

    def get_by_fulfillment_id_for_write(self, fulfillment_id):
        self.write_reads.append(fulfillment_id)
        return self.get_by_fulfillment_id(fulfillment_id)

    def list_provisioned_resources(self, capacity_reservation_id):
        if capacity_reservation_id == self.record.capacity_reservation_id:
            return self.provisioned_resources
        return []


class FakeUnitOfWork:
    def __init__(self, *transactions):
        self.transactions = list(transactions)
        self.write_entries = 0
        self.read_entries = 0
        self.read_transaction_open = False

    @contextmanager
    def transaction(self):
        self.write_entries += 1
        yield self.transactions.pop(0)

    @contextmanager
    def read_transaction(self):
        self.read_entries += 1
        self.read_transaction_open = True
        try:
            yield self.transactions.pop(0)
        finally:
            self.read_transaction_open = False


class _ProviderMock(MagicMock):
    """A mock provider that, like every real one, declares its host need."""

    needs_host = True


def _provider():
    provider = _ProviderMock()
    # Explicit, because a bare MagicMock returns a truthy Mock for any
    # attribute: the orchestrator would then try to attach that object as a
    # job id. Providers without an addressable job handle return None, and
    # that is the default this fake should represent.
    provider.resolve_executor_job_id.return_value = None
    provider.prepare_create.return_value = VersionedEnvelope(
        kind="vm.ansible.create.v1",
        schema_version=1,
        payload={"prepared": True},
    )
    provider.dispatch_create = AsyncMock(
        return_value=FulfillmentResult({"job_id": "job-1"})
    )
    provider.prepare_teardown.return_value = VersionedEnvelope(
        kind="vm.ansible.teardown.v1",
        schema_version=1,
        payload={"prepared": "teardown"},
    )
    provider.fetch_credentials = AsyncMock(
        return_value=VersionedEnvelope(
            kind="vm.fulfillment.result.v1",
            schema_version=1,
            payload={
                "credentials": [
                    {
                        "role": "tenant",
                        "password": "s3cr3t",
                        "ssh_commands": {"external": "ssh tenant@host"},
                        "provisioned_resource_ids": ["provisioned-1", "provisioned-2"],
                    }
                ]
            },
        )
    )
    return provider


def _orchestrator(uow, provider):
    return FulfillmentOrchestrator(
        provider_registry=ProviderRegistry({"ansible": provider}),
        unit_of_work=uow,
    )


def test_validate_uses_read_transaction_and_shared_preparation_path():
    tx = FakeTransaction(_record())
    provider = _provider()
    uow = FakeUnitOfWork(tx)

    result = _orchestrator(uow, provider).validate_fulfillment(
        "reservation-1", "compute", _request()
    )

    assert result.valid
    assert uow.read_entries == 1
    assert uow.write_entries == 0
    provider.prepare_create.assert_called_once()
    assert provider.prepare_create.call_args.kwargs["capacity_reservation_id"] == "reservation-1"

@pytest.mark.asyncio
async def test_withdrawn_pool_mode_blocks_prepared_dispatch_before_provider_io():
    prepared = VersionedEnvelope(
        kind="vm.ansible.create.v1",
        schema_version=1,
        payload={"prepared": True},
    )
    record = _record(prepared_create_operation=prepared.model_dump(mode="json"))
    tx = FakeTransaction(record)
    tx.pool.policy_tags = {"deliverable_modes": []}
    provider = _provider()

    with pytest.raises(
        FulfillmentConflictError,
        match="does not declare offering mode 'vm'",
    ):
        await _orchestrator(FakeUnitOfWork(tx), provider).begin_fulfillment(
            "reservation-1",
            "compute",
            _request(),
        )

    provider.dispatch_create.assert_not_called()


def _provisioned_resource(**overrides):
    values = {
        "provisioned_resource_id": "provisioned-1",
        "status": "active",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_get_fulfillment_status_reads_without_any_provider_call():
    record = _record(state=SettlementRecordState.active.value)
    tx = FakeTransaction(record)
    provider = _provider()
    uow = FakeUnitOfWork(tx)

    result = _orchestrator(uow, provider).get_fulfillment_status("fulfillment-1")

    assert result.fulfillment_id == "fulfillment-1"
    assert result.capacity_reservation_id == "reservation-1"
    assert result.state == SettlementRecordState.active.value
    assert result.failure_reason is None
    assert uow.read_entries == 1
    assert uow.write_entries == 0
    provider.prepare_create.assert_not_called()
    provider.dispatch_create.assert_not_called()



def test_get_fulfillment_status_repeated_reads_are_stable_and_provider_free():
    record = _record(state=SettlementRecordState.active.value)
    provider = _provider()
    uow = FakeUnitOfWork(FakeTransaction(record), FakeTransaction(record))
    orchestrator = _orchestrator(uow, provider)

    first = orchestrator.get_fulfillment_status("fulfillment-1")
    second = orchestrator.get_fulfillment_status("fulfillment-1")

    assert first == second
    assert uow.read_entries == 2
    assert uow.write_entries == 0
    provider.fetch_credentials.assert_not_called()


def test_get_fulfillment_status_reports_failure_detail():
    record = _record(
        state=SettlementRecordState.failed.value,
        failure_reason="create_failed",
        failure_message="provider reported a create failure",
    )
    uow = FakeUnitOfWork(FakeTransaction(record))

    result = _orchestrator(uow, _provider()).get_fulfillment_status("fulfillment-1")

    assert result.state == SettlementRecordState.failed.value
    assert result.failure_reason == "create_failed"
    assert result.failure_message == "provider reported a create failure"


def test_get_fulfillment_status_unknown_id_raises_not_found():
    uow = FakeUnitOfWork(FakeTransaction(_record()))

    with pytest.raises(SettlementEntityNotFoundError):
        _orchestrator(uow, _provider()).get_fulfillment_status("no-such-fulfillment")


@pytest.mark.asyncio
async def test_begin_fulfillment_teardown_prepares_and_queues_a_native_active_fulfillment():
    record = _record(
        state=SettlementRecordState.active.value,
        provider_metadata={"current_job_id": "job-1"},
    )
    tx = FakeTransaction(record)
    provider = _provider()
    uow = FakeUnitOfWork(tx)

    acceptance = await _orchestrator(uow, provider).begin_fulfillment_teardown(
        "fulfillment-1"
    )

    provider.prepare_teardown.assert_called_once()
    settlement_result = provider.prepare_teardown.call_args.args[0]
    assert settlement_result.capacity_reservation_id == "reservation-1"
    assert settlement_result.fulfillment_id == "fulfillment-1"
    assert settlement_result.provider_metadata == {"current_job_id": "job-1"}
    assert tx.teardown_prepared.payload == {"prepared": "teardown"}
    assert acceptance.state == SettlementRecordState.teardown_dispatch_pending.value
    assert record.prepared_teardown_operation == {
        "kind": "vm.ansible.teardown.v1",
        "schema_version": 1,
        "payload": {"prepared": "teardown"},
    }


@pytest.mark.asyncio
async def test_begin_fulfillment_teardown_reuses_an_already_prepared_operation():
    """A backfilled row already carries prepared_teardown_operation.

    ``begin_fulfillment_teardown`` must not re-prepare it -- re-preparing
    would call the provider with a live pool-config read instead of
    dispatching from what was frozen at backfill time, breaking the same
    "dispatch from what was accepted" invariant create-side preparation
    already honors.
    """

    already_prepared = {
        "kind": "vm.ansible.teardown.v1",
        "schema_version": 1,
        "payload": {"prepared": "from-backfill"},
    }
    record = _record(
        state=SettlementRecordState.active.value,
        prepared_teardown_operation=already_prepared,
    )
    tx = FakeTransaction(record)
    provider = _provider()
    uow = FakeUnitOfWork(tx)

    acceptance = await _orchestrator(uow, provider).begin_fulfillment_teardown(
        "fulfillment-1"
    )

    provider.prepare_teardown.assert_not_called()
    assert tx.teardown_prepared.payload == {"prepared": "from-backfill"}
    assert acceptance.state == SettlementRecordState.teardown_dispatch_pending.value


@pytest.mark.parametrize(
    "state",
    [
        SettlementRecordState.teardown_dispatch_pending.value,
        SettlementRecordState.tearing_down.value,
        SettlementRecordState.torn_down.value,
        SettlementRecordState.teardown_failed.value,
    ],
)
@pytest.mark.asyncio
async def test_begin_fulfillment_teardown_is_idempotent_once_already_initiated(state):
    record = _record(state=state)
    tx = FakeTransaction(record)
    provider = _provider()
    uow = FakeUnitOfWork(tx)

    acceptance = await _orchestrator(uow, provider).begin_fulfillment_teardown(
        "fulfillment-1"
    )

    assert acceptance.state == state
    provider.prepare_teardown.assert_not_called()


@pytest.mark.parametrize(
    "state",
    [
        SettlementRecordState.assigned.value,
        SettlementRecordState.dispatch_pending.value,
        SettlementRecordState.dispatching.value,
        SettlementRecordState.failed.value,
        SettlementRecordState.abandoned.value,
    ],
)
@pytest.mark.asyncio
async def test_begin_fulfillment_teardown_rejects_non_active_source_state(state):
    record = _record(state=state)
    uow = FakeUnitOfWork(FakeTransaction(record))

    with pytest.raises(FulfillmentConflictError):
        await _orchestrator(uow, _provider()).begin_fulfillment_teardown(
            "fulfillment-1"
        )


@pytest.mark.asyncio
async def test_begin_fulfillment_teardown_unknown_id_raises_not_found():
    uow = FakeUnitOfWork(FakeTransaction(_record()))

    with pytest.raises(SettlementEntityNotFoundError):
        await _orchestrator(uow, _provider()).begin_fulfillment_teardown(
            "no-such-fulfillment"
        )


def _failed_record(**overrides):
    values = {
        "state": SettlementRecordState.failed.value,
        "failure_reason": "provider_reported_failure",
        "failure_message": "create reported no delivery evidence",
        "provider_metadata": {"operation": "create", "job_id": "job-1"},
    }
    values.update(overrides)
    return _record(**values)


def _authorize_all(candidate):
    return True


def _assert_nothing_written(tx, record, before):
    assert not hasattr(tx, "compensation_prepared")
    assert not hasattr(tx, "teardown_prepared")
    assert vars(record) == before


@pytest.mark.asyncio
async def test_compensating_teardown_queues_an_authorized_failed_create():
    record = _failed_record()
    tx = FakeTransaction(record)
    provider = _provider()

    acceptance = await _orchestrator(
        FakeUnitOfWork(tx), provider
    ).begin_compensating_teardown("fulfillment-1", authorize=_authorize_all)

    assert tx.write_reads == ["fulfillment-1"]
    provider.prepare_teardown.assert_called_once()
    settlement_result, pool_config = provider.prepare_teardown.call_args.args
    assert settlement_result.fulfillment_id == "fulfillment-1"
    assert settlement_result.provider_metadata == {
        "operation": "create",
        "job_id": "job-1",
    }
    assert pool_config == {"playbook_path": "playbook.yml"}
    assert tx.compensation_prepared.payload == {"prepared": "teardown"}
    assert acceptance.state == SettlementRecordState.teardown_dispatch_pending.value
    assert record.failure_reason == CREATE_COMPENSATION
    assert record.failure_message == "create reported no delivery evidence"


@pytest.mark.asyncio
async def test_compensating_teardown_gives_authorize_the_records_fields():
    record = _failed_record()
    seen = []

    def authorize(candidate):
        seen.append(candidate)
        return True

    await _orchestrator(
        FakeUnitOfWork(FakeTransaction(record)), _provider()
    ).begin_compensating_teardown("fulfillment-1", authorize=authorize)

    assert len(seen) == 1
    candidate = seen[0]
    assert isinstance(candidate, CompensationCandidate)
    assert candidate.state == SettlementRecordState.failed.value
    assert candidate.failure_reason == "provider_reported_failure"
    assert dict(candidate.provider_metadata) == {
        "operation": "create",
        "job_id": "job-1",
    }
    with pytest.raises(TypeError):
        candidate.provider_metadata["operation"] = "teardown"


@pytest.mark.asyncio
async def test_compensating_teardown_refused_by_authorize_writes_nothing():
    record = _failed_record()
    before = dict(vars(record))
    tx = FakeTransaction(record)
    provider = _provider()

    with pytest.raises(CompensationRefusedError) as raised:
        await _orchestrator(
            FakeUnitOfWork(tx), provider
        ).begin_compensating_teardown("fulfillment-1", authorize=lambda _: False)

    assert isinstance(raised.value, FulfillmentConflictError)
    provider.prepare_teardown.assert_not_called()
    _assert_nothing_written(tx, record, before)


def _nested_metadata():
    return {
        "operation": "create",
        "job_id": "job-1",
        "target": {"host_id": "host-1", "labels": ["a"]},
    }


def _mutate_nested(candidate):
    candidate.provider_metadata["target"]["host_id"] = "host-2"
    candidate.provider_metadata["target"]["labels"].append("b")


@pytest.mark.asyncio
async def test_a_refusing_authorize_cannot_change_the_records_nested_metadata():
    record = _failed_record(provider_metadata=_nested_metadata())
    tx = FakeTransaction(record)
    provider = _provider()

    def authorize(candidate):
        _mutate_nested(candidate)
        return False

    with pytest.raises(CompensationRefusedError):
        await _orchestrator(
            FakeUnitOfWork(tx), provider
        ).begin_compensating_teardown("fulfillment-1", authorize=authorize)

    assert record.provider_metadata == _nested_metadata()
    assert record.state == SettlementRecordState.failed.value
    assert record.failure_reason == "provider_reported_failure"
    assert record.prepared_teardown_operation is None
    assert not hasattr(tx, "compensation_prepared")
    provider.prepare_teardown.assert_not_called()


@pytest.mark.asyncio
async def test_an_authorizing_callbacks_nested_mutation_never_reaches_preparation():
    record = _failed_record(provider_metadata=_nested_metadata())
    provider = _provider()

    def authorize(candidate):
        _mutate_nested(candidate)
        return True

    await _orchestrator(
        FakeUnitOfWork(FakeTransaction(record)), provider
    ).begin_compensating_teardown("fulfillment-1", authorize=authorize)

    assert record.provider_metadata == _nested_metadata()
    settlement_result = provider.prepare_teardown.call_args.args[0]
    assert settlement_result.provider_metadata == _nested_metadata()


@pytest.mark.asyncio
async def test_compensating_teardown_the_provider_cannot_prepare_is_refused():
    record = _failed_record()
    before = dict(vars(record))
    tx = FakeTransaction(record)
    provider = _provider()
    provider.prepare_teardown.side_effect = ProviderConfigInvalidError(
        "create job job-1 not found"
    )

    with pytest.raises(CompensationRefusedError, match="create job job-1 not found"):
        await _orchestrator(
            FakeUnitOfWork(tx), provider
        ).begin_compensating_teardown("fulfillment-1", authorize=_authorize_all)

    _assert_nothing_written(tx, record, before)


@pytest.mark.asyncio
async def test_compensating_teardown_propagates_any_other_preparation_error():
    record = _failed_record()
    before = dict(vars(record))
    tx = FakeTransaction(record)
    provider = _provider()
    provider.prepare_teardown.side_effect = ProviderUnavailableError("job store down")

    with pytest.raises(ProviderUnavailableError):
        await _orchestrator(
            FakeUnitOfWork(tx), provider
        ).begin_compensating_teardown("fulfillment-1", authorize=_authorize_all)

    _assert_nothing_written(tx, record, before)


@pytest.mark.parametrize(
    "state",
    [
        SettlementRecordState.teardown_dispatch_pending.value,
        SettlementRecordState.tearing_down.value,
        SettlementRecordState.torn_down.value,
        SettlementRecordState.teardown_failed.value,
    ],
)
@pytest.mark.asyncio
async def test_compensating_teardown_adopts_a_begun_teardown(state):
    record = _failed_record(state=state, failure_reason=CREATE_COMPENSATION)
    before = dict(vars(record))
    tx = FakeTransaction(record)
    provider = _provider()
    authorize = MagicMock(return_value=True)

    acceptance = await _orchestrator(
        FakeUnitOfWork(tx), provider
    ).begin_compensating_teardown("fulfillment-1", authorize=authorize)

    assert acceptance.state == state
    authorize.assert_not_called()
    provider.prepare_teardown.assert_not_called()
    _assert_nothing_written(tx, record, before)


@pytest.mark.parametrize(
    "state",
    [
        SettlementRecordState.assigned.value,
        SettlementRecordState.dispatch_pending.value,
        SettlementRecordState.dispatching.value,
        SettlementRecordState.active.value,
        SettlementRecordState.abandoned.value,
    ],
)
@pytest.mark.asyncio
async def test_compensating_teardown_refuses_any_other_state(state):
    record = _failed_record(state=state)
    before = dict(vars(record))
    tx = FakeTransaction(record)
    provider = _provider()
    authorize = MagicMock(return_value=True)

    with pytest.raises(FulfillmentConflictError) as raised:
        await _orchestrator(
            FakeUnitOfWork(tx), provider
        ).begin_compensating_teardown("fulfillment-1", authorize=authorize)

    assert not isinstance(raised.value, CompensationRefusedError)
    authorize.assert_not_called()
    provider.prepare_teardown.assert_not_called()
    _assert_nothing_written(tx, record, before)


@pytest.mark.asyncio
async def test_compensating_teardown_unknown_id_raises_not_found():
    uow = FakeUnitOfWork(FakeTransaction(_failed_record()))

    with pytest.raises(SettlementEntityNotFoundError):
        await _orchestrator(uow, _provider()).begin_compensating_teardown(
            "no-such-fulfillment", authorize=_authorize_all
        )


@pytest.mark.asyncio
async def test_get_fulfillment_result_active_state_includes_provisioned_resources_and_credentials():
    record = _record(
        state=SettlementRecordState.active.value,
        provider_metadata={"current_job_id": "job-1"},
    )
    outputs = [_provisioned_resource(), _provisioned_resource(
        provisioned_resource_id="provisioned-2"
    )]
    tx = FakeTransaction(record, provisioned_resources=outputs)
    provider = _provider()
    uow = FakeUnitOfWork(tx)

    envelope = await _orchestrator(uow, provider).get_fulfillment_result("fulfillment-1")

    assert envelope.kind == FULFILLMENT_RESULT_KIND
    assert envelope.schema_version == 1
    payload = envelope.payload
    assert payload["fulfillment_id"] == "fulfillment-1"
    assert payload["state"] == SettlementRecordState.active.value
    assert [r["provisioned_resource_id"] for r in payload["provisioned_resources"]] == [
        "provisioned-1",
        "provisioned-2",
    ]
    assert payload["domain_result"]["kind"] == "vm.fulfillment.result.v1"
    assert payload["domain_result"]["payload"]["credentials"][0]["provisioned_resource_ids"] == [
        "provisioned-1",
        "provisioned-2",
    ]
    provider.fetch_credentials.assert_called_once()
    assert provider.fetch_credentials.call_args.args[0] == {"current_job_id": "job-1"}
    provider.prepare_create.assert_not_called()



@pytest.mark.asyncio
async def test_get_fulfillment_result_preserves_many_to_many_domain_associations():
    record = _record(
        state=SettlementRecordState.active.value,
        provider_metadata={"current_job_id": "job-1"},
    )
    outputs = [
        _provisioned_resource(provisioned_resource_id="provisioned-1"),
        _provisioned_resource(provisioned_resource_id="provisioned-2"),
    ]
    provider = _provider()
    provider.fetch_credentials = AsyncMock(
        return_value=VersionedEnvelope(
            kind="vm.fulfillment.result.v1",
            schema_version=1,
            payload={
                "credentials": [
                    {
                        "role": "shared-admin",
                        "provisioned_resource_ids": ["provisioned-1", "provisioned-2"],
                    },
                    {
                        "role": "tenant",
                        "provisioned_resource_ids": ["provisioned-2"],
                    },
                ]
            },
        )
    )
    envelope = await _orchestrator(
        FakeUnitOfWork(FakeTransaction(record, provisioned_resources=outputs)), provider
    ).get_fulfillment_result("fulfillment-1")

    credentials = envelope.payload["domain_result"]["payload"]["credentials"]
    assert credentials[0]["provisioned_resource_ids"] == ["provisioned-1", "provisioned-2"]
    assert credentials[1]["provisioned_resource_ids"] == ["provisioned-2"]


@pytest.mark.parametrize(
    "state",
    [
        SettlementRecordState.assigned.value,
        SettlementRecordState.dispatch_pending.value,
        SettlementRecordState.dispatching.value,
        SettlementRecordState.failed.value,
        SettlementRecordState.teardown_dispatch_pending.value,
        SettlementRecordState.tearing_down.value,
        SettlementRecordState.torn_down.value,
        SettlementRecordState.teardown_failed.value,
        SettlementRecordState.abandoned.value,
    ],
)
@pytest.mark.asyncio
async def test_get_fulfillment_result_non_active_states_have_no_outputs_and_no_provider_call(state):
    record = _record(state=state)
    tx = FakeTransaction(record, provisioned_resources=[_provisioned_resource()])
    provider = _provider()
    uow = FakeUnitOfWork(tx)

    envelope = await _orchestrator(uow, provider).get_fulfillment_result("fulfillment-1")

    assert envelope.payload["provisioned_resources"] == []
    assert envelope.payload["domain_result"] is None
    assert envelope.payload["state"] == state
    provider.prepare_create.assert_not_called()
    provider.dispatch_create.assert_not_called()
    provider.fetch_credentials.assert_not_called()



@pytest.mark.asyncio
async def test_get_fulfillment_result_repeated_non_active_reads_are_stable_and_provider_free():
    record = _record(state=SettlementRecordState.dispatching.value)
    provider = _provider()
    uow = FakeUnitOfWork(FakeTransaction(record), FakeTransaction(record))
    orchestrator = _orchestrator(uow, provider)

    first = await orchestrator.get_fulfillment_result("fulfillment-1")
    second = await orchestrator.get_fulfillment_result("fulfillment-1")

    assert first == second
    assert uow.read_entries == 2
    assert uow.write_entries == 0
    provider.fetch_credentials.assert_not_called()


@pytest.mark.asyncio
async def test_get_fulfillment_result_closes_read_transaction_before_provider_io():
    record = _record(
        state=SettlementRecordState.active.value,
        provider_metadata={"current_job_id": "job-1"},
    )
    uow = FakeUnitOfWork(FakeTransaction(record, provisioned_resources=[_provisioned_resource()]))
    provider = _provider()

    async def fetch_credentials(*args, **kwargs):
        assert not uow.read_transaction_open
        return VersionedEnvelope(
            kind="vm.fulfillment.result.v1",
            schema_version=1,
            payload={"credentials": []},
        )

    provider.fetch_credentials = AsyncMock(side_effect=fetch_credentials)
    await _orchestrator(uow, provider).get_fulfillment_result("fulfillment-1")

    provider.fetch_credentials.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_fulfillment_result_unknown_id_raises_not_found():
    uow = FakeUnitOfWork(FakeTransaction(_record()))

    with pytest.raises(SettlementEntityNotFoundError):
        await _orchestrator(uow, _provider()).get_fulfillment_result("no-such-fulfillment")


@pytest.mark.asyncio
async def test_get_fulfillment_result_credential_fetch_failure_is_distinct_from_workload_failure():
    record = _record(state=SettlementRecordState.active.value)
    tx = FakeTransaction(record, provisioned_resources=[_provisioned_resource()])
    provider = _provider()
    provider.fetch_credentials = AsyncMock(
        side_effect=CredentialFetchFailedError("job not found")
    )
    uow = FakeUnitOfWork(tx)

    with pytest.raises(CredentialFetchFailedError):
        await _orchestrator(uow, provider).get_fulfillment_result("fulfillment-1")

    # The aggregate's own durable state is unaffected by a live-fetch failure.
    assert record.state == SettlementRecordState.active.value


async def test_get_fulfillment_result_unexpected_provider_exception_is_wrapped_not_leaked():
    """The defensive orchestration wrapper around a provider's credential
    fetch: an unexpected exception (not the provider's own
    CredentialFetchFailedError) still rejects the whole result as
    credential_fetch_failed, rather than leaking a raw provider-internal
    exception type to the caller."""
    record = _record(state=SettlementRecordState.active.value)
    tx = FakeTransaction(record, provisioned_resources=[_provisioned_resource()])
    provider = _provider()
    provider.fetch_credentials = AsyncMock(side_effect=RuntimeError("boom"))
    uow = FakeUnitOfWork(tx)

    with pytest.raises(CredentialFetchFailedError):
        await _orchestrator(uow, provider).get_fulfillment_result("fulfillment-1")

    assert record.state == SettlementRecordState.active.value


async def test_get_fulfillment_result_active_state_performs_a_fresh_lookup_every_call():
    """No caching: two reads of the same active fulfillment each call
    fetch_credentials again, not just once with the second read reusing a
    stored value."""
    record = _record(
        state=SettlementRecordState.active.value,
        provider_metadata={"current_job_id": "job-1"},
    )
    tx = FakeTransaction(record, provisioned_resources=[_provisioned_resource()])
    provider = _provider()
    uow = FakeUnitOfWork(tx, tx)

    await _orchestrator(uow, provider).get_fulfillment_result("fulfillment-1")
    await _orchestrator(uow, provider).get_fulfillment_result("fulfillment-1")

    assert provider.fetch_credentials.call_count == 2


async def test_get_fulfillment_result_durable_fields_are_stable_when_aggregate_unchanged():
    """State, failure detail, and provisioned-resource outputs are read
    straight from the durable aggregate on every call; two reads against an
    unchanged aggregate return identical values for all of them, even though
    the provider is free to return different domain-result content each
    time (see the next test)."""
    record = _record(
        state=SettlementRecordState.active.value,
        provider_metadata={"current_job_id": "job-1"},
    )
    tx = FakeTransaction(record, provisioned_resources=[_provisioned_resource()])
    provider = _provider()
    uow = FakeUnitOfWork(tx, tx)

    first = await _orchestrator(uow, provider).get_fulfillment_result("fulfillment-1")
    second = await _orchestrator(uow, provider).get_fulfillment_result("fulfillment-1")

    assert first.payload["state"] == second.payload["state"]
    assert first.payload["failure_reason"] == second.payload["failure_reason"]
    assert first.payload["provisioned_resources"] == second.payload["provisioned_resources"]


async def test_get_fulfillment_result_credential_equality_across_reads_is_not_guaranteed():
    """A live fetch is authoritative at read time; nothing in this contract
    promises two reads return equal credentials, and a provider that legitimately
    returns different content on each call (a rotated secret store, a
    changed role set) must not be treated as an error by the read path."""
    record = _record(
        state=SettlementRecordState.active.value,
        provider_metadata={"current_job_id": "job-1"},
    )
    tx = FakeTransaction(record, provisioned_resources=[_provisioned_resource()])
    provider = _provider()
    provider.fetch_credentials = AsyncMock(
        side_effect=[
            VersionedEnvelope(
                kind="vm.fulfillment.result.v1",
                schema_version=1,
                payload={"credentials": [{"role": "tenant", "password": "first"}]},
            ),
            VersionedEnvelope(
                kind="vm.fulfillment.result.v1",
                schema_version=1,
                payload={"credentials": [{"role": "tenant", "password": "second"}]},
            ),
        ]
    )
    uow = FakeUnitOfWork(tx, tx)

    first = await _orchestrator(uow, provider).get_fulfillment_result("fulfillment-1")
    second = await _orchestrator(uow, provider).get_fulfillment_result("fulfillment-1")

    assert first.payload["domain_result"] != second.payload["domain_result"]
    # Divergent credential content across reads is not itself an error --
    # both reads succeeded and returned a complete envelope.
    assert first.payload["state"] == second.payload["state"] == "active"


async def test_get_fulfillment_result_does_not_mutate_fulfillment_state():
    """A result read is a pure projection: it never opens a write
    transaction and never changes the durable aggregate, active or not."""
    record = _record(
        state=SettlementRecordState.active.value,
        provider_metadata={"current_job_id": "job-1"},
    )
    tx = FakeTransaction(record, provisioned_resources=[_provisioned_resource()])
    provider = _provider()
    uow = FakeUnitOfWork(tx, tx)

    await _orchestrator(uow, provider).get_fulfillment_result("fulfillment-1")
    await _orchestrator(uow, provider).get_fulfillment_result("fulfillment-1")

    assert record.state == SettlementRecordState.active.value
    assert uow.write_entries == 0
    assert uow.read_entries == 2


@pytest.mark.asyncio
async def test_begin_persists_then_dispatches_then_acknowledges():
    acceptance_tx = FakeTransaction(_record())
    acknowledgement_tx = FakeTransaction(acceptance_tx.record)
    provider = _provider()
    orchestrator = _orchestrator(
        FakeUnitOfWork(acceptance_tx, acknowledgement_tx),
        provider,
    )

    result = await orchestrator.begin_fulfillment(
        "reservation-1", "compute", _request()
    )

    assert len(acceptance_tx.persisted) == 1
    provider.dispatch_create.assert_awaited_once_with(acceptance_tx.persisted[0])
    assert acknowledgement_tx.acknowledged == [{"job_id": "job-1"}]
    assert result.state == SettlementRecordState.dispatching.value


@pytest.mark.asyncio
async def test_equivalent_acknowledged_retry_does_not_redispatch():
    record = _record(state=SettlementRecordState.dispatching.value)
    tx = FakeTransaction(record, dispatch_required=False)
    provider = _provider()

    result = await _orchestrator(FakeUnitOfWork(tx), provider).begin_fulfillment(
        "reservation-1", "compute", _request()
    )

    provider.prepare_create.assert_not_called()
    provider.dispatch_create.assert_not_awaited()
    assert result.state == SettlementRecordState.dispatching.value


@pytest.mark.asyncio
async def test_pending_retry_reuses_persisted_prepared_operation():
    prepared = VersionedEnvelope(
        kind="vm.ansible.create.v1",
        schema_version=1,
        payload={"frozen": True},
    )
    record = _record(prepared_create_operation=prepared.model_dump(mode="json"))
    acceptance_tx = FakeTransaction(record)
    acknowledgement_tx = FakeTransaction(record)
    provider = _provider()

    await _orchestrator(
        FakeUnitOfWork(acceptance_tx, acknowledgement_tx),
        provider,
    ).begin_fulfillment("reservation-1", "compute", _request())

    provider.prepare_create.assert_not_called()
    provider.dispatch_create.assert_awaited_once_with(prepared)


@pytest.mark.asyncio
async def test_recoverable_dispatch_failure_remains_pending(caplog):
    tx = FakeTransaction(_record())
    provider = _provider()
    provider.dispatch_create.side_effect = FulfillmentCreateFailedError("offline")

    result = await _orchestrator(FakeUnitOfWork(tx), provider).begin_fulfillment(
        "reservation-1", "compute", _request()
    )

    assert result.state == SettlementRecordState.dispatch_pending.value
    assert "dispatch failed after durable acceptance" in caplog.text.lower()


# ---------------------------------------------------------------------------
# The provider's create-job handle reaches the reservation
#
# The field was plumbed end to end with a `None` default at every hop and no
# VM supplier, so the VM path left it null while bare metal filled it -- a
# parameter with a default and no caller is invisible to tests of either side.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dispatch_attaches_the_providers_create_job_handle():
    acceptance_tx = FakeTransaction(_record())
    acknowledgement_tx = FakeTransaction(acceptance_tx.record)
    provider = _provider()
    provider.resolve_executor_job_id.return_value = "ansible-job-7"

    await _orchestrator(
        FakeUnitOfWork(acceptance_tx, acknowledgement_tx), provider
    ).begin_fulfillment("reservation-1", "compute", _request())

    # Same transaction as the acknowledgement: a reservation must not
    # reference a create the settlement row does not also record.
    assert acknowledgement_tx.attached_jobs == [
        ("reservation-1", "ansible-job-7")
    ]
    # Resolved from the metadata the provider returned at dispatch.
    provider.resolve_executor_job_id.assert_called_once_with(
        acknowledgement_tx.acknowledged[0]
    )


@pytest.mark.asyncio
async def test_a_provider_without_a_job_handle_attaches_nothing():
    """`None` is a legitimate answer, not a missing implementation.

    Asserted so the orchestrator never attaches a falsy placeholder: a
    reservation carrying an empty job reference is worse than one carrying
    none, because it reads as a handle an operator can look up.
    """
    acceptance_tx = FakeTransaction(_record())
    acknowledgement_tx = FakeTransaction(acceptance_tx.record)
    provider = _provider()
    provider.resolve_executor_job_id.return_value = None

    await _orchestrator(
        FakeUnitOfWork(acceptance_tx, acknowledgement_tx), provider
    ).begin_fulfillment("reservation-1", "compute", _request())

    assert acknowledgement_tx.acknowledged, (
        "dispatch did not complete, so this proves nothing"
    )
    assert acknowledgement_tx.attached_jobs == []
