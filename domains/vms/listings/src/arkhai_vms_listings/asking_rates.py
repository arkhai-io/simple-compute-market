"""The VM market's binding of the shared asking-rate resolution.

A rate is keyed by the digest VM listing identity uses, so an entry prices
exactly the listing whose shape it names. That digest is taken over a listing's
base shape, so an entry names a plain shape, and changing a listing's
constraints never moves its rate to another listing. The override's write-time judgement
and publication both resolve through this one function, so a write the
storefront accepts is one publication can read.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from arkhai_vms import vm_shape_digest, vm_shape_problems

VM_OFFERING_MODE = "vm"


def resolve_vm_asking_rates(
    policy_tags: Mapping[str, Any], *, override_rates: Any = None
) -> Any:
    """A pool's VM asking rates by shape digest: the override's, else the
    pool's, else none. Returns the kit's ``AskingRateResolution``."""
    # Local import: buyers install this package without the resource-pool kit,
    # and only storefront derivation and administration resolve rates.
    from market_resource_pools import resolve_asking_rates

    return resolve_asking_rates(
        policy_tags,
        VM_OFFERING_MODE,
        override_rates=override_rates,
        shape_digest=vm_shape_digest,
        shape_problems=vm_shape_problems,
    )


__all__ = ["resolve_vm_asking_rates"]
