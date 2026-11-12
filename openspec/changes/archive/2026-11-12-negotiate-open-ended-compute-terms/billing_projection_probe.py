"""Replay installed projections and neutral period quotes without rate service I/O."""

from __future__ import annotations

import runpy
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

from arkhai_vms import make_vm_provision_terms
from arkhai_vms_buyer.negotiation_amounts import amount_codec
from arkhai_vms_buyer.settlement_composition import buyer_settlement_registry
from arkhai_vms_negotiation.amounts import quote_from_multiplier, selected_billing_basis
from arkhai_vms_negotiation.storefront_round import _seller_reference_amount
from market_arkhai_payments import create_arkhai_payments_registration
from market_core.schemas import PriceBasis, SettlementOption, derive_settlement_option_id
from market_settlement_runtime import SettlementConfigurationRegistry


def refuses(call, fragment):
    try:
        call()
    except ValueError as exc:
        assert fragment in str(exc), str(exc)
    else:
        raise AssertionError("expected refusal: " + fragment)


def main():
    source = runpy.run_path(str(Path(__file__).with_name("codec_probe.py")))
    outcome, _, publication = source["probe"]()
    agreement = outcome.agreement
    installed = buyer_settlement_registry()
    quote = installed.agreed_price(agreement)
    assert (quote.amount, quote.unit, quote.period) == (5000000, "total", None)
    # Projection needs no current config or readiness: an accepted deal survives
    # disabling offers, while a registration without a projector fails closed.
    registration = create_arkhai_payments_registration()
    missing = SettlementConfigurationRegistry((replace(registration, project_billing=None),))
    refuses(lambda: missing.agreed_price(agreement), "no billing projection")
    unsupported = agreement.settlement.model_dump(mode="json", exclude_none=True)
    unsupported.pop("option_id")
    unsupported["settlement"]["period"] = "PT1M"
    unsupported["option_id"] = derive_settlement_option_id(**unsupported)
    rate = SettlementOption.model_validate(unsupported)
    refuses(lambda: installed.project_billing(rate), "Extra inputs")
    print("installed once projection; absent projector and unsupported rate parameters refused: PASS")

    listing = {
        **publication,
        "seller_principal": source["SELLER"].identity.model_dump(mode="json"),
        "listing_resource": {"vcpu_count": 4, "region": "California, US", "sla": 99.9,
                             "pool_id": "public-development-pool"},
        "rate_structure": {"cpu": [{"asset": "USD/6", "rate": "2.5", "per": "hour"}]},
    }
    for period, seconds, expected in (("PT15M", 900, 625000), ("PT1M", 60, 41667)):
        # This installed proposed projection is an injected neutral contract,
        # not evidence that the hosted payments adapter supports rates.
        projected = SettlementConfigurationRegistry((replace(
            registration, project_billing=lambda option: PriceBasis(
                unit="per_period", period=period, period_seconds=seconds,
            ),
        ),))
        fields = deepcopy(unsupported)
        fields.pop("option_id")
        fields["settlement"]["period"] = period
        option = SettlementOption(option_id=derive_settlement_option_id(**fields), **fields)
        listing["settlement_options"] = [option.model_dump(mode="json")]
        proposal = {"fields": {"amount": "10000"}, "settlement_selection": {
            "option_id": option.option_id, "settlement": {"schema": option.settlement_schema},
        }}
        basis = selected_billing_basis(listing, proposal, projected.project_billing)
        assert quote_from_multiplier(listing, proposal, 10000, 7200, price_basis=basis) == expected
        codec = amount_codec(listing, proposal, project_billing=projected.project_billing)
        for horizon in (7200, 172800):
            terms = make_vm_provision_terms(
                duration_seconds=horizon, ssh_public_key="ssh-ed25519 public-development-fixture",
                compute_resource={"vcpu_count": 4},
            )
            assert codec.payment_from_scalar(10000, terms) == expected
        raw = agreement.model_dump(mode="json")
        raw.update(settlement=option.model_dump(mode="json"), amount=str(expected))
        accepted = projected.agreed_price(raw)
        assert (accepted.amount, accepted.period_seconds, accepted.unit) == (expected, seconds, "per_period")
        flat = {**listing, "rate_structure": None}
        assert _seller_reference_amount(flat, 7200, proposal=proposal, price_basis=basis) == 2500000 * seconds // 3600
    print("VM buyer codec and exact multiplier quote use one injected period, not horizon: PASS")
    print("upward final rounding and accepted per-period labels: PT15M=625000, PT1M=41667: PASS")
    print("LIMIT: no proof-binding enforcement, hosted rate materialization, approval or deployment")


if __name__ == "__main__":
    main()
