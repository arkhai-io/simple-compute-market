"""Request signing and response verification shared by both client variants.

Every request carries the caller's version 2 proof over its method, the route's
signed operation and resource, a request identity, a timestamp, and the digest
of its canonical body; every response must carry a valid proof from one of the
pinned authority principals acting as ``service`` before its body is trusted.
The variants differ only in how they send.
"""

from __future__ import annotations

import hashlib
import time
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from typing import Any

import httpx
from compute_provisioning_contracts import (
    IDENTITY_IDENTIFIER_HEADER,
    IDENTITY_SCHEME_HEADER,
    PROVISIONING_ROUTE_TABLE,
    REQUEST_ID_HEADER,
    ROLE_HEADER,
    SIGNATURE_HEADER,
    SIGNATURE_VERSION_HEADER,
    TIMESTAMP_HEADER,
    ProvisioningRouteContract,
    canonical_provisioning_request_body,
    route_contract_from_declaration,
)
from market_identity import (
    EMPTY_BODY,
    AuthenticatedResponse,
    Identity,
    RequestEnvelope,
    SignatureProof,
    Signer,
    TrustedIdentitySet,
    canonical_body_hash,
    sign_request,
    verify_response,
)

from .errors import ComputeProvisioningAuthenticationError, ComputeProvisioningError

CALLER_ROLES = frozenset({"seller", "admin"})


def _unix_time() -> int:
    return int(time.time())


def wire_query(query: Mapping[str, Any] | None) -> dict[str, str]:
    """A query as it travels and is signed: strings, with ``None`` omitted.

    The service reads query values as strings, so the client signs the same
    strings it sends; a boolean travels as ``true`` or ``false``.
    """

    return {
        key: str(value).lower() if isinstance(value, bool) else str(value)
        for key, value in (query or {}).items()
        if value is not None
    }


def multipart_descriptor(request: httpx.Request, content: bytes) -> dict[str, str]:
    """What a multipart request is signed over: its content type and digest."""

    content_type = request.headers["content-type"].split(";", 1)[0].lower()
    return {"content_type": content_type, "sha256": hashlib.sha256(content).hexdigest()}


@dataclass(frozen=True)
class Signed:
    """One request's signing context, kept to verify its response."""

    method: str
    path: str
    operation: str
    resource: str
    request_id: str
    headers: dict[str, str]


class SigningBase:
    def __init__(
        self,
        base_url: str,
        signer: Signer,
        caller_role: str,
        expected_authorities: TrustedIdentitySet,
        *,
        max_timestamp_skew: int,
    ) -> None:
        if not isinstance(signer, Signer):
            raise TypeError("signer must implement market_identity.Signer")
        if caller_role not in CALLER_ROLES:
            raise ValueError("caller_role must be 'seller' or 'admin'")
        if not isinstance(expected_authorities, TrustedIdentitySet):
            raise TypeError(
                "expected_authorities must be a market_identity.TrustedIdentitySet"
            )
        if max_timestamp_skew < 0:
            raise ValueError("max_timestamp_skew must not be negative")
        self._base_url = base_url.rstrip("/")
        self._signer = signer
        self._caller_role = caller_role
        self._expected_authorities = expected_authorities
        self._max_timestamp_skew = max_timestamp_skew
        self._request_contexts: dict[str, tuple[str, str, str, str]] = {}

    @staticmethod
    def payload(body: Any) -> Any:
        if hasattr(body, "model_dump"):
            return body.model_dump(mode="json", exclude_none=True)
        return body

    def sign(
        self,
        method: str,
        path: str,
        signed_body: Any,
        *,
        request_id: str,
        route: ProvisioningRouteContract | Mapping[str, Any] | None,
    ) -> Signed:
        """Resolve the route, check the caller may use it, and sign the request.

        ``route`` names another owner's declaration; without it the path
        resolves against the family's own routes.
        """

        if route is None:
            contract, resource = PROVISIONING_ROUTE_TABLE.resolve(method, path, signed_body)
        else:
            contract = route_contract_from_declaration(route)
            matched = contract.match(method, path, signed_body)
            if matched is None:
                raise ValueError(f"route {contract.operation!r} does not describe {method} {path}")
            resource = matched
        if self._caller_role not in contract.allowed_roles:
            raise ComputeProvisioningAuthenticationError(
                f"{method} {path} permits caller roles {contract.allowed_roles}"
            )
        digest = canonical_body_hash(signed_body)
        context = (method.upper(), contract.operation, resource, digest)
        existing = self._request_contexts.get(request_id)
        if existing is not None and existing != context:
            raise ValueError("request_id was reused with changed request content")
        authenticated = sign_request(
            signer=self._signer,
            envelope=RequestEnvelope(
                role=self._caller_role,
                principal=self._signer.identity,
                method=method,
                operation=contract.operation,
                resource=resource,
                request_id=request_id,
                timestamp=_unix_time(),
                body_hash=digest,
            ),
        )
        self._request_contexts[request_id] = context
        return Signed(
            method=method,
            path=path,
            operation=contract.operation,
            resource=resource,
            request_id=request_id,
            headers={
                SIGNATURE_VERSION_HEADER: authenticated.protocol,
                IDENTITY_SCHEME_HEADER: authenticated.principal.scheme.value,
                IDENTITY_IDENTIFIER_HEADER: authenticated.principal.identifier,
                ROLE_HEADER: authenticated.role,
                REQUEST_ID_HEADER: authenticated.request_id,
                TIMESTAMP_HEADER: str(authenticated.timestamp),
                SIGNATURE_HEADER: authenticated.proof.value,
            },
        )

    @staticmethod
    def canonical(method: str, path: str, payload: Any, query: Mapping[str, str]) -> Any:
        return canonical_provisioning_request_body(method, path, payload, query=query)

    def finish(
        self,
        response: httpx.Response,
        signed: Signed,
        *,
        accepted_statuses: Collection[int] = (),
    ) -> Any:
        """Verify a response's authority proof, then return its body or raise."""

        if response.content:
            try:
                body: Any = response.json()
            except ValueError:
                body = response.text
        else:
            body = EMPTY_BODY
        self._verify(response, signed, body)
        if not response.is_success and response.status_code not in accepted_statuses:
            detail = body.get("detail", response.text) if isinstance(body, dict) else body
            raise ComputeProvisioningError(str(detail), status_code=response.status_code)
        return body

    def _verify(self, response: httpx.Response, signed: Signed, body: Any) -> None:
        try:
            principal = Identity(
                scheme=response.headers[IDENTITY_SCHEME_HEADER],
                identifier=response.headers[IDENTITY_IDENTIFIER_HEADER],
            )
            authenticated = AuthenticatedResponse(
                protocol=response.headers[SIGNATURE_VERSION_HEADER],
                role=response.headers[ROLE_HEADER],
                principal=principal,
                method=signed.method,
                operation=signed.operation,
                resource=signed.resource,
                request_id=response.headers[REQUEST_ID_HEADER],
                timestamp=int(response.headers[TIMESTAMP_HEADER]),
                status=response.status_code,
                body_hash=canonical_body_hash(body),
                proof=SignatureProof(
                    scheme=principal.scheme, value=response.headers[SIGNATURE_HEADER]
                ),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ComputeProvisioningAuthenticationError(
                "missing or malformed provisioning response authentication",
                status_code=response.status_code,
            ) from exc
        result = verify_response(
            authenticated,
            body=body,
            now=_unix_time(),
            max_skew=self._max_timestamp_skew,
            expected_role="service",
            expected_principals=self._expected_authorities,
            expected_method=signed.method,
            expected_operation=signed.operation,
            expected_resource=signed.resource,
            expected_request_id=signed.request_id,
        )
        if not result.verified:
            raise ComputeProvisioningAuthenticationError(
                f"provisioning response authentication failed: {result.code.value}",
                status_code=response.status_code,
            )

    @staticmethod
    def unsigned_body(
        response: httpx.Response, *, accepted_statuses: Collection[int] = ()
    ) -> Any:
        if not response.is_success and response.status_code not in accepted_statuses:
            raise ComputeProvisioningError(response.text[:500], status_code=response.status_code)
        return response.json()


__all__ = ["CALLER_ROLES", "Signed", "SigningBase", "multipart_descriptor", "wire_query"]
