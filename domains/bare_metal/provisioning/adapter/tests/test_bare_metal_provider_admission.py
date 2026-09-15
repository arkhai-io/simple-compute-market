"""The real fulfillment provider drives the real operations-service admission.

Only job submission, the executor's external process boundary, is recorded
instead of run, so the settlement identity a teardown carries is exactly the
one the provider builds.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from arkhai_bare_metal import (
    BARE_METAL_OFFERING_MODE,
    NODE_GRANT_ACCESS_ACTION,
    NODE_RECLAIM_ACCESS_ACTION,
    BareMetalLeaseAccountError,
    bare_metal_executor_ref,
    canonical_lease_account,
)
from market_fulfillment import (
    FulfillmentTeardownFailedError,
    SettlementResource,
    SettlementResult,
    VersionedEnvelope,
)

from bare_metal_provisioning_adapter.services.bare_metal_fulfillment_provider import (
    BareMetalFulfillmentProvider,
)
from bare_metal_provisioning_adapter.services.bare_metal_operations_service import (
    BareMetalOperationsService,
)

IDENTITIES = [
    pytest.param({"escrow_uid": "escrow-1"}, "escrow-1", id="escrow"),
    pytest.param(
        {"settlement_obligation_ref": "obligation-1"}, "obligation-1", id="obligation"
    ),
]


class RecordingJobs:
    """Records submitted executor jobs instead of starting them."""

    def __init__(self) -> None:
        self.submitted: list = []

    async def submit(self, params, queue, *, contract=None, operation_id=None):
        self.submitted.append(params)
        return SimpleNamespace(job_id=f"job-{len(self.submitted)}")

    def get_job(self, job_id):
        return SimpleNamespace(status="succeeded", error=None, result={})


class AllowingHosts:
    def get_host(self, machine_id):
        return SimpleNamespace(enabled=True, name=machine_id)


def _resource() -> SettlementResource:
    return SettlementResource(
        offering_mode=BARE_METAL_OFFERING_MODE,
        settlement_resource_id="resource-1",
        pool_id="pool-1",
        resource_kind="compute.bare-metal",
        provider="bare_metal.ansible",
        attributes={
            "bare_metal_publication": {
                "enabled": True,
                "machine_id": "machine-1",
                "physical_host_id": "physical-host-1",
            }
        },
    )


def _request(identity: dict) -> VersionedEnvelope:
    return VersionedEnvelope(
        kind="bare_metal.v1",
        schema_version=1,
        payload={
            "kind": "bare_metal.v1",
            **identity,
            "machine_id": "machine-1",
            "physical_host_id": "physical-host-1",
            "lease_start_utc": "2030-01-01T00:00:00Z",
            "lease_end_utc": "2030-01-02T00:00:00Z",
            "access_method": "ssh",
            "ssh_public_key": "ssh-ed25519 buyer",
        },
    )


def _compose() -> tuple[BareMetalFulfillmentProvider, BareMetalOperationsService, RecordingJobs]:
    jobs = RecordingJobs()
    operations = BareMetalOperationsService(
        job_service=jobs,
        job_queue_provider=lambda: object(),
        settings=SimpleNamespace(bare_metal_reclaim_policy="remove_lease_key"),
        host_service=AllowingHosts(),
    )
    provider = BareMetalFulfillmentProvider(operations_service=operations, job_service=jobs)
    return provider, operations, jobs


async def _granted(provider: BareMetalFulfillmentProvider, identity: dict):
    prepared = provider.prepare_create(
        capacity_reservation_id="reservation-1",
        request=_request(identity),
        resource=_resource(),
        pool_config={},
    )
    return await provider.dispatch_create(prepared)


def _teardown(provider: BareMetalFulfillmentProvider, provider_metadata: dict):
    return provider.prepare_teardown(
        SettlementResult(
            capacity_reservation_id="reservation-1",
            fulfillment_id="fulfillment-1",
            resource=_resource(),
            provisioned_resources=(),
            provider_metadata=provider_metadata,
        ),
        {},
    )


@pytest.mark.parametrize(("identity", "settlement"), IDENTITIES)
@pytest.mark.asyncio
async def test_teardown_reclaims_the_leases_own_account(identity, settlement) -> None:
    provider, _, jobs = _compose()
    account = canonical_lease_account(settlement)

    created = await _granted(provider, identity)
    await provider.dispatch_teardown(_teardown(provider, created.provider_metadata))

    assert [(params.executor_action, params.ssh_user) for params in jobs.submitted] == [
        (NODE_GRANT_ACCESS_ACTION, account),
        (NODE_RECLAIM_ACCESS_ACTION, account),
    ]


@pytest.mark.parametrize(("identity", "settlement"), IDENTITIES)
@pytest.mark.asyncio
async def test_teardown_refuses_another_leases_account(identity, settlement) -> None:
    provider, _, jobs = _compose()
    created = await _granted(provider, identity)
    metadata = dict(created.provider_metadata)
    metadata["access_ref"] = {
        **metadata["access_ref"],
        "ssh_user": canonical_lease_account("another-lease"),
    }

    with pytest.raises(FulfillmentTeardownFailedError) as exc_info:
        await provider.dispatch_teardown(_teardown(provider, metadata))

    assert isinstance(exc_info.value.__cause__, BareMetalLeaseAccountError)
    assert [params.executor_action for params in jobs.submitted] == [
        NODE_GRANT_ACCESS_ACTION
    ]


@pytest.mark.asyncio
async def test_privileged_reclaim_without_a_settlement_identity_submits_nothing() -> None:
    _, operations, jobs = _compose()
    access_ref = {"ssh_user": canonical_lease_account("escrow-1")}

    with pytest.raises(BareMetalLeaseAccountError):
        await operations.reclaim_access(
            {
                "capacity_reservation_id": "reservation-1",
                "executor_target": "machine-1",
                "access_ref": access_ref,
                "executor_ref": bare_metal_executor_ref(
                    "physical-host-1", access_ref=access_ref
                ),
            }
        )

    assert jobs.submitted == []
