"""The cached-acceptance door for a selected rate option.

A buyer selects an option from the listing record the storefront published, and
that record can hold a rate option the servicing declaration in force does not
qualify: one published before a restart under a narrower declaration. The
negotiation runtime refuses such a selection, asking for a refetch, before the
seller's round runs or any negotiation is written. The record is seeded as
service-internal state. The refusal comes before any recurring encoder, term
timing or billing projection is read, so the runtime runs with none of them
composed.
"""

from __future__ import annotations

import sqlite3
from unittest.mock import AsyncMock

import pytest
from market_core.schemas import (
    ProvisionTerms,
    RateValue,
    SettlementOption,
    SettlementPrice,
    derive_settlement_option_id,
)
from market_deal_lifecycle.terms import (
    Adjudication, DisputeAuthority, EarlyTermination, Entitlement, LifecycleTerms, encode_terms,
)
from market_negotiation_runtime import OfferUnfulfillableError
from market_settlement_runtime.rate_servicing import RateServicing, RateServicingDeclaration

from tests.unit.test_sync_negotiation_seller_round_hook import (  # noqa: F401 - db is a fixture
    _BUYER,
    _SELLER,
    _start,
    db,
)

MECHANISM = "arkhai.payments.v1"
# A fictional authority: the origin is a reserved name that resolves nowhere.
_AUTHORITY = DisputeAuthority(
    interface="fixture.mediation.v1", origin="https://mediation.invalid",
    account="fixture-account", record_key="fixture-record", params={},
)
#: A development payee account; never used on a public network.
_PAYEE = "22222222-2222-4222-8222-222222222222"


def _on_demand_option() -> dict:
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
    price = SettlementPrice(asset="USD/6", rates=[RateValue(field="amount", per="hour", value=2_500_000)])
    settlement = {
        "schema": MECHANISM, "payee_account": _PAYEE, "window": "PT5M",
        "period": "PT15M", "reserve_ahead_seconds": 1800,
    }
    return SettlementOption(
        option_id=derive_settlement_option_id(price=price, settlement=settlement, lifecycle=lifecycle),
        price=price, settlement=settlement, lifecycle=lifecycle,
    ).model_dump(mode="json")


def _thread_count(db) -> int:
    with sqlite3.connect(db.db_path) as connection:
        return connection.execute("SELECT COUNT(*) FROM negotiation_threads").fetchone()[0]


async def _refused(db, rate_servicing: RateServicing | None) -> OfferUnfulfillableError:
    option = _on_demand_option()
    await db.update_listing(listing_id="L-hook", settlement_options=[option])
    hook = AsyncMock()
    with pytest.raises(OfferUnfulfillableError) as refused:
        await _start(
            sqlite_client=db, our_listing_id="L-hook",
            buyer_principal=_BUYER, seller_principal=_SELLER,
            proposal={
                "fields": {"amount": 625_000},
                "settlement_selection": {
                    "option_id": option["option_id"],
                    "settlement": {"schema": MECHANISM, "payer_account": _PAYEE},
                    "expiration_unix": 1_800_000_000,
                },
            },
            provision_terms=ProvisionTerms(kind="compute.v1", version=1, payload={
                "duration_seconds": 3600, "ssh_public_key": "ssh-ed25519 AAAA",
            }),
            our_base_url="http://seller.test", their_agent_url="http://buyer.test",
            seller_round_hook=hook, rate_servicing=rate_servicing,
        )
    hook.assert_not_awaited()
    assert _thread_count(db) == 0
    return refused.value


@pytest.mark.asyncio
async def test_a_selected_rate_option_whose_treatment_is_withdrawn_is_refused_and_nothing_is_kept(db):
    narrowed = RateServicing({MECHANISM: RateServicingDeclaration(MECHANISM, frozenset({"charged"}), False)})
    refusal = await _refused(db, narrowed)

    assert "settlement_option_withdrawn_refetch" in str(refusal)
    assert "does not declare returned" in str(refusal)


@pytest.mark.asyncio
async def test_a_selected_rate_option_under_no_declaration_is_refused_and_nothing_is_kept(db):
    refusal = await _refused(db, None)

    assert "settlement_option_withdrawn_refetch: rate servicing is undeclared" in str(refusal)
