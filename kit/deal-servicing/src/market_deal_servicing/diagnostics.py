"""Seller exposure recommendations, never term validation or a servicing gate."""

from __future__ import annotations

import logging
import math
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TypeVar

logger = logging.getLogger(__name__)
T = TypeVar("T")


@dataclass(frozen=True)
class ServicingBudget:
    polling_seconds: float
    watchdog_seconds: float
    teardown_seconds: float

    def __post_init__(self) -> None:
        if any(not math.isfinite(value) or value < 0 for value in (
            self.polling_seconds, self.watchdog_seconds, self.teardown_seconds,
        )):
            raise ValueError("servicing budgets must be finite and nonnegative")

    @property
    def seconds(self) -> float:
        return self.polling_seconds + self.watchdog_seconds + self.teardown_seconds


class SellerBudgetDiagnostics:
    def __init__(
        self, budget: ServicingBudget, *, reserve_ahead_seconds: float | None,
        payer_notice_seconds: float | None, log: logging.Logger = logger,
    ):
        self.budget = budget
        self.reserve = reserve_ahead_seconds
        self.notice = payer_notice_seconds
        self.log = log

    def check(self, *, runtime_seconds: float = 0) -> tuple[str, ...]:
        """An observed slow cycle enlarges the recommendation, not buyer notice."""
        required = self.budget.polling_seconds + max(
            self.budget.watchdog_seconds, runtime_seconds,
        ) + self.budget.teardown_seconds
        messages = []
        for name, value in (("reserve-ahead", self.reserve), ("payer notice", self.notice)):
            if value is not None and value < required:
                message = (
                    f"Seller {name} of {value:g}s is below the servicing budget of {required:g}s "
                    "(polling/watchdog/teardown); unpaid delivery exposure is possible. "
                    "Recommendation only: lifecycle loops continue and accepted terms are unchanged."
                )
                self.log.warning(message)
                messages.append(message)
        return tuple(messages)

    def wrap(
        self, step: Callable[[], Awaitable[T]], *, clock: Callable[[], float] = time.monotonic,
    ) -> Callable[[], Awaitable[T]]:
        """Use as the controller's injected step; owns no timer or stop condition."""
        self.check()

        async def measured() -> T:
            start = clock()
            try:
                return await step()
            finally:
                self.check(runtime_seconds=max(0, clock() - start))

        return measured
