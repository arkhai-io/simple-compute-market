"""Framework-neutral token gate.

One ``TokenGate`` instance backs any number of web adapters (the ASGI
middleware in ``asgi.py`` is the first). It owns the verify cache, the
per-key balance estimate, the batched-charge accumulator, and the
background flush loop; an adapter only translates a request's
``Authorization`` header into ``authorize(...)`` and a ``GateDecision``
back into an HTTP response. ``authorize`` is ``verify`` then ``charge``; a
composition that must check a verified key before charging it calls the two
itself.

Decision vocabulary (status + machine-readable body) is identical
across languages — it is the behavioral contract the conformance
fixtures pin (``domains/api/gate-ports/conformance``).
"""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import hashlib
import heapq
import hmac
import itertools
import time
import uuid
from collections.abc import Callable, Collection, Container, Iterable, Iterator
from dataclasses import dataclass, field
from typing import Any

import httpx

from .client import (
    BATCH_UNAVAILABLE,
    CREDITS_UNAVAILABLE,
    INSUFFICIENT_CREDITS,
    KEY_NOT_FOUND,
    KEY_OUT_OF_SCOPE,
    KEY_REVOKED,
    REFUSALS,
    UNAUTHENTICATED_SERVICE,
    ConsumeResult,
    TokensClient,
    VerifyResult,
    VerifyUnavailable,
    scope_fields,
)
from .config import GateConfig

# An authority refusal of the key itself, by the verification status it is
# denied as from then on; any other refusal is of the key's credit.
_KEY_REFUSALS: dict[str, str | None] = {
    KEY_REVOKED: "revoked",
    KEY_OUT_OF_SCOPE: KEY_OUT_OF_SCOPE,
    KEY_NOT_FOUND: None,
}

# Error codes in the gate's own deny bodies — clients dispatch on these.
MISSING_API_KEY = "missing_api_key"
INVALID_API_KEY = "invalid_api_key"
GATE_CLOSED = "gate_closed"


class UnsettledCharges(Exception):
    """Closing ended with charges the authority never answered for.

    Each is a batch item — key, amount, idempotency key, scope — whose
    request was served; resending it unchanged cannot debit it twice.
    """

    def __init__(self, charges: list[dict[str, Any]]) -> None:
        super().__init__(f"{len(charges)} charge(s) left unsettled at close")
        self.charges = charges


@dataclass(frozen=True)
class GateDecision:
    """Outcome of authorizing one request.

    ``allowed`` requests pass through to the gated app. Denials carry a
    status (401/402/403, or 502/503 when the authority cannot settle the
    charge) and a machine-readable ``body`` — exhaustion
    and revocation bodies include the ``purchase`` pointer so a client
    can re-enter the buy loop.
    """

    allowed: bool
    status: int = 200
    key_id: str | None = None
    body: dict[str, Any] | None = None


@dataclass(frozen=True)
class VerifiedKey:
    """A key the authority verified, with the terms its first grant pinned, if any.

    Bound to the secret and the verification that produced it, so a charge
    can tell whether the gate's current knowledge of the key still admits it.
    """

    key_id: str
    accepted_terms: dict[str, Any] | None = None
    terms_digest: str | None = None
    request_charge: int | None = None
    secret_fingerprint: bytes = field(default=b"", repr=False, compare=False)
    verified_ticket: int = field(default=0, repr=False, compare=False)
    _secret: str = field(default="", repr=False, compare=False)


@dataclass
class _KeyState:
    verify: VerifyResult
    verify_expires: float
    estimated_balance: int
    secret_fingerprint: bytes
    verified_ticket: int
    pending: list[dict[str, Any]] = field(default_factory=list)
    # The admission order of each pending item, in step with ``pending``.
    admitted: list[int] = field(default_factory=list)
    # The credits in ``pending``, kept so settling is not a scan of the queue.
    queued: int = 0
    # Credits detached for a batch whose answer has not been processed.
    in_flight: int = 0
    exhausted: bool = False
    # When the authority last refused the key for insufficient credit.
    exhausted_at: float = 0.0
    # A consume went unanswered, so the authority may have applied it unseen.
    uncertain: bool = False

    def settle_balance(self, balance: int) -> None:
        """Rest the estimate on a balance the authority reported for this key.

        The key's authority calls are serialized, so the balance covers every
        earlier one; it lacks only the charges still queued or detached for a
        batch not yet answered.
        """
        self.estimated_balance = balance - self.in_flight - self.queued
        self.uncertain = False


def _fingerprint(secret: str) -> bytes:
    return hashlib.sha256(secret.encode("utf-8")).digest()


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
    """The authority issues secrets as ``<key_id>.<random>``."""
    key_id = secret.split(".", 1)[0]
    return key_id or None


class TokenGate:
    def __init__(
        self,
        config: GateConfig,
        client: TokensClient,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._cfg = config
        self._client = client
        self._clock = clock
        # Orders verifications by when they start; a clock cannot, since
        # two reads may return the same value.
        self._tickets = itertools.count(1)
        self._states: dict[str, _KeyState] = {}
        self._lock = asyncio.Lock()
        # Held across each call to the authority whose answer reports the
        # key's balance, so answers arrive in the order the authority applied
        # them. Taken before ``_lock``, never while holding it.
        self._key_locks: dict[str, asyncio.Lock] = {}
        self._admissions = itertools.count()
        self._flush_task: asyncio.Task[None] | None = None
        self._closing = False
        self._closed = False
        self._close_lock = asyncio.Lock()
        # Flushes and synchronous charges in progress, which ``aclose`` waits for.
        self._calls = 0
        self._idle = asyncio.Event()
        self._idle.set()

    # -- lifecycle ----------------------------------------------------

    def start(self) -> None:
        """Begin the background flush loop (batched mode only).

        No-op when batching is off (``flush_interval_seconds <= 0``);
        every charge is synchronous then, so there is nothing to flush.
        """
        if self._cfg.flush_interval_seconds > 0 and self._flush_task is None:
            self._flush_task = asyncio.ensure_future(self._flush_loop())

    async def aclose(self) -> None:
        """Stop the flush loop and offer every pending charge to the authority once more.

        A key whose batch answer is lost is not drained further, so its later
        charges never overtake the lost ones and retries never crowd out
        another key's; its charges are raised as ``UnsettledCharges``. A
        transport error ends the drain and propagates. Once closed, a charge
        is refused. A concurrent call waits for this one, then offers what it
        left once more.
        """
        async with self._close_lock:
            await self._close()

    async def _close(self) -> None:
        self._closing = True
        if self._flush_task is not None:
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass
            self._flush_task = None
        await self._settled()
        # Nothing is queued once closing, so the drain ends when every
        # charge queued before it has been offered.
        offered: set[int] = set()
        exclude: set[int] = set()
        try:
            while sent := await self._flush_once(exclude=exclude):
                offered.update(sent)
                for state in self._states.values():
                    if any(admitted in offered for admitted in state.admitted):
                        exclude.update(state.admitted)
                exclude.update(sent)
            await self._settled()
        finally:
            self._closed = True
        unsettled = [dict(item) for state in self._states.values() for item in state.pending]
        if unsettled:
            raise UnsettledCharges(unsettled)

    async def _settled(self) -> None:
        # Re-checked on every wake: the event says only that the count was
        # zero at some point.
        while self._calls:
            await self._idle.wait()

    @contextlib.contextmanager
    def _authority_call(self) -> Iterator[None]:
        self._calls += 1
        self._idle.clear()
        try:
            yield
        finally:
            self._calls -= 1
            if not self._calls:
                self._idle.set()

    # -- request path -------------------------------------------------

    async def authorize(
        self, authorization: str | None, *, idempotency_key: str | None = None,
    ) -> GateDecision:
        verified = await self.verify(authorization)
        if isinstance(verified, GateDecision):
            return verified
        return await self.charge(verified, idempotency_key=idempotency_key)

    async def verify(self, authorization: str | None) -> GateDecision | VerifiedKey:
        """Verify the presented key without charging it: a denial, or the verified key."""
        if self._closed:
            return self._closed_denial(None)
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

        verify, ticket = await self._verified_state(key_id, secret)
        if not verify.valid:
            return self._verify_denial(verify, key_id)
        return VerifiedKey(
            key_id=key_id,
            accepted_terms=verify.accepted_terms,
            terms_digest=verify.terms_digest,
            request_charge=verify.request_charge,
            secret_fingerprint=_fingerprint(secret),
            verified_ticket=ticket,
            _secret=secret,
        )

    async def charge(
        self, verified: VerifiedKey, *, idempotency_key: str | None = None,
    ) -> GateDecision:
        """Charge a verified key its pinned charge, else the configured amount.

        A key this gate has not verified, or verified for another secret, is
        answered as invalid; one whose cached verification has since been
        refused is denied as that refusal. A handle whose verification no
        longer vouches for it is verified again with its secret first, since
        the authority's consume never sees the secret and so cannot tell a
        secret rotated away meanwhile.
        """
        amount = (
            verified.request_charge
            if verified.request_charge is not None
            else self._cfg.amount_per_request
        )
        async with self._lock:
            state = self._states.get(verified.key_id)
            stale = (
                state is not None
                and state.verify.valid
                and hmac.compare_digest(state.secret_fingerprint, verified.secret_fingerprint)
                and not self._vouches(state, verified)
            )
        if stale and not self._closed:
            if not hmac.compare_digest(_fingerprint(verified._secret), verified.secret_fingerprint):
                return GateDecision(
                    allowed=False, status=401, key_id=verified.key_id,
                    body={"error": INVALID_API_KEY},
                )
            verify, ticket = await self._verified_state(verified.key_id, verified._secret)
            if not verify.valid:
                return self._verify_denial(verify, verified.key_id)
            verified = dataclasses.replace(verified, verified_ticket=ticket)
        return await self._charge(verified, amount, idempotency_key)

    def _vouches(self, state: _KeyState, verified: VerifiedKey) -> bool:
        # An expired verification, or one older than the handle's, does not
        # vouch for the key.
        return (
            state.verify_expires > self._clock()
            and state.verified_ticket >= verified.verified_ticket
        )

    async def _verified_state(self, key_id: str, secret: str) -> tuple[VerifyResult, int]:
        """The verification answering for ``secret`` and the ticket it was issued under."""
        # The key id is public, read off any bearer header, so a cached
        # verification answers only for the exact secret that earned it.
        fingerprint = _fingerprint(secret)
        async with self._lock:
            cached = self._cached(key_id, fingerprint)
            if cached is not None:
                return cached
            state = self._states.get(key_id)
            held = state is not None and hmac.compare_digest(
                state.secret_fingerprint, fingerprint,
            )
        if not held:
            # Only the held secret's answer may move the estimate, so any
            # other secret is verified without queueing behind the key's
            # calls: a flood of guessed secrets cannot delay the holder's.
            return await self._verify_and_record(key_id, secret, fingerprint, balance=False)
        async with self._key_lock(key_id):
            async with self._lock:
                cached = self._cached(key_id, fingerprint)
            if cached is not None:
                return cached
            return await self._verify_and_record(key_id, secret, fingerprint, balance=True)

    def _cached(self, key_id: str, fingerprint: bytes) -> tuple[VerifyResult, int] | None:
        state = self._states.get(key_id)
        if (
            state is not None
            and state.verify_expires > self._clock()
            and state.verify.valid
            and hmac.compare_digest(state.secret_fingerprint, fingerprint)
        ):
            return state.verify, state.verified_ticket
        return None

    async def _verify_and_record(
        self, key_id: str, secret: str, fingerprint: bytes, *, balance: bool,
    ) -> tuple[VerifyResult, int]:
        now = self._clock()
        ticket = next(self._tickets)
        verify = await self._client.verify(
            key_id=key_id,
            secret=secret,
            service=self._cfg.scope_service,
            resource_id=self._cfg.scope_resource_id,
        )
        if isinstance(verify, VerifyUnavailable):
            return verify, ticket

        async with self._lock:
            existing = self._states.get(key_id)
            if existing is not None and existing.verified_ticket > ticket:
                # A verification that started after this one has already
                # answered; an older answer must not replace what it knew.
                return verify, ticket
            if (
                existing is not None
                and not verify.valid
                and not hmac.compare_digest(existing.secret_fingerprint, fingerprint)
            ):
                # A refused secret other than the cached one says nothing
                # about the cached credential, so it must not evict it; but
                # an older answer for this secret must not be cached over it.
                existing.verified_ticket = max(existing.verified_ticket, ticket)
                return verify, ticket
            if existing is not None:
                if balance:
                    existing.settle_balance(verify.balance)
                existing.verify = verify
                existing.verify_expires = now + self._cfg.verify_ttl_seconds
                existing.secret_fingerprint = fingerprint
                existing.verified_ticket = ticket
                if verify.valid:
                    existing.exhausted = False
            else:
                self._states[key_id] = _KeyState(
                    verify=verify,
                    verify_expires=now + self._cfg.verify_ttl_seconds,
                    estimated_balance=verify.balance,
                    secret_fingerprint=fingerprint,
                    verified_ticket=ticket,
                )
        return verify, ticket

    async def _charge(
        self, verified: VerifiedKey, amount: int, idempotency_key: str | None,
    ) -> GateDecision:
        key_id = verified.key_id
        idem = idempotency_key or uuid.uuid4().hex
        batching = self._cfg.flush_interval_seconds > 0

        async with self._lock:
            if self._closed:
                return self._closed_denial(key_id)
            state = self._states.get(key_id)
            # The handle may be stale: another request can have refreshed the
            # state while this one awaited between verify and charge. A newer
            # valid verification of the same secret still admits it.
            if state is None or not hmac.compare_digest(
                state.secret_fingerprint, verified.secret_fingerprint,
            ):
                return GateDecision(
                    allowed=False, status=401, key_id=key_id,
                    body={"error": INVALID_API_KEY},
                )
            if not state.verify.valid:
                return self._verify_denial(state.verify, key_id)
            if (
                state.exhausted
                and self._clock() < state.exhausted_at + self._cfg.exhausted_recheck_seconds
            ):
                return self._deny(402, INSUFFICIENT_CREDITS, key_id)
            estimated_after = state.estimated_balance - amount
            # A verification that stopped vouching after the charge's own
            # re-verification leaves the authority to decide the charge, as
            # does an exhaustion old enough that a top-up may have lifted it.
            go_sync = (
                not batching
                or self._closing
                or state.exhausted
                or state.uncertain
                or not self._vouches(state, verified)
                or estimated_after <= self._cfg.low_balance_threshold
            )
            if not go_sync:
                state.pending.append(self._batch_item(key_id, amount, idem))
                state.admitted.append(next(self._admissions))
                state.queued += amount
                state.estimated_balance = estimated_after
                return GateDecision(allowed=True, status=200, key_id=key_id)
            admission = next(self._admissions)

        with self._authority_call():
            return await self._charge_now(key_id, amount, idem, admission)

    async def _charge_now(
        self, key_id: str, amount: int, idem: str, admission: int,
    ) -> GateDecision:
        async with self._key_lock(key_id):
            # The key's charges admitted before this one reach the authority
            # first, or a request already served could be refused for credit
            # this charge took.
            limit = max(self._cfg.flush_max_batch, 1)
            while True:
                async with self._lock:
                    entries = self._take(self._choose(limit, owners=(key_id,), before=admission))
                if not entries:
                    break
                try:
                    answered = await self._send(entries)
                except httpx.TransportError:
                    answered = False
                if not answered:
                    return GateDecision(
                        allowed=False, status=503, key_id=key_id,
                        body={"error": BATCH_UNAVAILABLE},
                    )
            result = await self._client.consume(
                key_id=key_id,
                amount=amount,
                idempotency_key=idem,
                service=self._cfg.scope_service,
                resource_id=self._cfg.scope_resource_id,
            )
            if result.reason == CREDITS_UNAVAILABLE:
                # Charged at the authority until it answers for the key again,
                # since its balance may already include this charge. A resend
                # would debit a request that is refused here.
                async with self._lock:
                    state = self._states.get(key_id)
                    if state is not None:
                        state.uncertain = True
                return GateDecision(
                    allowed=False, status=503, key_id=key_id,
                    body={"error": CREDITS_UNAVAILABLE},
                )
            if not result.ok and result.reason not in REFUSALS:
                # A refusal of the gate's own call, such as an unverifiable
                # answer or a missing scope, says nothing of the key, so
                # neither its balance nor its credit is touched.
                return GateDecision(
                    allowed=False, status=502, key_id=key_id,
                    body={"error": result.reason},
                )
            async with self._lock:
                state = self._states.get(key_id)
                if state is not None:
                    state.settle_balance(result.balance)
                    if result.ok:
                        state.exhausted = False
        if result.ok:
            return GateDecision(allowed=True, status=200, key_id=key_id)
        async with self._lock:
            state = self._states.get(key_id)
            if state is not None:
                self._refuse(state, result.reason)
        if result.reason == KEY_REVOKED:
            return self._deny(403, KEY_REVOKED, key_id)
        if result.reason == KEY_OUT_OF_SCOPE:
            return self._deny(403, KEY_OUT_OF_SCOPE, key_id)
        if result.reason == KEY_NOT_FOUND:
            return GateDecision(
                allowed=False, status=401, key_id=key_id,
                body={"error": INVALID_API_KEY},
            )
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
        """Settle up to one batch of accumulated charges with the authority."""
        if self._closing:
            return
        with self._authority_call():
            await self._flush_once()

    async def _flush_once(self, *, exclude: Container[int] = ()) -> list[int]:
        """Send one batch of the oldest charges not in ``exclude``; their admission numbers."""
        limit = max(self._cfg.flush_max_batch, 1)
        while True:
            async with self._lock:
                owners = sorted(self._choose(limit, exclude))
            if not owners:
                return []
            # A key's charges leave its queue only under its lock, so a
            # synchronous charge holding it sees every older charge queued.
            # Sorted, so two flushes sharing keys cannot deadlock.
            held: list[asyncio.Lock] = []
            try:
                for owner in owners:
                    lock = self._key_lock(owner)
                    await lock.acquire()
                    held.append(lock)
                async with self._lock:
                    entries = self._take(self._choose(limit, exclude, owners=owners))
                if entries:
                    await self._send(entries)
                    return [admitted for _, admitted, _ in entries]
                # A synchronous charge settled them meanwhile.
            finally:
                for lock in held:
                    lock.release()

    async def _send(self, entries: list[tuple[str, int, dict[str, Any]]]) -> bool:
        """Settle detached charges with the authority, their keys' locks held; whether all were answered."""
        items = [dict(item) for _, _, item in entries]
        # The authority may have committed a batch whose answer never arrived,
        # so an unanswered item, cancellation included, is requeued unchanged:
        # its idempotency key keeps a resend from debiting twice. Requeueing
        # never awaits, so it needs no lock.
        try:
            results = await self._client.consume_batch(items)
            await self._lock.acquire()
        except BaseException:
            self._requeue(entries)
            raise
        try:
            return self._settle_batch(entries, results)
        finally:
            self._lock.release()

    def _choose(
        self,
        limit: int,
        exclude: Container[int] = (),
        *,
        owners: Collection[str] | None = None,
        before: int | None = None,
    ) -> dict[str, list[int]]:
        """Queue positions of up to ``limit`` of the oldest pending charges across keys.

        Only ``owners``' charges, when given, and only those admitted before
        ``before``. A key's queue is in admission order.
        """
        def eligible(state: _KeyState, index: int) -> int | None:
            while index < len(state.admitted):
                admitted = state.admitted[index]
                if before is not None and admitted >= before:
                    return None
                if admitted not in exclude:
                    return index
                index += 1
            return None

        heads: list[tuple[int, str, int]] = []
        for key_id in self._states if owners is None else owners:
            state = self._states.get(key_id)
            index = None if state is None else eligible(state, 0)
            if state is not None and index is not None:
                heads.append((state.admitted[index], key_id, index))
        heapq.heapify(heads)
        chosen: dict[str, list[int]] = {}
        while heads and limit:
            _, key_id, index = heapq.heappop(heads)
            chosen.setdefault(key_id, []).append(index)
            limit -= 1
            state = self._states[key_id]
            following = eligible(state, index + 1)
            if following is not None:
                heapq.heappush(heads, (state.admitted[following], key_id, following))
        return chosen

    def _take(self, chosen: dict[str, list[int]]) -> list[tuple[str, int, dict[str, Any]]]:
        """Detach the chosen charges, oldest first."""
        entries: list[tuple[str, int, dict[str, Any]]] = []
        for key_id, indices in chosen.items():
            state = self._states[key_id]
            for index in indices:
                entries.append((key_id, state.admitted[index], state.pending[index]))
                state.in_flight += state.pending[index]["amount"]
                state.queued -= state.pending[index]["amount"]
            # Each key's share leaves its queue in one pass, not item by item.
            if indices[-1] == len(indices) - 1:
                del state.pending[:len(indices)]
                del state.admitted[:len(indices)]
            else:
                drop = set(indices)
                state.pending[:] = [p for i, p in enumerate(state.pending) if i not in drop]
                state.admitted[:] = [a for i, a in enumerate(state.admitted) if i not in drop]
        entries.sort(key=lambda entry: entry[1])
        return entries

    def _settle_batch(
        self, entries: list[tuple[str, int, dict[str, Any]]], results: list[ConsumeResult],
    ) -> bool:
        unanswered: list[tuple[str, int, dict[str, Any]]] = []
        for entry, result in zip(entries, results):
            owner, _, item = entry
            state = self._states.get(owner)
            if state is None:
                continue
            if result.reason in (BATCH_UNAVAILABLE, UNAUTHENTICATED_SERVICE):
                # Whether the authority applied it is unknown.
                unanswered.append(entry)
                continue
            state.in_flight -= item["amount"]
            if result.ok:
                state.settle_balance(result.balance)
                state.exhausted = False
            elif result.reason not in REFUSALS:
                # Refused for the gate's own call, not the key; not resent,
                # since the authority would refuse it again.
                continue
            else:
                if result.reason not in _KEY_REFUSALS:
                    state.settle_balance(result.balance)
                self._refuse(state, result.reason)
        unanswered.extend(entries[len(results):])
        self._requeue(unanswered)
        return not unanswered

    def _requeue(self, entries: Iterable[tuple[str, int, dict[str, Any]]]) -> None:
        """Put unsettled items back ahead of their owners' newer pending charges."""
        by_owner: dict[str, list[tuple[int, dict[str, Any]]]] = {}
        for owner, admitted, item in entries:
            by_owner.setdefault(owner, []).append((admitted, item))
        for owner, owned in by_owner.items():
            state = self._states.get(owner)
            if state is not None:
                credits = sum(item["amount"] for _, item in owned)
                state.in_flight -= credits
                state.queued += credits
                state.pending[:0] = [item for _, item in owned]
                state.admitted[:0] = [admitted for admitted, _ in owned]

    # -- helpers ------------------------------------------------------

    def _refuse(self, state: _KeyState, reason: str | None) -> None:
        """Record an authority refusal of the key itself, or else of its credit."""
        if reason in _KEY_REFUSALS:
            # Denied as verify would deny it until a fresh verification answers.
            state.verify = VerifyResult(valid=False, status=_KEY_REFUSALS[reason], balance=0)
            state.verified_ticket = next(self._tickets)
        else:
            state.exhausted = True
            state.exhausted_at = self._clock()

    def _key_lock(self, key_id: str) -> asyncio.Lock:
        return self._key_locks.setdefault(key_id, asyncio.Lock())

    def _batch_item(self, key_id: str, amount: int, idempotency_key: str) -> dict[str, Any]:
        return {
            "key_id": key_id,
            "amount": amount,
            "idempotency_key": idempotency_key,
            **scope_fields(self._cfg.scope_service, self._cfg.scope_resource_id),
        }

    def _verify_denial(self, verify: VerifyResult, key_id: str) -> GateDecision:
        if isinstance(verify, VerifyUnavailable):
            return GateDecision(
                allowed=False, status=503, key_id=key_id,
                body={"error": CREDITS_UNAVAILABLE},
            )
        if verify.status == "revoked":
            return self._deny(403, KEY_REVOKED, key_id)
        if verify.status == KEY_OUT_OF_SCOPE:
            return self._deny(403, KEY_OUT_OF_SCOPE, key_id)
        return GateDecision(
            allowed=False, status=401, key_id=key_id,
            body={"error": INVALID_API_KEY},
        )

    def _closed_denial(self, key_id: str | None) -> GateDecision:
        return GateDecision(
            allowed=False, status=503, key_id=key_id, body={"error": GATE_CLOSED},
        )

    def _deny(self, status: int, error: str, key_id: str) -> GateDecision:
        body: dict[str, Any] = {"error": error}
        pointer = self._cfg.purchase.as_body()
        if pointer:
            body["purchase"] = pointer
        return GateDecision(allowed=False, status=status, key_id=key_id, body=body)
