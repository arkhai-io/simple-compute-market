"""Batched-flush behavior, the ASGI binding, and the verify cache's tie to the secret.

The synchronous decision table is pinned by the conformance session;
these cover what is outside it: the optimistic batched charge path
(timing-dependent, so impl-local), the ASGI adapter end to end, and a
cached verification answering only for the secret that earned it.
"""

from __future__ import annotations

import asyncio
import dataclasses
import time

import httpx
import pytest

from arkhai_api_gate.client import ConsumeResult, TokensClient, VerifyResult, VerifyUnavailable
from arkhai_api_gate.config import GateConfig, PurchasePointer
from arkhai_api_gate.gate import TokenGate, UnsettledCharges, VerifiedKey
from arkhai_api_gate.asgi import TokenGateMiddleware


class FakeClient:
    """Records calls and returns canned results — for batch-vs-sync asserts."""

    def __init__(self, *, balance: int) -> None:
        self._balance = balance
        self.verify_calls = 0
        self.consume_calls: list[dict] = []
        self.batch_calls: list[list[dict]] = []

    async def verify(self, *, key_id: str, secret: str, service=None, resource_id=None) -> VerifyResult:
        self.verify_calls += 1
        return VerifyResult(valid=True, status="active", balance=self._balance)

    async def consume(self, *, key_id, amount, idempotency_key=None, service=None, resource_id=None) -> ConsumeResult:
        self.consume_calls.append({"key_id": key_id, "amount": amount})
        self._balance = max(0, self._balance - amount)
        if self._balance < 0:
            return ConsumeResult(ok=False, balance=0, reason="insufficient_credits")
        return ConsumeResult(ok=True, balance=self._balance, consumed=amount)

    async def consume_batch(self, items) -> list[ConsumeResult]:
        self.batch_calls.append(list(items))
        out = []
        for item in items:
            self._balance = max(0, self._balance - item["amount"])
            out.append(ConsumeResult(ok=True, balance=self._balance, consumed=item["amount"]))
        return out


def _cfg(**kw) -> GateConfig:
    base = dict(
        service_url="http://svc", authority_label="test-authority", amount_per_request=1,
        flush_interval_seconds=0.0, low_balance_threshold=0,
        purchase=PurchasePointer(listing_id="lst-1"),
    )
    base.update(kw)
    return GateConfig(**base)


async def test_batched_charges_accumulate_then_flush_once():
    client = FakeClient(balance=10)
    gate = TokenGate(_cfg(flush_interval_seconds=60.0, low_balance_threshold=1), client)

    for _ in range(3):
        d = await gate.authorize("Bearer ak_live.s")
        assert d.allowed
    # Comfortably above threshold → no synchronous consume yet.
    assert client.consume_calls == []
    assert client.verify_calls == 1  # verify cached after the first

    await gate.flush()
    assert len(client.batch_calls) == 1
    assert len(client.batch_calls[0]) == 3


async def test_charge_goes_synchronous_near_exhaustion():
    client = FakeClient(balance=3)
    # threshold 2: a charge that would leave <= 2 estimated is synchronous.
    gate = TokenGate(_cfg(flush_interval_seconds=60.0, low_balance_threshold=2), client)

    d = await gate.authorize("Bearer ak_live.s")  # 3 -> est 2 <= 2 => sync
    assert d.allowed
    assert len(client.consume_calls) == 1
    assert client.batch_calls == []


async def test_asgi_allows_valid_and_402s_exhausted():
    # A trivial downstream ASGI app the gate fronts.
    async def app(scope, receive, send):
        assert scope["type"] == "http"
        body = b'{"forecast":"sunny"}'
        await send({"type": "http.response.start", "status": 200,
                    "headers": [(b"content-type", b"application/json")]})
        await send({"type": "http.response.body", "body": body})

    # Scripted credits service: valid key, one credit then exhausted.
    state = {"balance": 1}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/verify"):
            return httpx.Response(200, json={
                "valid": True, "status": "active", "balance": state["balance"],
            })
        # consume
        if state["balance"] >= 1:
            state["balance"] -= 1
            return httpx.Response(200, json={"ok": True, "consumed": 1, "balance": state["balance"]})
        return httpx.Response(402, json={"error": "insufficient_credits", "balance": 0})

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = TokensClient(service_url="http://svc", http=http)
    gate = TokenGate(_cfg(purchase=PurchasePointer(listing_id="lst-1", storefront_url="http://sf")), client)
    gated = TokenGateMiddleware(app, gate=gate)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=gated), base_url="http://app",
    ) as c:
        r1 = await c.get("/api/forecast", headers={"Authorization": "Bearer ak_live.s"})
        assert r1.status_code == 200
        assert r1.json() == {"forecast": "sunny"}

        r2 = await c.get("/api/forecast", headers={"Authorization": "Bearer ak_live.s"})
        assert r2.status_code == 402
        body = r2.json()
        assert body["error"] == "insufficient_credits"
        assert body["purchase"]["listing_id"] == "lst-1"

        # Health is excluded — served without a token.
        r3 = await c.get("/health")
        # The trivial app answers everything 200; the point is no 401.
        assert r3.status_code == 200

    await http.aclose()


async def test_asgi_missing_key_is_401():
    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    http = httpx.AsyncClient(transport=httpx.MockTransport(
        lambda req: httpx.Response(200, json={"valid": True, "status": "active", "balance": 5})
    ))
    client = TokensClient(service_url="http://svc", http=http)
    gate = TokenGate(_cfg(), client)
    gated = TokenGateMiddleware(app, gate=gate)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=gated), base_url="http://app",
    ) as c:
        r = await c.get("/api/forecast")
        assert r.status_code == 401
        assert r.json()["error"] == "missing_api_key"
    await http.aclose()


class SecretCheckingClient:
    """An authority that accepts only the secrets it was given, recording what it was asked."""

    def __init__(self, *accepted: str) -> None:
        self.accepted = set(accepted)
        self.verified: list[str] = []
        self.consumed = 0

    async def verify(self, *, key_id: str, secret: str, service=None, resource_id=None) -> VerifyResult:
        self.verified.append(secret)
        if secret in self.accepted:
            return VerifyResult(valid=True, status="active", balance=10)
        return VerifyResult(valid=False, status=None, balance=0)

    async def consume(self, *, key_id, amount, idempotency_key=None, service=None, resource_id=None) -> ConsumeResult:
        self.consumed += 1
        return ConsumeResult(ok=True, balance=10 - self.consumed, consumed=amount)


async def test_a_cached_key_does_not_admit_a_different_secret():
    client = SecretCheckingClient("ak_victim.real")
    gate = TokenGate(_cfg(), client)

    assert (await gate.authorize("Bearer ak_victim.real")).allowed
    forged = await gate.authorize("Bearer ak_victim.forged")

    assert (forged.allowed, forged.status, forged.body) == (False, 401, {"error": "invalid_api_key"})
    assert client.verified == ["ak_victim.real", "ak_victim.forged"]
    assert client.consumed == 1


async def test_a_refused_secret_leaves_the_cached_verification_in_place():
    client = SecretCheckingClient("ak_victim.real")
    gate = TokenGate(_cfg(), client)

    await gate.authorize("Bearer ak_victim.real")
    await gate.authorize("Bearer ak_victim.forged")

    assert (await gate.authorize("Bearer ak_victim.real")).allowed
    assert client.verified == ["ak_victim.real", "ak_victim.forged"]


async def test_a_rotated_secret_the_authority_accepts_replaces_the_cached_one():
    client = SecretCheckingClient("ak_k.first", "ak_k.rotated")
    gate = TokenGate(_cfg(), client)

    await gate.authorize("Bearer ak_k.first")
    assert (await gate.authorize("Bearer ak_k.rotated")).allowed
    assert (await gate.authorize("Bearer ak_k.rotated")).allowed
    await gate.authorize("Bearer ak_k.first")

    assert client.verified == ["ak_k.first", "ak_k.rotated", "ak_k.first"]


class HeldVerificationClient(SecretCheckingClient):
    """Holds the first verification of one secret, answering it valid, until the test releases it."""

    def __init__(self, held: str, *accepted: str) -> None:
        super().__init__(*accepted)
        self.held = held
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def verify(self, *, key_id: str, secret: str, service=None, resource_id=None) -> VerifyResult:
        if secret != self.held or self.started.is_set():
            return await super().verify(key_id=key_id, secret=secret)
        self.verified.append(secret)
        self.started.set()
        await self.release.wait()
        return VerifyResult(valid=True, status="active", balance=10)


async def _hold_old_secret(gate: TokenGate, client: HeldVerificationClient) -> asyncio.Future:
    old = asyncio.ensure_future(gate.authorize("Bearer ak_k.old"))
    await asyncio.wait_for(client.started.wait(), timeout=5)
    return old


@pytest.mark.parametrize("clock", [time.monotonic, lambda: 100.0], ids=["monotonic", "frozen"])
async def test_a_late_answer_for_an_older_secret_does_not_replace_a_newer_one(clock):
    client = HeldVerificationClient("ak_k.old", "ak_k.new")
    gate = TokenGate(_cfg(), client, clock=clock)

    old = await _hold_old_secret(gate, client)
    assert (await gate.authorize("Bearer ak_k.new")).allowed
    client.release.set()
    # The gate now holds the newer secret's verification, so the late one is not charged.
    late = await asyncio.wait_for(old, timeout=5)
    assert (late.allowed, late.status) == (False, 401)

    again = await gate.authorize("Bearer ak_k.old")

    assert (again.allowed, again.status) == (False, 401)
    assert client.verified == ["ak_k.old", "ak_k.new", "ak_k.old"]


@pytest.mark.parametrize("clock", [time.monotonic, lambda: 100.0], ids=["monotonic", "frozen"])
async def test_a_late_answer_does_not_outlast_a_newer_refusal_of_the_same_secret(clock):
    client = HeldVerificationClient("ak_k.old", "ak_k.new")
    gate = TokenGate(_cfg(), client, clock=clock)

    assert (await gate.authorize("Bearer ak_k.new")).allowed
    old = await _hold_old_secret(gate, client)
    assert not (await gate.authorize("Bearer ak_k.old")).allowed
    client.release.set()
    await asyncio.wait_for(old, timeout=5)

    again = await gate.authorize("Bearer ak_k.old")

    assert (again.allowed, again.status) == (False, 401)
    assert client.verified == ["ak_k.new", "ak_k.old", "ak_k.old", "ak_k.old"]


# Verification and charge as separable steps


class ScriptedClient:
    """Answers verify with a scripted result and records every call with its arguments."""

    def __init__(self, verify: VerifyResult, *, consume: ConsumeResult | None = None) -> None:
        self._verify = verify
        self._consume = consume
        self.calls: list[tuple[str, dict]] = []

    async def verify(self, **kwargs) -> VerifyResult:
        self.calls.append(("verify", kwargs))
        return self._verify

    async def consume(self, **kwargs) -> ConsumeResult:
        self.calls.append(("consume", kwargs))
        return self._consume or ConsumeResult(ok=True, balance=self._verify.balance - kwargs["amount"], consumed=kwargs["amount"])

    async def consume_batch(self, items) -> list[ConsumeResult]:
        self.calls.append(("consume_batch", {"items": list(items)}))
        return [ConsumeResult(ok=True, balance=0, consumed=item["amount"]) for item in items]


PINNED = VerifyResult(
    valid=True, status="active", balance=50,
    accepted_terms={"rate_card": {}}, terms_digest="sha256:" + "a" * 64, request_charge=3,
)


async def test_verification_alone_makes_no_charge():
    client = ScriptedClient(PINNED)
    gate = TokenGate(_cfg(), client)

    verified = await gate.verify("Bearer ak_live.s")

    assert verified.key_id == "ak_live"
    assert (verified.accepted_terms, verified.terms_digest, verified.request_charge) == (
        PINNED.accepted_terms, PINNED.terms_digest, 3,
    )
    assert [name for name, _ in client.calls] == ["verify"]


@pytest.mark.parametrize("batched", [False, True], ids=["synchronous", "batched"])
async def test_verify_then_charge_makes_the_same_exchanges_and_state_as_authorize(batched):
    config = _cfg(flush_interval_seconds=60.0, low_balance_threshold=1) if batched else _cfg()
    separate, together = ScriptedClient(PINNED), ScriptedClient(PINNED)
    gate_a, gate_b = TokenGate(config, separate), TokenGate(config, together)

    for idem in ("idem-1", "idem-2"):
        decision_a = await gate_a.charge(await gate_a.verify("Bearer ak_live.s"), idempotency_key=idem)
        decision_b = await gate_b.authorize("Bearer ak_live.s", idempotency_key=idem)
        assert decision_a == decision_b
    await gate_a.flush()
    await gate_b.flush()

    # The second request is answered from the cached verification in both.
    assert separate.calls == together.calls
    assert [name for name, _ in separate.calls].count("verify") == 1


@pytest.mark.parametrize(
    ("verified", "charged"),
    [(PINNED, 3), (VerifyResult(valid=True, status="active", balance=50), 2)],
    ids=["pinned-charge", "configured-default"],
)
async def test_the_charge_is_the_verified_one_and_the_configured_amount_otherwise(verified, charged):
    client = ScriptedClient(verified)
    gate = TokenGate(_cfg(amount_per_request=2), client)

    assert (await gate.authorize("Bearer ak_live.s")).allowed
    assert client.calls[-1][1]["amount"] == charged


@pytest.mark.parametrize(
    ("scope", "sent"),
    [
        ({"scope_service": "svc", "scope_resource_id": "quota"}, {"service": "svc", "resource_id": "quota"}),
        ({}, {"service": None, "resource_id": None}),
    ],
    ids=["scoped", "unscoped"],
)
async def test_the_configured_scope_is_sent_on_verify_and_consume(scope, sent):
    client = ScriptedClient(PINNED)
    gate = TokenGate(_cfg(**scope), client)

    await gate.authorize("Bearer ak_live.s")

    for name, kwargs in client.calls:
        assert {key: kwargs[key] for key in ("service", "resource_id")} == sent, name


async def test_a_pinned_charge_is_batched_and_requeued_at_its_own_amount():
    client = ScriptedClient(PINNED)
    gate = TokenGate(_cfg(flush_interval_seconds=60.0, low_balance_threshold=1, scope_service="svc"), client)

    assert (await gate.authorize("Bearer ak_live.s")).allowed

    async def unavailable(items):
        client.calls.append(("consume_batch", {"items": list(items)}))
        return [ConsumeResult(ok=False, balance=0, reason="batch_unavailable") for _ in items]

    client.consume_batch = unavailable
    await gate.flush()
    await gate.flush()
    batches = [kwargs["items"] for name, kwargs in client.calls if name == "consume_batch"]
    assert [[item["amount"] for item in batch] for batch in batches] == [[3], [3]]


async def test_charging_a_key_the_gate_never_verified_is_an_invalid_key():
    decision = await TokenGate(_cfg(), ScriptedClient(PINNED)).charge(VerifiedKey(key_id="ak_other"))
    assert (decision.allowed, decision.status) == (False, 401)


async def test_a_key_out_of_scope_is_403_and_never_charged():
    client = ScriptedClient(VerifyResult(valid=False, status="key_out_of_scope", balance=0))
    gate = TokenGate(_cfg(scope_service="svc"), client)

    decision = await gate.authorize("Bearer ak_live.s")

    assert (decision.allowed, decision.status, decision.body["error"]) == (False, 403, "key_out_of_scope")
    assert [name for name, _ in client.calls] == ["verify"]


async def test_a_consume_refused_out_of_scope_is_403():
    client = ScriptedClient(PINNED, consume=ConsumeResult(ok=False, balance=0, reason="key_out_of_scope"))
    gate = TokenGate(_cfg(scope_service="svc"), client)

    decision = await gate.authorize("Bearer ak_live.s")

    assert (decision.allowed, decision.status, decision.body["error"]) == (False, 403, "key_out_of_scope")


async def test_a_batched_item_carries_the_configured_scope():
    client = ScriptedClient(PINNED)
    gate = TokenGate(
        _cfg(flush_interval_seconds=60.0, low_balance_threshold=1, scope_service="svc", scope_resource_id="quota"),
        client,
    )

    assert (await gate.authorize("Bearer ak_live.s", idempotency_key="idem-1")).allowed
    await gate.flush()

    assert client.calls[-1] == ("consume_batch", {"items": [
        {"key_id": "ak_live", "amount": 3, "idempotency_key": "idem-1", "service": "svc", "resource_id": "quota"},
    ]})


async def test_a_batched_item_refused_out_of_scope_denies_the_key_from_then_on():
    client = ScriptedClient(PINNED)
    gate = TokenGate(_cfg(flush_interval_seconds=60.0, low_balance_threshold=1, scope_service="svc"), client)
    assert (await gate.authorize("Bearer ak_live.s")).allowed
    verified = await gate.verify("Bearer ak_live.s")

    async def out_of_scope(items):
        return [ConsumeResult(ok=False, balance=0, reason="key_out_of_scope") for _ in items]

    client.consume_batch = out_of_scope
    await gate.flush()
    decision = await gate.charge(verified)

    assert (decision.allowed, decision.status, decision.body["error"]) == (False, 403, "key_out_of_scope")
    assert [name for name, _ in client.calls] == ["verify"]


# A verified key is charged only while the gate's verification still admits it


class Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


def _batched_gate(client, clock: Clock) -> TokenGate:
    return TokenGate(_cfg(flush_interval_seconds=60.0, low_balance_threshold=1, verify_ttl_seconds=30.0), client, clock=clock)


async def test_a_key_revoked_between_verify_and_charge_is_refused_and_never_charged():
    clock, client = Clock(), ScriptedClient(PINNED)
    gate = _batched_gate(client, clock)
    verified = await gate.verify("Bearer ak_live.s")

    # Another request re-verifies the key after its verification expired and finds it revoked.
    clock.now += 31
    client._verify = VerifyResult(valid=False, status="revoked", balance=50)
    assert (await gate.verify("Bearer ak_live.s")).status == 403
    decision = await gate.charge(verified)
    await gate.flush()

    assert (decision.allowed, decision.status, decision.body["error"]) == (False, 403, "key_revoked")
    assert [name for name, _ in client.calls] == ["verify", "verify"]


async def test_a_charge_after_the_verification_expired_verifies_the_secret_again():
    clock, client = Clock(), ScriptedClient(PINNED)
    gate = _batched_gate(client, clock)
    verified = await gate.verify("Bearer ak_live.s")

    clock.now += 31
    assert (await gate.charge(verified)).allowed
    await gate.flush()

    assert [(name, kwargs.get("secret")) for name, kwargs in client.calls] == [
        ("verify", "ak_live.s"), ("verify", "ak_live.s"), ("consume_batch", None),
    ]


async def test_a_handle_whose_secret_was_rotated_away_after_expiry_is_refused_and_never_charged():
    clock, client = Clock(), SecretCheckingClient("ak_k.first")
    gate = TokenGate(_cfg(verify_ttl_seconds=30.0), client, clock=clock)
    verified = await gate.verify("Bearer ak_k.first")

    clock.now += 31
    client.accepted = {"ak_k.rotated"}
    decision = await gate.charge(verified)

    assert (decision.allowed, decision.status, decision.body) == (False, 401, {"error": "invalid_api_key"})
    assert client.verified == ["ak_k.first", "ak_k.first"]
    assert client.consumed == 0


async def test_the_presented_secret_stays_out_of_a_verified_key_repr():
    verified = await TokenGate(_cfg(), ScriptedClient(PINNED)).verify("Bearer ak_live.s")
    assert "ak_live.s" not in repr(verified)


async def test_a_newer_valid_verification_of_the_same_secret_keeps_the_handle():
    clock, client = Clock(), ScriptedClient(PINNED)
    gate = _batched_gate(client, clock)
    verified = await gate.verify("Bearer ak_live.s")

    clock.now += 31
    assert (await gate.verify("Bearer ak_live.s")).key_id == "ak_live"
    assert (await gate.charge(verified)).allowed
    await gate.flush()

    assert [name for name, _ in client.calls] == ["verify", "verify", "consume_batch"]


async def test_a_handle_for_a_secret_the_gate_no_longer_holds_is_refused():
    client = SecretCheckingClient("ak_k.first", "ak_k.rotated")
    gate = TokenGate(_cfg(), client)
    verified = await gate.verify("Bearer ak_k.first")

    assert (await gate.authorize("Bearer ak_k.rotated")).allowed
    decision = await gate.charge(verified)

    assert (decision.allowed, decision.status, decision.body) == (False, 401, {"error": "invalid_api_key"})
    assert client.consumed == 1


# A batch whose outcome is unknown stays pending with its items unchanged


def _pending_gate(client) -> TokenGate:
    return TokenGate(_cfg(flush_interval_seconds=60.0, low_balance_threshold=1, scope_service="svc"), client)


def _sent_batches(client) -> list[list[dict]]:
    return [kwargs["items"] for name, kwargs in client.calls if name == "consume_batch"]


async def test_a_flush_that_raises_keeps_every_item_pending_and_resends_it_unchanged():
    client = ScriptedClient(PINNED)
    gate = _pending_gate(client)
    assert (await gate.authorize("Bearer ak_live.s", idempotency_key="idem-1")).allowed
    assert (await gate.authorize("Bearer ak_live.s", idempotency_key="idem-2")).allowed
    settle = client.consume_batch

    async def lost(items):
        client.calls.append(("consume_batch", {"items": [dict(item) for item in items]}))
        raise httpx.ReadTimeout("response lost")

    client.consume_batch = lost
    with pytest.raises(httpx.ReadTimeout):
        await gate.flush()
    assert [item["idempotency_key"] for item in gate._states["ak_live"].pending] == ["idem-1", "idem-2"]

    client.consume_batch = settle
    await gate.flush()
    first, second = _sent_batches(client)
    assert first == second
    assert [item["idempotency_key"] for item in second] == ["idem-1", "idem-2"]
    assert gate._states["ak_live"].pending == []


@pytest.mark.parametrize("reason", ["batch_unavailable", "unauthenticated_service"])
async def test_an_unavailable_batch_requeues_the_identical_item(reason):
    client = ScriptedClient(PINNED)
    gate = _pending_gate(client)
    assert (await gate.authorize("Bearer ak_live.s", idempotency_key="idem-1")).allowed

    async def unavailable(items):
        client.calls.append(("consume_batch", {"items": [dict(item) for item in items]}))
        return [ConsumeResult(ok=False, balance=0, reason=reason) for _ in items]

    client.consume_batch = unavailable
    await gate.flush()
    await gate.flush()

    first, second = _sent_batches(client)
    assert first == second == [
        {"key_id": "ak_live", "amount": 3, "idempotency_key": "idem-1", "service": "svc"},
    ]


async def test_a_short_batch_answer_requeues_the_unanswered_items():
    client = ScriptedClient(PINNED)
    gate = _pending_gate(client)
    for idem in ("idem-1", "idem-2", "idem-3"):
        assert (await gate.authorize("Bearer ak_live.s", idempotency_key=idem)).allowed
    settle = client.consume_batch

    async def short(items):
        client.calls.append(("consume_batch", {"items": [dict(item) for item in items]}))
        return [ConsumeResult(ok=True, balance=47, consumed=3)]

    client.consume_batch = short
    await gate.flush()
    client.consume_batch = settle
    await gate.flush()

    first, second = _sent_batches(client)
    assert second == first[1:]
    assert [item["idempotency_key"] for item in second] == ["idem-2", "idem-3"]


async def test_closing_during_a_flush_in_flight_resends_its_items_unchanged():
    client = ScriptedClient(PINNED)
    gate = TokenGate(_cfg(flush_interval_seconds=0.01, low_balance_threshold=1, scope_service="svc"), client)
    assert (await gate.authorize("Bearer ak_live.s", idempotency_key="idem-1")).allowed
    settle, in_flight = client.consume_batch, asyncio.Event()

    async def hang(items):
        client.calls.append(("consume_batch", {"items": [dict(item) for item in items]}))
        client.consume_batch = settle
        in_flight.set()
        await asyncio.Event().wait()

    client.consume_batch = hang
    gate.start()
    await in_flight.wait()
    await gate.aclose()

    first, second = _sent_batches(client)
    assert first == second
    assert gate._states["ak_live"].pending == []


async def test_a_flush_cancelled_before_it_processes_its_answer_requeues_every_item():
    client = ScriptedClient(PINNED)
    gate = _pending_gate(client)
    assert (await gate.authorize("Bearer ak_live.s", idempotency_key="idem-1")).allowed
    answered = asyncio.Event()

    async def unavailable(items):
        client.calls.append(("consume_batch", {"items": [dict(item) for item in items]}))
        # Taking the lock parks the flush between its answer and its processing.
        await gate._lock.acquire()
        answered.set()
        return [ConsumeResult(ok=False, balance=0, reason="batch_unavailable") for _ in items]

    client.consume_batch = unavailable
    flushing = asyncio.ensure_future(gate.flush())
    await answered.wait()
    await asyncio.sleep(0)
    flushing.cancel()
    with pytest.raises(asyncio.CancelledError):
        await flushing
    gate._lock.release()

    assert gate._states["ak_live"].pending == [
        {"key_id": "ak_live", "amount": 3, "idempotency_key": "idem-1", "service": "svc"},
    ]


async def test_an_unverifiable_consume_answer_is_a_502_that_leaves_the_key_untouched():
    client = FakeClient(balance=10)
    gate = TokenGate(_cfg(), client)

    async def unverifiable(**_):
        return ConsumeResult(ok=False, balance=0, reason="unauthenticated_service")

    client.consume = unverifiable
    decision = await gate.authorize("Bearer ak_live.s")

    assert (decision.allowed, decision.status, decision.body) == (
        False, 502, {"error": "unauthenticated_service"},
    )
    state = gate._states["ak_live"]
    assert (state.exhausted, state.estimated_balance) == (False, 10)


class BlockedBatch:
    """Holds each batch at the authority until released, then answers it as ``client`` would."""

    def __init__(self, client: FakeClient, *, fail_first: bool = False) -> None:
        self._answer = client.consume_batch
        self.items: list[list[dict]] = []
        self.arrived = asyncio.Event()
        self.release = asyncio.Event()
        self._fail_first = fail_first

    async def __call__(self, items):
        self.items.append([dict(item) for item in items])
        if len(self.items) == 1:
            self.arrived.set()
            await self.release.wait()
            if self._fail_first:
                raise httpx.ConnectError("connection reset")
        return await self._answer(items)


async def test_a_charge_admitted_while_a_flush_waits_keeps_its_deduction():
    client = FakeClient(balance=50)
    gate = TokenGate(_cfg(amount_per_request=3, flush_interval_seconds=60.0), client)
    client.consume_batch = batch = BlockedBatch(client)
    assert (await gate.authorize("Bearer ak_live.s")).allowed
    flushing = asyncio.ensure_future(gate.flush())
    await batch.arrived.wait()

    assert (await gate.authorize("Bearer ak_live.s")).allowed
    batch.release.set()
    await flushing

    state = gate._states["ak_live"]
    assert (state.estimated_balance, state.in_flight, len(state.pending)) == (44, 0, 1)


async def test_a_synchronous_charge_keeps_the_deduction_of_a_queued_one():
    client = FakeClient(balance=10)
    gate = TokenGate(
        _cfg(amount_per_request=3, flush_interval_seconds=60.0, low_balance_threshold=5), client,
    )
    assert (await gate.authorize("Bearer ak_live.s")).allowed
    # 7 - 3 falls to the threshold, so this one is consumed synchronously.
    assert (await gate.authorize("Bearer ak_live.s")).allowed

    assert len(client.consume_calls) == 1
    assert gate._states["ak_live"].estimated_balance == 4


async def test_closing_waits_for_a_flush_called_directly_and_resends_its_items():
    client = FakeClient(balance=50)
    gate = TokenGate(_cfg(flush_interval_seconds=60.0), client)
    client.consume_batch = batch = BlockedBatch(client, fail_first=True)
    assert (await gate.authorize("Bearer ak_live.s", idempotency_key="idem-1")).allowed
    flushing = asyncio.ensure_future(gate.flush())
    await batch.arrived.wait()

    closing = asyncio.ensure_future(gate.aclose())
    await asyncio.sleep(0)
    assert not closing.done()
    batch.release.set()
    with pytest.raises(httpx.ConnectError):
        await flushing
    await closing

    assert [item["idempotency_key"] for call in batch.items for item in call] == ["idem-1", "idem-1"]
    assert gate._states["ak_live"].pending == []


def _hold(client: FakeClient, name: str, answer=None) -> list[asyncio.Event]:
    """Apply each call at the authority as it arrives but hold its answer until released."""
    call = getattr(client, name)
    releases: list[asyncio.Event] = []

    async def held(*args, **kwargs):
        result = await call(*args, **kwargs)
        index = len(releases)
        releases.append(asyncio.Event())
        await releases[index].wait()
        return answer(index, result) if answer else result

    setattr(client, name, held)
    return releases


async def _until(condition) -> None:
    while not condition():
        await asyncio.sleep(0)


async def test_a_flush_takes_no_more_of_one_key_than_the_batch_limit():
    client = FakeClient(balance=50)
    gate = TokenGate(_cfg(flush_interval_seconds=60.0, flush_max_batch=2), client)
    for n in range(5):
        assert (await gate.authorize("Bearer ak_live.s", idempotency_key=f"idem-{n}")).allowed

    for _ in range(3):
        await gate.flush()

    assert [[item["idempotency_key"] for item in call] for call in client.batch_calls] == [
        ["idem-0", "idem-1"], ["idem-2", "idem-3"], ["idem-4"],
    ]


async def test_closing_offers_a_queue_longer_than_one_batch_in_full():
    client = FakeClient(balance=50)
    gate = TokenGate(_cfg(flush_interval_seconds=60.0, flush_max_batch=2), client)
    for _ in range(5):
        assert (await gate.authorize("Bearer ak_live.s")).allowed

    await gate.aclose()

    assert [len(call) for call in client.batch_calls] == [2, 2, 1]
    assert gate._states["ak_live"].pending == []


async def test_a_flush_started_while_closing_takes_nothing_and_closing_sends_its_charges():
    client = FakeClient(balance=50)
    gate = TokenGate(_cfg(flush_interval_seconds=60.0), client)
    client.consume_batch = batch = BlockedBatch(client)
    assert (await gate.authorize("Bearer ak_live.s", idempotency_key="idem-1")).allowed
    flushing = asyncio.ensure_future(gate.flush())
    await batch.arrived.wait()
    assert (await gate.authorize("Bearer ak_live.s", idempotency_key="idem-2")).allowed
    closing = asyncio.ensure_future(gate.aclose())
    await asyncio.sleep(0)

    await gate.flush()
    assert len(gate._states["ak_live"].pending) == 1
    batch.release.set()
    await flushing
    await closing

    assert [[item["idempotency_key"] for item in call] for call in batch.items] == [
        ["idem-1"], ["idem-2"],
    ]
    state = gate._states["ak_live"]
    assert (state.pending, state.in_flight) == ([], 0)


async def _ticks(n: int = 20) -> None:
    for _ in range(n):
        await asyncio.sleep(0)


def _done(*futures, timeout: float = 5):
    return asyncio.wait_for(asyncio.gather(*futures), timeout)


async def test_a_second_flush_sharing_a_key_waits_for_the_first_answer():
    client = FakeClient(balance=50)
    gate = TokenGate(_cfg(amount_per_request=3, flush_interval_seconds=60.0), client)
    releases = _hold(client, "consume_batch")
    assert (await gate.authorize("Bearer ak_live.s")).allowed
    first = asyncio.ensure_future(gate.flush())
    await _until(lambda: releases)
    assert (await gate.authorize("Bearer ak_live.s")).allowed
    second = asyncio.ensure_future(gate.flush())

    await _ticks()
    assert len(releases) == 1
    releases[0].set()
    await asyncio.wait_for(_until(lambda: len(releases) == 2), 5)
    releases[1].set()
    await _done(first, second)

    state = gate._states["ak_live"]
    assert (client._balance, state.estimated_balance, state.in_flight) == (44, 44, 0)


async def test_two_synchronous_charges_for_one_key_reach_the_authority_one_at_a_time():
    client = FakeClient(balance=50)
    gate = TokenGate(_cfg(amount_per_request=3), client)
    assert (await gate.authorize("Bearer ak_live.s")).allowed
    releases = _hold(client, "consume")
    charges = [asyncio.ensure_future(gate.authorize("Bearer ak_live.s")) for _ in range(2)]

    await _until(lambda: releases)
    await _ticks()
    assert len(releases) == 1
    releases[0].set()
    await asyncio.wait_for(_until(lambda: len(releases) == 2), 5)
    releases[1].set()
    assert all(decision.allowed for decision in await _done(*charges))

    assert (client._balance, gate._states["ak_live"].estimated_balance) == (41, 41)


async def test_a_synchronous_charge_waits_for_a_batch_out_for_its_key():
    client = FakeClient(balance=50)
    gate = TokenGate(
        _cfg(amount_per_request=3, flush_interval_seconds=60.0, low_balance_threshold=44), client,
    )
    releases = _hold(client, "consume_batch")
    assert (await gate.authorize("Bearer ak_live.s")).allowed
    flushing = asyncio.ensure_future(gate.flush())
    await _until(lambda: releases)
    # 47 - 3 reaches the threshold, so this charge is consumed synchronously.
    charging = asyncio.ensure_future(gate.authorize("Bearer ak_live.s"))

    await _ticks()
    assert client.consume_calls == []
    releases[0].set()
    _, decision = await _done(flushing, charging)

    assert decision.allowed
    assert (client._balance, gate._states["ak_live"].estimated_balance) == (44, 44)


async def test_a_reverification_waits_for_a_batch_out_for_its_key():
    now = [0.0]
    client = FakeClient(balance=50)
    gate = TokenGate(
        _cfg(amount_per_request=3, flush_interval_seconds=60.0, verify_ttl_seconds=10.0),
        client, clock=lambda: now[0],
    )
    releases = _hold(client, "consume_batch")
    assert (await gate.authorize("Bearer ak_live.s")).allowed
    flushing = asyncio.ensure_future(gate.flush())
    await _until(lambda: releases)
    now[0] = 20.0
    charging = asyncio.ensure_future(gate.authorize("Bearer ak_live.s"))

    await _ticks()
    assert client.verify_calls == 1
    releases[0].set()
    _, decision = await _done(flushing, charging)

    assert decision.allowed
    # The authority holds 47 with the second charge still queued.
    assert (client._balance, gate._states["ak_live"].estimated_balance) == (47, 44)


async def test_a_successful_charge_after_a_refused_batch_lifts_the_exhaustion():
    client = FakeClient(balance=50)
    gate = TokenGate(
        _cfg(amount_per_request=3, flush_interval_seconds=60.0, low_balance_threshold=44), client,
    )

    def refuse(index, result):
        return [ConsumeResult(ok=False, balance=4, reason="insufficient_credits")]

    releases = _hold(client, "consume_batch", refuse)
    assert (await gate.authorize("Bearer ak_live.s")).allowed
    flushing = asyncio.ensure_future(gate.flush())
    await _until(lambda: releases)
    # Admitted before the refusal is known, so it reaches the authority after it.
    charging = asyncio.ensure_future(gate.authorize("Bearer ak_live.s"))
    await _ticks()
    releases[0].set()
    _, decision = await _done(flushing, charging)

    assert decision.allowed
    assert gate._states["ak_live"].exhausted is False
    assert (await gate.authorize("Bearer ak_live.s")).allowed
    assert len(client.consume_calls) == 2


async def test_another_secret_is_verified_without_waiting_for_the_key_s_calls():
    client = SecretCheckingClient("ak_victim.real")
    gate = TokenGate(_cfg(), client)
    assert (await gate.authorize("Bearer ak_victim.real")).allowed
    lock = gate._key_lock("ak_victim")
    await lock.acquire()
    try:
        forged = await asyncio.wait_for(gate.authorize("Bearer ak_victim.forged"), 1)
    finally:
        lock.release()

    assert (forged.allowed, forged.status) == (False, 401)


async def test_a_charge_admitted_while_closing_is_consumed_rather_than_queued():
    client = FakeClient(balance=50)
    gate = TokenGate(_cfg(flush_interval_seconds=60.0), client)
    client.consume_batch = batch = BlockedBatch(client)
    assert (await gate.authorize("Bearer ak_live.s")).allowed
    closing = asyncio.ensure_future(gate.aclose())
    await batch.arrived.wait()

    late = asyncio.ensure_future(gate.authorize("Bearer ak_live.s"))
    await _ticks()
    batch.release.set()
    _, decision = await _done(closing, late)

    assert decision.allowed
    assert len(client.consume_calls) == 1
    assert gate._states["ak_live"].pending == []


async def test_a_batch_takes_the_oldest_charges_across_keys():
    client = FakeClient(balance=50)
    gate = TokenGate(_cfg(flush_interval_seconds=60.0, flush_max_batch=2), client)
    assert (await gate.authorize("Bearer ak_hot.s", idempotency_key="hot-0")).allowed
    assert (await gate.authorize("Bearer ak_cold.s", idempotency_key="cold-0")).allowed
    for n in range(1, 4):
        assert (await gate.authorize("Bearer ak_hot.s", idempotency_key=f"hot-{n}")).allowed

    await gate.flush()
    await gate.flush()

    assert [[item["idempotency_key"] for item in call] for call in client.batch_calls] == [
        ["hot-0", "cold-0"], ["hot-1", "hot-2"],
    ]


async def test_a_requeued_key_keeps_its_age_and_does_not_starve_an_older_charge():
    client = FakeClient(balance=50)
    gate = TokenGate(_cfg(flush_interval_seconds=60.0, flush_max_batch=2), client)
    answers = iter([[ConsumeResult(ok=False, balance=0, reason="batch_unavailable")] * 2])
    real = client.consume_batch

    async def unavailable_once(items):
        try:
            answer = next(answers)
        except StopIteration:
            return await real(items)
        client.batch_calls.append(list(items))
        return answer

    client.consume_batch = unavailable_once
    for n in range(2):
        assert (await gate.authorize("Bearer ak_hot.s", idempotency_key=f"hot-{n}")).allowed
    assert (await gate.authorize("Bearer ak_cold.s", idempotency_key="cold-0")).allowed
    assert (await gate.authorize("Bearer ak_hot.s", idempotency_key="hot-2")).allowed

    for _ in range(3):
        await gate.flush()

    assert [[item["idempotency_key"] for item in call] for call in client.batch_calls] == [
        ["hot-0", "hot-1"], ["hot-0", "hot-1"], ["cold-0", "hot-2"],
    ]


async def test_closing_stops_draining_a_key_whose_batch_answer_is_lost():
    client = FakeClient(balance=50)
    gate = TokenGate(_cfg(flush_interval_seconds=60.0, flush_max_batch=2), client)
    real = client.consume_batch
    lost = [True]

    async def lose_first(items):
        if lost:
            lost.pop()
            client.batch_calls.append(list(items))
            return [ConsumeResult(ok=False, balance=0, reason="batch_unavailable") for _ in items]
        return await real(items)

    client.consume_batch = lose_first
    for key, idem in [("a", "a-0"), ("a", "a-1"), ("b", "b-0"), ("a", "a-2"), ("b", "b-1")]:
        assert (await gate.authorize(f"Bearer ak_{key}.s", idempotency_key=idem)).allowed

    with pytest.raises(UnsettledCharges) as unsettled:
        await asyncio.wait_for(gate.aclose(), 5)

    # The later charge of the stalled key never overtakes its lost ones.
    assert [[item["idempotency_key"] for item in call] for call in client.batch_calls] == [
        ["a-0", "a-1"], ["b-0", "b-1"],
    ]
    assert [item["idempotency_key"] for item in unsettled.value.charges] == ["a-0", "a-1", "a-2"]
    state = gate._states["ak_a"]
    assert (state.queued, state.in_flight) == (3, 0)


async def test_a_second_close_waits_for_the_first_and_offers_what_it_left():
    client = FakeClient(balance=50)
    gate = TokenGate(_cfg(flush_interval_seconds=60.0), client)
    real = client.consume_batch
    arrived, release = asyncio.Event(), asyncio.Event()

    async def held_then_lost(items):
        client.batch_calls.append(list(items))
        if len(client.batch_calls) == 1:
            arrived.set()
            await release.wait()
            return [ConsumeResult(ok=False, balance=0, reason="batch_unavailable") for _ in items]
        return await real(items)

    client.consume_batch = held_then_lost
    assert (await gate.authorize("Bearer ak_live.s", idempotency_key="idem-1")).allowed
    first = asyncio.ensure_future(gate.aclose())
    await arrived.wait()
    second = asyncio.ensure_future(gate.aclose())
    await _ticks()

    assert not second.done()
    release.set()
    with pytest.raises(UnsettledCharges):
        await asyncio.wait_for(first, 5)
    await asyncio.wait_for(second, 5)
    assert gate._states["ak_live"].pending == []


async def test_a_batch_keeps_each_key_s_charges_in_order_and_the_rest_queued():
    client = FakeClient(balance=50)
    gate = TokenGate(_cfg(flush_interval_seconds=60.0, flush_max_batch=4), client)
    for n in range(3):
        assert (await gate.authorize("Bearer ak_a.s", idempotency_key=f"a-{n}")).allowed
        assert (await gate.authorize("Bearer ak_b.s", idempotency_key=f"b-{n}")).allowed

    await gate.flush()

    assert [item["idempotency_key"] for item in client.batch_calls[0]] == [
        "a-0", "b-0", "a-1", "b-1",
    ]
    for key_id, left in (("ak_a", "a-2"), ("ak_b", "b-2")):
        state = gate._states[key_id]
        assert [item["idempotency_key"] for item in state.pending] == [left]
        assert (len(state.admitted), state.queued) == (1, 1)


class AuthorityStateClient(FakeClient):
    """An authority whose key can be refused for credit, revoked, or deleted between calls."""

    def __init__(self, *, balance: int) -> None:
        super().__init__(balance=balance)
        self.refusal: str | None = None

    async def verify(self, *, key_id: str, secret: str, service=None, resource_id=None) -> VerifyResult:
        self.verify_calls += 1
        if self.refusal == "key_revoked":
            return VerifyResult(valid=False, status="revoked", balance=0)
        if self.refusal == "key_not_found":
            return VerifyResult(valid=False, status=None, balance=0)
        return VerifyResult(valid=True, status="active", balance=self._balance)

    def _answer(self, amount: int) -> ConsumeResult:
        if self.refusal:
            return ConsumeResult(ok=False, balance=0, reason=self.refusal)
        self._balance -= amount
        return ConsumeResult(ok=True, balance=self._balance, consumed=amount)

    async def consume(self, *, key_id, amount, idempotency_key=None, service=None, resource_id=None) -> ConsumeResult:
        self.consume_calls.append({"key_id": key_id, "amount": amount})
        return self._answer(amount)

    async def consume_batch(self, items) -> list[ConsumeResult]:
        self.batch_calls.append(list(items))
        return [self._answer(item["amount"]) for item in items]


async def test_a_topped_up_key_is_charged_again_once_the_recheck_window_lapses():
    now = [0.0]
    client = AuthorityStateClient(balance=50)
    gate = TokenGate(_cfg(exhausted_recheck_seconds=5.0), client, clock=lambda: now[0])
    client.refusal = "insufficient_credits"
    assert (await gate.authorize("Bearer ak_live.s")).status == 402

    client.refusal = None
    now[0] = 4.0
    assert (await gate.authorize("Bearer ak_live.s")).status == 402
    assert len(client.consume_calls) == 1
    now[0] = 6.0
    assert (await gate.authorize("Bearer ak_live.s")).allowed

    assert len(client.consume_calls) == 2
    assert client.verify_calls == 1
    assert gate._states["ak_live"].exhausted is False


async def test_a_batched_key_is_charged_synchronously_once_its_exhaustion_lapses():
    now = [0.0]
    client = AuthorityStateClient(balance=50)
    gate = TokenGate(
        _cfg(flush_interval_seconds=60.0, exhausted_recheck_seconds=5.0), client,
        clock=lambda: now[0],
    )
    assert (await gate.authorize("Bearer ak_live.s")).allowed
    client.refusal = "insufficient_credits"
    await gate.flush()
    assert (await gate.authorize("Bearer ak_live.s")).status == 402

    client.refusal = None
    now[0] = 6.0
    assert (await gate.authorize("Bearer ak_live.s")).allowed

    assert len(client.consume_calls) == 1
    assert gate._states["ak_live"].pending == []


@pytest.mark.parametrize(
    "reason, status, error",
    [("key_revoked", 403, "key_revoked"), ("key_not_found", 401, "invalid_api_key")],
)
async def test_a_batch_refusing_the_key_itself_denies_it_as_verify_would(reason, status, error):
    client = AuthorityStateClient(balance=50)
    gate = TokenGate(_cfg(flush_interval_seconds=60.0), client)
    assert (await gate.authorize("Bearer ak_live.s")).allowed
    client.refusal = reason
    await gate.flush()

    decision = await gate.authorize("Bearer ak_live.s")

    assert (decision.status, decision.body["error"]) == (status, error)
    assert gate._states["ak_live"].exhausted is False
    assert client.consume_calls == []
    assert len(client.batch_calls) == 1


async def test_a_synchronous_revocation_is_not_followed_by_an_admitted_charge():
    client = AuthorityStateClient(balance=50)
    gate = TokenGate(_cfg(flush_interval_seconds=60.0, low_balance_threshold=48), client)
    assert (await gate.authorize("Bearer ak_live.s")).allowed
    client.refusal = "key_revoked"
    # 49 - 1 reaches the threshold, so this charge is consumed synchronously.
    assert (await gate.authorize("Bearer ak_live.s")).status == 403

    decision = await gate.authorize("Bearer ak_live.s")

    assert (decision.status, decision.body["error"]) == (403, "key_revoked")
    # The charge admitted first reached the authority before the revoking one.
    assert gate._states["ak_live"].pending == []


class CreditClient(AuthorityStateClient):
    """An authority that refuses a charge its key's balance cannot cover."""

    def _answer(self, amount: int) -> ConsumeResult:
        if amount > self._balance:
            return ConsumeResult(ok=False, balance=self._balance, reason="insufficient_credits")
        return super()._answer(amount)


async def test_a_synchronous_charge_settles_the_older_queued_charges_first():
    client = CreditClient(balance=10)
    gate = TokenGate(
        _cfg(amount_per_request=6, flush_interval_seconds=60.0, low_balance_threshold=3), client,
    )
    assert (await gate.authorize("Bearer ak_live.s")).allowed
    # 4 - 6 falls below the threshold, so this one is consumed synchronously.
    decision = await gate.authorize("Bearer ak_live.s")

    # The queued charge took the credit first, so the later request is refused.
    assert (decision.status, decision.body["error"]) == (402, "insufficient_credits")
    assert (len(client.batch_calls), client._balance) == (1, 4)
    state = gate._states["ak_live"]
    assert (state.pending, state.in_flight) == ([], 0)


async def test_a_flush_waiting_for_a_key_leaves_its_charges_to_an_earlier_synchronous_one():
    client = CreditClient(balance=16)
    gate = TokenGate(
        _cfg(amount_per_request=6, flush_interval_seconds=60.0, low_balance_threshold=3), client,
    )
    client.consume_batch = batch = BlockedBatch(client)
    assert (await gate.authorize("Bearer ak_live.s")).allowed
    flushing = asyncio.ensure_future(gate.flush())
    await batch.arrived.wait()
    assert (await gate.authorize("Bearer ak_live.s")).allowed
    # 4 - 6 falls below the threshold; this charge waits for the key behind
    # the first flush, and a second flush waits behind it.
    charging = asyncio.ensure_future(gate.authorize("Bearer ak_live.s"))
    await _ticks()
    second = asyncio.ensure_future(gate.flush())
    await _ticks()

    batch.release.set()
    decision, _, _ = await _done(charging, flushing, second)

    assert decision.status == 402
    assert client._balance == 4
    assert len(client.consume_calls) == 1


async def test_a_synchronous_charge_is_refused_unconsumed_when_older_charges_go_unanswered():
    client = FakeClient(balance=10)
    gate = TokenGate(
        _cfg(amount_per_request=3, flush_interval_seconds=60.0, low_balance_threshold=5), client,
    )

    async def unavailable(items):
        return [ConsumeResult(ok=False, balance=0, reason="batch_unavailable") for _ in items]

    client.consume_batch = unavailable
    assert (await gate.authorize("Bearer ak_live.s", idempotency_key="idem-1")).allowed
    decision = await gate.authorize("Bearer ak_live.s")

    assert (decision.allowed, decision.status, decision.body) == (
        False, 503, {"error": "batch_unavailable"},
    )
    assert client.consume_calls == []
    assert [item["idempotency_key"] for item in gate._states["ak_live"].pending] == ["idem-1"]


async def test_closing_waits_for_a_charge_consumed_synchronously_while_it_drains():
    client = FakeClient(balance=50)
    gate = TokenGate(_cfg(flush_interval_seconds=60.0), client)
    client.consume_batch = batch = BlockedBatch(client)
    releases = _hold(client, "consume")
    assert (await gate.authorize("Bearer ak_live.s")).allowed
    flushing = asyncio.ensure_future(gate.flush())
    await batch.arrived.wait()
    closing = asyncio.ensure_future(gate.aclose())
    await _ticks()
    # Arriving while closing, it is consumed synchronously.
    charging = asyncio.ensure_future(gate.authorize("Bearer ak_live.s"))
    batch.release.set()
    await _until(lambda: releases)
    await _ticks()

    assert not closing.done()
    releases[0].set()
    decision, _, _ = await _done(charging, flushing, closing)
    assert decision.allowed


async def test_a_synchronous_charge_is_refused_unconsumed_when_older_charges_meet_a_transport_error():
    client = FakeClient(balance=10)
    gate = TokenGate(
        _cfg(amount_per_request=3, flush_interval_seconds=60.0, low_balance_threshold=5), client,
    )

    async def unreachable(items):
        raise httpx.ConnectError("connection refused")

    client.consume_batch = unreachable
    assert (await gate.authorize("Bearer ak_live.s", idempotency_key="idem-1")).allowed
    decision = await gate.authorize("Bearer ak_live.s")

    assert (decision.status, decision.body) == (503, {"error": "batch_unavailable"})
    assert client.consume_calls == []
    state = gate._states["ak_live"]
    assert ([item["idempotency_key"] for item in state.pending], state.in_flight) == (["idem-1"], 0)


async def test_a_request_verifying_when_the_gate_closes_is_refused_its_charge():
    client = HeldVerificationClient("ak_k.s", "ak_k.s")
    gate = TokenGate(_cfg(flush_interval_seconds=60.0), client)
    request = asyncio.ensure_future(gate.authorize("Bearer ak_k.s"))
    await asyncio.wait_for(client.started.wait(), timeout=5)

    await asyncio.wait_for(gate.aclose(), 5)
    client.release.set()
    decision = await asyncio.wait_for(request, 5)

    assert (decision.allowed, decision.status, decision.body) == (
        False, 503, {"error": "gate_closed"},
    )
    assert client.consumed == 0


async def test_the_middleware_reports_unsettled_charges_after_the_app_shuts_down():
    client = FakeClient(balance=50)
    gate = TokenGate(_cfg(flush_interval_seconds=60.0), client)

    async def unavailable(items):
        return [ConsumeResult(ok=False, balance=0, reason="batch_unavailable") for _ in items]

    client.consume_batch = unavailable
    assert (await gate.authorize("Bearer ak_live.s")).allowed
    seen: list[str] = []

    async def app(scope, receive, send):
        while (message := await receive())["type"] != "lifespan.shutdown":
            seen.append(message["type"])
        seen.append(message["type"])

    messages = iter([{"type": "lifespan.startup"}, {"type": "lifespan.shutdown"}])

    async def receive():
        return next(messages)

    async def send(message):
        pass

    with pytest.raises(UnsettledCharges):
        await TokenGateMiddleware(app, gate=gate)({"type": "lifespan"}, receive, send)
    assert seen == ["lifespan.startup", "lifespan.shutdown"]


async def test_a_closed_gate_refuses_verification_without_the_authority():
    client = FakeClient(balance=50)
    gate = TokenGate(_cfg(), client)
    await gate.aclose()

    decision = await gate.verify("Bearer ak_live.s")

    assert (decision.status, decision.body) == (503, {"error": "gate_closed"})
    assert client.verify_calls == 0


def _scripted_authority(consume_answers):
    """A TokensClient over HTTP: verify answers 100 credits, consume and batch take scripted answers."""
    batch_answers: list = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/verify"):
            return httpx.Response(200, json={"valid": True, "status": "active", "balance": 100})
        answer = (batch_answers if request.url.path.endswith("consume-batch") else consume_answers).pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return TokensClient(service_url="http://svc", http=http), batch_answers


@pytest.mark.parametrize("answer", [
    httpx.Response(503),
    httpx.Response(502, text="upstream down"),
    httpx.Response(500, json={"error": "internal"}),
    httpx.Response(200, json=["not", "an", "object"]),
    httpx.ConnectError("connection reset"),
], ids=["empty", "text", "unknown-error", "not-an-object", "transport"])
async def test_a_consume_without_an_answer_is_unavailable_not_exhaustion(answer):
    client, _ = _scripted_authority([answer])

    result = await client.consume(key_id="ak_live", amount=1, idempotency_key="idem-1")

    assert (result.ok, result.reason) == (False, "credits_unavailable")


async def test_a_batch_item_is_a_refusal_only_when_it_names_its_reason():
    client, batch_answers = _scripted_authority([])
    batch_answers.append(httpx.Response(200, json={"results": [
        {"ok": False}, {"ok": False, "reason": "scope_required"}, {"ok": False, "reason": "key_revoked"},
    ]}))

    results = await client.consume_batch([{"key_id": "a"}, {"key_id": "b"}, {"key_id": "c"}])

    assert [r.reason for r in results] == ["batch_unavailable", "scope_required", "key_revoked"]


async def test_a_consume_refused_with_a_named_reason_passes_it_on():
    client, _ = _scripted_authority([httpx.Response(400, json={"error": "scope_required"})])

    result = await client.consume(key_id="ak_live", amount=1)

    assert (result.ok, result.reason) == (False, "scope_required")


async def test_a_refusal_of_the_gate_s_own_call_is_502_and_leaves_the_key_untouched():
    client, _ = _scripted_authority([httpx.Response(400, json={"error": "scope_required"})])
    gate = TokenGate(_cfg(purchase=PurchasePointer(listing_id="lst-1")), client)

    decision = await gate.authorize("Bearer ak_live.s")

    assert (decision.status, decision.body) == (502, {"error": "scope_required"})
    state = gate._states["ak_live"]
    assert (state.exhausted, state.uncertain, state.estimated_balance) == (False, False, 100)


async def test_a_batched_item_refused_for_the_gate_s_own_call_is_not_resent_nor_exhausts_the_key():
    client, batch_answers = _scripted_authority([])
    batch_answers.append(httpx.Response(200, json={"results": [{"ok": False, "reason": "scope_required"}]}))
    gate = TokenGate(_cfg(flush_interval_seconds=60.0), client)
    assert (await gate.authorize("Bearer ak_live.s")).allowed

    await gate.flush()

    state = gate._states["ak_live"]
    assert (state.pending, state.in_flight, state.exhausted) == ([], 0, False)


async def test_an_unanswered_consume_is_503_and_the_key_is_charged_at_the_authority_until_it_answers():
    ok = httpx.Response(200, json={"ok": True, "consumed": 1, "balance": 97})
    client, _ = _scripted_authority([httpx.Response(503), ok])
    gate = TokenGate(
        _cfg(flush_interval_seconds=60.0, low_balance_threshold=99, purchase=PurchasePointer(listing_id="lst-1")),
        client,
    )

    decision = await gate.authorize("Bearer ak_live.s")

    # No purchase pointer: nothing says the key is out of credit.
    assert (decision.status, decision.body) == (503, {"error": "credits_unavailable"})
    state = gate._states["ak_live"]
    assert (state.exhausted, state.uncertain, state.estimated_balance) == (False, True, 100)

    gate._cfg = dataclasses.replace(gate._cfg, low_balance_threshold=0)
    # Charged synchronously although the estimate would admit it optimistically.
    assert (await gate.authorize("Bearer ak_live.s")).allowed
    assert (state.uncertain, state.estimated_balance, state.pending) == (False, 97, [])

    assert (await gate.authorize("Bearer ak_live.s")).allowed
    assert len(state.pending) == 1


async def test_the_middleware_shuts_the_app_down_before_raising_any_close_error():
    client = FakeClient(balance=50)
    gate = TokenGate(_cfg(flush_interval_seconds=60.0), client)

    async def unreachable(items):
        raise httpx.ConnectError("authority unavailable")

    client.consume_batch = unreachable
    assert (await gate.authorize("Bearer ak_live.s")).allowed
    seen: list[str] = []

    async def app(scope, receive, send):
        while (message := await receive())["type"] != "lifespan.shutdown":
            seen.append(message["type"])
        seen.append(message["type"])

    messages = iter([{"type": "lifespan.startup"}, {"type": "lifespan.shutdown"}])

    async def receive():
        return next(messages)

    async def send(message):
        pass

    with pytest.raises(httpx.ConnectError):
        await TokenGateMiddleware(app, gate=gate)({"type": "lifespan"}, receive, send)
    assert seen == ["lifespan.startup", "lifespan.shutdown"]


def _verifying_authority(verify_answers):
    """A TokensClient whose verifications take scripted answers and whose consumes succeed."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/verify"):
            answer = verify_answers.pop(0)
            if isinstance(answer, Exception):
                raise answer
            return answer
        return httpx.Response(200, json={"ok": True, "consumed": 1, "balance": 99})

    return TokensClient(service_url="http://svc", http=httpx.AsyncClient(transport=httpx.MockTransport(handler)))


@pytest.mark.parametrize("answer", [
    httpx.ConnectError("authority unavailable"),
    httpx.Response(503),
    httpx.Response(200, text="upstream down"),
    httpx.Response(200, json={"valid": "false", "status": "revoked", "balance": 100}),
    httpx.Response(200, json={"status": "active", "balance": 100}),
    httpx.Response(200, json={"valid": True, "status": "active", "balance": "100"}),
], ids=["transport", "5xx", "text", "string-valid", "no-valid", "string-balance"])
async def test_a_verification_without_a_readable_answer_is_unavailable(answer):
    client = _verifying_authority([answer])

    result = await client.verify(key_id="ak_live", secret="ak_live.s")

    assert isinstance(result, VerifyUnavailable)


async def test_a_verification_refused_at_the_http_layer_is_not_valid():
    client = _verifying_authority([httpx.Response(422, json={"error": "scope_required"})])

    result = await client.verify(key_id="ak_live", secret="ak_live.s")

    assert (type(result), result.valid) == (VerifyResult, False)


async def test_an_unavailable_verification_is_503_and_records_nothing():
    valid = httpx.Response(200, json={"valid": True, "status": "active", "balance": 100})
    client = _verifying_authority([httpx.ConnectError("authority unavailable"), valid])
    gate = TokenGate(_cfg(), client)

    decision = await gate.authorize("Bearer ak_live.s")

    assert (decision.status, decision.body) == (503, {"error": "credits_unavailable"})
    assert "ak_live" not in gate._states
    assert (await gate.authorize("Bearer ak_live.s")).allowed


@pytest.mark.parametrize("answer", [
    {"ok": "false", "balance": 10},
    {"ok": True, "balance": 10, "consumed": "1"},
], ids=["string-ok", "string-consumed"])
async def test_a_consume_with_mistyped_fields_is_unavailable(answer):
    client, batch_answers = _scripted_authority([httpx.Response(200, json=answer)])
    batch_answers.append(httpx.Response(200, json={"results": [answer]}))

    single = await client.consume(key_id="ak_live", amount=1)
    batched = await client.consume_batch([{"key_id": "ak_live"}])

    assert (single.ok, single.reason) == (False, "credits_unavailable")
    assert [(r.ok, r.reason) for r in batched] == [(False, "batch_unavailable")]
