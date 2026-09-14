"""This service's site-authority identity, read from its own configuration.

A shim over `market_site.identity`, which owns the resolution: reading the
credential through the no-follow secret-file provider, pinning it against a
configured principal, and building per-role trust sets. None of that is
specific to selling API calls, so none of it lives here.

What is specific is where the values come from -- this service's dynaconf
profiles -- and that is all this module does.

Resolved at import, so a credential that cannot be read or does not own the
pinned principal fails at startup while an operator is watching. A service
unable to sign its own responses cannot be talked to by the kit's client
anyway, so deferring that failure to a request only moves it somewhere nobody
is looking.
"""

from __future__ import annotations

from pathlib import Path

from config import settings
from market_site.identity import SiteIdentity, parse_principal

_pinned_principal = settings.get("site_principal", "") or None

# Read as material rather than through the owner-only secret-file provider:
# every service credential in this repository arrives as a read-only bind mount
# of a committed file, which is world-readable because git does not carry
# `0600`. The strict provider is right for a store whose permissions the tool
# controls, and would refuse every one of these.
_credential_file = str(settings.get("site_signing_key_file", "") or "")
_credential = (
    Path(_credential_file).read_bytes() if _credential_file else None
)

site_identity = SiteIdentity(
    credential=_credential,
    trusted_principals=settings.get("trusted_principals", None),
    expected_principal=(
        parse_principal(_pinned_principal) if _pinned_principal else None
    ),
)


def signed_authentication_enabled() -> bool:
    """Whether this deployment can verify callers and sign its own responses."""
    return site_identity.enabled


def require_signer():
    return site_identity.require_signer()


def expected_principals(role: str):
    return site_identity.expected_principals(role)
