"""Field-set contract of the VM lease models this service serves.

The operator client's lease methods send and return plain dictionaries, so the
route-level integration tests prove the route but never build these models on
the client side. Their field sets are asserted here, beside the service that
owns the contract.
"""

from __future__ import annotations

from vm_provisioning_operator.models import LeaseResponse, LeaseUpdate

_RETIRED = "vm_remove_job_id"


def test_lease_update_names_the_release_handle_release_job_id():
    assert "release_job_id" in LeaseUpdate.model_fields
    assert _RETIRED not in LeaseUpdate.model_fields


def test_lease_update_ignores_the_retired_name_like_any_unknown_field():
    """The retired name is not refused: it is ignored exactly as any field the
    model does not define, and it never reaches the release handle."""
    update = LeaseUpdate.model_validate({_RETIRED: "fulfillment-1"})

    assert update.release_job_id is None
    assert _RETIRED not in update.model_dump()


def test_lease_update_carries_a_supplied_release_handle():
    update = LeaseUpdate.model_validate({"release_job_id": "fulfillment-1"})

    assert update.release_job_id == "fulfillment-1"


def test_lease_response_publishes_the_release_handle_under_one_name():
    assert "release_job_id" in LeaseResponse.model_fields
    assert _RETIRED not in LeaseResponse.model_fields
