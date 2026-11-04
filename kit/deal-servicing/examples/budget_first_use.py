"""Try shortfall warnings without changing or suppressing a servicing cycle."""

import asyncio

from market_deal_servicing.diagnostics import SellerBudgetDiagnostics, ServicingBudget


async def main():
    diagnostics = SellerBudgetDiagnostics(
        ServicingBudget(polling_seconds=290, watchdog_seconds=0, teardown_seconds=60),
        reserve_ahead_seconds=300, payer_notice_seconds=0,
    )
    assert len(diagnostics.check()) == 2
    calls = []

    async def step():
        calls.append("serviced")
        return {"serviced": True}

    ticks = iter((0.0, 100.0, 100.0, 200.0))
    measured = diagnostics.wrap(step, clock=lambda: next(ticks))
    assert (await measured())["serviced"]
    assert (await measured())["serviced"] and len(calls) == 2
    print("350s configured and 450s observed budgets warn; both servicing cycles still run")


if __name__ == "__main__":
    asyncio.run(main())
