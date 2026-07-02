"""Framework-neutral token gate.

One ``TokenGate`` instance backs any number of web adapters (the ASGI
middleware in ``asgi.py`` is the first). It owns the verify cache, the
per-key balance estimate, the batched-charge accumulator, and the
background flush loop; an adapter only translates a request's
``Authorization`` header into ``authorize(...)`` and a ``GateDecision``
back into an HTTP response.

Decision vocabulary (status + machine-readable body) is identical
across languages — it is the behavioral contract the conformance
fixtures pin (``../conformance``).
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from .client import (
    INSUFFICIENT_CREDITS,
    KEY_NOT_FOUND,
    KEY_REVOKED,
    TokensClient,
    VerifyResult,
)
from .config import GateConfig

# Error codes in the gate's own deny bodies — clients dispatch on these.
MISSING_API_KEY = "missing_api_key"
INVALID_API_KEY = "invalid_api_key"


@dataclass(frozen=True)
class GateDecision:
    """Outcome of authorizing one request.

    ``allowed`` requests pass through to the gated app. Denials carry a
    status (401/402/403) and a machine-readable ``body`` — exhaustion
    and revocation bodies include the ``purchase`` pointer so a client
    can re-enter the buy loop.
    """

    allowed: bool
    status: int = 200
    key_id: str | None = None
    body: dict[str, Any] | None = None


@dataclass
class _KeyState:
    verify: VerifyResult
    verify_expires: float
    estimated_balance: int
    pending: list[dict[str, Any]] = field(default_factory=list)
    exhausted: bool = False


def parse_bearer(authorization: str | None) -> str | None:
    """Extract the bearer secret from an ``Authorization`` header.

    Accepts ``Bearer <secret>`` (case-insensitive scheme); returns the
    raw secret or None. A bare token with no scheme is also accepted so
    clients that send the key directly still work.
    """
    if not authorization:
        return None
    parts = authorization.strip().split(None, 1)
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1].strip() or None
    if len(parts) == 1 and parts[0]:
        return parts[0].strip() or None
    return None


def key_id_from_secret(secret: str) -> str | None:
    """The service issues secrets as ``<key_id>.<random>``."""
    key_id = secret.split(".", 1)[0]
    return key_id or None


class TokenGate:
    def __init__(self, config: GateConfig, client: TokensClient) -> None:
        self._cfg = config
        self._client = client
        self._states: dict[str, _KeyState] = {}
        self._lock = asyncio.Lock()
        self._flush_task: asyncio.Task[None] | None = None
        self._closing = False

    # -- lifecycle ----------------------------------------------------

    def start(self) -> None:
        """Begin the background flush loop (batched mode only).

        No-op when batching is off (``flush_interval_seconds <= 0``);
        every charge is synchronous then, so there is nothing to flush.
        """
        if self._cfg.flush_interval_seconds > 0 and self._flush_task is None:
            self._flush_task = asyncio.ensure_future(self._flush_loop())

    async def aclose(self) -> None:
        """Stop the flush loop and drain any pending charges once more."""
        self._closing = True
        if self._flush_task is not None:
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass
            self._flush_task = None
        await self.flush()

    # -- request path -------------------------------------------------

    async def authorize(
        self, authorization: str | None, *, idempotency_key: str | None = None,
    ) -> GateDecision:
        secret = parse_bearer(authorization)
        if secret is None:
            return GateDecision(
                allowed=False, status=401,
                body={"error": MISSING_API_KEY},
            )
        key_id = key_id_from_secret(secret)
        if key_id is None:
            return GateDecision(
                allowed=False, status=401,
                body={"error": INVALID_API_KEY},
            )

        verify = await self._verified_state(key_id, secret)
        if not verify.valid:
            if verify.status == "revoked":
                return self._deny(403, KEY_REVOKED, key_id)
            return GateDecision(
                allowed=False, status=401, key_id=key_id,
                body={"error": INVALID_API_KEY},
            )

        return await self._charge(key_id, idempotency_key)

    async def _verified_state(self, key_id: str, secret: str) -> VerifyResult:
        now = time.monotonic()
        async with self._lock:
            state = self._states.get(key_id)
            if state is not None and state.verify_expires > now and state.verify.valid:
                return state.verify

        verify = await self._client.verify(key_id=key_id, secret=secret)

        async with self._lock:
            existing = self._states.get(key_id)
            estimated = verify.balance
            if existing is not None:
                # Keep the running estimate (it may be ahead of the
                # verify-reported balance because of un-flushed charges).
                estimated = min(existing.estimated_balance, verify.balance) \
                    if existing.pending else verify.balance
                existing.verify = verify
                existing.verify_expires = now + self._cfg.verify_ttl_seconds
                existing.estimated_balance = estimated
                if verify.valid:
                    existing.exhausted = False
            else:
                self._states[key_id] = _KeyState(
                    verify=verify,
                    verify_expires=now + self._cfg.verify_ttl_seconds,
                    estimated_balance=estimated,
                )
        return verify

    async def _charge(
        self, key_id: str, idempotency_key: str | None,
    ) -> GateDecision:
        amount = self._cfg.amount_per_request
        idem = idempotency_key or uuid.uuid4().hex
        batching = self._cfg.flush_interval_seconds > 0

        async with self._lock:
            state = self._states[key_id]
            if state.exhausted:
                return self._deny(402, INSUFFICIENT_CREDITS, key_id)
            estimated_after = state.estimated_balance - amount
            go_sync = (not batching) or estimated_after <= self._cfg.low_balance_threshold
            if not go_sync:
                # Optimistic batched charge: let the request through now,
                # settle it with the service on the next flush.
                state.pending.append({
                    "key_id": key_id, "amount": amount, "idempotency_key": idem,
                })
                state.estimated_balance = estimated_after
                return GateDecision(allowed=True, status=200, key_id=key_id)

        # Synchronous charge — outside the lock (network call).
        result = await self._client.consume(
            key_id=key_id, amount=amount, idempotency_key=idem,
        )
        async with self._lock:
            state = self._states.get(key_id)
            if state is not None:
                state.estimated_balance = result.balance
        if result.ok:
            return GateDecision(allowed=True, status=200, key_id=key_id)
        if result.reason == KEY_REVOKED:
            return self._deny(403, KEY_REVOKED, key_id)
        if result.reason == KEY_NOT_FOUND:
            return GateDecision(
                allowed=False, status=401, key_id=key_id,
                body={"error": INVALID_API_KEY},
            )
        async with self._lock:
            state = self._states.get(key_id)
            if state is not None:
                state.exhausted = True
        return self._deny(402, INSUFFICIENT_CREDITS, key_id)

    # -- batched flush ------------------------------------------------

    async def _flush_loop(self) -> None:
        while not self._closing:
            try:
                await asyncio.sleep(self._cfg.flush_interval_seconds)
                await self.flush()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 — a flush error must not kill the loop
                continue

    async def flush(self) -> None:
        """Settle all accumulated batched charges with the service."""
        async with self._lock:
            items: list[dict[str, Any]] = []
            owners: list[str] = []
            for key_id, state in self._states.items():
                for item in state.pending:
                    items.append(dict(item))
                    owners.append(key_id)
                state.pending.clear()
                if len(items) >= self._cfg.flush_max_batch:
                    break
        if not items:
            return
        results = await self._client.consume_batch(items)
        async with self._lock:
            for owner, result in zip(owners, results):
                state = self._states.get(owner)
                if state is None:
                    continue
                if result.ok:
                    state.estimated_balance = result.balance
                elif result.reason == "batch_unavailable":
                    # Transport hiccup — requeue so the charge isn't lost.
                    state.pending.append(
                        {"key_id": owner, "amount": self._cfg.amount_per_request,
                         "idempotency_key": uuid.uuid4().hex}
                    )
                else:
                    state.estimated_balance = result.balance
                    state.exhausted = True

    # -- helpers ------------------------------------------------------

    def _deny(self, status: int, error: str, key_id: str) -> GateDecision:
        body: dict[str, Any] = {"error": error}
        pointer = self._cfg.purchase.as_body()
        if pointer:
            body["purchase"] = pointer
        return GateDecision(allowed=False, status=status, key_id=key_id, body=body)
