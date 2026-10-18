"""`bare-metal-storefront pool-override` calls the matching typed client method.

The client and the routes it calls are proven against the running app in
``test_pool_overrides_api.py``; this module proves the command's own decisions:
which method each subcommand calls, how failures surface, where it connects,
and that it signs only as the storefront's own identity.
"""

from __future__ import annotations

import contextlib
import dataclasses
import json

import pytest
from market_pool_overrides import (
    PoolOverride,
    PoolOverrideDeleteResponse,
    PoolOverrideListResponse,
    PoolOverrideWriteResponse,
    ProjectionGeneration,
)
from market_identity import TrustedIdentitySet
from storefront_client import StorefrontClientError
from typer.testing import CliRunner

from arkhai_bare_metal_storefront import pool_override_cli
from arkhai_bare_metal_storefront.admin_cli import storefront_url
from arkhai_bare_metal_storefront.cli import app
from arkhai_bare_metal_storefront.config import IDENTITY_CREDENTIAL_ENV
from loopback import serving
from storefront_configuration import (
    SELLER,
    SELLER_CREDENTIAL,
    publishable_configuration,
    write_configuration,
)
from test_http_system import _app, _runtime
from test_pool_overrides_api import _with_sites

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


def test_the_url_is_the_flag_then_the_configured_base_url():
    assert storefront_url("http://other:9", "https://seller.example/") == "http://other:9"
    assert storefront_url(None, "https://seller.example/") == "https://seller.example"


def test_it_signs_as_the_configured_identity_at_the_configured_url(monkeypatch, tmp_path):
    """Application integration: the command reads the storefront's principal and
    its ``base_url`` from the configuration files the server reads, and its
    credential from ARKHAI_IDENTITY_CREDENTIAL, then lists through the running
    app's administrator API, which admits only that principal."""
    runtime = dataclasses.replace(
        _with_sites(_runtime(str(tmp_path / "storefront.db")), "site-a"),
        admin_principals=TrustedIdentitySet(identities=(SELLER.identity,)),
    )
    with serving(_app(runtime)) as base_url:
        document = publishable_configuration(tmp_path / "unused.db")
        document["base_url"] = base_url
        write_configuration(monkeypatch, tmp_path, document)
        monkeypatch.setenv(IDENTITY_CREDENTIAL_ENV, SELLER_CREDENTIAL)

        result = runner.invoke(app, ["pool-override", "list"])

    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == {"overrides": []}


def test_configuration_that_cannot_be_read_is_reported_as_such(monkeypatch, tmp_path):
    write_configuration(monkeypatch, tmp_path, {"capacity": {"poll_interval": 0}})
    monkeypatch.setenv(IDENTITY_CREDENTIAL_ENV, SELLER_CREDENTIAL)

    result = runner.invoke(
        app, ["pool-override", "list", "--storefront-url", "http://127.0.0.1:9"]
    )

    assert result.exit_code != 0
    assert "capacity.poll_interval" in result.output
    assert "Identity.principal" not in result.output


def test_without_the_storefront_identity_it_refuses_before_connecting(
    monkeypatch, tmp_path
):
    write_configuration(monkeypatch, tmp_path)
    monkeypatch.delenv(IDENTITY_CREDENTIAL_ENV, raising=False)

    result = runner.invoke(
        app, ["pool-override", "list", "--storefront-url", "http://127.0.0.1:9"]
    )

    assert result.exit_code != 0
    assert "ARKHAI_IDENTITY_CREDENTIAL" in result.output
