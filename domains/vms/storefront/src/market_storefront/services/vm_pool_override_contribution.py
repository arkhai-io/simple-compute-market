"""The VM market's contribution to storefront pool overrides.

The pool-override kit stores and checks overrides for any market; for the VM
offering mode this supplies the two judgements only the VM market can make.
Terms are validated by ``VmPoolOverrideTerms`` and shapes by the VM capability
vocabulary. Feasibility is judged by the derivation VM publication runs, on
declared capacity, with the new record in place of the stored one, so a write's
report and the next publication cycle cannot disagree.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from arkhai_vms import canonical_vm_shape, vm_shape_digest, vm_shape_problems
from domains.vms.listings import (
    ShapeFeasibility as ShapeFeasibilityJudge,
    declared_shape_feasibility,
    vm_override_view,
)
from market_pool_overrides import PoolOverrideRecord, ShapeFeasibility
from pydantic import ValidationError

from market_storefront.models.pool_override_models import VmPoolOverrideTerms

VM_OFFERING_MODE = "vm"


class VmPoolOverrideContribution:
    """Pool overrides for the ``vm`` offering mode."""

    offering_mode = VM_OFFERING_MODE

    def __init__(self, *, db_path: str, shape_feasible: ShapeFeasibilityJudge) -> None:
        self._db_path = db_path
        self._shape_feasible = shape_feasible

    def vocabulary_problems(self, record: PoolOverrideRecord) -> Sequence[str]:
        problems: list[str] = []
        try:
            VmPoolOverrideTerms.model_validate(record.terms or {})
        except ValidationError as exc:
            problems.extend(
                f"terms.{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
                for error in exc.errors()
            )
        for index, shape in enumerate(record.listing_shapes or ()):
            problems.extend(
                f"listing_shapes[{index}] {problem}" for problem in vm_shape_problems(shape)
            )
        return problems

    def judge_shapes(
        self,
        site_pools: Sequence[Mapping[str, Any]],
        *,
        record: PoolOverrideRecord,
        home_site: str,
    ) -> Sequence[ShapeFeasibility]:
        shapes = record.listing_shapes or ()
        if not shapes:
            return []
        feasible = declared_shape_feasibility(
            self._db_path,
            list(site_pools),
            site_id=record.site_id,
            pool_id=record.pool_id,
            home_site=home_site,
            override=vm_override_view(
                listing_shapes=record.listing_shapes,
                settlements=record.settlements,
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


__all__ = ["VM_OFFERING_MODE", "VmPoolOverrideContribution"]
