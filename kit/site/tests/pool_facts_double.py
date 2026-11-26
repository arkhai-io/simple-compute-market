"""A pool-facts reader for the site authority's own tests.

The ledger reads every pool fact through the port its composition supplies,
so these tests supply one over a mapping from pool id to a record, as they
supply a fake report of the hosts taking new delivery. A test changes a pool by
replacing its record; the ledger sees the change at its next read, as it would
a committed pool write.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace

from sqlalchemy.orm import Session


@dataclass(frozen=True)
class PoolRecord:
    """One pool's facts, as the port reports them."""

    exists: bool
    enabled: bool
    deliverable_modes: frozenset[str] | None
    needs_host: bool


class PoolFactsDouble:
    """Pool facts from ``pools``; an id it does not hold is a missing pool.

    ``missing_needs_host`` is what a missing pool reports as its need for a
    host: true exactly when the composition the test stands in for supplies a
    host requirement. Each read is recorded with the session it was made in.
    """

    def __init__(self, *, missing_needs_host: bool = False) -> None:
        self.pools: dict[str, PoolRecord] = {}
        self.missing_needs_host = missing_needs_host
        self.reads: list[tuple[Session, str]] = []

    def declare(
        self,
        pool_id: str,
        modes: Iterable[str] = ("vm",),
        *,
        enabled: bool = True,
        needs_host: bool = False,
    ) -> None:
        """Store pool ``pool_id``, delivering ``modes``."""
        self.pools[pool_id] = PoolRecord(
            exists=True,
            enabled=enabled,
            deliverable_modes=frozenset(modes),
            needs_host=needs_host,
        )

    def change(self, pool_id: str, **facts) -> None:
        """Replace some of a stored pool's facts."""
        self.pools[pool_id] = replace(self.pools[pool_id], **facts)

    def pool_facts(self, db: Session, pool_id: str) -> PoolRecord:
        self.reads.append((db, pool_id))
        return self.pools.get(
            pool_id,
            PoolRecord(
                exists=False,
                enabled=False,
                deliverable_modes=None,
                needs_host=self.missing_needs_host,
            ),
        )
