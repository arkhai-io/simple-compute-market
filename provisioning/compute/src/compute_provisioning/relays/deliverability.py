"""Which hosts take new delivery once relays are counted.

Disabling a relay drains it, and the first part of a drain is that no new
delivery is placed on it. A delivery reaches its buyer through the relay its
declaration's pool references, so every host whose declaration sits in a pool
on a disabled relay, and every host placed in such a pool, is left out of the
hosts taking new delivery the site authority reads: the seam a disabled host
already uses. No claim is then admitted against, placed on, or projected
enabled for those hosts' declarations, and the site's own code learns nothing
of relays.

Both are counted because a host's placement and its declaration's pool are
recorded apart: a host need not be placed in a pool to have its one
declaration there, and a placed host's declaration is normally in its pool.

Leaving a host out takes nothing from it. Its leased deliveries, their
teardowns and reclaims included, run as before, and enabling the relay again
returns the host to new delivery.
"""

from __future__ import annotations

from market_resource_pools import DeliverableHosts
from market_site.db import CapacityBucket
from sqlalchemy.orm import Session

from ..hosts.db import Host
from .db import PoolRelay, Relay


class RelayDeliverableHosts:
    """The hosts ``hosts`` reports taking new delivery, less every host placed
    in, or declared in, a pool that references a disabled relay.

    A ``DeliverableHosts`` itself, composed over the host authority's, so
    admission, placement, and projection read it where they read the host
    authority's report. Read in the caller's session, as that report is, so
    each decision is judged against the relay state its own transaction sees.
    """

    def __init__(self, hosts: DeliverableHosts) -> None:
        self._hosts = hosts

    def deliverable_host_ids(self, db: Session) -> frozenset[str]:
        hosts = self._hosts.deliverable_host_ids(db)
        if not hosts:
            return hosts
        draining_pools = (
            db.query(PoolRelay.pool_id)
            .join(Relay, Relay.id == PoolRelay.relay_id)
            .filter(Relay.enabled.is_(False))
            .scalar_subquery()
        )
        placed = db.query(Host.host_id).filter(Host.pool_id.in_(draining_pools))
        declared = db.query(CapacityBucket.host_id).filter(
            CapacityBucket.pool_id.in_(draining_pools),
            CapacityBucket.host_id.is_not(None),
        )
        draining = {host_id for (host_id,) in placed.union(declared)}
        return hosts - draining


__all__ = ["RelayDeliverableHosts"]
