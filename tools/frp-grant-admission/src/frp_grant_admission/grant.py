"""Verifying a grant: an EdDSA-signed `frp-grant+jwt` for exactly one remote port.

The checks run in a fixed order and the first that fails decides the refusal:

1. the grant is at most 4 KiB of UTF-8, and its header is canonical base64url, padded
   or not, of a JSON object;
2. the unverified header's `kid` names a configured key;
3. the unverified header's `typ` is `frp-grant+jwt`, and it carries no `crit`;
4. PyJWT parses the token and checks its EdDSA signature under that key, the key's
   issuer's audience as one string, and the presence of `aud`, `exp`, and `port`;
5. `exp`, and `nbf` and `iat` when present, are JSON integers; the grant has expired
   from the second the clock reaches `exp`, and is not yet valid while `nbf` or `iat`
   is later than the clock, with no leeway;
6. `sub` and `jti`, when present, are strings;
7. `port` is a JSON integer equal to the remote port, inside the issuer's range.

PyJWT decides only what the library is trusted for: JWS parsing, the signature,
`aud`, and the required claims. Every rule whose behaviour is known to differ between
the PyJWT releases the tool declares — the header checks, the time checks, and the
claim types — is decided here, so none of those rules depends on the installed
release; the published vector is proven at the lock and at the declared floors, not
at every release in between. The header is read by this module rather than by PyJWT
because some releases reject `crit` while reading it, which would let the release
choose which refusal is reported.

The clock is the caller's. PyJWT reads the system clock while decoding, but every
time check it would make with it is switched off, so a verdict depends only on the
clock passed in, and a case of the published vector replays at its own time.
"""

from __future__ import annotations

import base64
import binascii
import json
import re
from dataclasses import dataclass

import jwt

from frp_grant_admission.config import Config
from frp_grant_admission.reasons import Reason

GRANT_TYPE = "frp-grant+jwt"
MAX_GRANT_BYTES = 4096

_SEGMENT = re.compile(r"[A-Za-z0-9_-]*={0,2}")
_UNREAD = object()
# PyJWT 2.8.0, the declared floor, has no module-level `jwt.decode_complete`; the
# `PyJWT` class carries it in every declared release. Decoding never changes the
# instance, so one serves every request thread.
_PYJWT = jwt.PyJWT()


@dataclass(frozen=True)
class GrantResult:
    """A grant's verdict and what it named.

    `kid`, `sub`, `jti`, and `exp` are what the token carried, for the decision log,
    and are `None` where the token carried none or could not be read. `verified` is
    true only when the signature, audience, and required claims passed and `exp`,
    `nbf`, `iat`, `sub`, and `jti` have their types: only then are those values the
    issuer's, and `sub` and `jti` strings. A grant refused for its time or its port,
    a `port` of the wrong type included, still carries verified claims; one refused
    earlier carries values anyone could have written.
    """

    reason: Reason | None
    issuer: str | None = None
    kid: object = None
    sub: object = None
    jti: object = None
    exp: object = None
    verified: bool = False

    @property
    def admitted(self) -> bool:
        return self.reason is None


def check_grant(grant: str, config: Config, remote_port: int, now: int) -> GrantResult:
    """Decide whether `grant` admits a proxy on `remote_port` at `now` (Unix seconds)."""
    try:
        size = len(grant.encode("utf-8"))
    except UnicodeEncodeError:
        # JSON can carry an unpaired surrogate, which no UTF-8 token contains.
        return GrantResult(Reason.GRANT_MALFORMED)
    if size > MAX_GRANT_BYTES:
        return GrantResult(Reason.GRANT_MALFORMED)
    unverified = _read_unverified(grant)
    if unverified is None:
        return GrantResult(Reason.GRANT_MALFORMED)
    header, claims = unverified
    read = {
        "kid": header.get("kid"),
        "sub": claims.get("sub"),
        "jti": claims.get("jti"),
        "exp": claims.get("exp"),
    }

    kid = header.get("kid")
    key = config.key(kid) if isinstance(kid, str) else None
    if key is None:
        return GrantResult(Reason.KEY_UNKNOWN, **read)
    issuer = key.issuer
    if header.get("typ") != GRANT_TYPE:
        return GrantResult(Reason.GRANT_TYPE_UNSUPPORTED, issuer.name, **read)
    if "crit" in header:
        return GrantResult(Reason.GRANT_MALFORMED, issuer.name, **read)

    try:
        decoded = _PYJWT.decode_complete(
            grant,
            key.public_key,
            algorithms=["EdDSA"],
            audience=issuer.audience,
            options={
                "require": ["exp", "aud", "port"],
                "strict_aud": True,
                "verify_exp": False,
                "verify_nbf": False,
                "verify_iat": False,
                "verify_sub": False,
                "verify_jti": False,
            },
        )
    except (jwt.InvalidSignatureError, jwt.InvalidAlgorithmError):
        return GrantResult(Reason.SIGNATURE_INVALID, issuer.name, **read)
    except jwt.MissingRequiredClaimError:
        return GrantResult(Reason.CLAIM_MISSING, issuer.name, **read)
    except jwt.InvalidAudienceError:
        return GrantResult(Reason.AUDIENCE_MISMATCH, issuer.name, **read)
    except (jwt.PyJWTError, RecursionError):
        # Some declared PyJWT releases let the JSON parser's RecursionError escape
        # from a deeply nested claims segment rather than raising DecodeError.
        return GrantResult(Reason.GRANT_MALFORMED, issuer.name, **read)

    payload = decoded["payload"]
    exp = payload["exp"]
    times_typed = _is_integer(exp) and all(
        _is_integer(payload[claim]) for claim in ("nbf", "iat") if claim in payload
    )
    ids_typed = all(isinstance(payload[claim], str) for claim in ("sub", "jti") if claim in payload)
    verified = times_typed and ids_typed
    result = {
        "issuer": issuer.name,
        "kid": kid,
        "sub": payload.get("sub"),
        "jti": payload.get("jti"),
        "exp": exp,
        "verified": verified,
    }

    if not times_typed:
        return GrantResult(Reason.GRANT_MALFORMED, **result)
    if now >= exp:
        return GrantResult(Reason.GRANT_EXPIRED, **result)
    if any(payload[claim] > now for claim in ("nbf", "iat") if claim in payload):
        return GrantResult(Reason.GRANT_NOT_YET_VALID, **result)
    if not ids_typed:
        return GrantResult(Reason.GRANT_MALFORMED, **result)
    port = payload["port"]
    if not _is_integer(port) or port != remote_port:
        return GrantResult(Reason.PORT_MISMATCH, **result)
    if not issuer.covers(port):
        return GrantResult(Reason.PORT_OUTSIDE_RANGE, **result)
    return GrantResult(None, **result)


def _is_integer(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _read_unverified(grant: str) -> tuple[dict, dict] | None:
    """The token's header and claims as written, before anything is verified.

    The header must decode to a JSON object or the token is malformed. Claims that do
    not decode to an object read as none: they are only reported, and PyJWT refuses
    such a token once the header has passed.
    """
    segments = grant.split(".")
    if len(segments) != 3:
        return None
    header = _segment_json(segments[0])
    if not isinstance(header, dict):
        return None
    claims = _segment_json(segments[1])
    return header, claims if isinstance(claims, dict) else {}


def _segment_json(segment: str) -> object:
    """The JSON a base64url segment encodes, padded or not, or `_UNREAD`."""
    if not _SEGMENT.fullmatch(segment):
        return _UNREAD
    stripped = segment.rstrip("=")
    if (stripped != segment and len(segment) % 4) or len(stripped) % 4 == 1:
        return _UNREAD
    try:
        data = base64.urlsafe_b64decode(stripped + "=" * (-len(stripped) % 4))
    except (binascii.Error, ValueError):
        return _UNREAD
    if base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii") != stripped:
        return _UNREAD
    try:
        return json.loads(data)
    except (ValueError, RecursionError):
        return _UNREAD
