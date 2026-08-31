"""Scheme-neutral signer, verifier, and signer-factory registries."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from market_identity.models import Identity, IdentityScheme

SecretMaterial = bytes | str


@runtime_checkable
class Signer(Protocol):
    """Signs bytes while exposing only its canonical public identity."""

    @property
    def identity(self) -> Identity: ...

    def sign(self, message: bytes) -> bytes: ...


@runtime_checkable
class IdentityVerifier(Protocol):
    """Verifies a raw signature against one canonical public identity."""

    name: IdentityScheme

    def verify_signature(
        self,
        identity: Identity,
        message: bytes,
        proof: bytes,
    ) -> bool: ...


@runtime_checkable
class SignerFactory(Protocol):
    """Builds a scheme-specific signer from separately resolved secret material."""

    name: IdentityScheme

    def create(self, secret: SecretMaterial) -> Signer: ...


_VERIFIERS: dict[IdentityScheme, IdentityVerifier] = {}
_SIGNER_FACTORIES: dict[IdentityScheme, SignerFactory] = {}


def register_identity_scheme(
    verifier: IdentityVerifier,
    signer_factory: SignerFactory | None = None,
) -> None:
    """Register one verifier and, optionally, its signer factory without replacement."""

    _register(_VERIFIERS, verifier.name, verifier, kind="verifier")
    if signer_factory is not None:
        if signer_factory.name != verifier.name:
            raise ValueError("signer factory scheme must match verifier scheme")
        _register(
            _SIGNER_FACTORIES,
            signer_factory.name,
            signer_factory,
            kind="signer factory",
        )


def register_signer_factory(factory: SignerFactory) -> None:
    """Register a signer factory for an already registered identity scheme."""

    if factory.name not in _VERIFIERS:
        raise ValueError(
            f"cannot register signer factory without verifier for {factory.name.value!r}"
        )
    _register(_SIGNER_FACTORIES, factory.name, factory, kind="signer factory")


def get_identity_verifier(scheme: IdentityScheme | str) -> IdentityVerifier:
    """Return the verifier registered for an explicit supported scheme."""

    normalized = _scheme(scheme)
    try:
        return _VERIFIERS[normalized]
    except KeyError as exc:
        raise KeyError(
            f"no identity verifier registered for scheme {normalized.value!r}"
        ) from exc


def get_signer_factory(scheme: IdentityScheme | str) -> SignerFactory:
    """Return the signer factory registered for an explicit supported scheme."""

    normalized = _scheme(scheme)
    try:
        return _SIGNER_FACTORIES[normalized]
    except KeyError as exc:
        raise KeyError(
            f"no signer factory registered for scheme {normalized.value!r}"
        ) from exc


def create_signer(scheme: IdentityScheme | str, secret: SecretMaterial) -> Signer:
    """Create a signer through explicit scheme dispatch."""

    return get_signer_factory(scheme).create(secret)


def list_identity_schemes() -> tuple[str, ...]:
    """Return registered verifier scheme names in deterministic order."""

    return tuple(sorted(scheme.value for scheme in _VERIFIERS))


def list_signer_schemes() -> tuple[str, ...]:
    """Return registered signer scheme names in deterministic order."""

    return tuple(sorted(scheme.value for scheme in _SIGNER_FACTORIES))


def _scheme(value: IdentityScheme | str) -> IdentityScheme:
    try:
        return value if isinstance(value, IdentityScheme) else IdentityScheme(value)
    except ValueError as exc:
        raise KeyError(f"unsupported identity scheme {value!r}") from exc


def _register(registry: dict, name: IdentityScheme, implementation: object, *, kind: str) -> None:
    if not isinstance(name, IdentityScheme):
        raise TypeError(f"{kind} name must be an IdentityScheme")
    existing = registry.get(name)
    if existing is None:
        registry[name] = implementation
        return
    if existing is implementation:
        return
    raise ValueError(
        f"identity {kind} {name.value!r} is already registered "
        f"(existing: {type(existing).__name__}, new: {type(implementation).__name__})"
    )
