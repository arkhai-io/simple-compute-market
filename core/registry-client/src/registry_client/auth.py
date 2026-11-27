"""Signing every registry request and verifying every registry answer.

Every request is signed under ``kit/identity``'s version 3 profile, naming the
registries the client would accept the answer from as its audience; its query is
built through the profile's one query encoding, so the client sends exactly the
query its signature covers. Every answer is verified against the request it
answers and the configured registry principals. The descriptor read is a public
operation, whose request carries only a request identity.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

import injected_time
from market_identity import (
    MarketRequest,
    RequestBinding,
    RequestRecord,
    Signer,
    TrustedIdentitySet,
    VerificationCode,
    encode_query,
    sign_market_request,
    verify_market_response,
)

#: How far a registry's signing time may be from the client's own instant.
RESPONSE_MAX_SKEW_SECONDS = 300

DESCRIPTOR_PATH = "/.well-known/arkhai/registry-descriptor.json"
DESCRIPTOR_OPERATION = "registry.descriptor.read"


def request_route(method: str, path: str) -> tuple[str, str | None]:
    """The operation a registry route binds, and the object it acts on, or
    ``None`` for an operation with no target: a publication, a collection read,
    validation, and the singleton reads."""

    parts = [part for part in path.split("/") if part]
    method = method.upper()
    if path == "/api/v1/system/health":
        return "health.read", None
    if path == "/api/v1/system/stats":
        return "system.stats.read", None
    if path == "/api/v1/listings/validate-publish":
        return "listing.validate", None
    if path == "/filter-spec":
        return "filter.get", None
    if parts[:1] == ["listings"]:
        if len(parts) == 1:
            return ("listing.publish" if method == "POST" else "listing.list"), None
        operation = {"GET": "listing.get", "PUT": "listing.update", "DELETE": "listing.delete"}[method]
        return operation, parts[1]
    if parts[:1] == ["publishers"]:
        if len(parts) == 1:
            return "publisher.list", None
        if len(parts) == 2:
            return "publisher.get", parts[1]
        if parts[2] == "identity-rotations":
            if len(parts) == 3:
                return "publisher.identity.rotate", parts[1]
            if len(parts) == 4:
                return "publisher.identity.rotation.read", f"{parts[1]}:{parts[3]}"
            if len(parts) == 5 and parts[4] == "retire":
                return "publisher.identity.retire", f"{parts[1]}:{parts[3]}"
    raise ValueError(f"unsupported registry route: {method} {path}")


@dataclass(frozen=True)
class SignedRegistryRequest:
    """A request ready to send: its target with the query it signed, its headers,
    the binding its answer is verified against, and its evidence record."""

    target: str
    headers: dict[str, str]
    binding: RequestBinding
    record: RequestRecord | None


def sign_registry_request(
    *,
    signer: Signer,
    role: str,
    method: str,
    path: str,
    body: bytes,
    audience: TrustedIdentitySet,
    query: Iterable[tuple[str, str]] = (),
    request_id: str | None = None,
    origin: int | None = None,
) -> SignedRegistryRequest:
    """Sign one registry request under the version 3 profile.

    An exact retry passes the ``request_id`` and ``origin`` of the request it
    repeats; a first attempt passes neither, and its origin is the signing
    instant.
    """

    operation, resource = request_route(method, path)
    now = injected_time.now()
    suffix = encode_query(query)
    request = MarketRequest(
        method=method,
        role=role,
        operation=operation,
        resource=resource,
        request_id=request_id or uuid.uuid4().hex,
        origin=now if origin is None else origin,
    )
    signed = sign_market_request(
        signer=signer, request=request, body=body, created=now, query=suffix, audience=audience
    )
    headers = dict(signed.headers)
    if body:
        headers["Content-Type"] = "application/json"
    return SignedRegistryRequest(target=path + suffix, headers=headers, binding=request.binding, record=signed.record)


def verify_registry_response(
    *,
    status: int,
    headers: Mapping[str, str],
    body: bytes,
    binding: RequestBinding,
    expected_registries: TrustedIdentitySet,
) -> None:
    """Verify a registry answer against the request it answers and the registry
    principals expected; raises :class:`ValueError` naming why it failed."""

    result = verify_market_response(
        status=status,
        headers=headers,
        body=body,
        request=binding,
        expected_principals=expected_registries,
        now=injected_time.now(),
        max_skew=RESPONSE_MAX_SKEW_SECONDS,
    )
    if result.code != VerificationCode.VERIFIED:
        raise ValueError(f"invalid registry response: {result.code.value}")


class RegistryClientError(Exception):
    """Raised when the Registry API returns a non-2xx status code."""

    def __init__(self, method: str, url: str, status_code: int, body: str) -> None:
        self.method = method
        self.url = url
        self.status_code = status_code
        self.body = body
        super().__init__(f"{method} {url} → HTTP {status_code}\n{body}")
