"""Key→owner lookup against the tokens service.

The negotiation round hook captures one key record per round through
this function — the side input ``key_owned_by_buyer_wallet`` consults,
analogous to the inventory snapshot. The guard is the interface, not
the enforcement: issuance re-checks the claim authoritatively.
"""

from __future__ import annotations

import logging
from typing import Any

from domains.apitokens.settlement.issuance import get_key

logger = logging.getLogger(__name__)


async def lookup_key_record(key_id: str) -> dict[str, Any] | None:
    from apitokens_storefront.utils import config

    return await get_key(
        service_url=config.tokens_service_url(),
        admin_key=config.tokens_admin_key(),
        key_id=key_id,
    )
