"""Async client for the tokens service's middleware-facing surface.

Thin wrapper over ``verify`` / ``consume`` / ``consume-batch``. All
verification and accounting authority lives in the service; this only
shapes requests and classifies responses into the small result vocab
the gate dispatches on. ``httpx`` is injectable so tests drive it with
a ``MockTransport`` instead of a live service.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx


# Service reason vocabulary (mirrors services.keys_service constants).
KEY_NOT_FOUND = "key_not_found"
KEY_REVOKED = "key_revoked"
INSUFFICIENT_CREDITS = "insufficient_credits"


@dataclass(frozen=True)
class VerifyResult:
    valid: bool
    status: str | None
    balance: int


@dataclass(frozen=True)
class ConsumeResult:
    ok: bool
    balance: int
    consumed: int = 0
    duplicate: bool = False
    reason: str | None = None  # set when ok is False


class TokensClient:
    """Calls the tokens service for one gated app.

    Pass ``http`` (an ``httpx.AsyncClient``) to reuse a pooled
    connection across requests; tests pass one backed by a
    ``MockTransport``. When omitted, a client is created per call —
    convenient but unpooled.
    """

    def __init__(
        self,
        *,
        service_url: str,
        admin_key: str = "",
        timeout: float = 10.0,
        http: httpx.AsyncClient | None = None,
    ) -> None:
        self._base = service_url.rstrip("/")
        self._headers = {"X-Admin-Key": admin_key} if admin_key else {}
        self._timeout = timeout
        self._http = http

    async def _post(self, path: str, body: dict[str, Any]) -> httpx.Response:
        url = self._base + path
        if self._http is not None:
            return await self._http.post(url, json=body, headers=self._headers)
        async with httpx.AsyncClient(timeout=self._timeout) as http:
            return await http.post(url, json=body, headers=self._headers)

    async def verify(self, *, key_id: str, secret: str) -> VerifyResult:
        resp = await self._post(f"/api/v1/keys/{key_id}/verify", {"secret": secret})
        if resp.status_code != 200:
            # Auth/transport problems are treated as "not valid" — the
            # gate denies rather than failing open.
            return VerifyResult(valid=False, status=None, balance=0)
        data = resp.json()
        return VerifyResult(
            valid=bool(data.get("valid")),
            status=data.get("status"),
            balance=int(data.get("balance") or 0),
        )

    async def consume(
        self, *, key_id: str, amount: int, idempotency_key: str | None = None,
    ) -> ConsumeResult:
        body: dict[str, Any] = {"amount": int(amount)}
        if idempotency_key is not None:
            body["idempotency_key"] = idempotency_key
        resp = await self._post(f"/api/v1/keys/{key_id}/consume", body)
        data = resp.json() if resp.content else {}
        if resp.status_code == 200 and data.get("ok"):
            return ConsumeResult(
                ok=True,
                balance=int(data.get("balance") or 0),
                consumed=int(data.get("consumed") or 0),
                duplicate=bool(data.get("duplicate")),
            )
        # Refusals carry {"error": reason, "balance": B}; an unexpected
        # status with no error maps to insufficient_credits so the gate
        # fails closed.
        reason = data.get("error") or data.get("reason") or INSUFFICIENT_CREDITS
        return ConsumeResult(
            ok=False, balance=int(data.get("balance") or 0), reason=reason,
        )

    async def consume_batch(
        self, items: list[dict[str, Any]],
    ) -> list[ConsumeResult]:
        resp = await self._post("/api/v1/keys/consume-batch", {"items": items})
        if resp.status_code != 200:
            # The whole flush failed at the transport/auth layer; report
            # every item as a soft failure so the caller can retry.
            return [
                ConsumeResult(ok=False, balance=0, reason="batch_unavailable")
                for _ in items
            ]
        results = resp.json().get("results") or []
        out: list[ConsumeResult] = []
        for r in results:
            if r.get("ok"):
                out.append(ConsumeResult(
                    ok=True,
                    balance=int(r.get("balance") or 0),
                    consumed=int(r.get("consumed") or 0),
                    duplicate=bool(r.get("duplicate")),
                ))
            else:
                out.append(ConsumeResult(
                    ok=False,
                    balance=int(r.get("balance") or 0),
                    reason=r.get("reason") or r.get("error") or INSUFFICIENT_CREDITS,
                ))
        return out
