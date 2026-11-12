"""Replay the shared rights policy and disclosure through each buyer's contexts.

The proposed rate capabilities below are explicitly injected diagnostic data,
not capabilities of the installed payments adapter. No approval, mandate or
external service is invoked. All identities are public development fixtures.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
from dataclasses import replace

from market_core.schemas import SettlementOption, derive_settlement_option_id
from market_deal_lifecycle.selection import AuthoritySelection
from market_settlement_runtime.buyer_terms import ALL_TERM_WAIVERS, BuyerTermsPolicy, lifecycle_disclosure

from market_arkhai_mediation.contract import INTERFACE as MEDIATION_INTERFACE
from market_arkhai_payments.fixtures import dispute_lifecycle
from market_deal_lifecycle.configuration import DisputeEntry

MECHANISM = "arkhai.payments.v1"
PAYEE = "22222222-2222-4222-8222-222222222222"
ENTRY = DisputeEntry.model_validate({
    **dispute_lifecycle("33333333-3333-4333-8333-333333333333")["adjudication"]["dispute"],
    "interface": MEDIATION_INTERFACE,
    "advertisement": {"mechanisms": [MECHANISM],
                      "minimum_dispute_window_seconds": 60,
                      "minimum_case_hold_seconds": None},
})


def option(*, deadline=True, early=None, mechanism=MECHANISM):
    body = {
        "price": {"asset": "USD/6", "rates": [{"field": "amount", "per": "hour", "value": "2500000"}]},
        "settlement": {"schema": mechanism, "payee_account": PAYEE,
                       **({"period": "PT15M", "reserve_ahead_seconds": 1800} if early else {})},
    }
    if mechanism == MECHANISM:
        body["lifecycle"] = {
            "adjudication": {
                "version": 1, "dispute": ENTRY.authority.model_dump(mode="json"),
                "dispute_window_seconds": 604800, "case_hold_max_seconds": None,
            },
            **({"delivery_deadline_seconds": 1200} if deadline else {}),
            **({"early_termination": early} if early else {}),
        }
    return SettlementOption(option_id=derive_settlement_option_id(**body), **body)


PARSER = argparse.ArgumentParser(description=__doc__)
PARSER.add_argument("domain", choices=("vm", "bare"))
ARGS = PARSER.parse_args()
if ARGS.domain == "vm":
    from arkhai_vms_buyer.settlement_composition import buyer_term_context
else:
    from arkhai_bare_metal_buyer.settlement_composition import buyer_term_context


def main():
    args = ARGS
    # These are proposed fixture capabilities, not an installed hosted rate lane.
    def policy(*, waive=False, support=True):
        waivers = ALL_TERM_WAIVERS if waive else frozenset()
        context = replace(
            buyer_term_context(MECHANISM, waivers=waivers),
            has_stoppable_part=True,
            supported_partial_periods=frozenset({"charged", "returned"}) if support else frozenset({"charged"}),
        )
        return BuyerTermsPolicy(
            AuthoritySelection({"": (ENTRY,)}, contexts={MECHANISM: context}),
            waivers=waivers,
        )

    early = {
        "version": 1,
        "entitlements": {"payer": {"notice_seconds": 0, "settles_through": "started_period"}},
        "settles_through": "last_boundary", "premature_stop_penalty": "15000000",
    }
    spot = deepcopy(early)
    spot["entitlements"]["payee"] = {"notice_seconds": 120, "settles_through": "last_boundary"}
    no_penalty = {key: value for key, value in early.items() if key != "premature_stop_penalty"}
    charged_end = {**early, "settles_through": "started_period"}
    charged_seller = deepcopy(spot)
    charged_seller["entitlements"]["payee"]["settles_through"] = "started_period"
    candidates = {
        "hosted once": option(),
        "on-demand": option(early=early),
        "spot": option(early=spot),
        "no penalty": option(early=no_penalty),
        "no deadline": option(deadline=False),
        "charged term end": option(early=charged_end),
        "charged seller stop": option(early=charged_seller),
        "Alkahest no promise": option(mechanism="alkahest.v1"),
    }
    for name, selected in candidates.items():
        expected_refusal = name in {"no penalty", "no deadline", "charged term end", "charged seller stop"}
        try:
            policy().rank(selected)
            assert not expected_refusal, name
            print(f"{args.domain}: {name}: selected")
        except ValueError as exc:
            assert expected_refusal, (name, str(exc))
            print(f"{args.domain}: {name}: refused: {exc}")
            policy(waive=True).rank(selected)
            print("  explicit waiver: selectable; codec/authority checks remain")
        context = buyer_term_context(selected.settlement_schema)
        rows = lifecycle_disclosure(selected, context=context)
        for key, value in rows:
            print(f"  {key}: {value}")
    try:
        policy(waive=True, support=False).rank(candidates["on-demand"])
    except ValueError as exc:
        assert "unsupported" in str(exc)
        print("waiver cannot bypass an unsupported returned treatment: PASS")
    else:
        raise AssertionError("waiver bypassed installed capabilities")
    print("PROPOSED RIGHTS/DISCLOSURE FIXTURE ONLY: no live rate, mandate, approval or lease")


if __name__ == "__main__":
    main()
