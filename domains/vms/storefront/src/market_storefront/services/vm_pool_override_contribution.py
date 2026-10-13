"""The VM market's contribution to storefront pool overrides.

The pool-override kit stores and checks overrides for any market; for the VM
offering mode this supplies the two judgements only the VM market can make.
Terms are validated by ``VmPoolOverrideTerms``, and asking rates by the VM
capability vocabulary. Shapes are split and resolved through the admissibility
kit as publication resolves them, over the storefront's configured default: an
override's shapes never merge with the pool's hint, so whether publication can
compute each listing's policy, and whether it admits each offer, is known
before any site is called. A write publication would close a listing for is
refused rather than stored. Feasibility is judged by the derivation VM
publication runs, on declared capacity, with the new record in place of the
stored one, so a write's report and the next publication cycle cannot disagree.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any

from arkhai_vms import VM_CAPABILITY_SCHEMA, canonical_vm_shape, vm_shape_digest
from arkhai_vms_listings import (
    SHAPE_SOURCE_OVERRIDE,
    ShapeFeasibility as ShapeFeasibilityJudge,
    declared_shape_feasibility,
    resolve_vm_asking_rates,
    vm_override_view,
)
from market_capability_admissibility import (
    AdmissibilityProblem,
    Declaration,
    ShapeListSplit,
    resolve,
    split_listing_shapes,
)
from market_pool_overrides import PoolOverrideRecord, ShapeFeasibility
from pydantic import ValidationError

from market_storefront.models.pool_override_models import VmPoolOverrideTerms

VM_OFFERING_MODE = "vm"


class VmPoolOverrideContribution:
    """Pool overrides for the ``vm`` offering mode."""

    offering_mode = VM_OFFERING_MODE

    def __init__(
        self,
        *,
        db_path: str,
        shape_feasible: ShapeFeasibilityJudge,
        home_site: Callable[[], str | None],
        admissibility_default: Declaration | None,
    ) -> None:
        # The home site is the VM storefront's own notion: its legacy override
        # rows apply only there. It is resolved when a record is judged, from the
        # storefront's configured sites.
        self._db_path = db_path
        self._shape_feasible = shape_feasible
        self._home_site = home_site
        self._admissibility_default = admissibility_default

    def vocabulary_problems(self, record: PoolOverrideRecord) -> Sequence[str]:
        problems: list[str] = []
        try:
            VmPoolOverrideTerms.model_validate(record.terms or {})
        except ValidationError as exc:
            problems.extend(
                f"terms.{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
                for error in exc.errors()
            )
        if record.listing_shapes is not None:
            problems.extend(self._shape_problems(record.listing_shapes))
        if record.asking_rates is not None:
            # The resolution publication runs, so a write accepted here is one
            # publication can read rather than one that later holds the pool.
            rates = resolve_vm_asking_rates({}, override_rates=record.asking_rates)
            problems.extend(f"asking_rates{problem}" for problem in rates.problems)
        return problems

    def _shape_problems(self, listing_shapes: Sequence[Any]) -> list[str]:
        """Every reason publication could not publish one of these shapes.

        An unreadable base shape, unreadable constraints, a base shape stated
        twice with different constraints, a range that merges empty against the
        configured default, and an offer outside the resolved range.
        """
        splits = _split(listing_shapes).shapes
        problems = [
            _located(problem, entry.entries) for entry in splits for problem in entry.problems
        ]
        tiers = [] if self._admissibility_default is None else [self._admissibility_default]
        for entry in splits:
            if entry.declaration is None or entry.base_shape is None:
                continue
            resolution = resolve([entry.declaration, *tiers], VM_CAPABILITY_SCHEMA)
            if resolution.policy is None:
                problems.extend(_located(problem, entry.entries) for problem in resolution.problems)
                continue
            problems.extend(
                f"{_located(problem, entry.entries)} (bound set by {problem.tier})"
                for problem in resolution.policy.admissibility_problems(entry.base_shape)
            )
        return problems

    def judge_shapes(
        self,
        site_pools: Sequence[Mapping[str, Any]],
        *,
        record: PoolOverrideRecord,
    ) -> Sequence[ShapeFeasibility]:
        if not record.listing_shapes:
            return []
        # The write check has refused any list whose base shapes cannot be read.
        shapes = [
            entry.base_shape
            for entry in _split(record.listing_shapes).shapes
            if entry.base_shape is not None
        ]
        feasible = declared_shape_feasibility(
            self._db_path,
            list(site_pools),
            site_id=record.site_id,
            pool_id=record.pool_id,
            home_site=self._home_site() or "",
            override=vm_override_view(
                listing_shapes=record.listing_shapes,
                settlements=record.settlements,
                asking_rates=record.asking_rates,
                terms=record.terms,
            ),
            shape_feasible=self._shape_feasible,
        )
        return [
            ShapeFeasibility(
                shape_digest=vm_shape_digest(shape),
                shape=canonical_vm_shape(shape),
                feasible=feasible.get(vm_shape_digest(shape), False),
            )
            for shape in shapes
        ]


def _split(listing_shapes: Sequence[Any]) -> ShapeListSplit:
    return split_listing_shapes(
        list(listing_shapes), tier=SHAPE_SOURCE_OVERRIDE, schema=VM_CAPABILITY_SCHEMA
    )


def _located(problem: AdmissibilityProblem, entries: tuple[int, ...]) -> str:
    """A problem prefixed by the list positions it concerns."""
    positions = problem.entries or entries
    return f"listing_shapes[{', '.join(str(index) for index in positions)}] {problem}"


__all__ = ["VM_OFFERING_MODE", "VmPoolOverrideContribution"]
