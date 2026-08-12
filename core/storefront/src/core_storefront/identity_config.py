"""Public storefront identity configuration and secret-bound signer resolution."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from market_identity import Identity, IdentityScheme, Signer, create_signer


class IdentityConfig(BaseModel):
    """Public marketplace principal selected for this storefront."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    scheme: IdentityScheme
    identifier: str

    @property
    def principal(self) -> Identity:
        return Identity(scheme=self.scheme, identifier=self.identifier)


def resolve_storefront_signer(
    config: IdentityConfig,
    credential: bytes | str,
) -> Signer:
    """Resolve secret material and fail closed unless it owns the configured principal."""

    signer = create_signer(config.scheme, credential)
    if signer.identity != config.principal:
        raise ValueError("storefront identity credential does not match configured principal")
    return signer
