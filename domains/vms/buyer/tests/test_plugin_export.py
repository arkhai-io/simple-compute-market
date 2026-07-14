"""The VM buyer CLI is a schema plugin on the core `market` skeleton.

Covers both halves of the flip: the entry-point metadata actually resolves
to our plugin (what the installed core console script relies on), and the
assembled app exposes the full VM verb surface.
"""

from __future__ import annotations

from typer.testing import CliRunner

from core_buyer.plugins import BuyerSchemaPlugin, discover_plugins
from domains.vms.buyer.cli import app, plugin

runner = CliRunner()


def test_entry_point_discovery_finds_vm_plugin():
    discovered = {p.schema_id: p for p in discover_plugins()}
    assert "vms.compute" in discovered, (
        "market.buyer_plugins entry point for the VM schema is not "
        "installed — `market` (core_buyer.cli:main) would fall back to "
        "the generic no-plugin CLI"
    )
    assert discovered["vms.compute"].distribution == "arkhai-vms-buyer"


def test_plugin_is_well_formed():
    assert isinstance(plugin, BuyerSchemaPlugin)
    assert plugin.schema_id == "vms.compute"


def test_assembled_app_exposes_vm_verbs():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0, result.output
    for name in (
        "buy", "negotiate", "settle",
        "listing", "config", "logs", "escrow", "network", "chain",
        "plugins",
    ):
        assert name in result.output, f"missing command {name!r}"


def test_assembled_listing_is_vm_rendering_not_generic_fallback():
    # The VM listing group documents the compute convenience flags; the
    # generic core fallback only has --filter passthrough.
    result = runner.invoke(app, ["listing", "list", "--help"])
    assert result.exit_code == 0, result.output
    assert "--gpu-model" in result.output
    assert "--filter" in result.output


def test_version_reports_plugin():
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "vms.compute" in result.output
    assert "arkhai-vms-buyer" in result.output
