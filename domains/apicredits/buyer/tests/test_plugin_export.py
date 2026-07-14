"""The API-credits buyer CLI is a schema plugin on the core `market` skeleton.

Covers both halves: the entry-point metadata actually resolves to our
plugin (what the installed core console script relies on), and the
assembled app exposes the namespaced `credits` verb surface — this
plugin claims no bare verbs, so it composes with the VM plugin in one
binary without shadowing.
"""

from __future__ import annotations

from typer.testing import CliRunner

from core_buyer.plugins import BuyerSchemaPlugin, discover_plugins
from domains.apicredits.buyer.cli import app, plugin

runner = CliRunner()


def test_entry_point_discovery_finds_apicredits_plugin():
    discovered = {p.schema_id: p for p in discover_plugins()}
    assert "api_credits" in discovered, (
        "market.buyer_plugins entry point for the API-credits schema is "
        "not installed — `market` (core_buyer.cli:main) would fall back "
        "to the generic no-plugin CLI"
    )
    assert discovered["api_credits"].distribution == "arkhai-apicredits-buyer"


def test_plugin_is_well_formed():
    assert isinstance(plugin, BuyerSchemaPlugin)
    assert plugin.schema_id == "api_credits"


def test_assembled_app_exposes_credits_group_only():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0, result.output
    assert "credits" in result.output
    # Bare verbs stay core fallbacks (the plugin claims none of them):
    # the stubs exist but belong to core, so a VM plugin installed
    # alongside can claim them without collision.
    result = runner.invoke(app, ["credits", "--help"])
    assert result.exit_code == 0, result.output
    for name in ("buy", "negotiate", "settle", "listing"):
        assert name in result.output, f"missing credits command {name!r}"


def test_buy_surface_has_quantity_key_and_scalar_price_flags():
    result = runner.invoke(app, ["credits", "buy", "--help"])
    assert result.exit_code == 0, result.output
    for flag in ("--quantity", "--new-key", "--key-id", "--service-name",
                 "--initial-price", "--max-price"):
        assert flag in result.output, f"missing flag {flag!r}"


def test_listing_surface_is_token_rendering_not_generic_fallback():
    result = runner.invoke(app, ["credits", "listing", "list", "--help"])
    assert result.exit_code == 0, result.output
    assert "--service-name" in result.output
    assert "--filter" in result.output


def test_version_reports_plugin():
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "api_credits" in result.output
    assert "arkhai-apicredits-buyer" in result.output
