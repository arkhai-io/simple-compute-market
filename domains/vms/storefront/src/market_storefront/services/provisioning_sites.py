"""Trusted configured provisioning connections keyed by durable site identity."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from compute_provisioning import ComputeProvisioningClient


@dataclass(frozen=True)
class ProvisioningSiteConnection:
    site_id: str
    base_url: str
    admin_key: str


def configured_provisioning_sites() -> dict[str, ProvisioningSiteConnection]:
    """Resolve operator-trusted site bindings without persisting secrets."""
    from market_storefront.utils import config

    settings = config.settings
    capacity = getattr(settings, "capacity", None)
    shared_key = str(getattr(settings, "admin_api_key", "") or "")
    bindings: dict[str, ProvisioningSiteConnection] = {}
    raw_sites = getattr(capacity, "sites", None)
    if raw_sites:
        for raw_site_id, raw_value in dict(raw_sites).items():
            site_id = str(raw_site_id)
            if isinstance(raw_value, str):
                url = raw_value
                key = shared_key
            else:
                value: dict[str, Any] = dict(raw_value)
                url = str(value.get("url") or value.get("base_url") or "")
                key = str(value.get("admin_api_key") or shared_key)
            if url.strip():
                bindings[site_id] = ProvisioningSiteConnection(
                    site_id=site_id,
                    base_url=url.rstrip("/"),
                    admin_key=key,
                )
    if not bindings:
        url = str(getattr(capacity, "authority_url", "") or "")
        if not url:
            url = str(
                getattr(getattr(settings, "provisioning", None), "service_url", "")
                or ""
            )
        if url.strip():
            bindings["default"] = ProvisioningSiteConnection(
                site_id="default", base_url=url.rstrip("/"), admin_key=shared_key
            )
    return bindings


def require_provisioning_site(site_id: str) -> ProvisioningSiteConnection:
    binding = configured_provisioning_sites().get(site_id)
    if binding is None:
        raise RuntimeError(f"configured provisioning site {site_id!r} is unavailable")
    return binding


def compute_client_for_site(site_id: str) -> ComputeProvisioningClient:
    binding = require_provisioning_site(site_id)
    return ComputeProvisioningClient(binding.base_url, binding.admin_key)
