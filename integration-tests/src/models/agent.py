"""
arkhai_e2e_tests/models/agent.py
---------------------------------
Typed dataclasses for the storefront REST API request and response shapes.

Derived from agent.py (_run_create_order_flow / _run_close_order_flow
response dicts, serve_erc8004_registration_file response shape).

Auth note: the storefront validates X-Signature / X-Timestamp headers using
EIP-191 where the message is  "<operation>:<resource_id>:<timestamp>".
The resource_id for create_listing is the storefront's BASE_URL_OVERRIDE string;
for close_listing it is the listing_id string.
"""

from __future__ import annotations

from dataclasses import dataclass


# ---------------------------------------------------------------------------
# ERC-8004 registration file and listing response models
#
# These classes have moved to the ``arkhai-storefront-client`` package
# (``storefront_client.models``).  They are re-exported here so that existing
# imports from ``src.models.agent`` continue to work without changes.
# ---------------------------------------------------------------------------

from storefront_client.models import (  # noqa: F401 — re-exported for backward compat
    StorefrontEndpoint,
    StorefrontListingCloseResponse,
    StorefrontListingCreateResponse,
    ERC8004RegistrationFile,
    RegistrationRecord,
)


# Listing-create / -close request builders previously lived here. They were
# tied to the legacy ``{offer, demand}`` shape and had no remaining callers
# inside integration-tests/ after the cutover. The canonical client method
# ``SyncStorefrontClient.create_listing(offer=..., accepted_escrows=...)`` is
# the supported path — see e.g. ``test_full_deal.py:02b``.


# ---------------------------------------------------------------------------
# Listing close  (POST /listings/close)
# ---------------------------------------------------------------------------

@dataclass
class AgentOrderCloseRequest:
    """Request body for POST /listings/close."""
    listing_id: str

    def to_dict(self) -> dict:
        return {"listing_id": self.listing_id}


