"""The storefront registers only what the mechanisms it composes contribute."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

from arkhai_api_selling.lifecycle import StorefrontLoops, loop_controller
from market_arkhai_payments import ARKHAI_PAYMENTS_MECHANISM
from market_core import SettlementStageTable

import apicredits_storefront.container as container
from apicredits_storefront.utils import config


def _composed():
    """A lifespan's composition serving payments, over a runtime the backfill reads."""
    return SimpleNamespace(
        servicing={ARKHAI_PAYMENTS_MECHANISM: object()}, runtime=object(),
        local_principal=object(), mechanism_resources={"clients": {"anvil": object()}},
    )


def _tables(monkeypatch, backfill):
    composition = _composed()
    monkeypatch.setattr(container, "resolved_settlement_composition", composition)
    monkeypatch.setattr(container, "resolved_sqlite_client", object())
    alkahest = container.alkahest_stage(backfill_escrows=backfill)
    payments = container.payments_stage()
    return (
        SettlementStageTable({alkahest.mechanism: alkahest}),
        SettlementStageTable({payments.mechanism: payments}),
    )


async def test_an_alkahest_only_storefront_registers_no_payment_loop(monkeypatch):
    alkahest_only, payments_only = _tables(monkeypatch, AsyncMock(return_value=0))

    for table, has_payment_loop in ((alkahest_only, False), (payments_only, True)):
        loops = loop_controller()
        StorefrontLoops(
            sqlite_client=lambda: container.resolved_sqlite_client,
            settlement_worker=lambda: None,
            capacity=container.QUOTA_CAPACITY,
            settings=config.LOOP_SETTINGS,
            contributed_loops=lambda table=table: container.mechanism_loops(table),
        ).register_steps(loops)
        assert ("payment_reconciliation" in loops.step_routes().values()) is has_payment_loop
    assert container.mechanism_health(alkahest_only) == {"alkahest": "anvil"}
    assert container.mechanism_health(payments_only) == {}


async def test_a_payments_only_storefront_runs_no_escrow_backfill(monkeypatch):
    backfill = AsyncMock(return_value=0)
    alkahest_only, payments_only = _tables(monkeypatch, backfill)

    for step in container.mechanism_startup_steps(payments_only):
        await step()
    backfill.assert_not_awaited()

    for step in container.mechanism_startup_steps(alkahest_only):
        await step()
    backfill.assert_awaited_once()


def test_this_storefront_composes_both_mechanisms_contributions(monkeypatch):
    monkeypatch.setattr(container, "resolved_settlement_composition", _composed())
    monkeypatch.setattr(container, "resolved_sqlite_client", object())

    assert [loop.name for loop in container.mechanism_loops(container.SELLER_STAGES)] == [
        "payment_reconciliation"
    ]
    assert len(container.mechanism_startup_steps(container.SELLER_STAGES)) == 1
