"""A pool's relay reference, read and written the same way for every provider.

Every provider whose deliveries may use a relay accepts ``provider_config.relay_id``
and hands it here: it is validated by one rule, stored in ``pool_relays``, and
changed only through ``set_pool_relay``, which runs the rebinding refusal and the
management-route check. So the rules that a pool's relay is fixed while its hosts
hold leases, and is never a relay its hosts are managed through, govern a VM pool
and a bare-metal pool alike, and no provider can write the reference around them.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from market_config import decrypt_secret
from market_fulfillment import ProviderConfigInvalidError
from market_resource_pools import PoolConfigValidationProblem, PoolValidationError
from sqlalchemy.orm import Session

from ..hosts.connection import ConnectionCodecs
from ..hosts.db import Host
from .db import PoolRelay, Relay
from .rebinding import check_pool_hosts_against_relay, check_pool_relay_change, pool_relay_id

#: The pool-configuration field naming a pool's relay.
RELAY_ID_FIELD = "relay_id"


def validate_relay_reference(
    config: Mapping[str, Any],
) -> tuple[str | None, tuple[PoolConfigValidationProblem, ...]]:
    """The relay a pool configuration names, or None, and any problem with it.

    Absent or ``null`` names no relay. Anything else must be a non-empty
    string; whether the relay exists needs stored state, so ``set_pool_relay``
    refuses an unknown one when it writes.
    """
    relay_id = config.get(RELAY_ID_FIELD)
    if relay_id is None:
        return None, ()
    if not isinstance(relay_id, str) or not relay_id.strip():
        return None, (
            PoolConfigValidationProblem(
                path=RELAY_ID_FIELD,
                code="invalid_type",
                message="provider_config.relay_id must be a non-empty string",
            ),
        )
    return relay_id, ()


def set_pool_relay(
    db: Session,
    pool_id: str,
    relay_id: str | None,
    *,
    codecs: ConnectionCodecs | None,
) -> None:
    """Point a pool at a relay, or at none, refusing a change its leases or
    its hosts' management routes forbid.

    An unknown relay is refused here rather than left to the foreign key: the
    service's SQLite connections do not enforce foreign keys, and a reference
    to no relay would fail every later table rebuild's whole-database
    foreign-key check. The rebinding check runs next, against the reference
    stored now, then the management-route check of every host the pool holds,
    so a refused change writes nothing.

    ``codecs`` read a host's connection address. Without them no host can be
    checked, so a pool holding hosts cannot be pointed at a new relay: the
    write is refused rather than let through unchecked.
    """
    relay = None
    if relay_id is not None:
        relay = db.get(Relay, relay_id)
        if relay is None:
            raise PoolValidationError(
                f"provider_config.relay_id names relay {relay_id!r}, which does not exist"
            )
    current = pool_relay_id(db, pool_id)
    check_pool_relay_change(
        db, pool_id=pool_id, current_relay_id=current, new_relay_id=relay_id
    )
    if relay is not None and relay_id != current:
        if codecs is None:
            if db.query(Host).filter(Host.pool_id == pool_id).first() is not None:
                raise RuntimeError(
                    f"pool {pool_id!r} holds hosts whose management routes must be "
                    f"checked against relay {relay_id!r}, and this pool "
                    "configuration was built without connection codecs"
                )
        else:
            check_pool_hosts_against_relay(db, relay=relay, pool_id=pool_id, codecs=codecs)
    row = db.get(PoolRelay, pool_id)
    if relay_id is None:
        if row is not None:
            db.delete(row)
        return
    if row is None:
        db.add(PoolRelay(pool_id=pool_id, relay_id=relay_id))
    else:
        row.relay_id = relay_id


def relay_execution_fields(
    db: Session, relay_id: str | None, encryption_key: str
) -> dict[str, Any]:
    """The referenced relay's endpoint, window, decrypted token, and active
    grant key's id, for preparing provider input at dispatch.

    A missing or disabled relay resolves to no fields rather than to an error,
    so the single rejection point for an unusable relay stays in pre-dispatch
    validation (``check_relay_usable``) instead of being split across two
    layers that could disagree. These fields describe the relay, not the pool,
    and no pool write accepts them. The grant key appears by id only: the
    private key is read at execution, when a grant is signed.
    """
    if not relay_id:
        return {}
    relay = db.get(Relay, relay_id)
    if relay is None or not relay.enabled:
        return {}
    return {
        "relay_addr": relay.relay_addr,
        "relay_port": relay.relay_port,
        "vm_port_range_start": relay.vm_port_range_start,
        "vm_port_range_count": relay.vm_port_range_count,
        "relay_token": (
            decrypt_secret(relay.relay_token_encrypted, encryption_key)
            if relay.relay_token_encrypted
            else None
        ),
        "grant_key_id": relay.grant_key_id,
    }


#: What a relay needs before a delivery may use it, by the execution read's
#: field, each named as a refusal reports it.
_USABLE_RELAY_FIELDS = (
    ("relay_addr", "relay address"),
    ("vm_port_range_start", "port window start"),
    ("vm_port_range_count", "port window size"),
    ("relay_token", "admission token"),
    ("grant_key_id", "active grant key"),
)


def check_relay_usable(relay_id: str, fields: Mapping[str, Any]) -> None:
    """Refuse a relay a delivery cannot use, naming the relay and what it lacks.

    ``fields`` is the pool's execution read, which ``relay_execution_fields``
    filled. A disabled relay contributes none, so it lacks everything. A relay
    with no active grant key is refused as one with no token is: every proxy
    carries a grant signed with that key, and a relay enforcing admission
    refuses a proxy without one. Answerable from configuration, so it runs in
    preparation, before anything is written.
    """
    missing = [name for field, name in _USABLE_RELAY_FIELDS if not fields.get(field)]
    if missing:
        raise ProviderConfigInvalidError(
            f"pool references relay {relay_id!r}, but the relay is unusable: "
            f"no {', no '.join(missing)}. A relay that is disabled, has no "
            "allocation window, or has no token or active grant key cannot carry "
            "a tunnel, and a delivery made through it would have no external "
            "route."
        )


__all__ = [
    "RELAY_ID_FIELD",
    "check_relay_usable",
    "pool_relay_id",
    "relay_execution_fields",
    "set_pool_relay",
    "validate_relay_reference",
]
