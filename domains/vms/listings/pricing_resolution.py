"""VM-domain three-tier resolution of per-GPU-model pricing.

`kit/resource-pools.hints.raw_pricing` owns the domain-neutral `pricing`
key and its bare read; this module owns the VM domain's family-grouped
shape (`{"gpu": {"<model>": {...}}}`, mirroring the `structured-capacity-
requirements` change's own family-grouped requirement shape -- see
`openspec/changes/pools-8-capacity-projection-and-listing-hints/design.md`,
"Region, SLA, and pricing move to resource-pool hints too") and how it
resolves against the storefront's own configured/overridden values.

Three tiers, highest to lowest precedence, resolved independently per
field (`min_price`, `token`, `max_duration_seconds`, `accepted_escrows`)
so a storefront override that only sets one field doesn't block the
others from falling through to a lower tier:

1. A per-pool storefront override (`compute_capacity_pools`' commercial
   columns, until POOLS-8's own follow-up change retires that table).
2. A resource-pool-declared pricing hint, keyed by GPU model.
3. The storefront's own `[pricing]` config default for that model, or
   the flat `default_min_price`/`default_token_address`/... if no
   per-model default is configured -- the fallback-of-last-resort that
   existed before this mechanism did.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from market_resource_pools.hints import raw_pricing

GPU_FAMILY_KEY = "gpu"

_FIELD_NAMES = ("min_price", "token", "max_duration_seconds", "accepted_escrows")


@dataclass(frozen=True)
class GpuPricingFields:
    """One tier's contribution to a GPU model's resolved pricing.
    ``None`` on any field means "this tier has no opinion," not "the
    field is empty" -- resolution falls through to the next tier for
    that field alone.
    """

    min_price: Any = None
    token: Any = None
    max_duration_seconds: Any = None
    accepted_escrows: Any = None


def resolve_gpu_pricing(
    policy_tags: Mapping[str, Any],
    *,
    gpu_model: str | None,
    storefront_override: GpuPricingFields,
    config_defaults_by_model: Mapping[str, GpuPricingFields],
    flat_default: GpuPricingFields,
) -> GpuPricingFields:
    """Resolve one GPU model's pricing through the three-tier chain.

    Each of the four fields is resolved independently: storefront
    override (if set) wins outright; otherwise the pool's own pricing
    hint for this model (if the hint declares that field); otherwise the
    storefront's per-model config default (if one is configured for this
    model); otherwise the storefront's flat config default. A field left
    unset all the way through every tier stays ``None`` -- callers
    already treat a ``None`` price as "priceless," matching every other
    publish flow's existing handling, not a new failure mode this
    resolver invents.
    """
    hint_fields = _hint_fields_for_model(policy_tags, gpu_model)
    config_fields = (
        config_defaults_by_model.get(gpu_model) if gpu_model else None
    )

    def _resolve(field: str) -> Any:
        override_value = getattr(storefront_override, field)
        if override_value is not None:
            return override_value
        if hint_fields is not None:
            hint_value = hint_fields.get(field)
            if hint_value is not None:
                return hint_value
        if config_fields is not None:
            config_value = getattr(config_fields, field)
            if config_value is not None:
                return config_value
        return getattr(flat_default, field)

    return GpuPricingFields(**{field: _resolve(field) for field in _FIELD_NAMES})


def _hint_fields_for_model(
    policy_tags: Mapping[str, Any], gpu_model: str | None,
) -> Mapping[str, Any] | None:
    if not gpu_model:
        return None
    pricing = raw_pricing(policy_tags)
    if not isinstance(pricing, Mapping):
        return None
    gpu_family = pricing.get(GPU_FAMILY_KEY)
    if not isinstance(gpu_family, Mapping):
        return None
    model_fields = gpu_family.get(gpu_model)
    if not isinstance(model_fields, Mapping):
        return None
    return model_fields
