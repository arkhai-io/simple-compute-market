"""`negotiate` and `buy` open in multiplier mode on a registry listing, with a shape.

The registry serves a shape-priced listing's family rates only in its pricing;
each command's registry boundary hands the VM codec a domain record it reads in
basis points. ``--shape`` fills the opening terms' ``compute_resource``, anchors
the codec's bounds to that shape, and is recorded in the run log.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from arkhai_vms import make_vm_provision_terms
from core_buyer.negotiation_client import NegotiationOutcome as CoreNegotiationOutcome
from core_buyer.registry_config import RegistryAuthority
from core_buyer.run_log import read_run, runs_dir
from market_config.config_loader import ChainConfig
from market_policy.negotiation_middleware import NegotiationRound
from typer.testing import CliRunner

from arkhai_vms_buyer.buy_orchestrator import BuyResult
from arkhai_vms_buyer.buyer_client import ResumeState, negotiate_with_seller
from arkhai_vms_buyer.cli import app
from arkhai_vms_buyer.registry_listing import domain_listing_record
from identity_helpers import seller_principals
from test_buy_resume_cli import _RESOLVED
from test_negotiation_amounts import RATE_STRUCTURE, selection
from test_opening_shape import registry_listing

#: Asset decimals the stubbed token resolution reports: a whole-token price of
#: 10 is 1,000 base units, the advertised shape's hourly rate.
DECIMALS = 2


def _served(listing_id: str = "L-shape", **resource) -> dict:
    listing = registry_listing()
    listing["listing_id"] = listing_id
    listing["listing_resource"] = {**listing["listing_resource"], **resource}
    return listing


@pytest.fixture
def buyer_env(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    monkeypatch.setattr("arkhai_vms_buyer.common.resolve_fresh_buyer_identity", lambda: _RESOLVED)
    monkeypatch.setattr("arkhai_vms_buyer.common.resolve_registry_authorities", lambda urls: {
        url: RegistryAuthority(authority="registry", principals=seller_principals())
        for url in urls
    })
    monkeypatch.setattr(
        "arkhai_vms_buyer.common.resolve_indexer_urls_for_schema",
        lambda _schema, **kw: list(kw["registry_authorities"]),
    )
    monkeypatch.setattr("arkhai_vms_buyer.common.resolve_registry_api_keys", lambda: {})
    monkeypatch.setattr("arkhai_vms_buyer.common.resolve_negotiation_config", lambda: (None, None))
    monkeypatch.setattr(
        "arkhai_vms_buyer.negotiate_cli.resolve_negotiation_config", lambda: (None, None)
    )
    monkeypatch.setattr("arkhai_vms_buyer.settlement_composition.load_user_config", lambda: {
        "Settlement": {
            "schema_version": 1, "priority": ["alkahest.v1"], "alkahest": {"enabled": True},
        },
    })
    monkeypatch.setattr("arkhai_vms_buyer.common.chain_by_name", lambda name: ChainConfig(
        name=name, rpc_url="http://rpc", chain_id=31337,
    ))
    monkeypatch.setattr(
        "arkhai_vms_buyer.common.resolve_buyer_wallet", lambda **_kw: ("address", "key")
    )
    token = SimpleNamespace(decimals=DECIMALS)
    monkeypatch.setattr("arkhai_vms_buyer.settlement_stages.resolve_token", lambda *a, **kw: token)
    monkeypatch.setattr("arkhai_vms_buyer.buy_cli.resolve_token", lambda *a, **kw: token)
    captured: dict = {}

    def negotiate(**fields):
        captured.update(fields)
        return CoreNegotiationOutcome(
            status="exited", negotiation_id="neg-1", reason="controlled stop", rounds=0,
        )

    # The VM wrapper and the buy stage both reach core's negotiation here, so
    # the codec each builds is the one observed.
    monkeypatch.setattr("arkhai_vms_buyer.buyer_client._core_negotiate_with_seller", negotiate)
    monkeypatch.setattr("core_buyer.orchestration.negotiate_with_seller", negotiate)
    monkeypatch.setattr(
        "core_buyer.orchestration.make_publisher_trust_resolver",
        lambda **_kw: seller_principals,
    )
    return captured


def _run_started() -> dict:
    (path,) = runs_dir().glob("*.jsonl")
    return next(event for event in read_run(path.stem) if event["event"] == "run_started")


# --- market negotiate -------------------------------------------------------


#: Explicit whole-token prices; a test of derived prices passes none.
PRICES = ("--initial-price", "8", "--max-price", "10")


def _negotiate(monkeypatch, listing, *extra, prices=PRICES):
    monkeypatch.setattr(
        "arkhai_vms_buyer.negotiate_cli.fetch_listing_dict", lambda *a, **kw: dict(listing)
    )
    return CliRunner().invoke(app, [
        "negotiate", "--listing-id", listing["listing_id"],
        "--registry-urls", "http://registry", "--duration-hours", "1",
        "--ssh-public-key", "ssh-ed25519 AAAA", "--yes", *prices, *extra,
    ])


def test_negotiate_reads_a_registry_listings_rates_in_basis_points(buyer_env, monkeypatch):
    result = _negotiate(monkeypatch, _served())
    assert result.exit_code == 4, (result.output, result.exception)
    codec = buyer_env["amount_codec"]
    assert codec is not None
    assert codec.scalar_from_price(buyer_env["max_price"]) == 10_000
    assert _run_started()["listing_record"]["rate_structure"] == RATE_STRUCTURE


def test_negotiate_opens_with_the_shape_and_anchors_its_bounds_to_it(buyer_env, monkeypatch):
    result = _negotiate(monkeypatch, _served(), "--shape", "vcpu_count=4")
    assert result.exit_code == 4, (result.output, result.exception)
    assert buyer_env["provision_terms"].compute_resource == {"vcpu_count": 4}
    # Four of eight vCPUs: the shape prices at 800 an hour, so a 1,000 ceiling
    # is 1.25 times what the buyer opens with.
    assert buyer_env["amount_codec"].scalar_from_price(buyer_env["max_price"]) == 12_500
    assert _run_started()["compute_resource"] == {"vcpu_count": 4}


@pytest.mark.parametrize("shape,hourly", [((), 1000), (("--shape", "vcpu_count=4"), 800)])
def test_negotiate_derives_its_prices_for_the_shape_it_opens_with(
    buyer_env, monkeypatch, shape, hourly,
):
    result = _negotiate(monkeypatch, _served(), *shape, prices=())
    assert result.exit_code == 4, (result.output, result.exception)
    # Derived prices open and bound at the advertised minimum for the shape
    # asked for: four of eight vCPUs price at 800 an hour, not the listing's 1,000.
    assert buyer_env["initial_price"] == buyer_env["max_price"] == hourly
    assert buyer_env["amount_codec"].scalar_from_price(buyer_env["max_price"]) == 10_000


def test_negotiate_refuses_a_shape_above_the_advertised_one(buyer_env, monkeypatch):
    result = _negotiate(monkeypatch, _served(), "--shape", "vcpu_count=16")
    assert result.exit_code == 2
    assert "vcpu_count 16 exceeds the advertised 8" in result.output
    assert not buyer_env


def test_a_resumed_negotiation_anchors_its_bounds_to_the_recorded_opening(buyer_env):
    listing = domain_listing_record(_served())
    # The seller's round-zero echo the run log recorded: the complete shape.
    echo = make_vm_provision_terms(
        duration_seconds=3600, ssh_public_key="",
        compute_resource={"gpu_model": "H200", "gpu_count": 1, "vcpu_count": 4},
    ).model_dump(mode="json")
    opening = {"fields": {"amount": "8000"}, "settlement_selection": selection(listing)}
    negotiate_with_seller(
        seller_url="http://seller.test", principal=_RESOLVED.principal,
        signer=_RESOLVED.signer, listing_id="L-shape", listing=listing,
        initial_price=800, max_price=1000,
        resume=ResumeState(
            negotiation_id="neg-1",
            transcript=[NegotiationRound(
                round_number=0, sender="us", action="initial", proposal=opening,
            )],
            last_seller_proposal={**opening, "fields": {"amount": "10000"}},
            rounds_completed=1,
            accepted_provision_terms=echo,
        ),
        resolve_seller_principals=seller_principals,
    )
    assert buyer_env["amount_codec"].scalar_from_price(1000) == 12_500


def test_a_resumed_negotiation_refuses_a_shape(buyer_env):
    result = CliRunner().invoke(app, ["negotiate", "--from", "run-1", "--shape", "vcpu_count=4"])
    assert result.exit_code == 2
    assert "--shape applies only to fresh negotiation" in result.output


# --- market buy -------------------------------------------------------------


def _buy(monkeypatch, listings, *extra, prices=PRICES):
    monkeypatch.setattr(
        "arkhai_vms_buyer.buy_cli.query_registry_for_matches_multi",
        lambda *a, **kw: [dict(listing) for listing in listings],
    )
    events: list[tuple[str, dict]] = []
    tried: list[list[dict]] = []

    def run_buy(**kwargs):
        tried.append(kwargs["matches"])
        kwargs["negotiate"](kwargs["matches"], lambda stage, body: events.append((stage, body)))
        return BuyResult(status="exited", reason="controlled stop")

    monkeypatch.setattr("arkhai_vms_buyer.buy_cli.run_buy", run_buy)
    result = CliRunner().invoke(app, [
        "buy", "--registry-urls", "http://registry", "--duration-hours", "1",
        "--ssh-public-key", "ssh-ed25519 AAAA", "--yes", "--max-matches", "1",
        *prices, *extra,
    ])
    return result, tried, events


def test_buy_reads_a_registry_listings_rates_in_basis_points(buyer_env, monkeypatch):
    result, _, events = _buy(monkeypatch, [_served()])
    assert result.exit_code == 4, (result.output, result.exception)
    codec = buyer_env["amount_codec"]
    assert codec is not None
    assert codec.scalar_from_price(buyer_env["max_price"]) == 10_000
    started = next(body for stage, body in events if stage == "negotiation_started")
    assert started["listing_record"]["rate_structure"] == RATE_STRUCTURE


def test_buy_opens_with_the_shape_and_caps_payment_at_the_ceiling(buyer_env, monkeypatch):
    result, _, _ = _buy(monkeypatch, [_served()], "--shape", "vcpu_count=4")
    assert result.exit_code == 4, (result.output, result.exception)
    assert buyer_env["provision_terms"].compute_resource == {"vcpu_count": 4}
    codec = buyer_env["amount_codec"]
    assert codec.scalar_from_price(buyer_env["max_price"]) == 12_500
    advertised = {
        "kind": "compute.v1", "version": 1, "payload": {
            "duration_seconds": 3600, "ssh_public_key": "ssh-ed25519 AAAA",
            "compute_resource": {"gpu_model": "H200", "gpu_count": 1, "vcpu_count": 8},
        },
    }
    # At the buyer's scalar ceiling, the advertised shape would cost 1,250 an
    # hour against the buyer's 1,000.
    with pytest.raises(RuntimeError, match="exceeds the buyer's ceiling"):
        codec.payment_from_scalar(12_500, advertised)
    assert _run_started()["compute_resource"] == {"vcpu_count": 4}


@pytest.mark.parametrize("shape,hourly", [((), 1000), (("--shape", "vcpu_count=4"), 800)])
def test_buy_derives_its_prices_for_the_shape_it_opens_with(
    buyer_env, monkeypatch, shape, hourly,
):
    result, _, _ = _buy(monkeypatch, [_served()], *shape, prices=())
    assert result.exit_code == 4, (result.output, result.exception)
    assert buyer_env["initial_price"] == buyer_env["max_price"] == hourly
    assert buyer_env["amount_codec"].scalar_from_price(buyer_env["max_price"]) == 10_000


def test_buy_skips_a_listing_that_cannot_price_the_shape(buyer_env, monkeypatch):
    unpriceable = _served("L-other-asset")
    # Family rates in another asset than the selected option's price nothing.
    unpriceable["pricing"] = {"rate_structure": {
        "gpu": [{"asset": "usd", "rate": "60", "per": "hour"}],
    }}
    result, tried, _ = _buy(
        monkeypatch, [unpriceable, _served()], "--shape", "vcpu_count=4", prices=(),
    )
    assert result.exit_code == 4, (result.output, result.exception)
    assert [match["listing_id"] for match in tried[0]] == ["L-shape"]
    assert "L-other-asset: shape_price_unavailable" in result.output
    assert buyer_env["max_price"] == 800


def test_buy_skips_a_listing_smaller_than_the_shape(buyer_env, monkeypatch):
    small, large = _served("L-small"), _served("L-large", vcpu_count=16)
    result, tried, _ = _buy(monkeypatch, [small, large], "--shape", "vcpu_count=12")
    assert result.exit_code == 4, (result.output, result.exception)
    assert [match["listing_id"] for match in tried[0]] == ["L-large"]
    assert "L-small: vcpu_count 12 exceeds the advertised 8" in result.output


def test_buy_refuses_a_shape_above_every_listing(buyer_env, monkeypatch):
    result, tried, _ = _buy(monkeypatch, [_served()], "--shape", "vcpu_count=16")
    assert result.exit_code == 2
    assert "exceeds every matching listing's" in result.output
    assert "vcpu_count 16 exceeds the advertised 8" in result.output
    assert not tried


def test_a_resumed_buy_refuses_a_shape(buyer_env):
    result = CliRunner().invoke(app, ["buy", "--from", "run-1", "--shape", "vcpu_count=4"])
    assert result.exit_code == 2
    assert "--shape applies only to fresh buys" in result.output
