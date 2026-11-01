"""A pool's relay reference, read and written the same way for every provider.

Every provider whose deliveries may use a relay accepts ``provider_config.relay_id``
and hands it here: it is validated by one rule, stored in ``pool_relays``, and
changed only through ``set_pool_relay``, which runs the rebinding refusal. So the
rule that a pool's relay is fixed while its hosts hold leases governs a VM pool
and a bare-metal pool alike, and no provider can write the reference around it.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from market_config import decrypt_secret
from market_resource_pools import PoolConfigValidationProblem, PoolValidationError
from sqlalchemy.orm import Session

from .db import PoolRelay, Relay
from .rebinding import check_pool_relay_change, pool_relay_id

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


def set_pool_relay(db: Session, pool_id: str, relay_id: str | None) -> None:
    """Point a pool at a relay, or at none, refusing a change its leases forbid.

    An unknown relay is refused here rather than left to the foreign key: the
    service's SQLite connections do not enforce foreign keys, and a reference
    to no relay would fail every later table rebuild's whole-database
    foreign-key check. The rebinding check runs next, against the reference
    stored now, so a refused change writes nothing.
    """
    if relay_id is not None and db.get(Relay, relay_id) is None:
        raise PoolValidationError(
            f"provider_config.relay_id names relay {relay_id!r}, which does not exist"
        )
    current = pool_relay_id(db, pool_id)
    check_pool_relay_change(
        db, pool_id=pool_id, current_relay_id=current, new_relay_id=relay_id
    )
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
    """The referenced relay's endpoint, window, and decrypted token, for
    preparing provider input at dispatch.

    A missing or disabled relay resolves to no fields rather than to an error,
    so the single rejection point for an unusable relay stays in pre-dispatch
    validation instead of being split across two layers that could disagree.
    These fields describe the relay, not the pool, and no pool write accepts
    them.
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
    }


__all__ = [
    "RELAY_ID_FIELD",
    "pool_relay_id",
    "relay_execution_fields",
    "set_pool_relay",
    "validate_relay_reference",
]
