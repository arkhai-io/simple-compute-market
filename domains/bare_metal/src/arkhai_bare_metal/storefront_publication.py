"""Storefront tracking for trusted bare-metal publication generations."""

from __future__ import annotations

import json
import logging
import sqlite3
from collections.abc import Iterable
from typing import Any

from .projections import TrustedBareMetalProjection
from .publication import available_bare_metal_listings, bare_metal_listing_key
from .schema import BareMetalListing

logger = logging.getLogger(__name__)


def bare_metal_listing_candidates(
    projections: Iterable[TrustedBareMetalProjection],
    *,
    min_duration_seconds: int | None = None,
    max_duration_seconds: int | None = None,
    site_labels_by_id: dict[str, dict[str, str]] | None = None,
) -> list[dict[str, Any]]:
    """Return candidates from retained complete trusted generations."""
    candidates: list[dict[str, Any]] = []
    labels = site_labels_by_id or {}
    for projection in projections:
        if not projection.complete or projection.stale:
            continue
        for resource in projection.resources:
            listings = available_bare_metal_listings(
                [resource],
                min_duration_seconds=min_duration_seconds,
                max_duration_seconds=max_duration_seconds,
                site=labels.get(projection.site_id),
            )
            if not listings:
                continue
            listing = listings[0]
            derivation_key = bare_metal_listing_key(
                site_id=projection.site_id,
                physical_resource_id=resource.physical_resource_id,
            )
            candidates.append(
                {
                    "derivation_key": derivation_key,
                    "site_id": projection.site_id,
                    "projection_revision": projection.revision,
                    "projection_digest": projection.digest,
                    "physical_resource_id": resource.physical_resource_id,
                    "pool_id": resource.pool_id,
                    "host_id": listing.host_id,
                    "physical_host_id": listing.physical_host_id,
                    "listing_resource": listing.model_dump(
                        mode="json",
                        exclude_none=True,
                    ),
                    "listing": listing,
                }
            )
    return candidates


def open_bare_metal_listing_keys(db_path: str) -> set[str]:
    """Return tracked derivation keys whose local listing remains open."""
    conn = _read_connection(db_path)
    try:
        rows = conn.execute(
            """
            SELECT d.derivation_key
            FROM derived_bare_metal_listings d
            JOIN listings l ON l.listing_id = d.listing_id
            WHERE d.status = 'open' AND l.status = 'open'
            """,
        ).fetchall()
    finally:
        conn.close()
    return {str(row[0]) for row in rows}


def stale_open_bare_metal_listing_ids(
    db_path: str,
    projections: Iterable[TrustedBareMetalProjection],
) -> list[str]:
    """Return stale listings only for sites with a complete generation."""
    complete = [projection for projection in projections if projection.complete]
    if not complete:
        return []
    complete_sites = {projection.site_id for projection in complete}
    available_keys = {
        candidate["derivation_key"]
        for candidate in bare_metal_listing_candidates(complete)
    }
    conn = _read_connection(db_path)
    try:
        placeholders = ", ".join("?" for _ in complete_sites)
        rows = conn.execute(
            f"""
            SELECT d.listing_id, d.derivation_key
            FROM derived_bare_metal_listings d
            JOIN listings l ON l.listing_id = d.listing_id
            WHERE d.site_id IN ({placeholders})
              AND d.status = 'open'
              AND l.status = 'open'
            ORDER BY d.listing_id
            """,
            tuple(sorted(complete_sites)),
        ).fetchall()
    finally:
        conn.close()
    return [str(row[0]) for row in rows if str(row[1]) not in available_keys]


def closed_available_bare_metal_listing_ids(
    db_path: str,
    projections: Iterable[TrustedBareMetalProjection],
) -> list[str]:
    """Return tracked closed listings available in complete generations."""
    available_keys = {
        candidate["derivation_key"]
        for candidate in bare_metal_listing_candidates(projections)
    }
    if not available_keys:
        return []
    conn = _read_connection(db_path)
    try:
        placeholders = ", ".join("?" for _ in available_keys)
        rows = conn.execute(
            f"""
            SELECT d.listing_id
            FROM derived_bare_metal_listings d
            LEFT JOIN listings l ON l.listing_id = d.listing_id
            WHERE d.derivation_key IN ({placeholders})
              AND (d.status != 'open' OR l.status != 'open')
            ORDER BY d.site_id, d.physical_resource_id
            """,
            tuple(sorted(available_keys)),
        ).fetchall()
    finally:
        conn.close()
    return [str(row[0]) for row in rows]


def load_derived_bare_metal_listing(
    db_path: str,
    *,
    derivation_key: str,
) -> dict[str, Any] | None:
    conn = _read_connection(db_path)
    try:
        row = conn.execute(
            """
            SELECT d.listing_id, d.site_id, d.physical_resource_id,
                   d.host_id, d.physical_host_id, d.status,
                   d.derivation_key, l.status AS listing_status
            FROM derived_bare_metal_listings d
            LEFT JOIN listings l ON l.listing_id = d.listing_id
            WHERE d.derivation_key = ?
            LIMIT 1
            """,
            (derivation_key,),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    keys = [
        "listing_id",
        "site_id",
        "physical_resource_id",
        "host_id",
        "physical_host_id",
        "status",
        "derivation_key",
        "listing_status",
    ]
    return dict(zip(keys, row))


def record_derived_bare_metal_listing(
    db_path: str,
    *,
    listing_id: str,
    candidate: dict[str, Any],
    status: str = "open",
) -> None:
    listing = BareMetalListing.model_validate(candidate["listing"])
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            INSERT INTO derived_bare_metal_listings(
              listing_id, site_id, physical_resource_id, host_id,
              physical_host_id, status, derivation_key, last_reconciled_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now'))
            ON CONFLICT(derivation_key) DO UPDATE SET
              listing_id=excluded.listing_id,
              site_id=excluded.site_id,
              physical_resource_id=excluded.physical_resource_id,
              host_id=excluded.host_id,
              physical_host_id=excluded.physical_host_id,
              status=excluded.status,
              last_reconciled_at=excluded.last_reconciled_at
            """,
            (
                listing_id,
                str(candidate["site_id"]),
                str(candidate["physical_resource_id"]),
                listing.host_id,
                listing.physical_host_id,
                status,
                str(candidate["derivation_key"]),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def mark_derived_bare_metal_listings_closed(
    db_path: str,
    listing_ids: list[str],
) -> None:
    """Record reconciliation closes; a seller's close is never made here."""
    if not listing_ids:
        return
    conn = sqlite3.connect(db_path)
    try:
        placeholders = ", ".join("?" for _ in listing_ids)
        conn.execute(
            f"""
            UPDATE derived_bare_metal_listings
            SET status = 'closed',
                last_reconciled_at = STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now')
            WHERE listing_id IN ({placeholders})
            """,
            tuple(listing_ids),
        )
        conn.execute(
            f"""
            UPDATE listings
            SET status = 'closed',
                closed_by = 'reconciliation',
                updated_at = STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now')
            WHERE listing_id IN ({placeholders})
            """,
            tuple(listing_ids),
        )
        conn.commit()
    finally:
        conn.close()


# A bare-metal listing's identity is the Physical Resource it offers. Every
# other published field is a term of sale, refreshed in place.
_IDENTITY_FIELDS = (
    "kind",
    "offering_mode",
    "host_id",
    "physical_host_id",
    "capabilities",
    "site",
)
_TERM_RESOURCE_FIELDS = ("access_methods", "min_duration_seconds", "max_duration_seconds")
_TERM_LISTING_FIELDS = (
    "accepted_escrows",
    "settlement_options",
    "demands",
    "max_duration_seconds",
)


def _stored_listing(db_path: str, listing_id: str) -> dict[str, Any] | None:
    conn = _read_connection(db_path)
    try:
        row = conn.execute(
            """
            SELECT listing_resource, accepted_escrows, settlement_options, demands,
                   max_duration_seconds
            FROM listings WHERE listing_id = ?
            """,
            (listing_id,),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None

    def _json(value: Any, default: Any) -> Any:
        try:
            return json.loads(value) if value else default
        except (TypeError, json.JSONDecodeError):
            return default

    return {
        "listing_resource": _json(row[0], {}),
        "accepted_escrows": _json(row[1], []),
        "settlement_options": _json(row[2], []),
        "demands": _json(row[3], []),
        "max_duration_seconds": row[4],
    }


def _identity_differences(
    stored_resource: dict[str, Any], fresh_resource: dict[str, Any]
) -> list[str]:
    # A field the stored listing does not publish is no commitment.
    return [
        name
        for name in _IDENTITY_FIELDS
        if stored_resource.get(name) is not None
        and stored_resource.get(name) != fresh_resource.get(name)
    ]


def reopen_derived_bare_metal_listing_if_present(
    *,
    db_path: str,
    base_url: str,
    candidate: dict[str, Any],
    listing_resource: dict[str, Any],
    accepted_escrows: list[dict[str, Any]],
    demands: list[dict[str, Any]],
    max_duration_seconds: int | None,
    publish_existing_listing: Any,
    close_listing: Any,
    settlement_options: list[dict[str, Any]] | None = None,
    publication_clauses: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    """Reconcile the listing already tracked under the candidate's key.

    An open listing whose terms changed is refreshed in place; one whose
    published identity no longer matches its Physical Resource is closed and
    not reopened while the difference persists; a closed one is reopened with
    the fresh payload unless its identity diverged. ``None`` means no listing is
    tracked under this key yet.
    """
    derived = load_derived_bare_metal_listing(
        db_path,
        derivation_key=str(candidate["derivation_key"]),
    )
    if not derived or not derived.get("listing_id"):
        return None
    listing_id = str(derived["listing_id"])
    stored = _stored_listing(db_path, listing_id) or {}
    stored_resource = stored.get("listing_resource") or {}
    diverged = _identity_differences(stored_resource, listing_resource)
    is_open = derived.get("listing_status") == "open"
    if diverged:
        logger.warning(
            "bare-metal listing %s no longer matches its Physical Resource in %s; %s",
            listing_id,
            diverged,
            "closing it" if is_open else "not reopening it",
        )
        if is_open:
            close_listing(base_url, listing_id)
            mark_derived_bare_metal_listings_closed(db_path, [listing_id])
        return {"status": "unchanged", "listing_id": listing_id}

    fresh_terms = {
        "accepted_escrows": accepted_escrows,
        "settlement_options": settlement_options or [],
        "demands": demands,
        "max_duration_seconds": max_duration_seconds,
    }
    if is_open and all(
        stored_resource.get(name) == listing_resource.get(name)
        for name in _TERM_RESOURCE_FIELDS
    ) and all(
        stored.get(name) == fresh_terms[name] for name in _TERM_LISTING_FIELDS
    ) and stored_resource.get("capacity_backing") == listing_resource.get(
        "capacity_backing"
    ):
        return {"status": "unchanged", "listing_id": listing_id}

    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            UPDATE listings
            SET status = 'open', closed_by = NULL, paused = 0,
                updated_at = STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now'),
                listing_resource = ?, accepted_escrows = ?,
                settlement_options = ?, publication_clauses = ?, demands = ?,
                max_duration_seconds = ?, storefront_url = ?
            WHERE listing_id = ?
            """,
            (
                json.dumps(listing_resource),
                json.dumps(accepted_escrows),
                json.dumps(settlement_options or []),
                json.dumps(publication_clauses or []),
                json.dumps(demands),
                max_duration_seconds,
                base_url,
                listing_id,
            ),
        )
        conn.commit()
    finally:
        conn.close()

    record_derived_bare_metal_listing(
        db_path,
        listing_id=listing_id,
        candidate=candidate,
        status="open",
    )
    return publish_existing_listing(
        listing_id=listing_id,
        listing_resource=listing_resource,
        accepted_escrows=accepted_escrows,
        settlement_options=settlement_options or [],
        publication_clauses=publication_clauses or [],
        demands=demands,
        max_duration_seconds=max_duration_seconds,
        storefront_url=base_url,
    )


def close_stale_bare_metal_listings(
    *,
    db_path: str,
    projections: Iterable[TrustedBareMetalProjection],
    close_listing: Any,
) -> list[str]:
    """Close stale listings and mark their tracking rows closed."""
    closed_listing_ids: list[str] = []
    for listing_id in stale_open_bare_metal_listing_ids(db_path, projections):
        response = close_listing(listing_id)
        if str(response.get("status", "?")) in ("closed", "skipped", "queued"):
            closed_listing_ids.append(listing_id)
    mark_derived_bare_metal_listings_closed(db_path, closed_listing_ids)
    return closed_listing_ids


def _read_connection(db_path: str) -> sqlite3.Connection:
    return sqlite3.connect(
        f"file:{db_path}?mode=ro&nolock=1",
        uri=True,
        timeout=5,
    )
