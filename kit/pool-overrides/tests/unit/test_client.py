"""The typed client builds exactly the requests the storefront binds."""

from __future__ import annotations

import asyncio
import inspect

import pytest

from market_pool_overrides import (
    PoolOverrideClient,
    PoolOverrideContractError,
    SyncPoolOverrideClient,
    pool_override_contract,
    pool_override_statuses,
)

STORED = {"site_id": "a/b", "pool_id": "gpu", "offering_mode": "vm", "terms": {"sla": 1.0},
          "created_at": "t", "updated_at": "t"}


class _Recording:
    """Stands where a core storefront client's ``authenticated_request`` does."""

    def __init__(self):
        self.calls = []

    def _answer(self, method, kwargs):
        if method == "PUT":
            return {"override": {**kwargs["body"], "created_at": "t", "updated_at": "t"},
                    "feasibility": [], "projection": {"revision": 2, "digest": "d"}}
        if method == "DELETE":
            return {**kwargs["params"], "deleted": True}
        if kwargs["operation"] == "admin_get_pool_override":
            return {"override": STORED}
        return {"overrides": [STORED]}

    def authenticated_request(self, method, path, **kwargs):
        self.calls.append((method, path, kwargs))
        return self._answer(method, kwargs)


class _AsyncRecording(_Recording):
    async def authenticated_request(self, method, path, **kwargs):
        return super().authenticated_request(method, path, **kwargs)


def _exercise_sync(recording):
    client = SyncPoolOverrideClient(recording)
    client.put_pool_override({"site_id": "a/b", "pool_id": "gpu", "offering_mode": "vm",
                              "terms": {"sla": 1.0}})
    client.get_pool_override("a/b", "gpu", "vm")
    client.list_pool_overrides()
    client.list_pool_overrides(site_id="a/b")
    client.delete_pool_override("a/b", "gpu", "vm")


def test_every_request_is_the_one_the_storefront_binds():
    recording = _Recording()
    _exercise_sync(recording)

    for method, path, kwargs in recording.calls:
        query = list((kwargs.get("params") or {}).items())
        contract = pool_override_contract(method, query, kwargs.get("body"))
        assert path == "/api/v1/admin/pool-overrides"
        assert (kwargs["operation"], kwargs["resource"]) == (contract.operation, contract.resource)
        assert kwargs["role"] == "admin"


def test_both_variants_send_identical_requests():
    sync, async_ = _Recording(), _AsyncRecording()
    _exercise_sync(sync)

    async def run():
        client = PoolOverrideClient(async_)
        await client.put_pool_override({"site_id": "a/b", "pool_id": "gpu",
                                        "offering_mode": "vm", "terms": {"sla": 1.0}})
        await client.get_pool_override("a/b", "gpu", "vm")
        await client.list_pool_overrides()
        await client.list_pool_overrides(site_id="a/b")
        await client.delete_pool_override("a/b", "gpu", "vm")

    asyncio.run(run())
    assert async_.calls == sync.calls


@pytest.mark.parametrize(
    "name",
    ["put_pool_override", "get_pool_override", "list_pool_overrides", "delete_pool_override"],
)
def test_the_two_variants_have_identical_signatures(name):
    assert inspect.signature(getattr(PoolOverrideClient, name)) == inspect.signature(
        getattr(SyncPoolOverrideClient, name)
    )


def test_an_unaddressable_record_is_refused_before_sending():
    recording = _Recording()

    with pytest.raises(PoolOverrideContractError):
        SyncPoolOverrideClient(recording).put_pool_override({"site_id": "a", "pool_id": "gpu"})

    assert recording.calls == []


def test_statuses_are_read_from_the_generic_status_extra():
    class Status:
        extra = {"pool_overrides": [{"state": "applied"}]}

    assert pool_override_statuses(Status()) == [{"state": "applied"}]
    assert pool_override_statuses(object()) is None
