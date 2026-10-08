"""`bare-metal-storefront pool-override` calls the matching typed client method.

The client and the routes it calls are proven against the running app in
``test_pool_overrides_api.py``; this module proves the command's own decisions:
which method each subcommand calls, how failures surface, where it connects,
and that it signs only as the storefront's own identity.
"""

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
)
from storefront_client import StorefrontClientError
from typer.testing import CliRunner

from arkhai_bare_metal_storefront import pool_override_cli
from arkhai_bare_metal_storefront.cli import app

ADDRESS = {"site_id": "site-a", "pool_id": "pool-1", "offering_mode": "bare_metal"}
STORED = PoolOverride(
    **ADDRESS, terms={"max_duration_seconds": 3600}, created_at="t", updated_at="t"
)
runner = CliRunner()


class _Client:
    def __init__(self, error: Exception | None = None) -> None:
        self.calls: list[tuple] = []
        self.error = error

    def _call(self, *call):
        self.calls.append(call)
        if self.error is not None:
            raise self.error

    def put_pool_override(self, record):
        self._call("put", record)
        return PoolOverrideWriteResponse(
            override=STORED, feasibility=[],
            projection=ProjectionGeneration(revision=1, digest="g1"),
        )

    def get_pool_override(self, site_id, pool_id, offering_mode):
        self._call("get", site_id, pool_id, offering_mode)
        return STORED

    def list_pool_overrides(self, *, site_id=None, pool_id=None):
        self._call("list", site_id, pool_id)
        return PoolOverrideListResponse(overrides=[STORED])

    def delete_pool_override(self, site_id, pool_id, offering_mode):
        self._call("delete", site_id, pool_id, offering_mode)
        return PoolOverrideDeleteResponse(**ADDRESS, deleted=True)


def _install(monkeypatch, fake: _Client) -> _Client:
    @contextlib.contextmanager
    def _client(_url):
        yield fake

    monkeypatch.setattr(pool_override_cli, "_client", _client)
    return fake


def test_set_sends_the_files_whole_record(monkeypatch, tmp_path):
    fake = _install(monkeypatch, _Client())
    record = {**ADDRESS, "terms": {"max_duration_seconds": 3600}}
    path = tmp_path / "override.json"
    path.write_text(json.dumps(record))

    result = runner.invoke(app, ["pool-override", "set", "--file", str(path)])

    assert result.exit_code == 0, result.output
    assert fake.calls == [("put", record)]
    assert json.loads(result.output)["override"]["terms"] == record["terms"]


@pytest.mark.parametrize(
    ("argv", "call"),
    [
        (["get", "--site", "site-a", "--pool", "pool-1", "--mode", "bare_metal"],
         ("get", "site-a", "pool-1", "bare_metal")),
        (["list", "--site", "site-a"], ("list", "site-a", None)),
        (["delete", "--site", "site-a", "--pool", "pool-1", "--mode", "bare_metal"],
         ("delete", "site-a", "pool-1", "bare_metal")),
    ],
)
def test_each_command_calls_its_client_method(monkeypatch, argv, call):
    fake = _install(monkeypatch, _Client())

    result = runner.invoke(app, ["pool-override", *argv])

    assert result.exit_code == 0, result.output
    assert fake.calls == [call]


def test_the_mode_is_never_defaulted(monkeypatch):
    fake = _install(monkeypatch, _Client())

    result = runner.invoke(app, ["pool-override", "get", "--site", "site-a", "--pool", "pool-1"])

    assert result.exit_code != 0
    assert fake.calls == []


def test_a_pool_without_its_site_is_refused_before_any_call(monkeypatch):
    fake = _install(monkeypatch, _Client())

    result = runner.invoke(app, ["pool-override", "list", "--pool", "pool-1"])

    assert result.exit_code != 0
    assert fake.calls == []


def test_a_storefront_refusal_exits_nonzero_with_its_message(monkeypatch):
    _install(monkeypatch, _Client(error=StorefrontClientError("HTTP 422: shapes refused")))

    result = runner.invoke(
        app, ["pool-override", "get", "--site", "s", "--pool", "p", "--mode", "bare_metal"]
    )

    assert result.exit_code == 1
    assert "shapes refused" in result.output


def test_the_url_is_the_flag_then_the_public_url_then_local():
    env = {"BARE_METAL_STOREFRONT_PUBLIC_URL": "https://seller.example/"}
    assert pool_override_cli.storefront_url("http://other:9", env) == "http://other:9"
    assert pool_override_cli.storefront_url(None, env) == "https://seller.example"
    assert pool_override_cli.storefront_url(None, {}) == "http://localhost:8000"


def test_without_the_storefront_identity_it_refuses_before_connecting(monkeypatch):
    for name in (
        "BARE_METAL_STOREFRONT_IDENTITY_SCHEME",
        "BARE_METAL_STOREFRONT_IDENTITY_IDENTIFIER",
        "ARKHAI_IDENTITY_CREDENTIAL",
    ):
        monkeypatch.delenv(name, raising=False)

    result = runner.invoke(
        app, ["pool-override", "list", "--storefront-url", "http://127.0.0.1:9"]
    )

    assert result.exit_code != 0
    assert "ARKHAI_IDENTITY_CREDENTIAL" in result.output
