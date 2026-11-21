import pytest
from pydantic import ValidationError

from core_storefront.models.listing_models import CreateListingRequest


def test_create_listing_request_keeps_settlement_config_schema_opaque() -> None:
    payload = {"mechanism_payload": {"arbitrary": ["shape"]}}

    request = CreateListingRequest(listing_resource={}, settlement_config=payload)

    assert request.settlement_config == payload


#: The least a create states besides its details: a resource and one settlement choice.
_CREATE = {"listing_resource": {}, "settlement_config": {"mechanism_payload": {}}}


def test_a_create_request_admits_details_at_their_limits() -> None:
    details = {
        "title": "t" * 200,
        "description": "d" * 4000,
        "metadata": {f"key{index}": "v" * 500 for index in range(50)},
    }

    request = CreateListingRequest(**_CREATE, **details)

    assert (request.title, request.description, request.metadata) == (
        details["title"],
        details["description"],
        details["metadata"],
    )


def test_a_create_request_states_no_details_by_default() -> None:
    request = CreateListingRequest(**_CREATE)

    assert (request.title, request.description, request.metadata) == (None, None, None)


# Each field carries the shared type; every limit of that type is the shared
# model's own unit suite's (core/tests/unit/test_listing_details.py).
@pytest.mark.parametrize(
    "detail",
    [
        {"title": "t" * 201},
        {"description": "d" * 4001},
        {"metadata": {f"key{index}": 1 for index in range(51)}},
    ],
    ids=["title", "description", "metadata"],
)
def test_a_create_request_refuses_a_detail_past_its_limit(detail) -> None:
    (field,) = detail

    with pytest.raises(ValidationError) as refused:
        CreateListingRequest(**_CREATE, **detail)

    assert {error["loc"][0] for error in refused.value.errors()} == {field}
