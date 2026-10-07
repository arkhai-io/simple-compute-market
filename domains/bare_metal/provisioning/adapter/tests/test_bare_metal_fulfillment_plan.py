"""Bare metal's plan: a grant for the selected whole host, and the reclaim undoing it."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from arkhai_bare_metal import (
    BARE_METAL_OFFERING_MODE,
    NODE_GRANT_ACCESS_ACTION,
    NODE_RECLAIM_ACCESS_ACTION,
)
from compute_provisioning.job_fulfillment import JobFulfillmentProvider
from compute_provisioning.jobs.submission import JobSubmissionService
from compute_provisioning_ansible import MockAnsibleRunner
from compute_provisioning_contracts import (
    AccessDelivery,
    JobCredentialsResponse,
    JobStatusResponse,
    JobSubmitResponse,
)
from market_core import VersionedEnvelope
from market_fulfillment import (
    ProviderConfigInvalidError,
    ProviderOperationState,
    SettlementResource,
    SettlementResult,
)

from bare_metal_provisioning_adapter.codec import BareMetalJobParams
from bare_metal_provisioning_adapter.services.bare_metal_fulfillment_plan import (
    BareMetalFulfillmentPlan,
)
from bare_metal_provisioning_adapter.services.mock_output import bare_metal_mock_output

from execution import HOST, executor, job_run


def _resource(*, physical_host_id: str = "physical-host-1") -> SettlementResource:
    return SettlementResource(
        offering_mode=BARE_METAL_OFFERING_MODE,
        settlement_resource_id="resource-1",
        pool_id="pool-1",
        resource_kind="compute.bare-metal",
        provider="bare_metal.ansible",
        host_id=HOST.host_id,
        attributes={
            "physical_host_id": physical_host_id,
            "bare_metal_publication": {"enabled": True},
        },
    )


def _request(*, host_id: str = HOST.host_id, **overrides) -> VersionedEnvelope:
    payload = {
        "kind": "bare_metal.v2",
        "settlement_obligation_ref": "obligation-1",
        "host_id": host_id,
        "physical_host_id": "physical-host-1",
        "lease_start_utc": "2030-01-01T00:00:00Z",
        "lease_end_utc": "2030-01-02T00:00:00Z",
        "access_method": "ssh",
        "ssh_public_key": "ssh-ed25519 buyer",
        **overrides,
    }
    return VersionedEnvelope(kind="bare_metal.v2", schema_version=1, payload=payload)


def _grant(plan: BareMetalFulfillmentPlan, **request):
    return plan.prepare_create(
        capacity_reservation_id="reservation-1",
        request=_request(**request),
        resource=_resource(),
        pool_config={},
        allocate=True,
    )


def test_a_grant_is_prepared_for_the_selected_whole_host() -> None:
    prepared = _grant(BareMetalFulfillmentPlan())

    assert (prepared.offering_mode, prepared.action) == (
        BARE_METAL_OFFERING_MODE,
        NODE_GRANT_ACCESS_ACTION,
    )
    assert prepared.host_id == prepared.executor_target == HOST.host_id
    params = BareMetalJobParams.model_validate(dict(prepared.parameters))
    assert params.physical_host_id == "physical-host-1"
    assert params.ssh_public_key == "ssh-ed25519 buyer"
    assert params.ssh_user and params.ssh_user.startswith("arkhai-")
    assert params.escrow_uid is None
    assert params.reclaim_policy is None


@pytest.mark.parametrize(
    ("request_fields", "message"),
    [
        ({"host_id": "attacker-machine"}, "host_id does not match"),
        ({"physical_host_id": "another-machine"}, "physical_host_id does not match"),
    ],
)
def test_a_buyer_payload_cannot_replace_the_selected_machine(request_fields, message) -> None:
    with pytest.raises(ProviderConfigInvalidError, match=message):
        _grant(BareMetalFulfillmentPlan(), **request_fields)


def test_pool_configuration_and_another_offering_mode_are_refused() -> None:
    plan = BareMetalFulfillmentPlan()

    with pytest.raises(ProviderConfigInvalidError, match="pool-local configuration"):
        plan.prepare_create(
            capacity_reservation_id="r", request=_request(), resource=_resource(),
            pool_config={"x": 1}, allocate=True,
        )
    with pytest.raises(ProviderConfigInvalidError, match="offering mode"):
        plan.prepare_create(
            capacity_reservation_id="r", request=_request(),
            resource=_resource().model_copy(update={"offering_mode": "vm"}),
            pool_config={}, allocate=True,
        )


def test_the_reclaim_undoes_exactly_what_the_grant_ran() -> None:
    plan = BareMetalFulfillmentPlan(reclaim_policy="lock_user")
    grant = _grant(plan)

    reclaim = plan.prepare_teardown(
        capacity_reservation_id="reservation-1",
        resource=_resource(),
        host_id=grant.host_id,
        executor_target=grant.executor_target,
        create_parameters=grant.parameters,
        pool_config={},
    )

    assert reclaim.action == NODE_RECLAIM_ACCESS_ACTION
    assert (reclaim.host_id, reclaim.executor_target) == (grant.host_id, grant.executor_target)
    assert dict(reclaim.parameters) == {
        **dict(grant.parameters),
        "action": NODE_RECLAIM_ACCESS_ACTION,
        "reclaim_policy": "lock_user",
    }


@pytest.mark.parametrize(
    ("create_parameters", "resource", "message"),
    [
        ({"action": NODE_RECLAIM_ACCESS_ACTION, "host_id": HOST.host_id}, _resource(), "not a grant"),
        ({"vm_action": "create"}, _resource(), "not a bare-metal grant"),
        (None, _resource(physical_host_id="moved"), "physical_host_id does not match"),
    ],
    ids=["a-reclaim", "another-domain", "another-machine"],
)
def test_a_reclaim_is_refused_when_the_grant_does_not_match(
    create_parameters, resource, message
) -> None:
    plan = BareMetalFulfillmentPlan()
    grant = _grant(plan)

    with pytest.raises(ProviderConfigInvalidError, match=message):
        plan.prepare_teardown(
            capacity_reservation_id="reservation-1",
            resource=resource,
            host_id=grant.host_id,
            executor_target=grant.executor_target,
            create_parameters=create_parameters or grant.parameters,
            pool_config={},
        )


def test_a_reclaim_policy_the_role_does_not_implement_is_refused_at_composition() -> None:
    with pytest.raises(ValueError, match="bare_metal_reclaim_policy"):
        BareMetalFulfillmentPlan(reclaim_policy="format_disk")


class _MockJobs:
    """A job authority that runs each job through bare metal's mock executor."""

    def __init__(self) -> None:
        self.jobs: dict[str, JobStatusResponse] = {}

    async def submit(self, *, params, operation_id, action, host_id, **_):
        outcome = await executor(
            MockAnsibleRunner(default_output=bare_metal_mock_output)
        ).execute(job_run(BareMetalJobParams.model_validate(dict(params))))
        self.jobs[operation_id] = JobStatusResponse(
            job_id=operation_id, status="succeeded", params=dict(params),
            host_id=host_id, result=outcome.result,
        )
        return JobSubmitResponse(job_id=operation_id, status="succeeded")

    def get_job(self, job_id):
        return self.jobs[job_id]

    def get_credentials(self, job_id):
        return JobCredentialsResponse(job_id=job_id, credentials=[])


@pytest.mark.asyncio
async def test_a_mock_grant_is_delivered_and_reclaimed_through_the_family_provider() -> None:
    """The plan, bare metal's codec under its mock, and the family's provider
    composed as the provisioning service composes them."""
    jobs = _MockJobs()
    provider = JobFulfillmentProvider(
        plan=BareMetalFulfillmentPlan(),
        submission=JobSubmissionService(
            engine=jobs,
            hosts=SimpleNamespace(get_host=lambda host_id: SimpleNamespace(enabled=True)),
            job_queue_provider=lambda: None,
        ),
        jobs=jobs,
    )
    created = await provider.dispatch_create(
        provider.prepare_create(
            capacity_reservation_id="reservation-1",
            request=_request(),
            resource=_resource(),
            pool_config={},
        )
    )
    metadata = created.provider_metadata

    status = await provider.get_status("reservation-1", _resource(), metadata)
    delivery = AccessDelivery.model_validate(
        (await provider.fetch_credentials(metadata, ())).payload
    )
    reclaim = await provider.dispatch_teardown(
        provider.prepare_teardown(
            SettlementResult(
                capacity_reservation_id="reservation-1",
                fulfillment_id="fulfillment-1",
                resource=_resource(),
                provisioned_resources=(),
                provider_metadata=metadata,
            ),
            {},
        )
    )

    assert status.state is ProviderOperationState.succeeded
    assert provider.resolve_provisioned_resources(metadata) == (HOST.host_id,)
    endpoint = delivery.endpoints[0]
    assert (endpoint.protocol, endpoint.host, endpoint.port) == ("ssh", "10.0.0.5", 2201)
    assert endpoint.user and endpoint.user.startswith("arkhai-")
    assert delivery.credentials == ()
    assert reclaim.provider_metadata["create_job_id"] == metadata["create_job_id"]
    reclaimed = jobs.get_job(reclaim.provider_metadata["teardown_job_id"])
    assert reclaimed.params["action"] == NODE_RECLAIM_ACCESS_ACTION
    assert reclaimed.result.value["action"] == NODE_RECLAIM_ACCESS_ACTION
