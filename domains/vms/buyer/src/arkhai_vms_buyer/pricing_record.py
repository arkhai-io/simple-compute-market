"""Acceptance-bound pricing inputs and their seller publication proof."""

from collections.abc import Mapping
from copy import deepcopy
from typing import Any


def retained_pricing_record(listing: Mapping[str, Any]) -> dict[str, Any]:
    """Keep pricing inputs and seller proof together for accepted recovery.

    This is retention, not verification. The raw publication preserves signed
    bytes and request context that a reconstructed listing subset cannot prove.
    Copy nested values so later selection or listing edits cannot rewrite them.
    """
    return deepcopy({key: listing[key] for key in (
        "listing_id", "listing_resource", "rate_structure", "settlement_options",
        "accepted_escrows", "publisher_publication", "publisher_updates",
        "publisher_principals", "publisher_id", "source_registry_url",
        "source_registry_authority",
    ) if key in listing})
