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
    gpu_count: int | str | None,
) -> str:
    """Fallback derivation key for one VM GPU slice."""
    return f"{resource_id}:gpus:{int(gpu_count or 1)}"


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


def vm_offer_resource_for_listing(
    candidate: dict[str, Any],
    *,
    interruptible: bool = False,
) -> dict[str, Any]:
    """Build the VM-domain listing payload for a publication candidate."""
    offer = {
        "pool_id": candidate.get("pool_id"),
        "gpu_model": candidate["gpu_model"],
        "gpu_count": candidate["gpu_count"],
        "sla": candidate["sla"],
        "region": candidate["region"],
    }
    if candidate.get("resource_id"):
        offer["resource_id"] = candidate["resource_id"]
    if interruptible:
        offer["interruptible"] = True
        offer["settlement_model"] = "splitter_refund"
    return offer


def vm_publication_adapter(
    *,
    open_keys: OpenKeysCallback,
    close_stale: CloseStaleCallback,
    available_candidates: CandidateCallback,
    offer_resource: OfferResourceCallback,
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
        offer_resource=offer_resource,
        record_published=record_published,
        reopen_existing=reopen_existing,
        reopen_error_label="reopen derived listing",
    )
