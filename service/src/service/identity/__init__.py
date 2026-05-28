"""Pluggable identity schemes.

Importing this package eagerly registers every built-in scheme via
:mod:`service.identity.schemes`. The default scheme is ``eip191``;
other schemes can be added by registering an :class:`IdentityVerifier`
through :func:`register_identity_scheme`.
"""

from service.identity.registry import (
    IdentityVerifier,
    get_identity_verifier,
    list_identity_schemes,
    register_identity_scheme,
)
from service.identity import schemes  # noqa: F401 — registers built-ins on import

__all__ = [
    "IdentityVerifier",
    "get_identity_verifier",
    "list_identity_schemes",
    "register_identity_scheme",
]
