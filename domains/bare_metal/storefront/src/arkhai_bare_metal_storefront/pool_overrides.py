"""Storefront pool overrides for the ``bare_metal`` offering mode.

The pool-override kit stores, checks, and reports overrides for any market. For
bare metal an override may state settlement clauses, lease-duration bounds, and
asking rates. It states no shapes: a whole machine has no shape to choose, so a
record stating ``listing_shapes`` is refused. Region and capacity backing remain
the site's. An override's clauses replace the configured publication clauses for
that pool as a whole, and each bound replaces its configured counterpart, as
configuration overlays do. The effective pair must still be ordered: a minimum
above the effective maximum is refused at the write and holds the pool at
publication, since configuration can change after the write.

Override status is judged against the resource-pool projection the storefront
holds for the override's site, the generation publication reads; a site whose
projection is not held, including just after a restart, is ``unknown``. No
projection generation is persisted for the purpose. See
openspec/specs/storefront-publication/spec.md, "Bare metal joins the
site-scoped pool-override store".
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Mapping, Sequence
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


def positive_lease_bound(seconds: int | None) -> int | None:
    """A maximum lease duration that bounds a listing, or None for one that cannot.

    ``[pricing].default_max_duration_seconds`` may be absent, zero, or negative;
    none of those bounds a lease, so a pool relying on it publishes nothing.
    """
    return seconds if seconds is not None and seconds > 0 else None


def effective_duration_problems(
    terms: BareMetalPoolOverrideTerms, configured_max: int | None
) -> list[str]:
    """Problems with the bounds a listing would publish under ``terms``.

    Each override bound replaces its configured counterpart; the pair that
    results must be ordered. Configuration states no minimum, so the only
    combination across tiers is an override minimum with the configured
    maximum.
    """
    effective_max = (
        terms.max_duration_seconds if terms.max_duration_seconds is not None else configured_max
    )
    low = terms.min_duration_seconds
    if low is not None and effective_max is not None and low > effective_max:
        return [
            f"terms.min_duration_seconds {low} exceeds the effective maximum "
            f"{effective_max} (the configured maximum, which this override does not replace)"
            if terms.max_duration_seconds is None
            else f"terms.min_duration_seconds {low} exceeds max_duration_seconds {effective_max}"
        ]
    return []


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
        BareMetalPoolOverrideTerms.model_validate({} if terms is None else terms)
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
    """Pool overrides for the ``bare_metal`` offering mode.

    ``configured_max_duration_seconds`` reads the storefront's current lease
    maximum when a record is judged, so the effective bounds are checked
    against the configuration publication would combine them with.
    """

    offering_mode = BARE_METAL_OFFERING_MODE

    def __init__(
        self, *, configured_max_duration_seconds: Callable[[], int | None] = lambda: None
    ) -> None:
        self._configured_max = configured_max_duration_seconds

    def vocabulary_problems(self, record: PoolOverrideRecord) -> Sequence[str]:
        # Judged by the same function publication reads a stored override with,
        # so a write accepted here is one publication can read.
        problems = _record_problems(
            listing_shapes=record.listing_shapes,
            settlements=None,
            asking_rates=record.asking_rates,
            terms=record.terms,
        )
        if problems:
            return problems
        terms = BareMetalPoolOverrideTerms.model_validate(record.terms or {})
        return effective_duration_problems(terms, self._configured_max())

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

    ``problems`` is non-empty when the stored override cannot be read;
    ``term_conflicts`` when it reads but its bounds conflict with current
    configuration. Either holds its pool rather than letting configuration
    speak for it or publishing an unordered pair.
    """

    clauses: tuple[SettlementPublicationClause, ...] | None = None
    min_duration_seconds: int | None = None
    max_duration_seconds: int | None = None
    asking_rates: Any = None
    problems: tuple[str, ...] = ()
    term_conflicts: tuple[str, ...] = ()


def read_bare_metal_pool_overrides(
    db_path: str,
    *,
    configured_max_duration_seconds: int | None = None,
) -> dict[tuple[str, str], BareMetalPoolOverride]:
    """Every stored bare-metal override, keyed by ``(site_id, pool_id)``,
    judged against the configured lease maximum it would combine with."""
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
        terms = BareMetalPoolOverrideTerms.model_validate(
            {} if item.terms is None else item.terms
        )
        conflicts = effective_duration_problems(terms, configured_max_duration_seconds)
        if conflicts:
            overrides[key] = BareMetalPoolOverride(term_conflicts=tuple(conflicts))
            continue
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


__all__ = [
    "BareMetalPoolOverride",
    "BareMetalPoolOverrideContribution",
    "BareMetalPoolOverrideTerms",
    "compile_publication_clauses",
    "effective_duration_problems",
    "positive_lease_bound",
    "read_bare_metal_pool_overrides",
]
