"""Whether a capacity declaration has a host to deliver through.

Some providers deliver through a host, so a declaration in their pools that
names none cannot be delivered, and every layer that admits or places capacity
refuses it. Each layer rechecks, as each rechecks a pool's deliverable offering
modes, so none relies on another having refused first. Whether a pool's
declarations need a host is the pool's fact, which the site reads through its
pool-facts port (``market_site.pool_facts``), so this rule names no provider.

Naming a host is not enough to deliver through it. Where a declaration's pool
is backed and needs a host, the declaration has a usable host only when it
names a host that is registered and enabled; a declaration without one is
neither admitted, placed, nor projected enabled, since a listing whose delivery
has no usable host is the same as a listing with no host. Which hosts take new
delivery is the host registry's fact, so the composition that owns hosts
supplies a ``DeliverableHosts`` report, and each layer reads it in the
transaction that makes its decision, so the decision is judged against the host
state that transaction sees rather than against a copy read before it began.
The layers learn only host identifiers, never connection details. The rule does
not apply in an unbacked pool, which delivers nothing through a host, nor where
the pool needs no host. See openspec/specs/site-capacity/architecture.md,
"Declared capacity and connection identity".
"""

from __future__ import annotations

from typing import Protocol

from sqlalchemy.orm import Session


class DeliverableHosts(Protocol):
    """The hosts taking new delivery, as the composition owning hosts reports them."""

    def deliverable_host_ids(self, db: Session) -> frozenset[str]:
        """The identifiers of the hosts taking new delivery: registered and
        enabled, less any host the composition withholds from new delivery,
        read in ``db``.

        Read in the caller's session, so the caller judges its decision against
        the host state its own transaction sees.
        """
        ...


def declaration_has_usable_host(
    host_id: str | None,
    *,
    needs_host: bool,
    backed: bool,
    deliverable: frozenset[str] | None,
) -> bool:
    """Whether a declaration naming ``host_id`` has a host to deliver through.

    True when no rule applies: the pool needs no host, or it is unbacked.
    Otherwise the declaration must name a host and, when ``deliverable`` is
    supplied, that host must be in it. With no ``deliverable`` report, any
    named host is usable: a composition that supplies no report has given
    nothing to judge a host by.
    """
    if not needs_host or not backed:
        return True
    if not host_id:
        return False
    if deliverable is None:
        return True
    return host_id in deliverable
