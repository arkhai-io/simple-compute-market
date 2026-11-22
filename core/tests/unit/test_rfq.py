import pytest
from pydantic import ValidationError

from market_core.registry_descriptor import RegistryPrincipal
from market_core.rfq import (
    RfqAccountClaim,
    RfqAudience,
    RfqInvocation,
    RfqMutationReceipt,
    RfqOperation,
    RfqTarget,
)


def test_the_account_body_round_trips_without_accepting_extra_claims():
    invocation = RfqInvocation(
        account=RfqAccountClaim(namespace="accounts", subject="account-a"),
        audience=RfqAudience(
            name="registry:compute",
            principal=RegistryPrincipal(scheme="ed25519", identifier="A" * 43),
        ),
        inputs={"term": {"value": 6, "unit": "month"}, "metadata": {"flexible": True}},
    )

    assert RfqInvocation.model_validate_json(invocation.model_dump_json()) == invocation
    with pytest.raises(ValidationError):
        RfqInvocation.model_validate({**invocation.model_dump(), "role": "admin"})


def test_resource_binding_is_route_specific():
    selection = RfqTarget(RfqOperation.SELECT, "request-a", "response-a")
    detail = RfqTarget(RfqOperation.READ, "request-a")

    assert selection.resource == "rfqs/request-a/responses/response-a"
    assert detail.resource == "rfqs/request-a"
    with pytest.raises(ValueError):
        RfqTarget(RfqOperation.SELECT, "request-a")
    with pytest.raises(ValueError):
        RfqTarget(RfqOperation.READ, "request-a/responses/response-a")


def test_a_receipt_refuses_fields_outside_the_contact_free_schema():
    with pytest.raises(ValidationError):
        RfqMutationReceipt.model_validate({
            "resource_id": "request-a", "state": "open", "version": 1,
            "contact": {"email": "example@example.test"},
        })
