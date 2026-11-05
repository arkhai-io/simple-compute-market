from unittest.mock import AsyncMock

import pytest
from market_deal_servicing import RetentionObservation, SellerBudgetDiagnostics, ServicingBudget


@pytest.mark.parametrize("missing", ["complete", "delivery_ended_at", "recovered_at", "payouts", "cases", "open_extensions"])
def test_incomplete_retention_never_has_a_boundary(missing):
    data = dict(observed_at=300, complete=True, delivery_ended_at=100, recovered_at=120,
                payouts={"once": 200}, cases={"case": 250}, open_extensions=[])
    assert RetentionObservation(**data).boundary() == 250
    data[missing] = {
        "complete": False, "delivery_ended_at": None, "recovered_at": None,
        "payouts": {"once": None}, "cases": {"case": None}, "open_extensions": ["open"],
    }[missing]
    assert RetentionObservation(**data).boundary() is None


async def test_budget_shortfalls_warn_without_stopping_cycles(caplog):
    diagnostics = SellerBudgetDiagnostics(
        ServicingBudget(polling_seconds=290, watchdog_seconds=0, teardown_seconds=60),
        reserve_ahead_seconds=300, payer_notice_seconds=0,
    )
    assert len(diagnostics.check()) == 2
    ticks = iter([0, 100, 100, 200])
    step = AsyncMock(return_value="serviced")
    run = diagnostics.wrap(step, clock=lambda: next(ticks))
    assert await run() == await run() == "serviced"
    assert step.await_count == 2 and "450s" in caplog.text
