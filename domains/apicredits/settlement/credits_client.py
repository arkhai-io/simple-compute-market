"""Strict client contract for the credits authority's issuance surface."""

from __future__ import annotations

import hashlib
import logging
import re
import time
import uuid
from collections.abc import Mapping
from typing import Any, Literal, Self

import httpx
from market_identity import (
    EMPTY_BODY,
    RESPONSE_PROTOCOL,
    AuthenticatedResponse,
    Identity,
    RequestEnvelope,
    SignatureProof,
    canonical_body_hash,
    canonical_json,
    sign_request,
    verify_response,
)
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


SIGNATURE_VERSION_HEADER = "X-Market-Signature-Version"
IDENTITY_SCHEME_HEADER = "X-Market-Identity-Scheme"
IDENTITY_IDENTIFIER_HEADER = "X-Market-Identity-Identifier"
ROLE_HEADER = "X-Market-Role"
REQUEST_ID_HEADER = "X-Market-Request-ID"
TIMESTAMP_HEADER = "X-Market-Timestamp"
SIGNATURE_HEADER = "X-Market-Signature"


class CreditsServiceAuthenticationError(CreditsServiceError):
    """Something answered, but not verifiably the credits authority.

    A subclass of `CreditsServiceError` so existing callers that already
    handle a failed credits call keep working, and a distinct type so an
    operator can tell "the authority refused" from "the authority did not
    answer this" -- including on refusals, which are signed too.
    """


def _required_header(headers: Mapping[str, str], name: str) -> str:
    value = headers.get(name)
    if value is None:
        raise KeyError(name)
    return str(value)


def _signed_response_body(response: httpx.Response) -> Any:
    """The body as the signature covers it.

    A bodyless response hashes as `EMPTY_BODY`, matching how the service
    signs one. Non-JSON text is passed through so a malformed answer fails
    verification rather than raising while being parsed.
    """
    if not response.content:
        return EMPTY_BODY
    try:
        return response.json()
    except ValueError:
        return response.text


#: This client's operations as the credits service names them. Must agree
#: exactly with `CREDITS_ROUTE_CONTRACTS` in
#: `domains/apicredits/service/src/middleware/route_contracts.py`: the
#: service recomputes the operation and resource from the route it matched
#: and verifies the signature over its own values, so a mismatch here is a
#: signature that cannot verify rather than a cosmetic drift. Asserted by
#: `tests/unit/test_credits_route_parity.py`.
#:
#: `credits_issue` signs the `fulfillment_id` carried in the request body
#: (`body_resource`, optional): unlike the others the resource is not in the
#: path, and an issuance without one signs the empty resource.
ISSUE_OPERATION = "credits_issue"
ISSUANCE_GET_OPERATION = "credits_issuance_get"
KEY_GET_OPERATION = "credits_key_get"
KEY_REVOKE_OPERATION = "credits_key_revoke"
KEY_ADJUST_OPERATION = "credits_key_adjust"

#: The role the storefront presents: it issues grants against settled deals
#: and administers keys. Distinct from the gated application's `service`,
#: which may only spend and check.
STOREFRONT_ROLE = "seller"

#: The role the authority signs its responses with.
AUTHORITY_RESPONSE_ROLE = "service"


class CreditsServiceClient:
    """Configured typed client for one credits authority.

    ``signer`` and ``expected_authorities`` select signed authentication:
    each request carries a marketplace identity v2 envelope signed in the
    ``seller`` role, and every response -- refusals included -- is verified
    as coming from a trusted authority principal. Omitting them falls back
    to the legacy ``X-Admin-Key`` shared secret.

    Both are kept because the service accepts exactly one of them at a
    time, chosen by its own configuration, so the two sides are flipped
    together and a deployment mid-flip must still be describable.
    """

    def __init__(
        self,
        service_url: str,
        admin_key: str = "",
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        signer: Any | None = None,
        expected_authorities: Any | None = None,
        max_response_skew: int = 300,
    ) -> None:
        if (signer is None) != (expected_authorities is None):
            raise ValueError(
                "signer and expected_authorities must be supplied together: "
                "signing requests without verifying responses would accept "
                "an unauthenticated answer to an authenticated question"
            )
        self._service_url = service_url.rstrip("/")
        self._admin_key = admin_key
        self._transport = transport  # test seam (httpx.MockTransport)
        self._signer = signer
        self._expected_authorities = expected_authorities
        self._max_response_skew = max_response_skew

    @property
    def signing_enabled(self) -> bool:
        return self._signer is not None

    def _headers(self) -> dict[str, str]:
        return {"X-Admin-Key": self._admin_key} if self._admin_key else {}

    def _http(self, timeout: float) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=timeout, transport=self._transport)

    async def _call(
        self,
        method: str,
        path: str,
        *,
        operation: str,
        resource: str,
        body: Any | None = None,
        timeout: float,
    ) -> httpx.Response:
        """Issue one request, signed when this client is configured to.

        On the signed path the RFC 8785 canonical bytes that were hashed are
        the bytes sent, because the service recomputes the body hash from
        what it receives.
        """
        url = f"{self._service_url}{path}"
        if self._signer is None:
            async with self._http(timeout) as http:
                return await http.request(
                    method,
                    url,
                    json=body,
                    headers=self._headers(),
                )

        envelope_body = EMPTY_BODY if body is None else body
        request_id = uuid.uuid4().hex
        authenticated = sign_request(
            signer=self._signer,
            envelope=RequestEnvelope(
                role=STOREFRONT_ROLE,
                principal=self._signer.identity,
                method=method,
                operation=operation,
                resource=resource,
                request_id=request_id,
                timestamp=int(time.time()),
                body_hash=canonical_body_hash(envelope_body),
            ),
        )
        headers = {
            "Accept": "application/json",
            SIGNATURE_VERSION_HEADER: authenticated.protocol,
            IDENTITY_SCHEME_HEADER: authenticated.principal.scheme.value,
            IDENTITY_IDENTIFIER_HEADER: authenticated.principal.identifier,
            ROLE_HEADER: authenticated.role,
            REQUEST_ID_HEADER: authenticated.request_id,
            TIMESTAMP_HEADER: str(authenticated.timestamp),
            SIGNATURE_HEADER: authenticated.proof.value,
        }
        content = None if body is None else canonical_json(body)
        if content is not None:
            headers["Content-Type"] = "application/json"
        async with self._http(timeout) as http:
            response = await http.request(
                method, url, content=content, headers=headers,
            )
        self._verify_authority_response(
            response,
            method=method,
            operation=operation,
            resource=resource,
            request_id=request_id,
        )
        return response

    def _verify_authority_response(
        self,
        response: httpx.Response,
        *,
        method: str,
        operation: str,
        resource: str,
        request_id: str,
    ) -> None:
        """Establish that a trusted authority produced this response.

        Verified against the operation, resource and request id that were
        *signed*, not values recovered from the response, so a substituted
        answer cannot nominate the question it is answering.

        `expected_role` is `service`: the authority signs its responses in
        the service role even though this client signs its requests as
        `seller`. The kit's own `verify_authenticated_response` fixes that
        expectation to `seller` because it verifies storefronts, which is
        why it is not reused here.
        """
        body = _signed_response_body(response)
        try:
            scheme = _required_header(response.headers, IDENTITY_SCHEME_HEADER)
            protocol = _required_header(
                response.headers, SIGNATURE_VERSION_HEADER
            )
            if protocol != RESPONSE_PROTOCOL:
                raise CreditsServiceAuthenticationError(
                    "unsupported_response_signature_version",
                    protocol,
                    status_code=response.status_code,
                )
            principal = Identity(
                scheme=scheme,
                identifier=_required_header(
                    response.headers, IDENTITY_IDENTIFIER_HEADER
                ),
            )
            authenticated = AuthenticatedResponse(
                protocol=protocol,
                role=_required_header(response.headers, ROLE_HEADER),
                principal=principal,
                method=method,
                operation=operation,
                resource=resource,
                request_id=_required_header(
                    response.headers, REQUEST_ID_HEADER
                ),
                timestamp=int(
                    _required_header(response.headers, TIMESTAMP_HEADER)
                ),
                status=response.status_code,
                body_hash=canonical_body_hash(body),
                proof=SignatureProof(
                    scheme=scheme,
                    value=_required_header(response.headers, SIGNATURE_HEADER),
                ),
            )
        except CreditsServiceAuthenticationError:
            raise
        except (KeyError, TypeError, ValueError) as exc:
            raise CreditsServiceAuthenticationError(
                "missing_or_malformed_response_authentication",
                f"HTTP {response.status_code}",
                status_code=response.status_code,
            ) from exc

        result = verify_response(
            authenticated,
            body=body,
            now=int(time.time()),
            max_skew=self._max_response_skew,
            expected_role=AUTHORITY_RESPONSE_ROLE,
            expected_principals=self._expected_authorities,
            expected_method=method,
            expected_operation=operation,
            expected_resource=resource,
            expected_request_id=request_id,
        )
        if not result.verified:
            raise CreditsServiceAuthenticationError(
                "response_authentication_failed",
                result.code.value,
                status_code=response.status_code,
            )

    async def submit_credit_issuance(
        self,
        request: CreditIssuanceRequest,
        *,
        timeout: float = 30.0,
    ) -> CreditIssuanceResult:
        """Commit or retrieve exactly the immutable issuance request."""

        payload = request.model_dump(mode="json", exclude_none=True)
        response = await self._call(
            "POST",
            "/api/v1/issuance",
            operation=ISSUE_OPERATION,
            # `credits_issue` declares an optional `body_resource` of
            # `fulfillment_id`; the service signs the empty resource when the
            # body carries none, so this mirrors that exactly.
            resource=str(payload.get("fulfillment_id") or ""),
            body=payload,
            timeout=timeout,
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

        response = await self._call(
            "GET",
            f"/api/v1/issuance/{fulfillment_id}",
            operation=ISSUANCE_GET_OPERATION,
            resource=fulfillment_id,
            timeout=timeout,
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
        resp = await self._call(
            "GET",
            f"/api/v1/keys/{key_id}",
            operation=KEY_GET_OPERATION,
            resource=key_id,
            timeout=timeout,
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
        resp = await self._call(
            "POST",
            f"/api/v1/keys/{key_id}/revoke",
            operation=KEY_REVOKE_OPERATION,
            resource=key_id,
            timeout=timeout,
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
        resp = await self._call(
            "POST",
            f"/api/v1/keys/{key_id}/adjust",
            operation=KEY_ADJUST_OPERATION,
            resource=key_id,
            body={"delta": int(delta), "reason": reason},
            timeout=timeout,
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
