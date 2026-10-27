"""The authority's typed client, binding each request from its route declaration.

Every method looks its route up by operation name in ``arkhai_api_contracts``
and takes the method, the path, and the signed resource from that one
declaration, so the request this client signs is the request the authority's
authentication reads. With a signer and a trusted authority set, each request
carries a marketplace identity v2 envelope in the ``seller`` role and every
response, refusals included, is verified as the authority's; without them the
client presents the shared ``X-Admin-Key`` an authority with no identity
provisioned accepts. ``AuthorityClient`` runs over an async transport and
``SyncAuthorityClient`` over a sync one, with identical methods.
"""

from __future__ import annotations

import logging
import re
import time
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import httpx
from market_identity import (
    EMPTY_BODY,
    RESPONSE_PROTOCOL,
    AuthenticatedResponse,
    Identity,
    RequestEnvelope,
    SignatureProof,
    Signer,
    TrustedIdentitySet,
    canonical_body_hash,
    canonical_json,
    sign_request,
    verify_response,
)

from arkhai_api_contracts import operations
from arkhai_api_contracts.headers import (
    IDENTITY_IDENTIFIER_HEADER,
    IDENTITY_SCHEME_HEADER,
    REQUEST_ID_HEADER,
    ROLE_HEADER,
    SIGNATURE_HEADER,
    SIGNATURE_VERSION_HEADER,
    TIMESTAMP_HEADER,
)
from arkhai_api_contracts.models import (
    IssuanceLabel,
    IssuanceRequest,
    IssuanceResult,
    issuance_request_model,
    issuance_result_model,
)
from arkhai_api_contracts.routes import SELLER_ROLE, SERVICE_ROLE, route

logger = logging.getLogger(__name__)

ADMIN_KEY_HEADER = "X-Admin-Key"
_PATH_PARAMETER = re.compile(r"\(\?P<(\w+)>[^)]*\)")


class AuthorityError(RuntimeError):
    """The authority refused a call; ``reason`` is its error vocabulary.

    Transport failures raise the underlying httpx error instead.
    """

    def __init__(self, reason: str, detail: str = "", *, status_code: int = 0) -> None:
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason
        self.detail = detail
        self.status_code = status_code


class AuthorityAuthenticationError(AuthorityError):
    """Something answered, but not verifiably the authority."""


@dataclass(frozen=True)
class _Call:
    method: str
    path: str
    operation: str
    resource: str
    body: Any | None
    params: Mapping[str, Any] | None
    timeout: float


def _call(
    operation: str,
    *,
    timeout: float,
    body: Any | None = None,
    params: Mapping[str, Any] | None = None,
    **path_params: str,
) -> _Call:
    """One request bound from its declaration: method, path, and signed resource."""

    declaration = route(operation)
    path = _PATH_PARAMETER.sub(lambda match: str(path_params[match.group(1)]), declaration["path"])
    if re.fullmatch(declaration["path"], path) is None:
        raise ValueError(f"{operation}: path parameters do not bind {declaration['path']!r}")
    resource = ""
    if (name := declaration.get("path_resource")) is not None:
        resource = str(path_params[name])
    elif (name := declaration.get("body_resource")) is not None:
        value = (body or {}).get(name)
        if value is None and not declaration.get("optional_body_resource", False):
            raise ValueError(f"{operation}: the request body names no {name}")
        resource = str(value or "")
    return _Call(declaration["method"], path, operation, resource, body, params, timeout)


@dataclass(frozen=True)
class _Prepared:
    url: str
    headers: dict[str, str]
    content: bytes | None
    json: Any | None
    request_id: str | None


def _prepare(call: _Call, *, service_url: str, admin_key: str, signer: Signer | None) -> _Prepared:
    """The request as sent: signed from the declaration, or under the shared secret.

    On the signed path the canonical bytes hashed into the envelope are the
    bytes sent, because the authority recomputes the body hash from what it
    receives. Query parameters are outside the envelope: the authority matches
    the route, and so the operation and resource it verifies, on the path alone.
    """

    url = f"{service_url}{call.path}"
    if signer is None:
        headers = {ADMIN_KEY_HEADER: admin_key} if admin_key else {}
        return _Prepared(url, headers, None, call.body, None)
    request_id = uuid.uuid4().hex
    authenticated = sign_request(
        signer=signer,
        envelope=RequestEnvelope(
            role=SELLER_ROLE,
            principal=signer.identity,
            method=call.method,
            operation=call.operation,
            resource=call.resource,
            request_id=request_id,
            timestamp=int(time.time()),
            body_hash=canonical_body_hash(EMPTY_BODY if call.body is None else call.body),
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
    content = None if call.body is None else canonical_json(call.body)
    if content is not None:
        headers["Content-Type"] = "application/json"
    return _Prepared(url, headers, content, None, request_id)


def _required_header(headers: Mapping[str, str], name: str) -> str:
    value = headers.get(name)
    if value is None:
        raise KeyError(name)
    return str(value)


def _signed_body(response: httpx.Response) -> Any:
    # A bodyless response hashes as EMPTY_BODY, as the authority signs one; non-JSON
    # text passes through so a malformed answer fails verification, not parsing.
    if not response.content:
        return EMPTY_BODY
    try:
        return response.json()
    except ValueError:
        return response.text


def _verify(
    response: httpx.Response,
    call: _Call,
    *,
    request_id: str,
    expected_authorities: TrustedIdentitySet,
    max_skew: int,
) -> None:
    """Establish that a trusted authority answered the request that was signed.

    Verified against the operation, resource, and request id that were sent,
    never values recovered from the response, so a substituted answer cannot
    nominate the question it is answering. The authority signs in the
    ``service`` role although this client signs as ``seller``.
    """

    body = _signed_body(response)
    try:
        protocol = _required_header(response.headers, SIGNATURE_VERSION_HEADER)
        if protocol != RESPONSE_PROTOCOL:
            raise AuthorityAuthenticationError(
                "unsupported_response_signature_version", protocol, status_code=response.status_code
            )
        scheme = _required_header(response.headers, IDENTITY_SCHEME_HEADER)
        authenticated = AuthenticatedResponse(
            protocol=protocol,
            role=_required_header(response.headers, ROLE_HEADER),
            principal=Identity(
                scheme=scheme,
                identifier=_required_header(response.headers, IDENTITY_IDENTIFIER_HEADER),
            ),
            method=call.method,
            operation=call.operation,
            resource=call.resource,
            request_id=_required_header(response.headers, REQUEST_ID_HEADER),
            timestamp=int(_required_header(response.headers, TIMESTAMP_HEADER)),
            status=response.status_code,
            body_hash=canonical_body_hash(body),
            proof=SignatureProof(
                scheme=scheme, value=_required_header(response.headers, SIGNATURE_HEADER)
            ),
        )
    except AuthorityAuthenticationError:
        raise
    except (KeyError, TypeError, ValueError) as exc:
        raise AuthorityAuthenticationError(
            "missing_or_malformed_response_authentication",
            f"HTTP {response.status_code}",
            status_code=response.status_code,
        ) from exc
    result = verify_response(
        authenticated,
        body=body,
        now=int(time.time()),
        max_skew=max_skew,
        expected_role=SERVICE_ROLE,
        expected_principals=expected_authorities,
        expected_method=call.method,
        expected_operation=call.operation,
        expected_resource=call.resource,
        expected_request_id=request_id,
    )
    if not result.verified:
        raise AuthorityAuthenticationError(
            "response_authentication_failed", result.code.value, status_code=response.status_code
        )


def _service_error(response: httpx.Response) -> AuthorityError:
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    return AuthorityError(
        str(payload.get("error") or f"http_{response.status_code}"),
        str(payload.get("detail") or response.text[:200]),
        status_code=response.status_code,
    )


def _require_both(signer: Signer | None, expected_authorities: TrustedIdentitySet | None) -> None:
    if (signer is None) != (expected_authorities is None):
        raise ValueError(
            "signer and expected_authorities must be supplied together: "
            "signing requests without verifying responses would accept "
            "an unauthenticated answer to an authenticated question"
        )


def _issue(request: IssuanceRequest, timeout: float) -> _Call:
    payload = request.model_dump(mode="json", exclude_none=True)
    return _call(operations.ISSUE, body=payload, timeout=timeout)


def _issuance_get(fulfillment_id: str, timeout: float) -> _Call:
    return _call(operations.ISSUANCE_GET, fulfillment_id=fulfillment_id, timeout=timeout)


def _key_get(key_id: str, timeout: float) -> _Call:
    return _call(operations.KEY_GET, key_id=key_id, timeout=timeout)


def _keys_list(status: str | None, owner_id: str | None, timeout: float) -> _Call:
    params = {k: v for k, v in (("status", status), ("owner_id", owner_id)) if v is not None}
    return _call(operations.KEYS_LIST, params=params or None, timeout=timeout)


def _key_grants_list(key_id: str, timeout: float) -> _Call:
    return _call(operations.KEY_GRANTS_LIST, key_id=key_id, timeout=timeout)


def _key_usage_list(key_id: str, after_id: int, limit: int, timeout: float) -> _Call:
    return _call(
        operations.KEY_USAGE_LIST,
        key_id=key_id,
        params={"after_id": int(after_id), "limit": int(limit)},
        timeout=timeout,
    )


def _key_revoke(key_id: str, timeout: float) -> _Call:
    return _call(operations.KEY_REVOKE, key_id=key_id, timeout=timeout)


def _key_adjust(key_id: str, delta: int, reason: str, timeout: float) -> _Call:
    return _call(
        operations.KEY_ADJUST,
        key_id=key_id,
        body={"delta": int(delta), "reason": reason},
        timeout=timeout,
    )


def _issued(model: type[IssuanceResult], response: httpx.Response) -> IssuanceResult:
    if response.status_code == 200:
        return model.model_validate(response.json())
    raise _service_error(response)


def _found_issuance(model: type[IssuanceResult], response: httpx.Response) -> IssuanceResult | None:
    if response.status_code == 404:
        return None
    return _issued(model, response)


def _found(response: httpx.Response) -> dict[str, Any] | None:
    if response.status_code == 404:
        return None
    return _json(response)


def _json(response: httpx.Response) -> dict[str, Any]:
    response.raise_for_status()
    return response.json()


def _rollback_target(issuance: Mapping[str, Any]) -> tuple[str, int, dict[str, Any]]:
    key_id = str(issuance.get("key_id") or "")
    quantity = int(issuance.get("quantity") or 0)
    outcome: dict[str, Any] = {"key_id": key_id, "rolled_back": False}
    if not key_id or quantity <= 0:
        outcome["reason"] = "nothing_to_roll_back"
    return key_id, quantity, outcome


def _rollback_failed(outcome: dict[str, Any], step: str, key_id: str, settlement_ref: str, exc: Exception) -> None:
    if step == "adjust":
        outcome["reason"] = f"adjust_failed: {exc}"
    else:
        outcome["revoked"] = False
    logger.warning(
        "[ISSUANCE] rollback %s failed for %s (settlement %s): %s", step, key_id, settlement_ref, exc
    )


class AuthorityClient:
    """The authority's typed client over an async transport.

    ``signer`` and ``expected_authorities`` are kept together because the
    authority accepts exactly one of signed and shared-secret authentication at
    a time, chosen by its own configuration, so the two sides flip together.
    """

    def __init__(
        self,
        service_url: str,
        admin_key: str = "",
        *,
        label: IssuanceLabel,
        transport: httpx.AsyncBaseTransport | None = None,
        signer: Signer | None = None,
        expected_authorities: TrustedIdentitySet | None = None,
        max_response_skew: int = 300,
    ) -> None:
        _require_both(signer, expected_authorities)
        self._service_url = service_url.rstrip("/")
        self._admin_key = admin_key
        self._transport = transport
        self._signer = signer
        self._expected_authorities = expected_authorities
        self._max_response_skew = max_response_skew
        self._request_model = issuance_request_model(label)
        self._result = issuance_result_model(label)
        self._http: httpx.AsyncClient | None = None

    @property
    def signing_enabled(self) -> bool:
        return self._signer is not None

    async def close(self) -> None:
        """Close the HTTP client and the transport it was given."""
        if self._http is not None:
            await self._http.aclose()
            self._http = None

    async def _request(self, call: _Call) -> httpx.Response:
        prepared = _prepare(
            call, service_url=self._service_url, admin_key=self._admin_key, signer=self._signer
        )
        # One HTTP client for this client's lifetime: closing one per call would
        # close the transport the caller supplied with it.
        if self._http is None:
            self._http = httpx.AsyncClient(transport=self._transport)
        response = await self._http.request(
            call.method,
            prepared.url,
            json=prepared.json,
            content=prepared.content,
            headers=prepared.headers,
            params=call.params,
            timeout=call.timeout,
        )
        if prepared.request_id is not None:
            assert self._expected_authorities is not None
            _verify(
                response,
                call,
                request_id=prepared.request_id,
                expected_authorities=self._expected_authorities,
                max_skew=self._max_response_skew,
            )
        return response

    async def submit_issuance(self, request: IssuanceRequest, *, timeout: float = 30.0) -> IssuanceResult:
        """Commit, or retrieve on an exact retry, the immutable issuance request.

        The request is bound to this client's label before anything is sent, so
        another label's command never reaches the authority.
        """
        bound = self._request_model.model_validate(request.model_dump(mode="json"))
        return _issued(self._result, await self._request(_issue(bound, timeout)))

    async def get_issuance(self, fulfillment_id: str, *, timeout: float = 10.0) -> IssuanceResult | None:
        """One committed grant, without its secret, or None when unknown."""
        return _found_issuance(self._result, await self._request(_issuance_get(fulfillment_id, timeout)))

    async def get_key(self, key_id: str, *, timeout: float = 10.0) -> dict[str, Any] | None:
        """The key's ownership claim and status, or None when unknown."""
        return _found(await self._request(_key_get(key_id, timeout)))

    async def list_keys(
        self, *, status: str | None = None, owner_id: str | None = None, timeout: float = 10.0
    ) -> dict[str, Any]:
        return _json(await self._request(_keys_list(status, owner_id, timeout)))

    async def list_key_grants(self, key_id: str, *, timeout: float = 10.0) -> dict[str, Any]:
        return _json(await self._request(_key_grants_list(key_id, timeout)))

    async def list_key_usage(
        self, key_id: str, *, after_id: int = 0, limit: int = 500, timeout: float = 10.0
    ) -> dict[str, Any]:
        return _json(await self._request(_key_usage_list(key_id, after_id, limit, timeout)))

    async def revoke_key(self, key_id: str, *, timeout: float = 10.0) -> dict[str, Any]:
        return _json(await self._request(_key_revoke(key_id, timeout)))

    async def adjust_key_balance(
        self, key_id: str, *, delta: int, reason: str, timeout: float = 10.0
    ) -> dict[str, Any]:
        return _json(await self._request(_key_adjust(key_id, delta, reason, timeout)))

    async def rollback_issuance(
        self, *, settlement_ref: str, issuance: Mapping[str, Any], key_mode: str
    ) -> dict[str, Any]:
        """Undo an issuance whose deal failed after the grant landed.

        Claws the granted quantity back and revokes a key this deal created. A
        refused adjustment is reported, not hidden: the operator decides.
        """
        key_id, quantity, outcome = _rollback_target(issuance)
        if "reason" in outcome:
            return outcome
        try:
            await self.adjust_key_balance(key_id, delta=-quantity, reason=f"rollback:{settlement_ref}")
            outcome["rolled_back"] = True
        except Exception as exc:
            _rollback_failed(outcome, "adjust", key_id, settlement_ref, exc)
        if key_mode == "new":
            try:
                await self.revoke_key(key_id)
                outcome["revoked"] = True
            except Exception as exc:
                _rollback_failed(outcome, "revoke", key_id, settlement_ref, exc)
        return outcome


class SyncAuthorityClient:
    """The authority's typed client over a sync transport; see ``AuthorityClient``."""

    def __init__(
        self,
        service_url: str,
        admin_key: str = "",
        *,
        label: IssuanceLabel,
        transport: httpx.BaseTransport | None = None,
        signer: Signer | None = None,
        expected_authorities: TrustedIdentitySet | None = None,
        max_response_skew: int = 300,
    ) -> None:
        _require_both(signer, expected_authorities)
        self._service_url = service_url.rstrip("/")
        self._admin_key = admin_key
        self._transport = transport
        self._signer = signer
        self._expected_authorities = expected_authorities
        self._max_response_skew = max_response_skew
        self._request_model = issuance_request_model(label)
        self._result = issuance_result_model(label)
        self._http: httpx.Client | None = None

    @property
    def signing_enabled(self) -> bool:
        return self._signer is not None

    def close(self) -> None:
        """Close the HTTP client and the transport it was given."""
        if self._http is not None:
            self._http.close()
            self._http = None

    def _request(self, call: _Call) -> httpx.Response:
        prepared = _prepare(
            call, service_url=self._service_url, admin_key=self._admin_key, signer=self._signer
        )
        if self._http is None:
            self._http = httpx.Client(transport=self._transport)
        response = self._http.request(
            call.method,
            prepared.url,
            json=prepared.json,
            content=prepared.content,
            headers=prepared.headers,
            params=call.params,
            timeout=call.timeout,
        )
        if prepared.request_id is not None:
            assert self._expected_authorities is not None
            _verify(
                response,
                call,
                request_id=prepared.request_id,
                expected_authorities=self._expected_authorities,
                max_skew=self._max_response_skew,
            )
        return response

    def submit_issuance(self, request: IssuanceRequest, *, timeout: float = 30.0) -> IssuanceResult:
        """Commit, or retrieve on an exact retry, the immutable issuance request; see ``AuthorityClient``."""
        bound = self._request_model.model_validate(request.model_dump(mode="json"))
        return _issued(self._result, self._request(_issue(bound, timeout)))

    def get_issuance(self, fulfillment_id: str, *, timeout: float = 10.0) -> IssuanceResult | None:
        """One committed grant, without its secret, or None when unknown."""
        return _found_issuance(self._result, self._request(_issuance_get(fulfillment_id, timeout)))

    def get_key(self, key_id: str, *, timeout: float = 10.0) -> dict[str, Any] | None:
        """The key's ownership claim and status, or None when unknown."""
        return _found(self._request(_key_get(key_id, timeout)))

    def list_keys(
        self, *, status: str | None = None, owner_id: str | None = None, timeout: float = 10.0
    ) -> dict[str, Any]:
        return _json(self._request(_keys_list(status, owner_id, timeout)))

    def list_key_grants(self, key_id: str, *, timeout: float = 10.0) -> dict[str, Any]:
        return _json(self._request(_key_grants_list(key_id, timeout)))

    def list_key_usage(
        self, key_id: str, *, after_id: int = 0, limit: int = 500, timeout: float = 10.0
    ) -> dict[str, Any]:
        return _json(self._request(_key_usage_list(key_id, after_id, limit, timeout)))

    def revoke_key(self, key_id: str, *, timeout: float = 10.0) -> dict[str, Any]:
        return _json(self._request(_key_revoke(key_id, timeout)))

    def adjust_key_balance(
        self, key_id: str, *, delta: int, reason: str, timeout: float = 10.0
    ) -> dict[str, Any]:
        return _json(self._request(_key_adjust(key_id, delta, reason, timeout)))

    def rollback_issuance(
        self, *, settlement_ref: str, issuance: Mapping[str, Any], key_mode: str
    ) -> dict[str, Any]:
        """Undo an issuance whose deal failed after the grant landed; see ``AuthorityClient``."""
        key_id, quantity, outcome = _rollback_target(issuance)
        if "reason" in outcome:
            return outcome
        try:
            self.adjust_key_balance(key_id, delta=-quantity, reason=f"rollback:{settlement_ref}")
            outcome["rolled_back"] = True
        except Exception as exc:
            _rollback_failed(outcome, "adjust", key_id, settlement_ref, exc)
        if key_mode == "new":
            try:
                self.revoke_key(key_id)
                outcome["revoked"] = True
            except Exception as exc:
                _rollback_failed(outcome, "revoke", key_id, settlement_ref, exc)
        return outcome
