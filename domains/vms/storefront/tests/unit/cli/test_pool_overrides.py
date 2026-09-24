"""`market-storefront pool-override` calls the matching typed client method."""

from __future__ import annotations

import contextlib
import json

import pytest
from market_pool_overrides import (
    PoolOverride,
    PoolOverrideDeleteResponse,
    PoolOverrideListResponse,
    PoolOverrideWriteResponse,
    ProjectionGeneration,
    ShapeFeasibility,
)
from storefront_client import StorefrontClientError

from market_storefront.groups import pool_overrides as group

SHAPE = {"gpu": {"count": 1, "model": "H100"}, "memory": {"gib": 64}}
ADDRESS = {"site_id": "site-a", "pool_id": "gpu", "offering_mode": "vm"}
STORED = PoolOverride(**ADDRESS, terms={"sla": 99.0}, created_at="t", updated_at="t")


class _Client:
    def __init__(self, *, feasible: bool = True, error: Exception | None = None):
        self.calls: list[tuple] = []
        self.feasible = feasible
        self.error = error

    def _call(self, *call):
        self.calls.append(call)
        if self.error is not None:
            raise self.error

    def put_pool_override(self, record):
        self._call("put", record)
        return PoolOverrideWriteResponse(
            override=STORED,
            feasibility=[ShapeFeasibility(shape_digest="d", shape=SHAPE, feasible=self.feasible)],
            projection=ProjectionGeneration(revision=4, digest="gen-4"),
        )

    def get_pool_override(self, site_id, pool_id, offering_mode):
        self._call("get", site_id, pool_id, offering_mode)
        return STORED

    def list_pool_overrides(self, *, site_id=None, pool_id=None):
        self._call("list", site_id, pool_id)
        return PoolOverrideListResponse(overrides=[STORED])

    def delete_pool_override(self, site_id, pool_id, offering_mode):
        self._call("delete", site_id, pool_id, offering_mode)
        return PoolOverrideDeleteResponse(
            site_id=site_id, pool_id=pool_id, offering_mode=offering_mode, deleted=True
        )


def _install(monkeypatch, fake: _Client) -> _Client:
    @contextlib.contextmanager
    def _client(_url):
        yield fake

    monkeypatch.setattr(group, "_client", _client)
    return fake


@pytest.fixture
def client(monkeypatch):
    return _install(monkeypatch, _Client())


def test_set_sends_the_whole_record_from_the_file(runner, app, client, tmp_path):
    record = {**ADDRESS, "listing_shapes": [SHAPE]}
    path = tmp_path / "override.json"
    path.write_text(json.dumps(record))

    result = runner.invoke(app, ["pool-override", "set", "--file", str(path)])

    assert result.exit_code == 0, result.output
    assert client.calls == [("put", record)]
    assert json.loads(result.stdout)["projection"]["revision"] == 4


def test_set_warns_about_a_shape_no_member_is_feasible_for(runner, app, monkeypatch, tmp_path):
    _install(monkeypatch, _Client(feasible=False))
    path = tmp_path / "override.json"
    path.write_text(json.dumps({**ADDRESS, "listing_shapes": [SHAPE]}))

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
        (["get", "--site", "site-a", "--pool", "gpu", "--mode", "vm"],
         ("get", "site-a", "gpu", "vm")),
        (["list"], ("list", None, None)),
        (["list", "--site", "site-a"], ("list", "site-a", None)),
        (["list", "--site", "site-a", "--pool", "gpu"], ("list", "site-a", "gpu")),
        (["delete", "--site", "site-a", "--pool", "gpu", "--mode", "vm"],
         ("delete", "site-a", "gpu", "vm")),
    ],
)
def test_each_command_calls_its_client_method(runner, app, client, args, call):
    result = runner.invoke(app, ["pool-override", *args])

    assert result.exit_code == 0, result.output
    assert client.calls == [call]


@pytest.mark.parametrize(
    "args",
    [
        ["get", "--site", "site-a", "--pool", "gpu"],
        ["delete", "--site", "site-a", "--pool", "gpu"],
        ["list", "--pool", "gpu"],
    ],
)
def test_the_mode_is_never_defaulted_and_a_pool_needs_its_site(runner, app, client, args):
    result = runner.invoke(app, ["pool-override", *args])

    assert result.exit_code != 0
    assert client.calls == []


def test_a_storefront_refusal_exits_non_zero_and_names_it(runner, app, monkeypatch):
    _install(
        monkeypatch,
        _Client(error=StorefrontClientError("returned 503: site unreachable", 503)),
    )

    result = runner.invoke(
        app, ["pool-override", "get", "--site", "site-a", "--pool", "gpu", "--mode", "vm"]
    )

    assert result.exit_code == 1
    assert "site unreachable" in result.stderr
