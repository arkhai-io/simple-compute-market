"""Shared test fixtures.

The buyer's runtime default chain is ``[rl]``, which needs torch + the
compute domain on PYTHONPATH. The unit-test env deliberately ships
neither (these tests cover transport + orchestration, not the strategy).
Alias ``rl`` to ``bisection_middleware`` so the chain loader resolves
without dragging torch into pytest.
"""

from __future__ import annotations

from market_policy.negotiation_middleware import (
    bisection_middleware,
    register_negotiation_middleware,
)

register_negotiation_middleware("rl")(bisection_middleware)
