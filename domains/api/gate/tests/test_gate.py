"""Batched-flush behavior, the ASGI binding, and the verify cache's tie to the secret.

The synchronous decision table is pinned by the conformance session;
these cover what is outside it: the optimistic batched charge path
(timing-dependent, so impl-local), the ASGI adapter end to end, and a
cached verification answering only for the secret that earned it.
"""

from __future__ import annotations

import httpx

from arkhai_api_gate.client import ConsumeResult, TokensClient, VerifyResult
from arkhai_api_gate.config import GateConfig, PurchasePointer
from arkhai_api_gate.gate import TokenGate
from arkhai_api_gate.asgi import TokenGateMiddleware


class FakeClient:
    """Records calls and returns canned results — for batch-vs-sync asserts."""

    def __init__(self, *, balance: int) -> None:
        self._balance = balance
        self.verify_calls = 0
        self.consume_calls: list[dict] = []
        self.batch_calls: list[list[dict]] = []

    async def verify(self, *, key_id: str, secret: str) -> VerifyResult:
        self.verify_calls += 1
        return VerifyResult(valid=True, status="active", balance=self._balance)

    async def consume(self, *, key_id, amount, idempotency_key=None) -> ConsumeResult:
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

    async def verify(self, *, key_id: str, secret: str) -> VerifyResult:
        self.verified.append(secret)
        if secret in self.accepted:
            return VerifyResult(valid=True, status="active", balance=10)
        return VerifyResult(valid=False, status=None, balance=0)

    async def consume(self, *, key_id, amount, idempotency_key=None) -> ConsumeResult:
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
