"""Strict client contract for the credits authority's issuance surface."""

from __future__ import annotations

import hashlib
import logging
import re
from typing import Any, Literal, Self

import httpx
from market_identity import Identity, canonical_json
from pydantic import BaseModel, ConfigDict, Field, model_validator

logger = logging.getLogger(__name__)

ISSUANCE_REQUEST_SCHEMA = "arkhai.api-credits.issuance-request.v1"
ISSUANCE_RESULT_SCHEMA = "arkhai.api-credits.issuance-result.v1"
_SAFE_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,254}$")


class _CreditsContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class CreditKeyTarget(_CreditsContract):
    """Immutable public key target for one issuance."""

    mode: Literal["new", "existing"]
    key_id: str | None = Field(default=None, min_length=1, max_length=255)

    @model_validator(mode="after")
    def validate_target(self) -> Self:
        if self.mode == "new" and self.key_id is not None:
            raise ValueError("new key target must not provide key_id")
        if self.mode == "existing" and self.key_id is None:
            raise ValueError("existing key target requires key_id")
        return self


def derive_credit_fulfillment_id(obligation_ref: str) -> str:
    """Derive the mechanism-neutral grant key for one accepted obligation."""

    if not isinstance(obligation_ref, str) or not _SAFE_REF.fullmatch(obligation_ref):
        raise ValueError("obligation_ref must be a safe opaque reference")
    digest = hashlib.sha256(
        canonical_json(
            {
                "domain": "api-credits",
                "obligation_ref": obligation_ref,
                "version": 1,
            }
        )
    ).hexdigest()
    return f"api-credit-fulfillment.v1:{digest}"


def credit_issuance_request_digest(
    *,
    fulfillment_id: str,
    obligation_ref: str,
    mechanism: str,
    owner: Identity,
    service: str,
    resource_id: str,
    quantity: int,
    key: CreditKeyTarget,
) -> str:
    """Digest every authority-owned mutation input, excluding transient quota hints."""

    payload = {
        "fulfillment_id": fulfillment_id,
        "key": key.model_dump(mode="json"),
        "mechanism": mechanism,
        "obligation_ref": obligation_ref,
        "owner": owner.model_dump(mode="json"),
        "quantity": quantity,
        "resource_id": resource_id,
        "schema": ISSUANCE_REQUEST_SCHEMA,
        "service": service,
    }
    return "sha256:" + hashlib.sha256(canonical_json(payload)).hexdigest()


class CreditIssuanceRequest(_CreditsContract):
    """Complete immutable command accepted by the credits authority."""

    schema: Literal["arkhai.api-credits.issuance-request.v1"] = ISSUANCE_REQUEST_SCHEMA
    fulfillment_id: str = Field(min_length=1, max_length=320)
    obligation_ref: str = Field(min_length=1, max_length=255)
    mechanism: Literal["alkahest.v1", "fiat.stripe.v1"]
    owner: Identity
    service: str = Field(min_length=1, max_length=255)
    resource_id: str = Field(min_length=1, max_length=255)
    quantity: int = Field(ge=1)
    key: CreditKeyTarget
    request_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    capacity_reservation_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=255,
    )

    @classmethod
    def create(
        cls,
        *,
        obligation_ref: str,
        mechanism: Literal["alkahest.v1", "fiat.stripe.v1"],
        owner: Identity,
        service: str,
        resource_id: str,
        quantity: int,
        key: CreditKeyTarget,
        capacity_reservation_id: str | None = None,
        fulfillment_id: str | None = None,
    ) -> Self:
        resolved_fulfillment_id = fulfillment_id or derive_credit_fulfillment_id(
            obligation_ref
        )
        digest = credit_issuance_request_digest(
            fulfillment_id=resolved_fulfillment_id,
            obligation_ref=obligation_ref,
            mechanism=mechanism,
            owner=owner,
            service=service,
            resource_id=resource_id,
            quantity=quantity,
            key=key,
        )
        return cls(
            fulfillment_id=resolved_fulfillment_id,
            obligation_ref=obligation_ref,
            mechanism=mechanism,
            owner=owner,
            service=service,
            resource_id=resource_id,
            quantity=quantity,
            key=key,
            request_digest=digest,
            capacity_reservation_id=capacity_reservation_id,
        )

    @model_validator(mode="after")
    def validate_identity_and_digest(self) -> Self:
        if not _SAFE_REF.fullmatch(self.obligation_ref):
            raise ValueError("obligation_ref must be a safe opaque reference")
        if self.fulfillment_id != derive_credit_fulfillment_id(self.obligation_ref):
            raise ValueError("fulfillment_id does not match obligation_ref")
        expected = credit_issuance_request_digest(
            fulfillment_id=self.fulfillment_id,
            obligation_ref=self.obligation_ref,
            mechanism=self.mechanism,
            owner=self.owner,
            service=self.service,
            resource_id=self.resource_id,
            quantity=self.quantity,
            key=self.key,
        )
        if self.request_digest != expected:
            raise ValueError("request_digest does not match issuance request")
        return self


class CreditIssuanceResult(_CreditsContract):
    """Committed grant projection; bearer material is excluded from serialization."""

    schema: Literal["arkhai.api-credits.issuance-result.v1"] = ISSUANCE_RESULT_SCHEMA
    fulfillment_id: str = Field(min_length=1, max_length=320)
    grant_id: str = Field(min_length=1, max_length=320)
    obligation_ref: str = Field(min_length=1, max_length=255)
    mechanism: Literal["alkahest.v1", "fiat.stripe.v1"]
    owner: Identity | None
    service: str = Field(min_length=1, max_length=255)
    resource_id: str = Field(min_length=1, max_length=255)
    quantity: int = Field(ge=1)
    key_mode: Literal["new", "existing"]
    key_id: str = Field(min_length=1, max_length=255)
    balance: int = Field(ge=0)
    request_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    committed_at_unix: int = Field(ge=0)
    capacity_reservation_id: str | None = Field(default=None, max_length=255)
    already_issued: bool = False
    secret: str | None = Field(
        default=None,
        min_length=1,
        max_length=512,
        exclude=True,
        repr=False,
    )

    @model_validator(mode="after")
    def validate_result(self) -> Self:
        if self.grant_id != self.fulfillment_id:
            raise ValueError("grant_id must equal fulfillment_id")
        if self.mechanism == "fiat.stripe.v1" and self.owner is None:
            raise ValueError("hosted issuance result requires a canonical owner")
        if self.key_mode == "existing" and self.secret is not None:
            raise ValueError("existing-key top-up must not return a secret")
        if self.secret is not None and not self.secret.startswith(f"{self.key_id}."):
            raise ValueError("issued credential does not match key_id")
        return self


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


def _service_error(response: httpx.Response) -> CreditsServiceError:
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    return CreditsServiceError(
        str(payload.get("error") or f"http_{response.status_code}"),
        str(payload.get("detail") or response.text[:200]),
        status_code=response.status_code,
    )


class CreditsServiceClient:
    """Configured typed client for one credits authority."""

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
        request: CreditIssuanceRequest,
        *,
        timeout: float = 30.0,
    ) -> CreditIssuanceResult:
        """Commit or retrieve exactly the immutable issuance request."""

        async with self._http(timeout) as http:
            response = await http.post(
                f"{self._service_url}/api/v1/issuance",
                json=request.model_dump(mode="json", exclude_none=True),
                headers=self._headers(),
            )
        if response.status_code == 200:
            return CreditIssuanceResult.model_validate(response.json())
        raise _service_error(response)

    async def get_credit_issuance(
        self,
        fulfillment_id: str,
        *,
        timeout: float = 10.0,
    ) -> CreditIssuanceResult | None:
        """Resolve one committed grant without rotating or returning its secret."""

        async with self._http(timeout) as http:
            response = await http.get(
                f"{self._service_url}/api/v1/issuance/{fulfillment_id}",
                headers=self._headers(),
            )
        if response.status_code == 404:
            return None
        if response.status_code == 200:
            return CreditIssuanceResult.model_validate(response.json())
        raise _service_error(response)

    async def get_key(
        self,
        key_id: str,
        *,
        timeout: float = 10.0,
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
        self,
        key_id: str,
        *,
        timeout: float = 10.0,
    ) -> dict[str, Any]:
        async with self._http(timeout) as http:
            resp = await http.post(
                f"{self._service_url}/api/v1/keys/{key_id}/revoke",
                headers=self._headers(),
            )
        resp.raise_for_status()
        return resp.json()

    async def adjust_key_balance(
        self,
        key_id: str,
        *,
        delta: int,
        reason: str,
        timeout: float = 10.0,
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
        self,
        *,
        escrow_uid: str,
        issuance: dict[str, Any],
        key_mode: str,
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
                key_id,
                delta=-quantity,
                reason=f"rollback:{escrow_uid}",
            )
            out["rolled_back"] = True
        except Exception as exc:
            out["reason"] = f"adjust_failed: {exc}"
            logger.warning(
                "[ISSUANCE] rollback adjust failed for %s (escrow %s): %s",
                key_id,
                escrow_uid,
                exc,
            )
        if key_mode == "new":
            try:
                await self.revoke_key(key_id)
                out["revoked"] = True
            except Exception as exc:
                out["revoked"] = False
                logger.warning(
                    "[ISSUANCE] rollback revoke failed for %s (escrow %s): %s",
                    key_id,
                    escrow_uid,
                    exc,
                )
        return out
