"""A site authority's own credential and the callers it trusts.

Nothing here is domain-specific. A site authority verifies signed requests and
signs its own responses whether its inventory is virtual machines, bare metal
or prepaid API credits, so the resolution belongs beside the middleware that
consumes it rather than repeated in each service that mounts the router.

Deliberately takes plain values -- a credential reference, a pinned principal,
a mapping of role to principal entries -- rather than a settings object. Each
service resolves configuration its own way (dynaconf profiles here, environment
there), and a kit that knew about any one of those would force the others to
satisfy it. The service-side shim is then small enough to be obviously correct.

Credential reading goes through `market_identity`'s
`SecretFileCredentialProvider`, which opens no-follow, owner-only and
size-bounded. Re-implementing that with `read_bytes` is how a credential file
becomes a symlink to something else.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from market_identity import (
    CredentialProviderError,
    CredentialProviderKind,
    CredentialReference,
    Identity,
    Signer,
    TrustedIdentitySet,
    create_signer,
    default_credential_registry,
)

logger = logging.getLogger(__name__)

DEFAULT_SCHEME = "ed25519"

#: Length of a raw, unencoded Ed25519 seed. Distinguishes the two accepted
#: credential-file encodings, which matters only for whitespace handling.
_RAW_SEED_BYTES = 32


class SiteIdentityError(RuntimeError):
    """A site authority's identity configuration cannot be honoured."""


def parse_principal(entry: Any, *, default_scheme: str = DEFAULT_SCHEME) -> Identity:
    """Read one configured principal.

    Accepts the scheme/identifier mapping already used for
    `expected_authorities` in storefront configuration, and a bare string as
    shorthand for the default scheme -- the form an operator is most likely to
    paste from a key listing.
    """
    if isinstance(entry, str):
        identifier = entry.strip()
        if not identifier:
            raise SiteIdentityError("trusted principal is an empty string")
        return Identity(scheme=default_scheme, identifier=identifier)
    if isinstance(entry, Mapping):
        identifier = str(entry.get("identifier") or "").strip()
        if not identifier:
            raise SiteIdentityError(f"trusted principal {entry!r} names no identifier")
        return Identity(
            scheme=str(entry.get("scheme") or default_scheme),
            identifier=identifier,
        )
    raise SiteIdentityError(
        f"trusted principal {entry!r} is neither a string nor a mapping"
    )


def resolve_trusted_principals(
    configured: Mapping[str, Any] | None,
    *,
    default_scheme: str = DEFAULT_SCHEME,
) -> dict[str, TrustedIdentitySet]:
    """Build per-role trust sets, omitting roles that name nobody.

    A role with no entries is *absent*, not empty. `TrustedIdentitySet` refuses
    to be empty, and the distinction is load-bearing: `expected_principals`
    raises for an absent role and the middleware turns that into a signed
    refusal naming the missing configuration. Silently trusting nobody and
    silently trusting anybody are both worse than saying which role was never
    configured.
    """
    resolved: dict[str, TrustedIdentitySet] = {}
    for role, entries in dict(configured or {}).items():
        identities = tuple(
            parse_principal(entry, default_scheme=default_scheme)
            for entry in (entries or ())
        )
        if not identities:
            continue
        resolved[str(role).strip().lower()] = TrustedIdentitySet(
            identities=identities
        )
    return resolved


def resolve_site_signer(
    credential_locator: str | None = None,
    *,
    credential: bytes | str | None = None,
    expected_principal: Identity | None = None,
    scheme: str = DEFAULT_SCHEME,
) -> Signer:
    """Build this authority's signer from supplied material or a secret file.

    Two sources because the repository has two delivery mechanisms and this
    kit should not pick one. Services receive their credential as a read-only
    bind mount of a committed file (`*_IDENTITY_CREDENTIAL_FILE` in compose),
    which is group- and world-readable because git does not carry `0600`; the
    buyer generates its own into an owner-only store. `credential` serves the
    first, `credential_locator` the second, and the locator path goes through
    the no-follow owner-only provider precisely because that is the case where
    the permissions are under the tool's control.

    Supplying neither is a programming error, not a disabled deployment --
    `SiteIdentity` decides that by passing neither and is where "no credential
    configured" is represented.

    Fails closed when `expected_principal` is given and the credential does not
    own it. That check is the point of pinning: without it a service starts
    happily on the wrong credential and signs every response as a principal no
    counterparty pinned, which reads to them as an impostor rather than as a
    misconfiguration -- and the service itself has no way to notice.
    """
    if credential is not None:
        secret: bytes | str = credential
        source = "supplied credential"
    elif credential_locator:
        reference = CredentialReference(
            provider=CredentialProviderKind.SECRET_FILE,
            locator=credential_locator,
        )
        try:
            secret = default_credential_registry().load(reference)
        except CredentialProviderError as exc:
            raise SiteIdentityError(
                f"site signing credential at {credential_locator!r} cannot be "
                f"read: {exc}"
            ) from exc
        source = f"credential at {credential_locator!r}"
    else:
        raise SiteIdentityError("no site signing credential was supplied")

    # A committed or mounted credential file ends with a newline far more often
    # than not -- git adds one, editors add one -- and the scheme's secret
    # parser requires canonical unpadded base64url, which a trailing newline is
    # not. Stripped only for the encoded form: a raw 32-byte seed may
    # legitimately end in 0x0a and must pass through untouched.
    if isinstance(secret, bytes) and len(secret) != _RAW_SEED_BYTES:
        secret = secret.strip()
    elif isinstance(secret, str):
        secret = secret.strip()

    try:
        signer = create_signer(scheme, secret)
    except Exception as exc:
        raise SiteIdentityError(
            f"site {source} is not a valid {scheme} secret"
        ) from exc

    if expected_principal is not None and signer.identity != expected_principal:
        raise SiteIdentityError(
            "site signing credential does not own the configured principal: "
            f"credential is {signer.identity.identifier!r}, configuration pins "
            f"{expected_principal.identifier!r}"
        )
    return signer


class SiteIdentity:
    """One authority's resolved credential and trust sets.

    Resolved eagerly by its constructor, so a service builds this at startup
    and fails there. A credential that cannot be read is not a per-request
    error to retry: the service cannot sign anything, and the kit's client
    refuses an unsigned response, so every call would fail anyway and later,
    with nobody watching.
    """

    def __init__(
        self,
        *,
        credential_locator: str | None = None,
        credential: bytes | str | None = None,
        trusted_principals: Mapping[str, Any] | None = None,
        expected_principal: Identity | None = None,
        scheme: str = DEFAULT_SCHEME,
    ) -> None:
        self.trusted_principals = resolve_trusted_principals(
            trusted_principals, default_scheme=scheme
        )
        self.signer: Signer | None = (
            resolve_site_signer(
                credential_locator,
                credential=credential,
                expected_principal=expected_principal,
                scheme=scheme,
            )
            if (credential or credential_locator)
            else None
        )

    @property
    def enabled(self) -> bool:
        """Whether signed authentication can be honoured in both directions.

        Both halves required. An authority holding trust sets but no credential
        could verify a caller and then answer unsigned, which is the one
        outcome the kit's client cannot read at all -- so a half-configured
        deployment is better served by whatever gate it had than by this.
        """
        return self.signer is not None and bool(self.trusted_principals)

    def require_signer(self) -> Signer:
        if self.signer is None:
            raise SiteIdentityError("no site signing credential is configured")
        return self.signer

    def expected_principals(self, role: str) -> TrustedIdentitySet:
        """The principals trusted for one caller role.

        Raises for a role nobody is configured for; `SiteAuthMiddleware` turns
        that into a signed refusal naming the gap.
        """
        return self.trusted_principals[role.strip().lower()]
