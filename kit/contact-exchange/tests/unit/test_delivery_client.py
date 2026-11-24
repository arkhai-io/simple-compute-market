"""Typed clients conform to the independently frozen signed route vectors."""
import inspect
import json
from importlib.resources import files

import pytest
from pydantic import ValidationError

from market_contact_exchange.delivery_client import ContactDeliveryClient, SyncContactDeliveryClient
from market_contact_exchange.delivery_contract import FinalizationCancel, IntroductionFinalize, IntroductionReview

TRACE = json.loads(files("market_contact_exchange.fixtures").joinpath("delivery_vectors.json").read_text())


class Transport:
    def __init__(self):
        self.calls = []

    def authenticated_request(self, method, path, **kwargs):
        self.calls.append((method, path, kwargs))
        return {}


class AsyncTransport(Transport):
    async def authenticated_request(self, method, path, **kwargs):
        return super().authenticated_request(method, path, **kwargs)


def invocation(client, row):
    operation = row["signed_request"]["operation"]
    body = row["body"]
    ref = "a" * 64
    fid = "12345678-1234-4234-8234-123456789abc"
    if operation == "introduction_review":
        return client.review(IntroductionReview.model_validate(body))
    if operation == "introduction_start":
        return client.finalize(IntroductionFinalize.model_validate(body))
    if operation == "introduction_finalization_cancel":
        return client.cancel(FinalizationCancel.model_validate(body))
    if operation == "introduction_finalization_read":
        return client.read_finalization(ref, fid)
    return client.read_delivery(ref)


def assert_wire(transport, row):
    method, path, kwargs = transport.calls[-1]
    signed = row["signed_request"]
    assert method == signed["method"] and path == row["path"]
    assert kwargs["operation"] == signed["operation"]
    assert kwargs["resource"] == signed["resource"]
    assert kwargs["role"] == "buyer"
    assert kwargs.get("body") == row["body"]


@pytest.mark.parametrize("row", TRACE["requests"], ids=lambda row: row["signed_request"]["operation"])
async def test_async_and_sync_clients_match_frozen_signed_route_contract(row):
    sync = Transport()
    invocation(SyncContactDeliveryClient(sync), row)
    assert_wire(sync, row)
    asynchronous = AsyncTransport()
    await invocation(ContactDeliveryClient(asynchronous), row)
    assert_wire(asynchronous, row)


def test_public_client_signatures_match_and_invalid_paths_are_not_dispatched():
    for name, method in vars(ContactDeliveryClient).items():
        if name.startswith("_"):
            continue
        assert inspect.signature(method) == inspect.signature(getattr(SyncContactDeliveryClient, name))
    transport = Transport()
    with pytest.raises(ValidationError):
        SyncContactDeliveryClient(transport).read_finalization("a" * 64, "../other")
    assert transport.calls == []
