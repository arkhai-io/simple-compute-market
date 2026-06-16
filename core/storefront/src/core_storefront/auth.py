"""Framework-free signed request verification for storefront APIs."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Mapping

from market_identity import Identity, get_identity_verifier

DEFAULT_IDENTITY_SCHEME = "eip191"
DEFAULT_MAX_TIMESTAMP_SKEW = 300


@dataclass
class AuthError(ValueError):
    """Authentication failure with an HTTP-friendly status code."""

    detail: str
    status_code: int = 403

    def __str__(self) -> str:
        return self.detail


def _header(headers: Mapping[str, str], name: str) -> str | None:
    try:
        return headers.get(name)
    except AttributeError:
        return None


def resolve_buyer_identity(
    headers: Mapping[str, str],
    claimed_address: str,
    *,
    default_scheme: str = DEFAULT_IDENTITY_SCHEME,
) -> Identity:
    """Resolve buyer identity headers, falling back to the legacy address claim."""
    scheme = _header(headers, "X-Identity-Scheme") or default_scheme
    header_identifier = _header(headers, "X-Identity")
    identifier = header_identifier or claimed_address
    identity = Identity(scheme=scheme, identifier=identifier)

    if header_identifier is not None and scheme == default_scheme:
        if identity.identifier != claimed_address.lower():
            raise AuthError("X-Identity does not match buyer_address")
    return identity


def resolve_expected_identity(
    headers: Mapping[str, str],
    expected: Identity,
) -> Identity:
    """Resolve seller/admin identity headers against an expected identity."""
    scheme = _header(headers, "X-Identity-Scheme") or expected.scheme
    identifier = _header(headers, "X-Identity") or expected.identifier
    claimed = Identity(scheme=scheme, identifier=identifier)

    if claimed.scheme != expected.scheme:
        raise AuthError("Identity scheme mismatch")
    if claimed.identifier != expected.identifier:
        raise AuthError("Identity mismatch")
    return claimed


def _parse_timestamp(headers: Mapping[str, str]) -> int:
    ts_raw = _header(headers, "X-Timestamp")
    if not ts_raw:
        raise AuthError("Missing auth headers")
    try:
        return int(ts_raw)
    except ValueError as exc:
        raise AuthError("Invalid X-Timestamp") from exc


def _parse_signature(headers: Mapping[str, str]) -> bytes:
    sig = _header(headers, "X-Signature")
    if not sig:
        raise AuthError("Missing auth headers")
    try:
        return bytes.fromhex(sig.removeprefix("0x"))
    except ValueError as exc:
        raise AuthError("Malformed X-Signature") from exc


def verify_signed_identity(
    *,
    headers: Mapping[str, str],
    identity: Identity,
    operation: str,
    resource_id: str,
    now: float | None = None,
    max_timestamp_skew: int = DEFAULT_MAX_TIMESTAMP_SKEW,
) -> None:
    """Verify X-Signature/X-Timestamp for an operation/resource pair."""
    ts = _parse_timestamp(headers)
    if abs((time.time() if now is None else now) - ts) > max_timestamp_skew:
        raise AuthError("Timestamp out of range")

    proof = _parse_signature(headers)
    try:
        verifier = get_identity_verifier(identity.scheme)
    except KeyError as exc:
        raise AuthError(
            f"Unknown identity scheme: {identity.scheme}",
            status_code=400,
        ) from exc

    message = f"{operation}:{resource_id}:{ts}".encode("utf-8")
    if not verifier.verify_signature(identity, message, proof):
        raise AuthError("Invalid signature")


def verify_buyer_signature(
    *,
    headers: Mapping[str, str],
    operation: str,
    resource_id: str,
    claimed_address: str,
    now: float | None = None,
    max_timestamp_skew: int = DEFAULT_MAX_TIMESTAMP_SKEW,
) -> Identity:
    """Verify a buyer-signed storefront request."""
    if (
        not claimed_address
        or not claimed_address.startswith("0x")
        or len(claimed_address) != 42
    ):
        raise AuthError("Missing or malformed buyer_address", status_code=400)

    identity = resolve_buyer_identity(headers, claimed_address)
    try:
        verify_signed_identity(
            headers=headers,
            identity=identity,
            operation=operation,
            resource_id=resource_id,
            now=now,
            max_timestamp_skew=max_timestamp_skew,
        )
    except AuthError as exc:
        if exc.detail == "Invalid signature":
            raise AuthError(
                "Invalid signature for claimed buyer identity",
                status_code=exc.status_code,
            ) from exc
        raise
    return identity


def verify_expected_identity_signature(
    *,
    headers: Mapping[str, str],
    operation: str,
    resource_id: str,
    expected: Identity | None,
    now: float | None = None,
    max_timestamp_skew: int = DEFAULT_MAX_TIMESTAMP_SKEW,
) -> Identity | None:
    """Verify a request against an expected identity.

    ``expected=None`` disables verification, matching storefront local-dev
    behavior.
    """
    if expected is None:
        return None
    identity = resolve_expected_identity(headers, expected)
    verify_signed_identity(
        headers=headers,
        identity=identity,
        operation=operation,
        resource_id=resource_id,
        now=now,
        max_timestamp_skew=max_timestamp_skew,
    )
    return identity


def verify_admin_key(*, configured: str | None, supplied: str | None) -> None:
    """Verify a configured admin API key.

    Empty ``configured`` disables verification for local development.
    """
    if not configured:
        return
    if not supplied or supplied != configured:
        raise AuthError("Valid X-Admin-Key header required")
