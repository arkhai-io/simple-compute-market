"""The `market` verb skeleton: generic no-plugin behavior and plugin override."""

from __future__ import annotations

import json

import typer
from typer.testing import CliRunner

import core_buyer.cli as cli_mod
from core_buyer.cli import build_app, parse_filter_options
from core_buyer.plugins import BuyerSchemaPlugin

runner = CliRunner()


def _all_output(result) -> str:
    """stdout + stderr regardless of click version (mix_stderr was removed)."""
    out = result.output
    try:
        out += result.stderr
    except Exception:
        pass
    return out


def _quiet_config(monkeypatch):
    """Pin config-derived values so tests never read a real buyer.toml."""
    monkeypatch.setattr(cli_mod, "resolve_indexer_auth", lambda: {})
    monkeypatch.setattr(
        cli_mod, "resolve_discovery_timeout", lambda *, override=None: override or 5.0
    )


# ---------------------------------------------------------------------------
# No plugins: generic --filter passthrough, raw JSON, stubs for buy verbs
# ---------------------------------------------------------------------------


def test_generic_listing_list_passes_filters_and_prints_raw_json(monkeypatch):
    _quiet_config(monkeypatch)
    seen = {}

    def fake_query(urls, timeout=30.0, *, filters=None, auth=None):
        seen.update(urls=urls, timeout=timeout, filters=filters, auth=auth)
        return [{"listing_id": "L1", "offer_resource": {"anything": 1}}]

    monkeypatch.setattr(cli_mod, "query_registry_for_matches_multi", fake_query)

    result = runner.invoke(
        build_app(plugins=[]),
        [
            "listing", "list",
            "-r", "http://reg.example/",
            "--filter", "gpu_model=H200",
            "-f", "region=eu",
            "--limit", "7",
        ],
    )

    assert result.exit_code == 0, result.output
    assert seen["urls"] == ["http://reg.example"]
    assert seen["filters"] == {
        "limit": 7, "offset": 0, "gpu_model": "H200", "region": "eu",
    }
    assert json.loads(result.output) == [
        {"listing_id": "L1", "offer_resource": {"anything": 1}}
    ]


def test_generic_listing_show_prints_raw_json(monkeypatch):
    _quiet_config(monkeypatch)
    monkeypatch.setattr(
        cli_mod, "fetch_listing_dict_multi",
        lambda urls, listing_id, timeout=30.0, *, auth=None: {"listing_id": listing_id},
    )
    result = runner.invoke(
        build_app(plugins=[]), ["listing", "show", "L9", "-r", "http://reg.example"],
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == {"listing_id": "L9"}


def test_generic_listing_show_missing_listing_exits_nonzero(monkeypatch):
    _quiet_config(monkeypatch)
    monkeypatch.setattr(
        cli_mod, "fetch_listing_dict_multi",
        lambda urls, listing_id, timeout=30.0, *, auth=None: None,
    )
    result = runner.invoke(
        build_app(plugins=[]), ["listing", "show", "L9", "-r", "http://reg.example"],
    )
    assert result.exit_code == 1


def test_buy_without_plugin_is_a_helpful_stub():
    # Extra args must not produce a usage error; the stub owns the message.
    result = runner.invoke(
        build_app(plugins=[]), ["buy", "--gpu-model", "H200", "--max-price", "5"],
    )
    assert result.exit_code == 2
    assert "schema plugin" in _all_output(result)


def test_negotiate_and_settle_without_plugin_are_stubs():
    app = build_app(plugins=[])
    for verb in ("negotiate", "settle"):
        result = runner.invoke(app, [verb])
        assert result.exit_code == 2, verb
        assert "schema plugin" in _all_output(result)


def test_plugins_command_reports_empty():
    result = runner.invoke(build_app(plugins=[]), ["plugins"])
    assert result.exit_code == 0
    assert "No buyer schema plugins installed" in _all_output(result)


# ---------------------------------------------------------------------------
# With a plugin: registered verbs replace the core fallbacks
# ---------------------------------------------------------------------------


def _vm_like_plugin() -> BuyerSchemaPlugin:
    def register(app: typer.Typer) -> None:
        listing_app = typer.Typer()

        @listing_app.command("list")
        def listing_list() -> None:
            typer.echo("plugin rendering")

        app.add_typer(listing_app, name="listing")

        @app.command("buy")
        def buy(max_price: float = typer.Option(..., "--max-price")) -> None:
            typer.echo(f"plugin buy at {max_price}")

    return BuyerSchemaPlugin(
        schema_id="vms.compute", register=register, distribution="market-buyer",
    )


def test_plugin_buy_replaces_stub():
    result = runner.invoke(
        build_app(plugins=[_vm_like_plugin()]), ["buy", "--max-price", "5"],
    )
    assert result.exit_code == 0, result.output
    assert "plugin buy at 5.0" in result.output


def test_plugin_listing_suppresses_generic_fallback():
    result = runner.invoke(build_app(plugins=[_vm_like_plugin()]), ["listing", "list"])
    assert result.exit_code == 0, result.output
    assert "plugin rendering" in result.output


def test_unclaimed_verbs_still_get_stubs_with_plugin_installed():
    result = runner.invoke(build_app(plugins=[_vm_like_plugin()]), ["negotiate"])
    assert result.exit_code == 2
    assert "schema plugin" in _all_output(result)


def test_plugins_command_lists_schema_ids():
    result = runner.invoke(build_app(plugins=[_vm_like_plugin()]), ["plugins"])
    assert result.exit_code == 0
    assert "vms.compute" in result.output


def test_version_reports_core_and_plugins():
    result = runner.invoke(build_app(plugins=[_vm_like_plugin()]), ["--version"])
    assert result.exit_code == 0
    assert "core-buyer" in result.output
    assert "vms.compute" in result.output


# ---------------------------------------------------------------------------
# --filter parsing
# ---------------------------------------------------------------------------


def test_parse_filter_options_roundtrip():
    assert parse_filter_options(["a=1", "b = x=y "]) == {"a": "1", "b": "x=y"}
    assert parse_filter_options(None) == {}


def test_parse_filter_options_rejects_bad_input():
    import pytest

    with pytest.raises(typer.Exit):
        parse_filter_options(["novalue"])
    with pytest.raises(typer.Exit):
        parse_filter_options(["=v"])
