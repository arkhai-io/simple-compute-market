"""The API-credit buyer CLI contributes a validated market-domain contract."""

from __future__ import annotations

from typer.testing import CliRunner

from core_buyer.plugins import discover_domains
from domains.apicredits.buyer.cli import app, domain
from market_core import DomainCapability, MarketDomainContract

runner = CliRunner()


def test_entry_point_discovery_finds_api_credit_domain():
    discovered = {item.identity: item for item in discover_domains()}
    assert "api_credits.v1" in discovered


def test_domain_is_well_formed_without_compute_capability():
    assert isinstance(domain, MarketDomainContract)
    assert domain.identity == "api_credits.v1"
    assert domain.has_capability(DomainCapability.BUYER)
    assert not domain.has_capability(DomainCapability.COMPUTE_PROVISIONING)
    assert domain.compute_provisioning is None


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
    for flag in (
        "--quantity", "--new-key", "--key-id", "--resource",
        "--initial-price", "--max-price",
    ):
        assert flag in result.output, f"missing flag {flag!r}"


def test_listing_surface_uses_typed_resource_query():
    result = runner.invoke(app, ["credits", "listing", "list", "--help"])
    assert result.exit_code == 0, result.output
    assert "--resource" in result.output
    assert "--service-name" not in result.output
    assert "--filter" not in result.output


def test_version_reports_domain_contract():
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "api_credits.v1" in result.output
    assert "contract 1.0" in result.output
