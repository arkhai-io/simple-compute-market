"""The VM buyer CLI contributes a validated market-domain contract."""

from __future__ import annotations

from core_buyer.plugins import discover_domains
from arkhai_vms_buyer import cli as buyer_cli
from arkhai_vms_buyer.cli import app, domain
from market_settlement_runtime import MechanismReadiness, SettlementConfig
from market_core import DomainCapability, MarketDomainContract
from typer.testing import CliRunner

from arkhai_vms_buyer.cli import app, domain

runner = CliRunner()


def test_entry_point_discovery_finds_vm_domain():
    discovered = {item.identity: item for item in discover_domains()}
    assert "compute.v1" in discovered


def test_domain_is_well_formed():
    assert isinstance(domain, MarketDomainContract)
    assert domain.identity == "compute.v1"
    assert domain.has_capability(DomainCapability.BUYER)
    assert domain.buyer.identity_injection_contract == "core.resolved-buyer-identity.v1"


def test_assembled_app_exposes_vm_verbs():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0, result.output
    for name in (
        "buy",
        "negotiate",
        "settle",
        "listing",
        "config",
        "logs",
        "settlement",
        "network",
        "plugins",
    ):
        assert name in result.output, f"missing command {name!r}"
    assert "profile" in result.output


def test_assembled_listing_uses_typed_resource_query() -> None:
    result = runner.invoke(app, ["listing", "list", "--help"])
    assert result.exit_code == 0, result.output
    assert "--resource" in result.output
    assert "--settlement" in result.output
    assert "--gpu-model" not in result.output
    assert "--filter" not in result.output


def test_version_reports_domain_contract():
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "compute.v1" in result.output
    assert "contract 1.0" in result.output

def test_raw_settlement_utilities_are_mechanism_namespaced() -> None:
    status = runner.invoke(app, ["settlement", "status", "--help"])
    nested = runner.invoke(app, ["settlement", "alkahest", "escrow", "--help"])
    legacy_escrow = runner.invoke(app, ["escrow", "--help"])
    legacy_chain = runner.invoke(app, ["chain", "--help"])

    assert status.exit_code == 0, status.output
    assert nested.exit_code == 0, nested.output
    assert legacy_escrow.exit_code == 2
    assert legacy_chain.exit_code == 2
