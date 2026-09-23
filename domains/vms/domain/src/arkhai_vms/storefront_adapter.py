"""VM storefront publication adapter.

The VM domain package owns this lightweight adapter because it defines how VM
publication candidates map into the core storefront publication-source slots.
Concrete storefront executables still inject local inventory, tracking, close,
and registry-publish callbacks.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from core_storefront.publication_sources import PublicationSource

CandidateCallback = Callable[[str], list[dict[str, Any]]]
OpenKeysCallback = Callable[[str], set[str]]
CloseStaleCallback = Callable[[str, str, str | None], list[str]]
OfferResourceCallback = Callable[[dict[str, Any]], dict[str, Any]]
RecordPublishedCallback = Callable[[str, dict[str, Any], str], None]
ReopenExistingCallback = Callable[
    [
        str,
        str,
        dict[str, Any],
        dict[str, Any],
        list[dict[str, Any]],
        list[dict[str, Any]],
        int | None,
        str | None,
    ],
    dict[str, Any] | None,
]


def vm_listing_resource_key(
    resource_id: str | None,
    gpu_count: int,
) -> str:
    """Fallback derivation key for one VM GPU slice.

    The count is required: a candidate is always "N GPUs of this resource", and
    substituting a count for a missing one would key it as a different slice.
    """
    if isinstance(gpu_count, bool) or not isinstance(gpu_count, int) or gpu_count <= 0:
        raise ValueError(f"gpu_count must be a positive integer, not {gpu_count!r}")
    return f"{resource_id}:gpus:{gpu_count}"


def vm_candidate_skip_keys(candidate: dict[str, Any]) -> set[str]:
    """Return skip keys that identify one VM publication candidate."""
    keys: set[str] = set()
    resource_key = candidate.get("resource_key") or vm_listing_resource_key(
        candidate.get("resource_id") or candidate.get("pool_id"),
        candidate.get("gpu_count"),
    )
    for value in (
        resource_key,
        candidate.get("legacy_resource_key"),
        candidate.get("resource_id"),
        candidate.get("pool_id"),
    ):
        if value is not None:
            keys.add(str(value))
    return keys


def vm_listing_resource_for_listing(
    candidate: dict[str, Any],
    *,
    interruptible: bool = False,
) -> dict[str, Any]:
    """Build the VM-domain listing payload for a publication candidate."""
    listing_resource = {
        "pool_id": candidate.get("pool_id"),
        "gpu_model": candidate["gpu_model"],
        "gpu_count": candidate["gpu_count"],
        "sla": candidate["sla"],
        "region": candidate["region"],
        "offering_mode": candidate["offering_mode"],
        "capacity_backing": candidate["capacity_backing"],
    }
    if candidate.get("resource_id"):
        listing_resource["resource_id"] = candidate["resource_id"]
    if interruptible:
        listing_resource["interruptible"] = True
        listing_resource["settlement_model"] = "splitter_refund"
    return listing_resource


def vm_publication_adapter(
    *,
    open_keys: OpenKeysCallback,
    close_stale: CloseStaleCallback,
    available_candidates: CandidateCallback,
    listing_resource: OfferResourceCallback,
    record_published: RecordPublishedCallback,
    reopen_existing: ReopenExistingCallback,
) -> PublicationSource:
    """Build the VM publication source for a concrete storefront."""
    return PublicationSource(
        name="vms",
        open_keys=open_keys,
        close_stale=close_stale,
        available_candidates=available_candidates,
        skip_keys=vm_candidate_skip_keys,
        listing_resource=listing_resource,
        record_published=record_published,
        reopen_existing=reopen_existing,
        reopen_error_label="reopen derived listing",
    )
