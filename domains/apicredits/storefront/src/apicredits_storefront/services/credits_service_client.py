"""Storefront-owned composition of the family authority client."""

from __future__ import annotations

from arkhai_api_client import AuthorityClient
from arkhai_apicredits.label import API_CREDITS_LABEL

_client: AuthorityClient | None = None


def get_credits_service_client() -> AuthorityClient:
    """Return the process-wide client for the configured credits service.

    Signed authentication is selected by the presence of a configured
    authority trust set. It is resolved together with the storefront's own
    signer, because signing requests without verifying responses would
    accept an unauthenticated answer to an authenticated question -- the
    client refuses that combination.

    The storefront signs eip191 (see `[identity]` in
    `storefront.credits.toml`), while the authority signs ed25519. Neither
    side infers the other's scheme: each is configured.
    """
    global _client
    if _client is None:
        from apicredits_storefront.utils import config

        authorities = config.credits_expected_authorities()
        _client = AuthorityClient(
            config.credits_service_url(),
            config.credits_admin_key(),
            label=API_CREDITS_LABEL,
            signer=config.resolve_identity_signer() if authorities else None,
            expected_authorities=authorities,
        )
    return _client
