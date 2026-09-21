"""POST /api/v1/capacity/definitions/import, through the canonical operator client.

Every import goes through ``ProvisioningClient.import_capacity_definitions``,
and every read of the result through the canonical site clients, so a route,
body, or response-shape change breaks these tests through the clients rather
than through a test-local copy of the wire contract.
"""

from __future__ import annotations

import pytest
from compute_provisioning import PoolCreate
from vm_provisioning_operator import ProvisioningError

from compute_provisioning_service.db.models import DefinitionDocumentImport
from compute_provisioning_service import container as _container_module

from .test_capacity_api import CapacityApi, capacity  # noqa: F401

_DOCUMENT = """\
resources:
  - resource_id: compute-kvm1
    pool_id: default
    resource_type: compute.gpu
    host_id: kvm1
    capacity: {gpu_count: 8}
    attributes: {gpu_model: H200}
"""


def _entry(resource_id: str, *, pool_id: str = "default", extra: str = "") -> str:
    return (
        f"  - resource_id: {resource_id}\n"
        f"    pool_id: {pool_id}\n"
        "    resource_type: compute.gpu\n"
        "    capacity: {gpu_count: 4}\n"
        f"{extra}"
    )


async def _resources(capacity: CapacityApi) -> dict[str, dict]:
    return {row["resource_id"]: row for row in await capacity.admin.list_resources()}


async def test_an_import_declares_capacity_and_a_reimport_writes_nothing(
    client_and_queue, capacity: CapacityApi
):
    client, _ = client_and_queue

    first = await client.import_capacity_definitions(_DOCUMENT)
    _, version = await capacity.events()
    second = await client.import_capacity_definitions(_DOCUMENT + "# reviewed\n")
    _, version_after = await capacity.events()

    assert first.applied and first.diff.created == ["compute-kvm1"]
    assert second.applied and second.diff.unchanged == ["compute-kvm1"]
    assert version_after == version
    resource = (await _resources(capacity))["compute-kvm1"]
    assert resource["capacity"] == {"gpu_count": 8}
    assert resource["host_id"] == "kvm1"


async def test_declarations_a_document_does_not_name_are_retained(
    client_and_queue, capacity: CapacityApi
):
    client, _ = client_and_queue
    await capacity.register(
        "api-registered", pool_id="default", total_units=2, enabled=False
    )

    await client.import_capacity_definitions(_DOCUMENT)

    resources = await _resources(capacity)
    assert set(resources) == {"api-registered", "compute-kvm1"}
    assert resources["api-registered"]["enabled"] is False


async def test_an_explicit_import_leaves_the_startup_digest_alone(client_and_queue):
    """The startup gate compares the mounted document with the one startup
    last reconciled; an operator's import is not that document."""
    client, _ = client_and_queue

    await client.import_capacity_definitions(_DOCUMENT)

    with _container_module.resolved_session_factory() as db:
        assert db.get(DefinitionDocumentImport, "capacity") is None


async def test_a_refused_import_reports_every_problem_and_applies_nothing(
    client_and_queue, capacity: CapacityApi
):
    """A structural problem, an unknown pool, and a pool move under a live
    obligation are all reported, and the acceptable first entry is not
    applied either."""
    client, _ = client_and_queue
    await client.create_pool(PoolCreate(
        id="pool-b", label="Pool B", provider="ansible",
        provider_config={"playbook_path": "playbooks/vm-operations.yaml"},
    ))
    await capacity.register("held", pool_id="default", total_units=4)
    reserved = await capacity.reserve(
        {"offering_mode": "vm", "gpu_count": 1, "resource_id": "held"}, {}
    )
    assert reserved is not None

    document = (
        _DOCUMENT
        + _entry("elsewhere", pool_id="no-such-pool")
        + _entry("held", pool_id="pool-b")
    )
    with pytest.raises(ProvisioningError) as refused:
        await client.import_capacity_definitions(document)

    assert refused.value.status_code == 422
    assert "unknown_pool" in str(refused.value)
    assert "conflict" in str(refused.value)
    resources = await _resources(capacity)
    assert "compute-kvm1" not in resources
    assert resources["held"]["pool_id"] == "default"

    with pytest.raises(ProvisioningError) as malformed:
        await client.import_capacity_definitions(
            _DOCUMENT + "    total_units: 8\n"
        )
    assert malformed.value.status_code == 422
    assert "unknown_field" in str(malformed.value)


async def test_validate_only_reports_the_plan_and_problems_without_applying(
    client_and_queue, capacity: CapacityApi
):
    client, _ = client_and_queue
    await capacity.register("holder", pool_id="default", total_units=1, host_id="kvm2")

    clean = await client.import_capacity_definitions(_DOCUMENT, validate_only=True)
    refused = await client.import_capacity_definitions(
        _DOCUMENT + _entry("newcomer", extra="    host_id: kvm2\n"),
        validate_only=True,
    )

    assert clean.applied is False
    assert clean.diff.created == ["compute-kvm1"]
    assert clean.problems == []
    assert refused.applied is False
    assert [(p.path, p.code) for p in refused.problems] == [("resources[1]", "conflict")]
    assert set(await _resources(capacity)) == {"holder"}


async def test_a_structurally_invalid_document_is_not_checked_against_stored_state(
    client_and_queue, capacity: CapacityApi
):
    """An unknown field in one entry and an unknown pool in another: only the
    structural problem is reported, because stored state is consulted only
    for a document whose every entry is a declaration."""
    client, _ = client_and_queue
    document = _DOCUMENT + "    total_units: 8\n" + _entry("elsewhere", pool_id="no-such-pool")

    report = await client.import_capacity_definitions(document, validate_only=True)

    assert [(p.path, p.code) for p in report.problems] == [
        ("resources[0].total_units", "unknown_field"),
    ]
    assert await _resources(capacity) == {}
