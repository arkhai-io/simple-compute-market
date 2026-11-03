"""The grants a relay's proxies carry, signed for one lease each.

A relay running the admission plugin admits a proxy only when the proxy's own
metadata carries a grant its provisioning service signed for exactly that port.
A grant is the plugin's grant specification, version 1: a compact JWT of type
``frp-grant+jwt``, signed with EdDSA (Ed25519) by the relay's active key, whose
header and claims are serialized as RFC 8785 JSON, so a signer reproduces the
specification's test vector byte for byte. No JWT library serializes claims
canonically, so the token is built here from ``rfc8785`` and ``cryptography``.

Every claim has the type the plugin requires, and the plugin refuses a grant
whose claim has another: ``exp`` is a JSON integer of seconds, ``sub`` and
``jti`` are strings, ``sub`` is omitted rather than ``null`` when the lease
records no host, and the header carries exactly ``alg``, ``kid``, and ``typ``.
No ``iat`` or ``nbf`` is set: the plugin refuses an issue time later than the
relay's clock, with no leeway, so a service clock ahead of the relay's would
have a freshly signed grant refused.
"""

from __future__ import annotations

import base64
from datetime import datetime, timezone
from typing import Any, Mapping

import rfc8785
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from .db import RelayPortLease
from .keys import GrantKey

#: The grant's type: the plugin's grant specification, version 1.
GRANT_TYPE = "frp-grant+jwt"
GRANT_ALGORITHM = "EdDSA"


def _segment(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def sign_compact(
    header: Mapping[str, Any], claims: Mapping[str, Any], private_key: Ed25519PrivateKey
) -> str:
    """A compact token: header and claims as RFC 8785 JSON, signed with Ed25519.

    Each part is canonicalized, then encoded as unpadded base64url; the two are
    joined with a dot, and the signature over those ASCII bytes is appended as
    a third segment.
    """
    signing_input = f"{_segment(rfc8785.dumps(dict(header)))}.{_segment(rfc8785.dumps(dict(claims)))}"
    signature = private_key.sign(signing_input.encode("ascii"))
    return f"{signing_input}.{_segment(signature)}"


def epoch_seconds(stored: datetime) -> int:
    """A stored lease time, UTC with no zone, as integer epoch seconds.

    Converted as UTC explicitly: ``timestamp()`` on a naive datetime reads it
    as the process's local time, which would shift a grant's expiry by the
    local offset.
    """
    if stored.tzinfo is None:
        stored = stored.replace(tzinfo=timezone.utc)
    return int(stored.astimezone(timezone.utc).timestamp())


def grant_claims(lease: RelayPortLease) -> dict[str, Any]:
    """The claims of the grant for one lease.

    ``aud`` is the relay, ``port`` the leased port, ``exp`` the lease's
    recorded grant expiry, ``sub`` its host when it records one, and ``jti``
    its owning reservation, which names the tenancy even after the port's row
    is reused for another.
    """
    if lease.grant_expires_at is None:
        raise ValueError(
            f"lease of port {lease.remote_port} on relay '{lease.relay_id}' "
            "records no grant expiry"
        )
    claims: dict[str, Any] = {
        "aud": str(lease.relay_id),
        "port": int(lease.remote_port),
        "exp": epoch_seconds(lease.grant_expires_at),
        "jti": str(lease.owner_id),
    }
    if lease.host_id:
        claims["sub"] = str(lease.host_id)
    return claims


def sign_grant(lease: RelayPortLease, key: GrantKey) -> str:
    """The grant for one lease, signed with the relay's active key."""
    header = {"alg": GRANT_ALGORITHM, "kid": key.kid, "typ": GRANT_TYPE}
    return sign_compact(header, grant_claims(lease), key.private_key)


__all__ = [
    "GRANT_ALGORITHM",
    "GRANT_TYPE",
    "epoch_seconds",
    "grant_claims",
    "sign_compact",
    "sign_grant",
]
