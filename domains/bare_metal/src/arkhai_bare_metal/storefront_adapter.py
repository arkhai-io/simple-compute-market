"""Bare-metal publication source composed from storefront-owned callbacks.

The domain owns what a candidate is and which key identifies it; the
storefront owns every read and write of its own state, so each callback that
touches the database is supplied by the concrete storefront.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from core_storefront.publication_sources import PublicationSource

OpenKeysCallback = Callable[[str], set[str]]
CloseStaleCallback = Callable[[str, str], list[str]]
CandidateCallback = Callable[[str], list[dict[str, Any]]]
RecordPublishedCallback = Callable[[str, dict[str, Any], str], None]
ReopenExistingCallback = Callable[..., dict[str, Any] | None]


def bare_metal_candidate_skip_keys(candidate: dict[str, Any]) -> set[str]:
    """Return the one key identifying a candidate: its common derivation key."""
    return {str(candidate["derivation_key"])}


def bare_metal_publication_adapter(
    *,
    open_keys: OpenKeysCallback,
    close_stale: CloseStaleCallback,
    available_candidates: CandidateCallback,
    record_published: RecordPublishedCallback,
    reopen_existing: ReopenExistingCallback,
) -> PublicationSource:
    """Build the bare-metal publication source for a concrete storefront."""
    return PublicationSource(
        name="bare_metal",
        open_keys=open_keys,
        close_stale=close_stale,
        available_candidates=available_candidates,
        skip_keys=bare_metal_candidate_skip_keys,
        listing_resource=lambda candidate: dict(candidate["listing_resource"]),
        pricing_resource=lambda _candidate, listing_resource: listing_resource,
        record_published=record_published,
        reopen_existing=reopen_existing,
        reopen_error_label="reconcile bare-metal listing",
    )
