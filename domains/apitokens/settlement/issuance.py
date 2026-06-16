"""Tokens-service issuance client.

The storefront's settlement job talks to the tokens service
(``arkhai-apitokens-service``) over its admin-gated HTTP surface:
``POST /api/v1/issuance`` is the fulfillment call (idempotent on
``escrow_uid`` — the service owns retry semantics, secret rotation,
and the authoritative ownership re-check), ``GET /api/v1/keys/{id}``
is the negotiation guards' key→owner lookup, and the revoke/adjust
verbs back the fulfillment-failure rollback.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class TokensServiceError(RuntimeError):
    """A tokens-service call failed with a market-meaningful reason.

    ``reason`` carries the service's error vocabulary (``key_not_found``
    / ``key_not_owned`` / ``key_revoked`` / ``quota_exhausted``);
    transport-level failures raise the underlying httpx error instead.
    """

    def __init__(self, reason: str, detail: str = "", *, status_code: int = 0) -> None:
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason
        self.detail = detail
        self.status_code = status_code


def _headers(admin_key: str) -> dict[str, str]:
    return {"X-Admin-Key": admin_key} if admin_key else {}


async def submit_token_issuance(
    *,
    service_url: str,
    admin_key: str,
    escrow_uid: str,
    quantity: int,
    key_mode: str = "new",
    key_id: str | None = None,
    buyer_wallet: str | None = None,
    allocation_id: str | None = None,
    resource_id: str | None = None,
    timeout: float = 30.0,
) -> dict[str, Any]:
    """Issue ``quantity`` credits for a settled escrow.

    Returns the issuance dict ``{key_id, secret?, quantity, balance,
    allocation_id, already_issued}``. ``secret`` is present only for a
    newly created (or rotated-on-retry) key — delivered once, to the
    buyer, through the settle-status channel.

    Raises :class:`TokensServiceError` on a market-state refusal and
    httpx errors on transport failure.
    """
    key: dict[str, Any] = {"mode": key_mode}
    if key_id is not None:
        key["key_id"] = key_id
    body: dict[str, Any] = {
        "escrow_uid": escrow_uid,
        "quantity": int(quantity),
        "key": key,
    }
    if buyer_wallet:
        body["buyer"] = {"scheme": "wallet", "id": buyer_wallet}
    if allocation_id:
        body["allocation_id"] = allocation_id
    if resource_id:
        body["resource_id"] = resource_id

    async with httpx.AsyncClient(timeout=timeout) as http:
        resp = await http.post(
            f"{service_url.rstrip('/')}/api/v1/issuance",
            json=body,
            headers=_headers(admin_key),
        )
    if resp.status_code == 200:
        return resp.json()
    try:
        payload = resp.json()
    except ValueError:
        payload = {}
    raise TokensServiceError(
        str(payload.get("error") or f"http_{resp.status_code}"),
        str(payload.get("detail") or resp.text[:200]),
        status_code=resp.status_code,
    )


async def get_key(
    *,
    service_url: str,
    admin_key: str,
    key_id: str,
    timeout: float = 10.0,
) -> dict[str, Any] | None:
    """The key's ownership claim + status, or None when unknown."""
    async with httpx.AsyncClient(timeout=timeout) as http:
        resp = await http.get(
            f"{service_url.rstrip('/')}/api/v1/keys/{key_id}",
            headers=_headers(admin_key),
        )
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    return resp.json()


async def revoke_key(
    *,
    service_url: str,
    admin_key: str,
    key_id: str,
    timeout: float = 10.0,
) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=timeout) as http:
        resp = await http.post(
            f"{service_url.rstrip('/')}/api/v1/keys/{key_id}/revoke",
            headers=_headers(admin_key),
        )
    resp.raise_for_status()
    return resp.json()


async def adjust_key_balance(
    *,
    service_url: str,
    admin_key: str,
    key_id: str,
    delta: int,
    reason: str,
    timeout: float = 10.0,
) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=timeout) as http:
        resp = await http.post(
            f"{service_url.rstrip('/')}/api/v1/keys/{key_id}/adjust",
            json={"delta": int(delta), "reason": reason},
            headers=_headers(admin_key),
        )
    resp.raise_for_status()
    return resp.json()


async def rollback_issuance(
    *,
    service_url: str,
    admin_key: str,
    escrow_uid: str,
    issuance: dict[str, Any],
    key_mode: str,
) -> dict[str, Any]:
    """Undo an issuance whose deal failed after the grant landed.

    Claws the granted quantity back off the balance; a key this deal
    created is also revoked (nothing else funds it). The adjust may
    refuse when the buyer already consumed below the clawback — that is
    surfaced, not hidden: the operator decides, the action result says
    what happened.
    """
    key_id = str(issuance.get("key_id") or "")
    quantity = int(issuance.get("quantity") or 0)
    out: dict[str, Any] = {"key_id": key_id, "rolled_back": False}
    if not key_id or quantity <= 0:
        out["reason"] = "nothing_to_roll_back"
        return out
    try:
        await adjust_key_balance(
            service_url=service_url,
            admin_key=admin_key,
            key_id=key_id,
            delta=-quantity,
            reason=f"rollback:{escrow_uid}",
        )
        out["rolled_back"] = True
    except Exception as exc:
        out["reason"] = f"adjust_failed: {exc}"
        logger.warning(
            "[ISSUANCE] rollback adjust failed for %s (escrow %s): %s",
            key_id, escrow_uid, exc,
        )
    if key_mode == "new":
        try:
            await revoke_key(
                service_url=service_url, admin_key=admin_key, key_id=key_id,
            )
            out["revoked"] = True
        except Exception as exc:
            out["revoked"] = False
            logger.warning(
                "[ISSUANCE] rollback revoke failed for %s (escrow %s): %s",
                key_id, escrow_uid, exc,
            )
    return out
