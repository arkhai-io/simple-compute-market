"""Identity-scheme verifier registry."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from market_identity.models import Identity


@runtime_checkable
class IdentityVerifier(Protocol):
    """Verifies that a signed message proves ownership of an identity."""

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

    Re-registering the same object is a no-op. Registering a different
    verifier under an existing name raises, because silent replacement
    would let different packages disagree about what a scheme means.
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
    """Return the verifier registered for ``scheme``."""

    try:
        return _VERIFIERS[scheme]
    except KeyError as exc:
        raise KeyError(f"no identity verifier registered for scheme {scheme!r}") from exc


def list_identity_schemes() -> list[str]:
    """Return all registered identity scheme names."""

    return sorted(_VERIFIERS)
