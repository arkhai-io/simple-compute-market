"""The asking-rate period rule stays equal to what settlement can scale.

The resource-pool kit states the periods an asking rate may be quoted per as its
own contract, so widening it is a decision about what buyers compare. This
guards that it never drifts from the time units settlement arithmetic scales by:
a published period no settlement path can scale, or a scalable one buyers
cannot publish, is caught here rather than in a deployment.
"""

from __future__ import annotations

from market_core.schemas import PER_UNIT_SECONDS
from market_resource_pools import ACCEPTED_ASKING_RATE_PERIODS


def test_accepted_asking_rate_periods_equal_settlement_time_units():
    assert ACCEPTED_ASKING_RATE_PERIODS == frozenset(PER_UNIT_SECONDS)
