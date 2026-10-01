"""Storefront pool overrides for the ``bare_metal`` offering mode.

The pool-override kit stores, checks, and reports overrides for any market. For
bare metal an override may state settlement clauses, lease-duration bounds, and
asking rates. It states no shapes: a whole machine has no shape to choose, so a
record stating ``listing_shapes`` is refused. Region and capacity backing remain
the site's. An override's clauses replace the configured publication clauses for
that pool as a whole, and its bounds replace the configured bounds.

Bare-metal publication runs in the server's administrator step or in the
one-shot publication command, and either may be the last thing to read a site.
Every run therefore records, per site whose generation it accepted, the pools
that generation projected. Override status is judged against that durable
record, so it survives restarts and command-line runs; a site with no record is
``unknown``. See openspec/specs/storefront-publication/spec.md.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from market_pool_overrides import (
    PoolOverrideRecord,
    ShapeFeasibility,
    read_pool_overrides,
)
from market_settlement_runtime import SettlementPublicationClause
from pydantic import BaseModel, ConfigDict, Field, StrictInt, ValidationError, model_validator

from arkhai_bare_metal import BARE_METAL_OFFERING_MODE

from .migrations import ACCEPTED_GENERATIONS_TABLE
from .site_reading import resolve_bare_metal_asking_rates


class BareMetalPoolOverrideTerms(BaseModel):
    """What a bare-metal override may say about a pool's lease bounds."""

    model_config = ConfigDict(extra="forbid")

    min_duration_seconds: StrictInt | None = Field(default=None, gt=0)
    max_duration_seconds: StrictInt | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def _ordered(self) -> "BareMetalPoolOverrideTerms":
        low, high = self.min_duration_seconds, self.max_duration_seconds
        if low is not None and high is not None and low > high:
            raise ValueError("min_duration_seconds must not exceed max_duration_seconds")
        return self


def compile_publication_clauses(
    values: Sequence[Mapping[str, Any]],
) -> tuple[SettlementPublicationClause, ...]:
    """Validate clauses as configured publication clauses are validated."""
    return tuple(SettlementPublicationClause.model_validate(value) for value in values)


def _record_problems(
    *,
    listing_shapes: Any,
    settlements: Any,
    asking_rates: Any,
    terms: Any,
) -> list[str]:
    problems: list[str] = []
    if listing_shapes is not None:
        problems.append(
            "listing_shapes: a bare-metal listing's shape is its machine's "
            "declaration, so an override states none"
        )
    try:
        BareMetalPoolOverrideTerms.model_validate(terms or {})
    except ValidationError as exc:
        problems.extend(
            f"terms.{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
            if error["loc"]
            else f"terms: {error['msg']}"
            for error in exc.errors()
        )
    if settlements is not None:
        try:
            compile_publication_clauses(settlements)
        except (TypeError, ValueError) as exc:
            problems.append(f"settlements do not compile: {exc}")
    if asking_rates is not None:
        rates = resolve_bare_metal_asking_rates({}, override_rates=asking_rates)
        problems.extend(f"asking_rates{problem}" for problem in rates.problems)
    return problems


class BareMetalPoolOverrideContribution:
    """Pool overrides for the ``bare_metal`` offering mode."""

    offering_mode = BARE_METAL_OFFERING_MODE

    def vocabulary_problems(self, record: PoolOverrideRecord) -> Sequence[str]:
        # Judged by the same function publication reads a stored override with,
        # so a write accepted here is one publication can read.
        return _record_problems(
            listing_shapes=record.listing_shapes,
            settlements=None,
            asking_rates=record.asking_rates,
            terms=record.terms,
        )

    def judge_shapes(
        self,
        site_pools: Sequence[Mapping[str, Any]],
        *,
        record: PoolOverrideRecord,
    ) -> Sequence[ShapeFeasibility]:
        return []


@dataclass(frozen=True)
class BareMetalPoolOverride:
    """One stored override as bare-metal publication reads it.

    ``problems`` is non-empty when the stored override cannot be read; such an
    override holds its pool rather than letting configuration speak for it.
    """

    clauses: tuple[SettlementPublicationClause, ...] | None = None
    min_duration_seconds: int | None = None
    max_duration_seconds: int | None = None
    asking_rates: Any = None
    problems: tuple[str, ...] = ()


def read_bare_metal_pool_overrides(
    db_path: str,
) -> dict[tuple[str, str], BareMetalPoolOverride]:
    """Every stored bare-metal override, keyed by ``(site_id, pool_id)``."""
    conn = sqlite3.connect(db_path)
    try:
        stored = read_pool_overrides(conn, offering_mode=BARE_METAL_OFFERING_MODE)
    finally:
        conn.close()
    overrides: dict[tuple[str, str], BareMetalPoolOverride] = {}
    for item in stored:
        problems = list(item.problems) or _record_problems(
            listing_shapes=item.listing_shapes,
            settlements=item.settlements,
            asking_rates=item.asking_rates,
            terms=item.terms,
        )
        key = (item.site_id, item.pool_id)
        if problems:
            overrides[key] = BareMetalPoolOverride(problems=tuple(problems))
            continue
        terms = BareMetalPoolOverrideTerms.model_validate(item.terms or {})
        overrides[key] = BareMetalPoolOverride(
            clauses=(
                compile_publication_clauses(item.settlements)
                if item.settlements is not None
                else None
            ),
            min_duration_seconds=terms.min_duration_seconds,
            max_duration_seconds=terms.max_duration_seconds,
            asking_rates=item.asking_rates,
        )
    return overrides


def record_accepted_generation(
    db_path: str,
    *,
    site_id: str,
    revision: int,
    digest: str,
    pool_ids: Sequence[str],
) -> None:
    """Record the latest site generation a publication run accepted."""
    conn = sqlite3.connect(db_path)
    try:
        with conn:
            conn.execute(
                f"INSERT INTO {ACCEPTED_GENERATIONS_TABLE} "
                "(site_id, revision, digest, pool_ids) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(site_id) DO UPDATE SET revision = excluded.revision, "
                "digest = excluded.digest, pool_ids = excluded.pool_ids, "
                "accepted_at = STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now')",
                (site_id, revision, digest, json.dumps(sorted(set(pool_ids)))),
            )
    finally:
        conn.close()


def accepted_site_projection(db_path: str) -> dict[str, list[dict[str, str]]]:
    """Each site's last accepted pools, in the shape override status reads.

    A site with no record is absent, so its overrides are ``unknown`` rather than
    judged against pools nobody has read.
    """
    conn = sqlite3.connect(db_path)
    try:
        exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (ACCEPTED_GENERATIONS_TABLE,),
        ).fetchone()
        if exists is None:
            return {}
        rows = conn.execute(
            f"SELECT site_id, pool_ids FROM {ACCEPTED_GENERATIONS_TABLE}"
        ).fetchall()
    finally:
        conn.close()
    return {
        str(site_id): [{"pool_id": str(pool_id)} for pool_id in json.loads(pool_ids)]
        for site_id, pool_ids in rows
    }


__all__ = [
    "ACCEPTED_GENERATIONS_TABLE",
    "BareMetalPoolOverride",
    "BareMetalPoolOverrideContribution",
    "BareMetalPoolOverrideTerms",
    "accepted_site_projection",
    "compile_publication_clauses",
    "read_bare_metal_pool_overrides",
    "record_accepted_generation",
]
