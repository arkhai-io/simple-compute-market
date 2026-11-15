"""The VM buyer's domain record of a listing a registry served."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from arkhai_vms_listings.models import registry_rate_structure


def domain_listing_record(listing: Mapping[str, Any]) -> dict[str, Any]:
    """A registry listing with its family rates where the VM buyer reads them.

    A registry serves a shape-priced listing's family rates only as
    ``pricing.rate_structure``. The buyer lifts them into the record's
    ``rate_structure`` where it receives a listing from a registry, so the
    amount codec, the listing record a run log keeps, and a resume all read
    one key. A listing whose pricing carries no rate structure is returned
    unchanged.
    """
    record = dict(listing)
    published = registry_rate_structure(listing)
    if published is not None:
        record["rate_structure"] = published
    return record
