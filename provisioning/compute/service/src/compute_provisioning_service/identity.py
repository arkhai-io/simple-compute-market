"""Marketplace identity composition for the provisioning authority."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from market_identity import Identity, Signer, create_signer

IDENTITY_CREDENTIAL_ENV = "ARKHAI_IDENTITY_CREDENTIAL"


@dataclass(frozen=True, slots=True)
class ProvisioningIdentityContext:
    """The authority signer and exact seller/admin caller trust pins."""

    signer: Signer
    storefront_principal: Identity
    admin_principal: Identity
    storefront_site_id: str


def resolve_identity_context(
    settings: Any,
    *,
    environ: Mapping[str, str] | None = None,
) -> ProvisioningIdentityContext:
    """Resolve public principals and require a matching Secret-injected signer."""

    identity = _principal(settings, "identity")
    storefront = _principal(settings, "storefront_identity")
    admin = _principal(settings, "admin_identity")
    if admin in {identity, storefront} or identity == storefront:
        raise RuntimeError(
            "identity, storefront_identity, and admin_identity must be distinct"
        )
    source = getattr(settings, "_source", settings)
    storefront_site_id = str(source.get("storefront_site_id", "") or "").strip()
    if not storefront_site_id:
        raise RuntimeError("storefront_site_id is required")
    environment = os.environ if environ is None else environ
    credential = environment.get(IDENTITY_CREDENTIAL_ENV)
    if credential is None or credential == "":
        raise RuntimeError(f"{IDENTITY_CREDENTIAL_ENV} is required")
    try:
        signer = create_signer(identity.scheme, credential)
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeError("provisioning identity credential is invalid") from exc
    if signer.identity != identity:
        raise RuntimeError(
            "provisioning identity credential does not match identity.scheme/identifier"
        )
    return ProvisioningIdentityContext(
        signer=signer,
        storefront_principal=storefront,
        admin_principal=admin,
        storefront_site_id=storefront_site_id,
    )


def _principal(settings: Any, namespace: str) -> Identity:
    source = getattr(settings, "_source", settings)
    scheme = str(source.get(f"{namespace}.scheme", "") or "").strip()
    identifier = str(source.get(f"{namespace}.identifier", "") or "").strip()
    if not scheme or not identifier:
        raise RuntimeError(
            f"{namespace}.scheme and {namespace}.identifier are required"
        )
    try:
        return Identity(scheme=scheme, identifier=identifier)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"{namespace} principal is invalid") from exc
