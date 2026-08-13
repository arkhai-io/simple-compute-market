"""Storefront-owned API-credit service client composition."""

from __future__ import annotations

from domains.apicredits.settlement import CreditsServiceClient

_client: CreditsServiceClient | None = None


def get_credits_service_client() -> CreditsServiceClient:
    """Return the process-wide client for the configured credits service."""
    global _client
    if _client is None:
        from apicredits_storefront.utils import config

        _client = CreditsServiceClient(
            config.credits_service_url(),
            config.credits_admin_key(),
        )
    return _client
