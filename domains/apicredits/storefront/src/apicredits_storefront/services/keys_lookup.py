"""Key→owner lookup against the credits service.

The negotiation round hook captures one key record per round through
this function — the side input ``key_owned_by_buyer_wallet`` consults,
analogous to the inventory snapshot. The guard is the interface, not
the enforcement: issuance re-checks the claim authoritatively.
"""

from __future__ import annotations

import logging
from typing import Any

from domains.apicredits.settlement.credits_client import CreditsServiceClient

logger = logging.getLogger(__name__)


async def lookup_key_record(key_id: str) -> dict[str, Any] | None:
    from apicredits_storefront.utils import config

    client = CreditsServiceClient(
        config.credits_service_url(), config.credits_admin_key(),
    )
    return await client.get_key(key_id)
