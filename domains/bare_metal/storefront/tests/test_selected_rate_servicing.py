"""The cached-acceptance door for a selected rate option.

A buyer selects an option from the listing record the storefront published, and
that record can hold a rate option the servicing declaration in force does not
qualify: one published before a restart under a narrower declaration. The
negotiation runtime refuses such a selection with a 409 asking for a refetch, and
keeps nothing. The record is seeded as service-internal state. The refusal comes
before any recurring encoder, term timing or billing projection is read, so the
runtime runs with none of them composed.
"""

from __future__ import annotations

from typing import Any

import pytest
from market_core.schemas import RateValue, SettlementOption, SettlementPrice, derive_settlement_option_id
from market_deal_lifecycle.terms import (
    Adjudication, DisputeAuthority, EarlyTermination, Entitlement, LifecycleTerms, encode_terms,
)
from market_settlement_runtime.rate_servicing import RateServicing, RateServicingDeclaration

from arkhai_bare_metal_storefront.negotiation_runtime import BareMetalNegotiationRefusal
from test_selection_dispatch import (
    BUYER_SIGNER,
    PAYMENT_MECHANISM,
    _nothing_accepted,
    _payment_service,
    _request,
    _ssh_purchase,
)

# A fictional authority: the origin is a reserved name that resolves nowhere.
_AUTHORITY = DisputeAuthority(
    interface="fixture.mediation.v1", origin="https://mediation.invalid",
    account="fixture-account", record_key="fixture-record", params={},
)


def _on_demand_option() -> dict[str, Any]:
    """A rate option whose payer's stop charges its started period and whose term
    end returns the last one."""
    lifecycle = encode_terms(LifecycleTerms(
        adjudication=Adjudication(version=1, dispute=_AUTHORITY, dispute_window_seconds=604800,
                                  case_hold_max_seconds=None),
        early_termination=EarlyTermination(version=1, settles_through="last_boundary", entitlements={
            "payer": Entitlement(notice_seconds=0, settles_through="started_period"),
        }),
        delivery_deadline_seconds=1200,
    ))
    price = SettlementPrice(asset="usd", rates=[RateValue(field="amount", per="hour", value=1_000_000)])
    settlement = {"schema": PAYMENT_MECHANISM, "period": "PT15M", "reserve_ahead_seconds": 1800}
    return SettlementOption(
        option_id=derive_settlement_option_id(price=price, settlement=settlement, lifecycle=lifecycle),
        price=price, settlement=settlement, lifecycle=lifecycle,
    ).model_dump(mode="json")


async def _refused(tmp_path, rate_servicing: RateServicing | None) -> BareMetalNegotiationRefusal:
    calls: list = []
    service, option = await _payment_service(
        tmp_path, calls, option=_on_demand_option(), rate_servicing=rate_servicing,
    )
    with pytest.raises(BareMetalNegotiationRefusal) as refused:
        await service.open(
            request=_request(option, payload=_ssh_purchase(3600)),
            buyer_principal=BUYER_SIGNER.identity,
        )
    await _nothing_accepted(service, calls)
    return refused.value


async def test_a_selected_rate_option_whose_treatment_is_withdrawn_is_refused_and_nothing_is_kept(
    tmp_path,
) -> None:
    narrowed = RateServicing({PAYMENT_MECHANISM: RateServicingDeclaration(
        PAYMENT_MECHANISM, frozenset({"charged"}), False,
    )})
    refusal = await _refused(tmp_path, narrowed)

    assert refusal.status_code == 409
    assert "settlement_option_withdrawn_refetch" in refusal.detail
    assert "does not declare returned" in refusal.detail


async def test_a_selected_rate_option_under_no_declaration_is_refused_and_nothing_is_kept(
    tmp_path,
) -> None:
    refusal = await _refused(tmp_path, None)

    assert refusal.status_code == 409
    assert "settlement_option_withdrawn_refetch: rate servicing is undeclared" in refusal.detail
