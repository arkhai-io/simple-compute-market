"""A read of an Agreement nobody has filed on.

The authority answers the first record page of an Agreement it holds no record
of `404 invalid_request`; the adapter reads that as an accepted, empty record.
Every other refusal of a record read stays a failure. The first two cases read
the in-process contract peer's own answers; the others replace its record
answer with the refusal under test.
"""

import asyncio
import json

import httpx
import pytest

from market_arkhai_mediation.fixtures.authority import MediationContractFake
from .test_adapter import Scenario


def run(scenario):
    asyncio.run(scenario())


class Recording(httpx.AsyncBaseTransport):
    """Serves the peer, rewriting record answers as a test asks, and keeps each status."""

    def __init__(self, peer: MediationContractFake, rewrite=None):
        self.peer = peer
        self.rewrite = rewrite or (lambda number, response: response)
        self.records: list[int] = []

    async def handle_async_request(self, request):
        response = self.peer.handle(request)
        if request.url.path == "/record":
            response = self.rewrite(len(self.records), response)
            self.records.append(response.status_code)
        return response


def test_an_agreement_with_no_record_is_read_as_no_case():
    async def scenario():
        peer = MediationContractFake()
        transport = Recording(peer)
        s = Scenario(peer=peer, transport=transport)
        try:
            view = await s.adapter.read()
            assert transport.records == [404]
            assert view.outcome.status == "accepted"
            assert view.disputes == [] and view.cases == []
        finally:
            await s.client.close()
    run(scenario)


def test_after_a_filing_the_next_read_shows_the_case():
    async def scenario():
        s = Scenario()
        try:
            assert (await s.adapter.read()).cases == []
            filed = await s.file()
            assert filed.status == "accepted"
            view = await s.adapter.read()
            assert view.outcome.status == "accepted"
            assert [case.case_ref for case in view.cases] == [filed.filing.case_ref]
            assert [event.kind for event in view.disputes] == ["filed"]
        finally:
            await s.client.close()
    run(scenario)


def test_a_404_after_a_page_was_read_is_a_failure():
    # The client refuses a page with more after it and no entries, so a page
    # read before the 404 holds the filed record.
    def rewrite(number, response):
        if number == 0:
            page = json.loads(response.content)
            return httpx.Response(200, json={**page, "has_more": True})
        return httpx.Response(404, json={"code": "invalid_request"})

    async def scenario():
        peer = MediationContractFake()
        transport = Recording(peer, rewrite)
        s = Scenario(peer=peer, transport=transport)
        try:
            await s.file()
            transport.records.clear()
            view = await s.adapter.read()
            assert transport.records == [200, 404]
            assert view.outcome.status == "rejected"
            assert view.disputes == [] and view.cases == []
        finally:
            await s.client.close()
    run(scenario)


@pytest.mark.parametrize("status,code,outcome", [
    (503, "temporarily_unavailable", "pending"),
    (404, "authentication_required", "rejected"),
    (403, "invalid_request", "rejected"),
])
def test_any_other_first_page_refusal_is_a_failure(status, code, outcome):
    async def scenario():
        peer = MediationContractFake()
        transport = Recording(peer, lambda _, __: httpx.Response(status, json={"code": code}))
        s = Scenario(peer=peer, transport=transport)
        try:
            view = await s.adapter.read()
            assert transport.records == [status]
            assert view.outcome.status == outcome
        finally:
            await s.client.close()
    run(scenario)
