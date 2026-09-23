"""`market-storefront publish` is a client of the storefront's publication loop."""

from __future__ import annotations

import ast
import inspect

import pytest
import typer
from typer.testing import CliRunner

from market_storefront import cli_publish
from tests.fixtures.publication_cycle import build_cycle_report


class _Client:
    def __init__(self, report=None, pages=None):
        self.report = report
        self.pages = list(pages or [])
        self.calls: list[tuple] = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def admin_run_lifecycle_cycle(self, loop):
        self.calls.append(("run", loop))
        return self.report

    def admin_dry_run_lifecycle_cycle(self, loop):
        self.calls.append(("dry_run", loop))
        return self.report

    def list_listings(self, *, status, limit):
        self.calls.append(("list", status))
        listings = self.pages.pop(0) if self.pages else []
        return type("Page", (), {"listings": listings})()

    def close_listing(self, listing_id):
        self.calls.append(("close", listing_id))


@pytest.fixture
def app():
    application = typer.Typer()
    cli_publish.register(application)
    return application


def _invoke(app, monkeypatch, client, *args):
    monkeypatch.setattr(cli_publish, "_admin_client", lambda _url: client)
    monkeypatch.setattr(cli_publish, "_seller_client", lambda _url: client)
    monkeypatch.setattr(
        cli_publish, "resolve_storefront_url", lambda _url, default_port: "http://sf"
    )
    return CliRunner().invoke(app, list(args))


def test_a_run_advances_exactly_one_publication_cycle(app, monkeypatch):
    client = _Client(report=build_cycle_report())

    result = _invoke(app, monkeypatch, client)

    assert result.exit_code == 0, result.output
    assert client.calls == [("run", "publication")]
    assert "publish: 1" in result.output


def test_dry_run_previews_without_advancing(app, monkeypatch):
    client = _Client(report=build_cycle_report(dry_run=True))

    result = _invoke(app, monkeypatch, client, "--dry-run")

    assert result.exit_code == 0, result.output
    assert client.calls == [("dry_run", "publication")]


def test_abort_all_seller_closes_every_open_listing(app, monkeypatch):
    listing = type("L", (), {"listing_id": "l-1"})()
    client = _Client(pages=[[listing]])

    result = _invoke(app, monkeypatch, client, "--abort-all")

    assert result.exit_code == 0, result.output
    assert ("close", "l-1") in client.calls
    assert not any(call[0] in {"run", "dry_run"} for call in client.calls)


@pytest.mark.parametrize(
    "retired",
    ["--settlement", "--max-duration-seconds", "--watch", "--inventory", "--db"],
)
def test_retired_options_are_refused(app, monkeypatch, retired):
    result = _invoke(app, monkeypatch, _Client(report=build_cycle_report()), retired, "x")

    assert result.exit_code != 0


def test_the_command_never_opens_the_storefront_database():
    tree = ast.parse(inspect.getsource(cli_publish))
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    } | {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }

    assert "sqlite3" not in imported
    assert not any("sqlite_client" in name for name in imported)
