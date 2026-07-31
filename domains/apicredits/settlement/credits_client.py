"""Typed client for the credits service's admin-gated issuance surface.

Centralizes what ``issuance.py``'s free functions used to each do
independently: a fresh ``httpx.AsyncClient`` per call, hand-built
``X-Admin-Key`` headers, and ad hoc error translation. One
``CreditsServiceClient`` instance now owns all five operations
(``submit_credit_issuance``, ``get_key``, ``revoke_key``,
``adjust_key_balance``, ``rollback_issuance``); ``issuance.py``'s
existing free functions are kept as thin wrappers over a
per-call-constructed client so every current caller's signature stays
exactly as it was — this is an internal centralization, not a wire or
call-site contract change.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class CreditsServiceError(RuntimeError):
    """A credits-service call failed with a market-meaningful reason.

    ``reason`` carries the service's error vocabulary (``key_not_found``
    / ``key_not_owned`` / ``key_revoked`` / ``quota_exhausted``);
    transport-level failures raise the underlying httpx error instead.
    """

    def __init__(self, reason: str, detail: str = "", *, status_code: int = 0) -> None:
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason
        self.detail = detail
        self.status_code = status_code


class CreditsServiceClient:
    """One configured client for a single credits-service instance.

    Construction takes ``service_url``/``admin_key`` once; every
    operation reuses that configuration instead of threading the same
    two strings through every call. ``timeout`` defaults match what each
    free function in ``issuance.py`` used individually before this
    centralization (30s for issuance, 10s for everything else).
    """

    def __init__(
        self,
        service_url: str,
        admin_key: str = "",
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._service_url = service_url.rstrip("/")
        self._admin_key = admin_key
        self._transport = transport  # test seam (httpx.MockTransport)

    def _headers(self) -> dict[str, str]:
        return {"X-Admin-Key": self._admin_key} if self._admin_key else {}

    def _http(self, timeout: float) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=timeout, transport=self._transport)

    async def submit_credit_issuance(
        self,
        *,
        escrow_uid: str,
        quantity: int,
        key_mode: str = "new",
        key_id: str | None = None,
        buyer_wallet: str | None = None,
        capacity_reservation_id: str | None = None,
        resource_id: str | None = None,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        """Issue ``quantity`` credits for a settled escrow.

        Returns the issuance dict ``{key_id, secret?, quantity, balance,
        capacity_reservation_id, already_issued}``. ``secret`` is present
        only for a newly created (or rotated-on-retry) key — delivered
        once, to the buyer, through the settle-status channel.

        Raises :class:`CreditsServiceError` on a market-state refusal and
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
        if capacity_reservation_id:
            body["capacity_reservation_id"] = capacity_reservation_id
        if resource_id:
            body["resource_id"] = resource_id

        async with self._http(timeout) as http:
            resp = await http.post(
                f"{self._service_url}/api/v1/issuance",
                json=body,
                headers=self._headers(),
            )
        if resp.status_code == 200:
            return resp.json()
        try:
            payload = resp.json()
        except ValueError:
            payload = {}
        raise CreditsServiceError(
            str(payload.get("error") or f"http_{resp.status_code}"),
            str(payload.get("detail") or resp.text[:200]),
            status_code=resp.status_code,
        )

    async def get_key(
        self, key_id: str, *, timeout: float = 10.0,
    ) -> dict[str, Any] | None:
        """The key's ownership claim + status, or None when unknown."""
        async with self._http(timeout) as http:
            resp = await http.get(
                f"{self._service_url}/api/v1/keys/{key_id}",
                headers=self._headers(),
            )
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json()

    async def revoke_key(
        self, key_id: str, *, timeout: float = 10.0,
    ) -> dict[str, Any]:
        async with self._http(timeout) as http:
            resp = await http.post(
                f"{self._service_url}/api/v1/keys/{key_id}/revoke",
                headers=self._headers(),
            )
        resp.raise_for_status()
        return resp.json()

    async def adjust_key_balance(
        self, key_id: str, *, delta: int, reason: str, timeout: float = 10.0,
    ) -> dict[str, Any]:
        async with self._http(timeout) as http:
            resp = await http.post(
                f"{self._service_url}/api/v1/keys/{key_id}/adjust",
                json={"delta": int(delta), "reason": reason},
                headers=self._headers(),
            )
        resp.raise_for_status()
        return resp.json()

    async def rollback_issuance(
        self, *, escrow_uid: str, issuance: dict[str, Any], key_mode: str,
    ) -> dict[str, Any]:
        """Undo an issuance whose deal failed after the grant landed.

        Claws the granted quantity back off the balance; a key this deal
        created is also revoked (nothing else funds it). The adjust may
        refuse when the buyer already consumed below the clawback — that
        is surfaced, not hidden: the operator decides, the action result
        says what happened.
        """
        key_id = str(issuance.get("key_id") or "")
        quantity = int(issuance.get("quantity") or 0)
        out: dict[str, Any] = {"key_id": key_id, "rolled_back": False}
        if not key_id or quantity <= 0:
            out["reason"] = "nothing_to_roll_back"
            return out
        try:
            await self.adjust_key_balance(
                key_id, delta=-quantity, reason=f"rollback:{escrow_uid}",
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
                await self.revoke_key(key_id)
                out["revoked"] = True
            except Exception as exc:
                out["revoked"] = False
                logger.warning(
                    "[ISSUANCE] rollback revoke failed for %s (escrow %s): %s",
                    key_id, escrow_uid, exc,
                )
        return out
