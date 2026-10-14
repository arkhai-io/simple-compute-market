"""Pool declaration tag names, problem codes, and the problem record.

Shared by the declaration resolver in :mod:`.hints` and the backing delegate in
:mod:`.backing`, which judges the cross-declaration rules the resolver reports,
so neither module needs the other's internals.
"""

from __future__ import annotations

from dataclasses import dataclass

DELIVERABLE_MODES_POLICY_TAG = "deliverable_modes"
ADVERTISABLE_MODES_POLICY_TAG = "advertisable_modes"
CAPACITY_BACKING_POLICY_TAG = "capacity_backing"

# Structured problem codes shared by the pool models, document validation,
# stored-state checks, and the projection resolver.
MISSING_DECLARATION = "missing_declaration"
INVALID_DELIVERABLE_MODES = "invalid_deliverable_modes"
INVALID_ADVERTISABLE_MODES = "invalid_advertisable_modes"
INVALID_CAPACITY_BACKING = "invalid_capacity_backing"
ADVERTISABLE_EXCEEDS_DELIVERABLE = "advertisable_exceeds_deliverable"
UNBACKED_POOL_DELIVERS = "unbacked_pool_delivers"


@dataclass(frozen=True)
class PoolDeclarationProblem:
    """One reason a pool's advertisement or backing declaration is invalid."""

    tag: str
    code: str
    message: str
