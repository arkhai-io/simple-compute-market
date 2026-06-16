"""Per-chain transaction serialization for one-wallet processes.

A storefront submits on-chain transactions from one wallet out of
several concurrent asyncio tasks — settlement fulfillment, the claims
engine's collection sweep, arbitration requests, admin
reclaims/arbitration. alkahest_py fetches the account's transaction
count per submission with no cross-call coordination, so two
in-flight submissions from the same wallet race to the same nonce and
the loser fails with ``nonce too low``.

``chain_tx_lock(chain)`` hands every submitter the same per-(event
loop, chain) ``asyncio.Lock``; holding it across a submission
serializes the wallet's transactions without coordinating anything
across processes (each process has its own wallet/nonce view of the
same key only in tests — and serialization per process is exactly the
guarantee alkahest_py's nonce fetch needs).
"""

from __future__ import annotations

import asyncio

_locks: dict[tuple[int, str], asyncio.Lock] = {}


def chain_tx_lock(chain_name: str | None) -> asyncio.Lock:
    """The submission lock for ``chain_name`` on the running loop.

    Keyed per event loop so test suites that spin fresh loops never
    receive a lock bound to a dead loop.
    """
    loop = asyncio.get_running_loop()
    key = (id(loop), chain_name or "default")
    lock = _locks.get(key)
    if lock is None or getattr(lock, "_loop_id", None) != id(loop):
        lock = asyncio.Lock()
        lock._loop_id = id(loop)  # type: ignore[attr-defined]
        _locks[key] = lock
    return lock
