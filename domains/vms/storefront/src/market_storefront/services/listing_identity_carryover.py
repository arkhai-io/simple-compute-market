"""Carry a seller's close or pause onto the listing that succeeds a pre-shape listing.

A listing's derivation identity includes its shape, and a listing bound before
shapes (``compute.listing_source`` version 1) has none, so reconciliation never
derives its key again: while open it closes as stale, and its equivalent default
shape publishes under a new identity. A seller's close and pause belong to a
listing ID, so on their own they would not reach that successor. This step binds
the successor first, with the seller's state:

- a listing its seller closed gets a successor closed by its seller and never
  published, so publication binds no replacement under that identity;
- an open, paused listing gets a paused successor, withheld from registries
  until the seller resumes it.

Nothing is recorded for a listing reconciliation closed or an open unpaused one;
publication handles those. The step runs before any lifecycle loop, because the
first publication cycle would otherwise publish the successor first. It is
idempotent: a successor already bound under its derivation key is left alone.

See openspec/specs/storefront-publication/spec.md, "A listing's derivation
identity includes its shape".
"""

from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from domains.vms.listings.reconciler import LISTING_SOURCE_KIND, positive_gpu_count
from market_identity import Identity

from market_storefront.publication_binding import prepare_vm_listing_binding

logger = logging.getLogger(__name__)

_PRE_SHAPE_SCHEMA_VERSION = 1


@dataclass
class CarryOverReport:
    """Which pre-shape listings carried seller state, and to which successor."""

    successors: dict[str, str] = field(default_factory=dict)
    not_carried: dict[str, str] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "carried": len(self.successors),
            "successors": dict(sorted(self.successors.items())),
            "not_carried": dict(sorted(self.not_carried.items())),
        }


_LATEST_REPORT = CarryOverReport()


def carryover_report() -> dict[str, Any]:
    """The report of this process's carry-over, for system status."""
    return _LATEST_REPORT.as_dict()


def _pre_shape_listings(db_path: str) -> list[tuple[str, dict[str, Any]]]:
    """Listing IDs and source payloads of every VM listing bound before shapes."""
    conn = sqlite3.connect(f"file:{db_path}?mode=ro&nolock=1", uri=True, timeout=5)
    try:
        rows = conn.execute(
            "SELECT listing_id, source_envelope_json FROM storefront_listing_bindings "
            "WHERE offering_mode = 'vm'"
        ).fetchall()
    finally:
        conn.close()
    out: list[tuple[str, dict[str, Any]]] = []
    for listing_id, raw in rows:
        try:
            envelope = json.loads(raw or "")
        except json.JSONDecodeError:
            continue
        if (
            isinstance(envelope, dict)
            and envelope.get("kind") == LISTING_SOURCE_KIND
            and envelope.get("schema_version") == _PRE_SHAPE_SCHEMA_VERSION
        ):
            out.append((str(listing_id), dict(envelope.get("payload") or {})))
    return out


def _listing_resource(record: dict[str, Any]) -> dict[str, Any]:
    raw = record.get("listing_resource")
    if hasattr(raw, "model_dump"):
        raw = raw.model_dump(mode="json")
    if isinstance(raw, str):
        raw = json.loads(raw)
    return dict(raw or {})


async def carry_over_seller_state(sqlite_client: Any) -> CarryOverReport:
    """Bind a successor carrying each pre-shape listing's seller close or pause."""
    global _LATEST_REPORT
    report = CarryOverReport()
    for listing_id, payload in _pre_shape_listings(sqlite_client.db_path):
        record = await sqlite_client.load_listing(listing_id=listing_id)
        if record is None:
            continue
        seller_closed = record["status"] == "closed" and record.get("closed_by") == "seller"
        paused = record["status"] == "open" and bool(record.get("paused"))
        if not (seller_closed or paused):
            continue
        stored = await sqlite_client.load_listing_binding(listing_id=listing_id)
        listing_resource = _listing_resource(record)
        gpu_count = positive_gpu_count(payload.get("gpu_count"))
        gpu_model = listing_resource.get("gpu_model")
        if stored is None or gpu_count is None or not isinstance(gpu_model, str) or not gpu_model:
            report.not_carried[listing_id] = "no equivalent default shape"
            continue
        successor_id = str(uuid.uuid4())
        binding = prepare_vm_listing_binding(
            listing_id=successor_id,
            candidate={
                "site_id": stored.site_id,
                "pool_id": payload.get("pool_id"),
                "resource_id": payload.get("resource_id"),
                "capacity_backing": stored.capacity_backing,
                "listing_shape": {"gpu": {"count": gpu_count, "model": gpu_model}},
            },
        )
        existing = await sqlite_client.load_listing_binding_by_derivation(
            derivation_key=binding.derivation_key
        )
        if existing is not None:
            report.successors[listing_id] = existing.listing_id
            continue
        now = datetime.now(UTC).isoformat()
        await sqlite_client.upsert_listing_with_binding(
            binding=binding,
            status="closed" if seller_closed else "open",
            closed_by="seller" if seller_closed else None,
            paused=paused,
            created_at=now,
            updated_at=now,
            listing_resource=listing_resource,
            fulfillment_resource=record.get("fulfillment_resource"),
            max_duration_seconds=record.get("max_duration_seconds"),
            storefront_url=record["storefront_url"],
            seller_principal=Identity.model_validate(record["seller_principal"]),
            oracle_address=record.get("oracle_address"),
            accepted_escrows=record.get("accepted_escrows"),
            settlement_options=record.get("settlement_options"),
            publication_clauses=record.get("publication_clauses"),
            demands=record.get("demands"),
        )
        report.successors[listing_id] = successor_id
    _LATEST_REPORT = report
    if report.successors or report.not_carried:
        logger.info(
            "[STARTUP] Carried seller state to %d shape-bearing listing(s); %d not carried",
            len(report.successors),
            len(report.not_carried),
        )
    return report


__all__ = ["CarryOverReport", "carry_over_seller_state", "carryover_report"]
