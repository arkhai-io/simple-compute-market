"""Compatibility shim for :mod:`market_identity.registry`."""

from market_identity.registry import (  # noqa: F401
    _VERIFIERS,
    IdentityVerifier,
    get_identity_verifier,
    list_identity_schemes,
    register_identity_scheme,
)
