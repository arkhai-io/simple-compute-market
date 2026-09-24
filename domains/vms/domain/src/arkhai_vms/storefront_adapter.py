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

from arkhai_vms.capability_shapes import flatten_vm_shape

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


def vm_candidate_skip_keys(candidate: dict[str, Any]) -> set[str]:
    """Return skip keys that identify one VM publication candidate.

    A candidate's structural key names its source and its shape digest. It is
    required: rebuilding one from published fields would key a shaped listing
    as a GPU-count slice it is not.
    """
    resource_key = candidate.get("resource_key")
    if not resource_key:
        raise ValueError("VM publication candidate carries no structural key")
    keys: set[str] = set()
    for value in (
        resource_key,
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
    """Build the VM-domain listing payload for a publication candidate.

    A listing publishes every quantity and attribute its shape declares, under
    the wire names the VM schema maps them to, and no quantity its shape omits:
    a published quantity is what the capacity claim requests.
    """
    shape = candidate.get("listing_shape")
    if shape is None:
        raise ValueError("VM publication candidate carries no listing shape")
    flat = flatten_vm_shape(shape)
    listing_resource = {
        "pool_id": candidate.get("pool_id"),
        **dict(flat.attributes),
        **dict(flat.quantities),
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
