"""When a delivery's relay binding may change, and when it may not.

A delivery's relay is recorded on its port lease at allocation and is that
delivery's relay for the whole of its life. Nothing moves an existing delivery
between relays, and the reason is not tidiness: the buyer was given
``ssh -p <port> <user>@<relay>``, both halves of which are delivered artifacts
of a paid rental. A remote port is not portable either — 6142 on one rendezvous
says nothing about 6142 on another, which may already be leased to a different
host. Repointing a host's client does not migrate its deliveries; it strands
every buyer on that host and asks the new relay for ports that may not be free.

So there is one rebinding rule, applied at three write paths:

    A host's pool, a pool's relay reference, and a relay's address or port may
    each change only while no affected host holds an active lease — unless the
    relay is the same on both sides, in which case no delivered connection
    string moves and the change is free.

There is deliberately no new draining primitive. Disabling a pool already
excludes it from new scheduling without invalidating active workloads, so
rebinding is disable, wait, rebind, re-enable. A second draining concept beside
the existing one would be a second thing to understand and keep consistent.
"""

from __future__ import annotations

from typing import Sequence

from sqlalchemy.orm import Session

from ..hosts.connection import ConnectionCodecs
from ..hosts.db import Host
from ..hosts.service import (
    ConnectionChangeHook,
    ConnectionChangeRefusedError,
    PoolChangeHook,
    PoolChangeRefusedError,
)
from .allocator import RelayPortAllocator
from .db import PoolRelay, Relay, RelayPortLease


class RelayRebindingRefused(ValueError):
    """A relay binding cannot change while deliveries are still reachable through it."""


# How an operator gets past this. Carried in the message rather than left to
# documentation, because the operator who hits the rule is the one who needs it.
_DRAIN_HINT = (
    "Disable the pool to stop new scheduling without disturbing running deliveries, "
    "wait for these leases to be released, then make the change and re-enable."
)


def _describe(leases: Sequence[RelayPortLease], limit: int = 5) -> str:
    shown = [
        f"{lease.host_id or '<unknown host>'}:{lease.remote_port}"
        for lease in sorted(leases, key=lambda l: (l.host_id or "", l.remote_port))[:limit]
    ]
    more = len(leases) - len(shown)
    if more > 0:
        shown.append(f"and {more} more")
    return ", ".join(shown)


def _refuse(what: str, leases: Sequence[RelayPortLease]) -> RelayRebindingRefused:
    return RelayRebindingRefused(
        f"{what} while {len(leases)} tunnel(s) are still bound through it "
        f"({_describe(leases)}). Each one corresponds to a connection string a "
        f"buyer already holds, and a remote port does not carry across relays. "
        f"{_DRAIN_HINT}"
    )


def pool_relay_id(db: Session, pool_id: str | None) -> str | None:
    """The relay a pool references, or None, whatever the pool's provider.

    The one read of a pool's relay reference: every rebinding rule and every
    provider's pool configuration reads it here.
    """
    if not pool_id:
        return None
    row = db.get(PoolRelay, pool_id)
    return None if row is None else row.relay_id


def check_relay_endpoint_change(
    db: Session,
    *,
    relay: Relay,
    new_addr: str,
    new_port: int,
) -> None:
    """Refuse moving a relay that is still carrying tunnels.

    This is the widest of the three: a relay serves every pool that references
    it, so moving one affects every host on it at once.
    """
    if relay.relay_addr == new_addr and relay.relay_port == int(new_port):
        return
    held = RelayPortAllocator.active_leases_for_relay(db, relay.id)
    if held:
        raise _refuse(
            f"Relay '{relay.id}' cannot move from "
            f"{relay.relay_addr}:{relay.relay_port} to {new_addr}:{new_port}",
            held,
        )


def check_relay_token_rotation(db: Session, *, relay: Relay) -> None:
    """Refuse rotating the token of a relay that is still carrying tunnels.

    Rotation does not change the address or port a buyer holds, so it does not
    obviously belong to this rule — but it belongs for a different reason. A
    host adopts a new token only by restarting its tunnel client, since `auth`
    is not among the sections a reload applies, and that restart drops every
    proxy the client registered. And `frps` admits on one token, so a rotation
    invalidates every client still holding the old one at its next reconnect.
    A shared bearer token cannot be rotated one host at a time.

    Setting a token on a relay that has none, or rotating one before any host
    dials it, is unaffected: neither has leases.
    """
    held = RelayPortAllocator.active_leases_for_relay(db, relay.id)
    if held:
        raise _refuse(
            f"Relay '{relay.id}' cannot have its admission token rotated",
            held,
        )


def check_pool_relay_change(
    db: Session,
    *,
    pool_id: str,
    current_relay_id: str | None,
    new_relay_id: str | None,
) -> None:
    """Refuse repointing a pool whose hosts still hold leases.

    Unchanged, or changed between two references to one relay, is free: what
    the rule protects is the endpoint a buyer was given, not the identifier.
    """
    if current_relay_id == new_relay_id:
        return
    held = RelayPortAllocator.active_leases_for_pool(db, pool_id)
    if held:
        raise _refuse(
            f"Pool '{pool_id}' cannot change its relay from "
            f"{current_relay_id or '<none>'} to {new_relay_id or '<none>'}",
            held,
        )


def check_host_pool_change(
    db: Session,
    *,
    host_id: str,
    current_pool_id: str | None,
    new_pool_id: str | None,
) -> None:
    """Refuse moving a host between pools that dial different relays.

    A move between pools referencing the same relay is unconditional, including
    while deliveries are running and whichever provider each pool uses: the
    host keeps dialling the same rendezvous, its proxies keep their ports, and
    nothing a buyer holds changes.
    """
    if current_pool_id == new_pool_id:
        return
    if pool_relay_id(db, current_pool_id) == pool_relay_id(db, new_pool_id):
        return
    held = RelayPortAllocator.active_leases_for_host(db, host_id)
    if held:
        raise _refuse(
            f"Host '{host_id}' cannot move from pool "
            f"{current_pool_id or '<none>'} to {new_pool_id or '<none>'}, which "
            f"dials a different relay",
            held,
        )


def relay_host_pool_change(
    db: Session, host_id: str, current_pool_id: str | None, new_pool_id: str | None
) -> None:
    """The host authority's pool-change hook for relays.

    A host moving to a pool on a different relay while it holds leases would
    strand its buyers on the old address; the move is refused in the host
    authority's own refusal, so every host route answers it alike.
    """
    try:
        check_host_pool_change(
            db,
            host_id=host_id,
            current_pool_id=current_pool_id,
            new_pool_id=new_pool_id,
        )
    except RelayRebindingRefused as exc:
        raise PoolChangeRefusedError(str(exc)) from exc


class ManagementRouteRefused(ValueError):
    """A host would reach the service through the relay its pool sells buyers on."""


def check_management_route(
    *, relay_id: str, relay_addr: str, host_id: str, address: str | None
) -> None:
    """Refuse a host whose connection address is its pool's buyer relay's.

    Management proxies carry no grant, so a relay enforcing admission refuses
    them, and admitting them by a static list would let anyone holding the
    relay's token bind a dropped host's management port. So management ports
    use another relay. Normalized addresses are compared, which catches the
    obvious case only: an alias or another name for the relay is not detected.
    """
    relay_addr = Relay.normalize_addr(relay_addr)
    if address and Relay.normalize_addr(address) == relay_addr:
        raise ManagementRouteRefused(
            f"Host '{host_id}' is reached at {relay_addr}, the address "
            f"of relay '{relay_id}', which its pool sells buyer access through. "
            "Management proxies carry no grant, so that relay would refuse them; "
            "reach the host's management port through another relay."
        )


def _check_host_in_pool(
    db: Session, codecs: ConnectionCodecs, host_id: str, pool_id: str | None
) -> None:
    """Refuse a host, as the session holds it, in a pool whose relay it is
    reached through."""
    relay_id = pool_relay_id(db, pool_id)
    if relay_id is None:
        return
    relay = db.get(Relay, relay_id)
    host = db.query(Host).filter(Host.host_id == host_id).one_or_none()
    if relay is None or host is None:
        return
    check_management_route(
        relay_id=relay.id,
        relay_addr=relay.relay_addr,
        host_id=host.host_id,
        address=codecs.address(host.connection()),
    )


def relay_host_pool_change_hooks(codecs: ConnectionCodecs) -> tuple[PoolChangeHook, ...]:
    """The host pool-change checks the relays contribute to the host authority.

    ``codecs`` are the host authority's own, through which the management
    check reads a host's connection address without learning its kind's
    fields. The composition root builds the authority and these hooks over one
    set of codecs.
    """

    def management_route(
        db: Session, host_id: str, current_pool_id: str | None, new_pool_id: str | None
    ) -> None:
        try:
            _check_host_in_pool(db, codecs, host_id, new_pool_id)
        except ManagementRouteRefused as exc:
            raise PoolChangeRefusedError(str(exc)) from exc

    return (relay_host_pool_change, management_route)


def relay_host_connection_change_hooks(
    codecs: ConnectionCodecs,
) -> tuple[ConnectionChangeHook, ...]:
    """The checks the relays run when a placed host's connection changes.

    The management-route rule constrains a host's connection as much as its
    pool: a host already in a relay-backed pool, given that relay's address as
    its connection, would lose its management route as surely as one moved
    there.
    """

    def management_route(db: Session, host_id: str, pool_id: str) -> None:
        try:
            _check_host_in_pool(db, codecs, host_id, pool_id)
        except ManagementRouteRefused as exc:
            raise ConnectionChangeRefusedError(str(exc)) from exc

    return (management_route,)


def check_pool_hosts_against_relay(
    db: Session, *, relay: Relay, pool_id: str, codecs: ConnectionCodecs
) -> None:
    """Refuse pointing a pool at a relay one of its hosts is reached through."""
    for host in db.query(Host).filter(Host.pool_id == pool_id).order_by(Host.host_id):
        check_management_route(
            relay_id=relay.id,
            relay_addr=relay.relay_addr,
            host_id=host.host_id,
            address=codecs.address(host.connection()),
        )


def check_relay_address_against_hosts(
    db: Session, *, relay: Relay, new_addr: str, codecs: ConnectionCodecs
) -> None:
    """Refuse moving a relay onto the connection address of a host it serves."""
    pool_ids = [
        row.pool_id
        for row in db.query(PoolRelay).filter(PoolRelay.relay_id == relay.id).all()
    ]
    if not pool_ids:
        return
    for host in db.query(Host).filter(Host.pool_id.in_(pool_ids)).order_by(Host.host_id):
        check_management_route(
            relay_id=relay.id,
            relay_addr=new_addr,
            host_id=host.host_id,
            address=codecs.address(host.connection()),
        )


__all__ = [
    "ManagementRouteRefused",
    "RelayRebindingRefused",
    "check_host_pool_change",
    "check_management_route",
    "check_pool_hosts_against_relay",
    "check_pool_relay_change",
    "check_relay_address_against_hosts",
    "check_relay_endpoint_change",
    "check_relay_token_rotation",
    "pool_relay_id",
    "relay_host_connection_change_hooks",
    "relay_host_pool_change",
    "relay_host_pool_change_hooks",
]
