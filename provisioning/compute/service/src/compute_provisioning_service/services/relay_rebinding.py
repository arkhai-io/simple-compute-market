"""When a VM's relay binding may change, and when it may not.

A VM's relay is recorded on its port lease at allocation and is that VM's relay
for the whole of its life. Nothing moves an existing VM between relays, and the
reason is not tidiness: the buyer was given ``ssh -p <port> <user>@<relay>``,
both halves of which are delivered artifacts of a paid rental. A remote port is
not portable either — 6142 on one rendezvous says nothing about 6142 on
another, which may already be leased to a different host. Repointing a host's
client does not migrate its VMs; it strands every buyer on that host and asks
the new relay for ports that may not be free.

So there is one rule, applied at three write paths:

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

from compute_provisioning_service.db.models import (
    AnsiblePoolConfig,
    Relay,
    RelayPortLease,
)
from compute_provisioning_service.services.relay_port_allocator import (
    RelayPortAllocator,
)


class RelayRebindingRefused(ValueError):
    """A relay binding cannot change while VMs are still reachable through it."""


# How an operator gets past this. Carried in the message rather than left to
# documentation, because the operator who hits the rule is the one who needs it.
_DRAIN_HINT = (
    "Disable the pool to stop new scheduling without disturbing running VMs, "
    "wait for these leases to be released, then make the change and re-enable."
)


def _describe(leases: Sequence[RelayPortLease], limit: int = 5) -> str:
    shown = [
        f"{lease.host_name or '<unknown host>'}:{lease.remote_port}"
        for lease in sorted(leases, key=lambda l: (l.host_name or "", l.remote_port))[:limit]
    ]
    more = len(leases) - len(shown)
    if more > 0:
        shown.append(f"and {more} more")
    return ", ".join(shown)


def _refuse(what: str, leases: Sequence[RelayPortLease]) -> RelayRebindingRefused:
    return RelayRebindingRefused(
        f"{what} while {len(leases)} VM tunnel(s) are still bound through it "
        f"({_describe(leases)}). Each one corresponds to a connection string a "
        f"buyer already holds, and a remote port does not carry across relays. "
        f"{_DRAIN_HINT}"
    )


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
    host_name: str,
    current_pool_id: str | None,
    new_pool_id: str | None,
) -> None:
    """Refuse moving a host between pools that dial different relays.

    A move between pools referencing the same relay is unconditional, including
    while VMs are running: the host keeps dialling the same rendezvous, its
    proxies keep their ports, and nothing a buyer holds changes.
    """
    if current_pool_id == new_pool_id:
        return
    if _relay_of_pool(db, current_pool_id) == _relay_of_pool(db, new_pool_id):
        return
    held = RelayPortAllocator.active_leases_for_host(db, host_name)
    if held:
        raise _refuse(
            f"Host '{host_name}' cannot move from pool "
            f"{current_pool_id or '<none>'} to {new_pool_id or '<none>'}, which "
            f"dials a different relay",
            held,
        )


def _relay_of_pool(db: Session, pool_id: str | None) -> str | None:
    if not pool_id:
        return None
    row = (
        db.query(AnsiblePoolConfig)
        .filter(AnsiblePoolConfig.pool_id == pool_id)
        .one_or_none()
    )
    return None if row is None else row.relay_id
