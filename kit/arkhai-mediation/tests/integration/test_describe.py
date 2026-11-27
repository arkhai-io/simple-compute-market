"""The authority's public description is read at its root and held to the published schema."""

import asyncio
from copy import deepcopy

import httpx
import pytest

from market_arkhai_mediation.client import MediationProtocolError
from market_arkhai_mediation.contract import vectors
from .test_adapter import Scenario


def _describe(body, requests=None):
    async def drive():
        def answer(request):
            if requests is not None:
                requests.append(request)
            return httpx.Response(200, json=body)

        s = Scenario(transport=httpx.MockTransport(answer))
        try:
            return await s.client.describe()
        finally:
            await s.client.close()
    return asyncio.run(drive())


def test_the_published_description_is_returned_as_served():
    requests = []
    description = deepcopy(vectors()["description"])
    assert _describe(description, requests) == description
    assert [(request.method, request.url.path) for request in requests] == [("GET", "/")]


def test_a_description_the_schema_refuses_is_refused():
    description = deepcopy(vectors()["description"])
    description.pop("contact")
    with pytest.raises(MediationProtocolError):
        _describe(description)


def test_a_description_naming_another_authority_is_refused():
    description = deepcopy(vectors()["description"])
    description["dispute"]["account"] = "44444444-4444-4444-8444-444444444444"
    with pytest.raises(MediationProtocolError):
        _describe(description)
