"""The pool facts the site authority decides on, read through a port.

The site ledger decides admission, registration and its offered read on four
facts about a Resource Pool: whether it exists, whether it is enabled, the
offering modes it delivers, and whether its declarations need a host. The pool
is another authority's record, so the ledger reads none of its storage: the
composition root supplies a ``PoolFactsReader``, and the ledger asks it for one
pool's facts in the session of the transaction making the decision.

Both protocols are structural, the returned value included, so a reader
satisfies them with values of its own and never imports this package; a
concrete value class here would make every reader depend on the site
authority. See openspec/specs/site-capacity/architecture.md, "Declared
capacity and connection identity".
"""

from __future__ import annotations

from typing import Protocol

from sqlalchemy.orm import Session


class PoolFacts(Protocol):
    """What the site authority knows of one pool when it decides, as read in
    the session of the transaction making the decision.

    A pool the reader does not find is reported as not existing, not enabled,
    with unreadable deliverable modes, and as needing a host exactly when its
    composition supplies a host requirement, so every decision refuses it and
    the offered read fails closed.
    """

    @property
    def exists(self) -> bool:
        """Whether the pool is stored."""
        ...

    @property
    def enabled(self) -> bool:
        """Whether the pool is enabled; ``False`` for a missing pool."""
        ...

    @property
    def deliverable_modes(self) -> frozenset[str] | None:
        """The offering modes the pool declares it delivers, or ``None`` when
        that declaration cannot be read, as for a missing pool."""
        ...

    @property
    def needs_host(self) -> bool:
        """Whether a declaration in the pool must name a host to be delivered,
        as the composition's host requirement resolves the pool's provider."""
        ...


class PoolFactsReader(Protocol):
    """The composition's source of pool facts."""

    def pool_facts(self, db: Session, pool_id: str) -> PoolFacts:
        """The facts of pool ``pool_id``, read in ``db``.

        Read in the caller's session, so a decision is judged against the pool
        state its own transaction sees: admission reads inside the transaction
        that creates the reservation, under the ledger's serialization, and a
        pool's deliverable modes cannot narrow between the check and the write.
        A pool the reader does not find is reported as ``PoolFacts`` describes:
        not existing, not enabled, with unreadable deliverable modes, and
        needing a host exactly when the composition supplies a host
        requirement.
        """
        ...
