"""Async client for the authority's gate-facing surface.

Thin wrapper over ``verify`` / ``consume`` / ``consume-batch``. All
verification and accounting authority lives in the authority; this only
shapes requests and classifies responses into the small result vocab
the gate dispatches on. ``httpx`` is injectable so tests drive it with
a ``MockTransport`` instead of a live authority.
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


# The authority's consume refusal reasons.
KEY_NOT_FOUND = "key_not_found"
KEY_REVOKED = "key_revoked"
INSUFFICIENT_CREDITS = "insufficient_credits"
KEY_OUT_OF_SCOPE = "key_out_of_scope"
#: The family authority's refusals of a key or of its credit.
REFUSALS = frozenset({KEY_NOT_FOUND, KEY_REVOKED, INSUFFICIENT_CREDITS, KEY_OUT_OF_SCOPE})

#: Denial reported when the authority answered but could not be established
#: as the authority. Distinct from `insufficient_credits`: the key may be
#: perfectly good and something on the path is answering for the authority.
UNAUTHENTICATED_SERVICE = "unauthenticated_service"

#: Reported for every item of a batch the authority did not answer; whether
#: it settled them is unknown.
BATCH_UNAVAILABLE = "batch_unavailable"

#: Reported for a consume the authority did not answer with a result or a
#: refusal — a ``4xx`` naming its reason; whether it was applied is unknown.
CREDITS_UNAVAILABLE = "credits_unavailable"

#: The path and signed operation of each route this client calls, spelled
#: locally so the gate depends on httpx alone. The authority signs over its
#: own declarations, so any drift fails verification;
#: `tests/test_contract_parity.py` holds them equal. The batch route names no
#: single key, so it signs the empty resource.
VERIFY_PATH = "/api/v1/keys/{key_id}/verify"
CONSUME_PATH = "/api/v1/keys/{key_id}/consume"
CONSUME_BATCH_PATH = "/api/v1/keys/consume-batch"
VERIFY_OPERATION = "credits_key_verify"
CONSUME_OPERATION = "credits_key_consume"
CONSUME_BATCH_OPERATION = "credits_key_consume_batch"
BATCH_RESOURCE = ""

#: Re-exported beside the operation table it pairs with: the role is what
#: decides whether a verified signature is also permitted on the route.
__all_roles__ = (GATED_APP_ROLE,)


@dataclass(frozen=True)
class VerifyResult:
    """A key's verification; a pinned key's accepted terms, digest, and charge, ``None`` when unpinned."""

    valid: bool
    status: str | None
    balance: int
    accepted_terms: dict[str, Any] | None = None
    terms_digest: str | None = None
    request_charge: int | None = None


@dataclass(frozen=True)
class VerifyUnavailable(VerifyResult):
    """No readable answer from the authority, so nothing is known about the key."""


_UNAVAILABLE = VerifyUnavailable(valid=False, status=None, balance=0)


def _flag(data: dict[str, Any], name: str, *, required: bool = False) -> bool:
    value = data[name] if required else data.get(name, False)
    if not isinstance(value, bool):
        raise ValueError(f"{name} is not a boolean")
    return value


def _whole(data: dict[str, Any], name: str) -> int:
    value = data.get(name)
    if value is None:
        return 0
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} is not an integer")
    return value


def _text(data: dict[str, Any], name: str) -> str | None:
    value = data.get(name)
    if value is not None and not isinstance(value, str):
        raise ValueError(f"{name} is not a string")
    return value


def scope_fields(service: str | None, resource_id: str | None) -> dict[str, str]:
    """The expected key scope a request or batch item carries; nothing when unset."""
    scope = {}
    if service is not None:
        scope["service"] = service
    if resource_id is not None:
        scope["resource_id"] = resource_id
    return scope


@dataclass(frozen=True)
class ConsumeResult:
    ok: bool
    balance: int
    consumed: int = 0
    duplicate: bool = False
    reason: str | None = None  # set when ok is False


class TokensClient:
    """Calls the authority for one gated app.

    Pass ``http`` (an ``httpx.AsyncClient``) to reuse a pooled
    connection across requests; tests pass one backed by a
    ``MockTransport``. When omitted, a client is created per call —
    convenient but unpooled.

    ``signing`` selects how the authority is authenticated to. With it, each
    request carries a marketplace identity v2 envelope signed in the
    ``service`` role and every response — refusals included — is verified
    as the authority's. Without it, the legacy ``X-Admin-Key`` shared
    secret is sent, which is all the TypeScript and Rust siblings can
    currently do. Both are supported because the authority accepts exactly
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

        ``operation`` is required for a signed call and is the authority's own
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

    async def verify(
        self,
        *,
        key_id: str,
        secret: str,
        service: str | None = None,
        resource_id: str | None = None,
    ) -> VerifyResult:
        try:
            resp = await self._post(
                VERIFY_PATH.format(key_id=key_id),
                {"secret": secret, **scope_fields(service, resource_id)},
                operation=VERIFY_OPERATION,
                resource=key_id,
            )
            if resp.status_code >= 500:
                return _UNAVAILABLE
            if resp.status_code != 200:
                return VerifyResult(valid=False, status=None, balance=0)
            data = resp.json()
            if not isinstance(data, dict):
                return _UNAVAILABLE
            terms = data.get("accepted_terms")
            if terms is not None and not isinstance(terms, dict):
                return _UNAVAILABLE
            return VerifyResult(
                valid=_flag(data, "valid", required=True),
                status=_text(data, "status"),
                balance=_whole(data, "balance"),
                accepted_terms=terms,
                terms_digest=_text(data, "terms_digest"),
                request_charge=None if data.get("request_charge") is None else _whole(data, "request_charge"),
            )
        except (ResponseAuthenticationError, httpx.TransportError, KeyError, ValueError):
            # An answer that cannot be authenticated, an unsigned proxy outage
            # included, says nothing about the key.
            return _UNAVAILABLE

    async def consume(
        self,
        *,
        key_id: str,
        amount: int,
        idempotency_key: str | None = None,
        service: str | None = None,
        resource_id: str | None = None,
    ) -> ConsumeResult:
        body: dict[str, Any] = {"amount": int(amount)}
        if idempotency_key is not None:
            body["idempotency_key"] = idempotency_key
        body.update(scope_fields(service, resource_id))
        unavailable = ConsumeResult(ok=False, balance=0, reason=CREDITS_UNAVAILABLE)
        try:
            resp = await self._post(
                CONSUME_PATH.format(key_id=key_id),
                body,
                operation=CONSUME_OPERATION,
                resource=key_id,
            )
            data = resp.json() if resp.content else {}
            if not isinstance(data, dict):
                return unavailable
            if resp.status_code == 200 and _flag(data, "ok"):
                return ConsumeResult(
                    ok=True,
                    balance=_whole(data, "balance"),
                    consumed=_whole(data, "consumed"),
                    duplicate=_flag(data, "duplicate"),
                )
            reason = data.get("error") or data.get("reason")
            if not (400 <= resp.status_code < 500 and isinstance(reason, str) and reason):
                return unavailable
            return ConsumeResult(ok=False, balance=_whole(data, "balance"), reason=reason)
        except ResponseAuthenticationError:
            # Fails closed, and says which kind of closed: an unverifiable
            # answer is not evidence the key is out of credits.
            return ConsumeResult(
                ok=False, balance=0, reason=UNAUTHENTICATED_SERVICE,
            )
        except (httpx.TransportError, ValueError):
            return unavailable

    async def consume_batch(
        self, items: list[dict[str, Any]],
    ) -> list[ConsumeResult]:
        """Settle ``items`` as given; each carries its own key, amount, idempotency key, and scope."""
        try:
            resp = await self._post(
                CONSUME_BATCH_PATH,
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
                ConsumeResult(ok=False, balance=0, reason=BATCH_UNAVAILABLE)
                for _ in items
            ]
        try:
            results = resp.json().get("results") or []
        except (ValueError, AttributeError):
            results = []
        out: list[ConsumeResult] = []
        for r in results:
            try:
                if not isinstance(r, dict):
                    raise ValueError("not an object")
                if _flag(r, "ok"):
                    out.append(ConsumeResult(
                        ok=True,
                        balance=_whole(r, "balance"),
                        consumed=_whole(r, "consumed"),
                        duplicate=_flag(r, "duplicate"),
                    ))
                elif isinstance(reason := r.get("reason") or r.get("error"), str) and reason:
                    out.append(ConsumeResult(ok=False, balance=_whole(r, "balance"), reason=reason))
                else:
                    raise ValueError("neither a result nor a refusal")
            except ValueError:
                out.append(ConsumeResult(ok=False, balance=0, reason=BATCH_UNAVAILABLE))
        return out


def _response_body(response: httpx.Response) -> Any:
    """The body exactly as the signature covers it.

    An empty body is ``None`` here and becomes ``EMPTY_BODY`` in the
    envelope, matching how the authority hashes a bodyless response. A
    non-JSON body is passed through as text so a malformed answer fails
    verification rather than raising while being read.
    """
    if not response.content:
        return None
    try:
        return response.json()
    except ValueError:
        return response.text
