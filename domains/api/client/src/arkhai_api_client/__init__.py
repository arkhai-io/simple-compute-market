"""The api family authority's typed client, sync and async."""

from arkhai_api_client.client import (
    ADMIN_KEY_HEADER,
    AuthorityAuthenticationError,
    AuthorityClient,
    AuthorityError,
    SyncAuthorityClient,
)

__all__ = [
    "ADMIN_KEY_HEADER",
    "AuthorityAuthenticationError",
    "AuthorityClient",
    "AuthorityError",
    "SyncAuthorityClient",
]
