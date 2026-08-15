"""Key→owner lookup against the credits service.

The negotiation round hook captures one key record per round through
this function — the side input ``key_owned_by_buyer_principal`` consults,
analogous to the inventory snapshot. The guard is the interface, not
the enforcement: issuance re-checks the claim authoritatively.
"""

from __future__ import annotations

import logging
from typing import Any

from apicredits_storefront.services.credits_service_client import (
    get_credits_service_client,
)

logger = logging.getLogger(__name__)


async def lookup_key_record(key_id: str) -> dict[str, Any] | None:
    return await get_credits_service_client().get_key(key_id)
