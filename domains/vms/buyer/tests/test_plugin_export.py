"""The VM buyer CLI contributes a validated market-domain contract."""

from __future__ import annotations

from typer.testing import CliRunner

from core_buyer.plugins import discover_domains
from domains.vms.buyer.cli import app, domain
from market_core import DomainCapability, MarketDomainContract

runner = CliRunner()


def test_entry_point_discovery_finds_vm_domain():
    discovered = {item.identity: item for item in discover_domains()}
    assert "compute.v1" in discovered


def test_domain_is_well_formed():
    assert isinstance(domain, MarketDomainContract)
    assert domain.identity == "compute.v1"
    assert domain.has_capability(DomainCapability.BUYER)


def test_assembled_app_exposes_vm_verbs():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0, result.output
    for name in (
        "buy", "negotiate", "settle",
        "listing", "config", "logs", "escrow", "network", "chain",
        "plugins",
    ):
        assert name in result.output, f"missing command {name!r}"


def test_assembled_listing_uses_typed_resource_query() -> None:
    result = runner.invoke(app, ["listing", "list", "--help"])
    assert result.exit_code == 0, result.output
    assert "--resource" in result.output
    assert "--gpu-model" not in result.output
    assert "--filter" not in result.output


def test_version_reports_domain_contract():
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "compute.v1" in result.output
    assert "contract 1.0" in result.output
