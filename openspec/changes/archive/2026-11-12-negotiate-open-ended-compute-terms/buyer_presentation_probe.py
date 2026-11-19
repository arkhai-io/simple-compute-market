"""Invocation-local price/horizon disclosure replay using proposed payment ports.

No HTTP service, mandate, approval, stop or lease is created. The diagnostic's
rate/setup/reserve parser below is a proposed mechanism owner, not buyer code.
"""

from __future__ import annotations

import argparse
import base64
import math
from fractions import Fraction
import runpy
from copy import deepcopy
from dataclasses import replace
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from market_arkhai_payments import create_arkhai_payments_registration
from market_core.schemas import AgreedPrice, PriceBasis, SettlementOption, derive_settlement_option_id
from market_settlement_runtime import SettlementConfigurationRegistry
from market_settlement_runtime.buyer_terms import option_quote
from market_settlement_runtime.presentation import PaymentPresentation

HERE = Path(__file__).parent
PARSER = argparse.ArgumentParser(description=__doc__)
PARSER.add_argument("domain", choices=("vm", "bare"))
ARGS = PARSER.parse_args()
if ARGS.domain == "vm":
    from arkhai_vms import make_vm_provision_terms
    from arkhai_vms_buyer import settlement_composition as composition
    from arkhai_vms_buyer import buy_cli, settle_cli
    from arkhai_vms_buyer.negotiation_amounts import amount_codec, priced_unit_count
    from rich.console import Console
else:
    from arkhai_bare_metal_buyer import settlement_composition as composition
    from arkhai_bare_metal_buyer.settlement_stages import purchase_quote, require_quoted_agreement


def refuses(call, fragment):
    try:
        call()
    except ValueError as exc:
        assert fragment in str(exc), str(exc)
    else:
        raise AssertionError("expected refusal: " + fragment)


def main():
    domain = ARGS.domain
    fixture = runpy.run_path(str(HERE / "codec_probe.py"))
    outcome, _, publication = fixture["probe"]()
    once = outcome.agreement.settlement
    installed = SettlementConfigurationRegistry((create_arkhai_payments_registration(),))
    refuses(lambda: option_quote(once, None, registry=installed), "reserved selections require")
    assert option_quote(once, 7200, registry=installed).amount == 5000000
    body = once.model_dump(mode="json", exclude={"option_id"})
    body["settlement"].update(period="PT15M", reserve_ahead_seconds=1800, setup_amount="750000")
    body["lifecycle"]["early_termination"] = {
        "version": 1, "entitlements": {
            "payer": {"notice_seconds": 0, "settles_through": "started_period"},
        }, "settles_through": "last_boundary", "premature_stop_penalty": "15000000",
    }
    rate = SettlementOption(option_id=derive_settlement_option_id(**body), **body)

    # Only this proposed mechanism owns these diagnostic payment fields.
    def basis(option):
        assert option.settlement_params["period"] == "PT15M"
        return PriceBasis(unit="per_period", period="PT15M", period_seconds=900)

    def present(option, duration, accepted):
        projected = basis(option)
        quote = accepted or AgreedPrice(
            **projected.model_dump(), asset=option.price_asset,
            amount=math.ceil(Fraction(option.price_rates[0].value, 4)),
        )
        return PaymentPresentation(
            quote=quote, setup_once=int(option.settlement_params["setup_amount"]),
            initial_reserve=quote.amount * math.ceil(option.settlement_params["reserve_ahead_seconds"] / 900),
        )

    proposed = SettlementConfigurationRegistry((replace(
        create_arkhai_payments_registration(), project_billing=basis, present_payment=present,
    ),))
    refuses(lambda: installed.project_billing(rate), "Extra inputs")
    missing = SettlementConfigurationRegistry((replace(
        create_arkhai_payments_registration(), project_billing=basis, present_payment=None,
    ),))
    refuses(lambda: missing.present_payment(rate), "no payment presentation")
    for duration in (None, 1801, 43201):
        assert option_quote(rate, duration, registry=proposed).amount == 625000
    listing = {**publication, "max_duration_seconds": 86401, "available_until_utc": "2026-11-08T00:00:01Z"}
    accepted = outcome.agreement.model_copy(update={
        "settlement": rate, "amount": 625000, "duration_seconds": 43201,
    })
    if domain == "vm":
        selected_listing = {
            **listing, "settlement_options": [rate.model_dump(mode="json")],
            "seller_principal": fixture["SELLER"].identity.model_dump(mode="json"),
            "listing_resource": {"vcpu_count": 4, "region": "example", "sla": 99.9, "pool_id": "public-development-pool"},
            "rate_structure": {"cpu": [{"asset": "USD/6", "rate": "2.5", "per": "hour"}]},
        }
        selection = {"option_id": rate.option_id, "settlement": {"schema": rate.settlement_schema}}
        codec = amount_codec(selected_listing, selection, project_billing=basis)
        for duration in (None, 1801, 43201):
            terms = make_vm_provision_terms(duration_seconds=duration, ssh_public_key="ssh-ed25519 public-development-fixture")
            assert codec.payment_from_scalar(10000, terms) == 625000
            assert priced_unit_count(selected_listing, selection, duration, project_billing=basis) == 0.25
        output = StringIO()
        with patch.object(buy_cli.typer, "confirm", return_value=False):
            buy_cli._confirm_settlement_interactive(
                terms=SimpleNamespace(seller_url="https://seller.example", listing_id="example-terms",
                                      negotiation_id="example-negotiation", agreed_amount=625000,
                                      duration_seconds=43201, quote=proposed.agreed_price(accepted)),
                listing={}, console=Console(file=output, width=120, color_system=None),
            )
        assert "per_period (PT15M)" in output.getvalue()
        assert "Total payment" not in output.getvalue()
        print("VM omitted/shorter horizons price one period; confirmation is not labelled total: PASS")
        # Drive the actual accepted recovery entry point, with effects replaced.
        # No listing fetch or current offer is supplied to recovery.
        deal = SimpleNamespace(
            agreement=accepted.model_dump(mode="json"),
            agreement_bytes=base64.b64encode(accepted.model_dump_json().encode()).decode(),
            negotiation_id=accepted.negotiation_id, settlement_selection=None, settlement_plan=None,
        )
        with patch.object(composition, "buyer_settlement_registry", return_value=proposed), \
             patch.object(settle_cli, "load_deal_context", return_value=deal), \
             patch.object(settle_cli, "buyer_stage", return_value=SimpleNamespace(resume=lambda context: {"status": "diagnostic-no-effects"})), \
             patch.object(settle_cli, "open_run_log", return_value=SimpleNamespace(event=lambda *args, **kwargs: None)), \
             patch.object(settle_cli, "make_deal_publisher_trust_resolver", return_value=lambda: None):
            assert settle_cli.run_settle_from_log(
                run_id="diagnostic", poll_interval=1, settlement_timeout=1,
                identity=SimpleNamespace(signer=fixture["SELLER"], profile_id="diagnostic"),
            )["status"] == "diagnostic-no-effects"
        print("VM recovery pre-approval disclosure reads retained accepted bytes, without current listings: PASS")
    else:
        for duration in (None, 1801, 43201):
            assert purchase_quote(rate, duration, registry=proposed) == 625000
        require_quoted_agreement(
            SimpleNamespace(agreement=accepted), amount=625000, duration_seconds=None,
            quote=option_quote(rate, None, registry=proposed), registry=proposed,
        )
        refuses(lambda: require_quoted_agreement(
            SimpleNamespace(agreement=accepted.model_copy(update={"amount": 625001})),
            amount=625000, duration_seconds=None,
            quote=option_quote(rate, None, registry=proposed), registry=proposed,
        ), "differs from the quoted")
        print("bare-metal optional horizon and per-period acceptance hold exact quoted money/unit: PASS")
    with patch.object(composition, "buyer_settlement_registry", return_value=proposed):
        rows = dict(composition.buyer_compute_disclosure(rate, listing=listing))
        assert rows["Class"] == "on-demand"
        assert "625000" in rows["Selected price"] and "per_period (PT15M, 900 seconds)" in rows["Selected price"]
        assert rows["Setup once charge"].startswith("750000")
        assert rows["Initial reserve"].startswith("1250000")
        assert rows["Maximum duration"] == "86401 seconds"
        assert rows["Available until"] == listing["available_until_utc"]
        for key, value in rows.items():
            print(f"{domain} selected {key}: {value}")
        changed_listing = deepcopy(listing)
        changed_listing.update(max_duration_seconds=1, available_until_utc="2000-01-01T00:00:00Z")
        rows = dict(composition.buyer_compute_disclosure(rate, agreement=accepted, listing=changed_listing))
        assert rows["Effective horizon"] == "43201 seconds (not rounded to periods)"
        assert rows["Accepted price"].startswith("625000")
        assert "2000" not in str(rows)
        for key, value in rows.items():
            print(f"{domain} accepted {key}: {value}")
    print("PROPOSED PRESENTATION PORTS ONLY: no live rate, mandate, approval or lease")


if __name__ == "__main__":
    main()
