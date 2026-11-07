"""What a market supplies for its offering mode.

The kit stores, checks, and reports overrides without knowing any market's
vocabulary. For each offering mode a storefront sells, the market that serves it
contributes the two judgements only it can make: whether a record's shapes and
terms are ones it understands, and whether a site's declarations are feasible for
each stated shape.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Protocol

from market_pool_overrides.records import PoolOverrideRecord, ShapeFeasibility


class PoolOverrideContribution(Protocol):
    """One market's part in overrides for one offering mode."""

    @property
    def offering_mode(self) -> str: ...

    def vocabulary_problems(self, record: PoolOverrideRecord) -> Sequence[str]:
        """Every reason ``record``'s shapes or terms are outside this market's
        vocabulary; empty when the record is readable."""
        ...

    def judge_shapes(
        self,
        site_pools: Sequence[Mapping[str, Any]],
        *,
        record: PoolOverrideRecord,
    ) -> Sequence[ShapeFeasibility]:
        """Each stated shape and whether some member of ``site_pools``, a whole
        site projection, is feasible for it on declared capacity.

        Judged exactly as the market's publication would judge the record, so a
        write's report and the next publication cycle cannot disagree. Context
        only this market needs is given to the contribution when it is built;
        nothing here depends on how the storefront orders its sites.
        """
        ...


__all__ = ["PoolOverrideContribution"]
