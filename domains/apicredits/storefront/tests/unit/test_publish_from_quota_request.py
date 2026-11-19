"""The quota-backed publish request holds the seller's prose to the envelope's limit.

The request's ``description`` publishes beside the listing envelope as well as
inside its resource, so the request model takes the shared description type and
refuses what the registry would refuse.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from apicredits_storefront.listing_publication import PublishFromQuotaRequest

REQUEST = {"resource_id": "svc-quota", "service_name": "Acme"}


def test_a_description_at_the_envelope_limit_is_admitted():
    request = PublishFromQuotaRequest.model_validate({**REQUEST, "description": "d" * 4000})

    assert request.description == "d" * 4000


def test_a_description_past_the_envelope_limit_is_refused_on_its_field():
    with pytest.raises(ValidationError) as refused:
        PublishFromQuotaRequest.model_validate({**REQUEST, "description": "d" * 4001})

    assert [error["loc"] for error in refused.value.errors()] == [("description",)]
