"""Shared test fixtures.

The buyer's runtime default is the trained ``rl`` strategy, which
needs torch + the compute domain on PYTHONPATH. The unit-test env
deliberately ships neither (these tests cover transport + orchestration,
not the strategy). Register ``BisectionStrategy`` under the name ``rl``
so ``load_strategy()`` resolves without dragging torch into pytest.
"""

from __future__ import annotations

from market_policy.negotiation_strategy import BisectionStrategy, register_strategy

register_strategy("rl", lambda cfg: BisectionStrategy(**cfg))
