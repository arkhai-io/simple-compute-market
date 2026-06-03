"""Identity-scheme verifier registry.

Schemes register themselves at import time via
:func:`register_identity_scheme`; the storefront's auth middlewares and
the registry's signed-request verifiers dispatch through
:func:`get_identity_verifier`.

The protocol layer never knows about specific schemes — it carries
:class:`service.schemas.Identity` values end-to-end and consults the
registry only at signature-verification time.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from service.schemas import Identity


@runtime_checkable
class IdentityVerifier(Protocol):
    """Verifies a signed message proves ownership of an :class:`Identity`.

    ``name`` must match the ``Identity.scheme`` strings that route to
    this verifier. ``verify_signature`` returns True iff ``proof``
    demonstrates that the principal at ``identity.identifier`` signed
    ``message`` under this scheme.

    Implementations should be exception-safe: invalid signatures,
    malformed proofs, and recovery failures all return False rather
    than raising. Network or import errors may raise.
    """

    name: str

    def verify_signature(
        self,
        identity: Identity,
        message: bytes,
        proof: bytes,
    ) -> bool: ...


_VERIFIERS: dict[str, IdentityVerifier] = {}


def register_identity_scheme(verifier: IdentityVerifier) -> None:
    """Register ``verifier`` under its ``name``.

    Idempotent on identical re-registration (same object); raises if a
    different verifier is registered under an already-taken name, since
    silent override would mean two parts of the codebase disagree about
    what a scheme means.
    """
    name = verifier.name
    existing = _VERIFIERS.get(name)
    if existing is None:
        _VERIFIERS[name] = verifier
        return
    if existing is verifier:
        return
    raise ValueError(
        f"identity scheme {name!r} is already registered "
        f"(existing: {type(existing).__name__}, new: {type(verifier).__name__})"
    )


def get_identity_verifier(scheme: str) -> IdentityVerifier:
    """Return the verifier registered for ``scheme``.

    Raises :class:`KeyError` if no verifier is registered. Callers in
    auth paths should translate this into a 400-style response so
    unknown schemes are rejected at the protocol edge.
    """
    try:
        return _VERIFIERS[scheme]
    except KeyError as exc:
        raise KeyError(f"no identity verifier registered for scheme {scheme!r}") from exc


def list_identity_schemes() -> list[str]:
    """Return the names of all currently-registered schemes (sorted)."""
    return sorted(_VERIFIERS)
