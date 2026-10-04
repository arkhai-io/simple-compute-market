from __future__ import annotations

import inspect
import re

import pytest

from market_resource_pools_client import ResourcePoolClient, SyncResourcePoolClient
from market_resource_pools_contracts import PoolCreate, PoolReplace, PoolUpdate

_POOL = {
    "id": "pool-a",
    "label": "Pool A",
    "provider": "ansible",
    "provider_config": {},
    "policy_tags": {},
    "enabled": True,
    "created_at": "2026-10-04T00:00:00Z",
    "updated_at": "2026-10-04T00:00:00Z",
}

_DECLARATIONS = {
    "policy_tags": {
        "deliverable_modes": ["vm"],
        "advertisable_modes": ["vm"],
        "capacity_backing": "backed",
    }
}


def _public(cls) -> dict[str, inspect.Signature]:
    return {
        name: inspect.signature(member)
        for name, member in inspect.getmembers(cls, inspect.isfunction)
        if not name.startswith("_")
    }


def test_async_and_sync_variants_offer_identical_methods():
    assert _public(ResourcePoolClient) == _public(SyncResourcePoolClient)


class _Recorder:
    """A transport that records each call and checks it names its own route."""

    def __init__(self, response):
        self.calls: list[tuple[str, str, object, dict]] = []
        self._response = response

    def _record(self, method, path, body=None, *, request_id=None, route):
        assert route["method"] == method
        assert re.fullmatch(route["path"], path), (route["operation"], path)
        assert "admin" in route["roles"]
        self.calls.append((method, path, body, route))
        return self._response(route["operation"])

    def authenticated_request(self, *args, **kwargs):
        return self._record(*args, **kwargs)


class _AsyncRecorder(_Recorder):
    async def authenticated_request(self, *args, **kwargs):
        return self._record(*args, **kwargs)


def _response(operation: str):
    if operation == "provisioning_pools_list":
        return {"pools": [_POOL], "total": 1}
    if operation == "provisioning_pools_export":
        return "pools: []\n"
    if operation in {"provisioning_pools_import", "provisioning_pools_validate"}:
        return {"valid": True, "problems": [], "diff": {}} if operation.endswith("validate") else {"diff": {}}
    return _POOL


def _calls(client):
    create = PoolCreate(id="pool-a", label="Pool A", provider="ansible", **_DECLARATIONS)
    return [
        lambda: client.list_pools(),
        lambda: client.get_pool("pool-a"),
        lambda: client.export_pools_yaml(),
        lambda: client.create_pool(create),
        lambda: client.replace_pool(
            "pool-a", PoolReplace(label="Pool A", provider="ansible", enabled=True, **_DECLARATIONS)
        ),
        lambda: client.patch_pool("pool-a", PoolUpdate(label="Pool A")),
        lambda: client.delete_pool("pool-a"),
    ]


def test_each_sync_request_names_the_declaration_describing_it():
    transport = _Recorder(_response)
    client = SyncResourcePoolClient(transport)
    for call in _calls(client):
        call()
    operations = [route["operation"] for *_, route in transport.calls]
    assert operations == [
        "provisioning_pools_list",
        "provisioning_pool_get",
        "provisioning_pools_export",
        "provisioning_pool_create",
        "provisioning_pool_replace",
        "provisioning_pool_update",
        "provisioning_pool_disable",
    ]


@pytest.mark.asyncio
async def test_each_async_request_names_the_declaration_describing_it():
    transport = _AsyncRecorder(_response)
    client = ResourcePoolClient(transport)
    for call in _calls(client):
        await call()
    assert len(transport.calls) == 7
    assert transport.calls[2][2] is None  # a read sends no body
