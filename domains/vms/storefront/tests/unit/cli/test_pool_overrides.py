"""`market-storefront pool-override` calls the matching administrator client method."""

from __future__ import annotations

import json

import pytest
from storefront_client import StorefrontClientError
from storefront_client.models import (
    PoolOverride,
    PoolOverrideDeleteResponse,
    PoolOverrideListResponse,
    PoolOverrideShapeFeasibility,
    PoolOverrideWriteResponse,
)

from market_storefront.groups import pool_overrides as group

SHAPE = {"gpu": {"count": 1, "model": "H100"}, "memory": {"gib": 64}}
STORED = PoolOverride(site_id="site-a", pool_id="gpu", sla=99.0)


class _Client:
    def __init__(self, *, feasible: bool = True, error: Exception | None = None):
        self.calls: list[tuple] = []
        self.feasible = feasible
        self.error = error

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def _call(self, *call):
        self.calls.append(call)
        if self.error is not None:
            raise self.error

    def admin_put_pool_override(self, record):
        self._call("put", record)
        return PoolOverrideWriteResponse(
            override=STORED,
            feasibility=[
                PoolOverrideShapeFeasibility(shape_digest="d", shape=SHAPE, feasible=self.feasible)
            ],
            projection_revision=4,
            projection_digest="gen-4",
        )

    def admin_get_pool_override(self, site_id, pool_id):
        self._call("get", site_id, pool_id)
        return STORED

    def admin_list_pool_overrides(self, *, site_id=None):
        self._call("list", site_id)
        return PoolOverrideListResponse(overrides=[STORED])

    def admin_delete_pool_override(self, site_id, pool_id):
        self._call("delete", site_id, pool_id)
        return PoolOverrideDeleteResponse(site_id=site_id, pool_id=pool_id, deleted=True)


@pytest.fixture
def client(monkeypatch):
    fake = _Client()
    monkeypatch.setattr(group, "_client", lambda _url: fake)
    return fake


def test_set_sends_the_whole_record_from_the_file(runner, app, client, tmp_path):
    record = {"site_id": "site-a", "pool_id": "gpu", "listing_shapes": [SHAPE]}
    path = tmp_path / "override.json"
    path.write_text(json.dumps(record))

    result = runner.invoke(app, ["pool-override", "set", "--file", str(path)])

    assert result.exit_code == 0, result.output
    assert client.calls == [("put", record)]
    assert json.loads(result.stdout)["projection_revision"] == 4


def test_set_warns_about_a_shape_no_member_is_feasible_for(runner, app, monkeypatch, tmp_path):
    monkeypatch.setattr(group, "_client", lambda _url: _Client(feasible=False))
    path = tmp_path / "override.json"
    path.write_text(json.dumps({"site_id": "site-a", "pool_id": "gpu", "listing_shapes": [SHAPE]}))

    result = runner.invoke(app, ["pool-override", "set", "--file", str(path)])

    assert result.exit_code == 0
    assert "publish nothing" in result.stderr


def test_set_refuses_a_document_that_is_not_an_object(runner, app, client, tmp_path):
    path = tmp_path / "override.json"
    path.write_text("[]")

    result = runner.invoke(app, ["pool-override", "set", "--file", str(path)])

    assert result.exit_code != 0
    assert client.calls == []


@pytest.mark.parametrize(
    ("args", "call"),
    [
        (["get", "--site", "site-a", "--pool", "gpu"], ("get", "site-a", "gpu")),
        (["list"], ("list", None)),
        (["list", "--site", "site-a"], ("list", "site-a")),
        (["delete", "--site", "site-a", "--pool", "gpu"], ("delete", "site-a", "gpu")),
    ],
)
def test_each_command_calls_its_client_method(runner, app, client, args, call):
    result = runner.invoke(app, ["pool-override", *args])

    assert result.exit_code == 0, result.output
    assert client.calls == [call]


def test_a_storefront_refusal_exits_non_zero_and_names_it(runner, app, monkeypatch):
    monkeypatch.setattr(
        group,
        "_client",
        lambda _url: _Client(error=StorefrontClientError("returned 503: site unreachable", 503)),
    )

    result = runner.invoke(app, ["pool-override", "get", "--site", "site-a", "--pool", "gpu"])

    assert result.exit_code == 1
    assert "site unreachable" in result.stderr
