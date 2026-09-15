"""Async client for the credits service's middleware-facing surface.

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

from .signing import (
    GATED_APP_ROLE,
    AuthoritySigning,
    ResponseAuthenticationError,
)


# Service reason vocabulary (mirrors services.keys_service constants).
KEY_NOT_FOUND = "key_not_found"
KEY_REVOKED = "key_revoked"
INSUFFICIENT_CREDITS = "insufficient_credits"

#: Denial reported when the authority answered but could not be established
#: as the authority. Distinct from `insufficient_credits`: the key may be
#: perfectly good and something on the path is answering for the service.
UNAUTHENTICATED_SERVICE = "unauthenticated_service"

#: The signed identity of each operation this client performs, keyed by the
#: client method that performs it.
#:
#: These must agree exactly with `CREDITS_ROUTE_CONTRACTS` in the credits
#: service (`domains/apicredits/service/src/middleware/route_contracts.py`):
#: the service recomputes the operation and resource from the matched route
#: and verifies the signature over *its* values, so a disagreement here is
#: not a loose end -- it is a signature that cannot verify. The batch route
#: signs the empty resource because it names no single key; its contract
#: declares no `path_resource`.
#:
#: `test_route_contract_parity.py` asserts this table against the service's,
#: so a route change on either side fails a test rather than a deployment.
VERIFY_OPERATION = "credits_key_verify"
CONSUME_OPERATION = "credits_key_consume"
CONSUME_BATCH_OPERATION = "credits_key_consume_batch"
BATCH_RESOURCE = ""

#: Re-exported beside the operation table it pairs with: the role is what
#: decides whether a verified signature is also permitted on the route.
__all_roles__ = (GATED_APP_ROLE,)


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
    """Calls the credits service for one gated app.

    Pass ``http`` (an ``httpx.AsyncClient``) to reuse a pooled
    connection across requests; tests pass one backed by a
    ``MockTransport``. When omitted, a client is created per call —
    convenient but unpooled.

    ``signing`` selects how the service is authenticated to. With it, each
    request carries a marketplace identity v2 envelope signed in the
    ``service`` role and every response — refusals included — is verified
    as the authority's. Without it, the legacy ``X-Admin-Key`` shared
    secret is sent, which is all the TypeScript and Rust siblings can
    currently do. Both are supported because the service accepts exactly
    one of them at a time, chosen by its own configuration.
    """

    def __init__(
        self,
        *,
        service_url: str,
        admin_key: str = "",
        timeout: float = 10.0,
        http: httpx.AsyncClient | None = None,
        signing: AuthoritySigning | None = None,
    ) -> None:
        self._base = service_url.rstrip("/")
        self._headers = {"X-Admin-Key": admin_key} if admin_key else {}
        self._timeout = timeout
        self._http = http
        self._signing = signing

    async def _post(
        self,
        path: str,
        body: dict[str, Any],
        *,
        operation: str | None = None,
        resource: str = "",
    ) -> httpx.Response:
        """POST ``body`` to ``path``, signed when this client is configured to.

        ``operation`` is required for a signed call and is the service's own
        name for the route, not a label chosen here.
        """
        url = self._base + path
        if self._signing is None:
            return await self._send(url, json=body, headers=self._headers)
        if operation is None:
            raise ValueError("a signed request requires its operation name")
        call = self._signing.sign(
            method="POST", operation=operation, resource=resource, body=body,
        )
        response = await self._send(url, content=call.content, headers=call.headers)
        self._signing.verify(
            call,
            headers=response.headers,
            status=response.status_code,
            body=_response_body(response),
        )
        return response

    async def _send(self, url: str, **kwargs: Any) -> httpx.Response:
        if self._http is not None:
            return await self._http.post(url, **kwargs)
        async with httpx.AsyncClient(timeout=self._timeout) as http:
            return await http.post(url, **kwargs)

    async def verify(self, *, key_id: str, secret: str) -> VerifyResult:
        try:
            resp = await self._post(
                f"/api/v1/keys/{key_id}/verify",
                {"secret": secret},
                operation=VERIFY_OPERATION,
                resource=key_id,
            )
        except ResponseAuthenticationError:
            # Same disposition as a transport failure below: the gate denies
            # rather than failing open. Logged by the caller's handler.
            return VerifyResult(valid=False, status=None, balance=0)
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
        try:
            resp = await self._post(
                f"/api/v1/keys/{key_id}/consume",
                body,
                operation=CONSUME_OPERATION,
                resource=key_id,
            )
        except ResponseAuthenticationError:
            # Fails closed, and says which kind of closed: an unverifiable
            # answer is not evidence the key is out of credits.
            return ConsumeResult(
                ok=False, balance=0, reason=UNAUTHENTICATED_SERVICE,
            )
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
        try:
            resp = await self._post(
                "/api/v1/keys/consume-batch",
                {"items": items},
                operation=CONSUME_BATCH_OPERATION,
                resource=BATCH_RESOURCE,
            )
        except ResponseAuthenticationError:
            return [
                ConsumeResult(
                    ok=False, balance=0, reason=UNAUTHENTICATED_SERVICE,
                )
                for _ in items
            ]
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


def _response_body(response: httpx.Response) -> Any:
    """The body exactly as the signature covers it.

    An empty body is ``None`` here and becomes ``EMPTY_BODY`` in the
    envelope, matching how the service hashes a bodyless response. A
    non-JSON body is passed through as text so a malformed answer fails
    verification rather than raising while being read.
    """
    if not response.content:
        return None
    try:
        return response.json()
    except ValueError:
        return response.text
