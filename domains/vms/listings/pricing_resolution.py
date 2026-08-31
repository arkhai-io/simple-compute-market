"""VM-domain three-tier resolution of per-GPU-model pricing.

`kit/resource-pools.hints.raw_pricing` owns the domain-neutral `pricing`
key and its bare read; this module owns the VM domain's family-grouped
shape (`{"gpu": {"<model>": {...}}}`) and how it resolves against the
storefront's own configured/overridden values.

Three tiers, highest to lowest precedence, resolved independently per
field (`min_price`, `token`, `max_duration_seconds`, `accepted_escrows`)
so a storefront override that only sets one field doesn't block the
others from falling through to a lower tier:

1. A per-pool storefront override (`compute_capacity_pools`' commercial
   columns -- the storefront's own local, per-pool pricing record).
2. A resource-pool-declared pricing hint, keyed by GPU model.
3. The storefront's own `[pricing]` config default for that model, or
   the flat `default_min_price`/`default_token_address`/... if no
   per-model default is configured -- the fallback-of-last-resort that
   existed before this mechanism did.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

GPU_FAMILY_KEY = "gpu"

_FIELD_NAMES = (
    "min_price",
    "token",
    "max_duration_seconds",
    "accepted_escrows",
    "settlements",
)


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
    settlements: Any = None


def resolve_gpu_pricing(
    policy_tags: Mapping[str, Any],
    *,
    gpu_model: str | None,
    storefront_override: GpuPricingFields,
    config_defaults_by_model: Mapping[str, GpuPricingFields],
    flat_default: GpuPricingFields,
) -> GpuPricingFields:
    """Resolve one GPU model's pricing through the three-tier chain.

    Each field is resolved independently: storefront
    override (if set) wins outright; otherwise the pool's own pricing
    hint for this model (if the hint declares that field *and* it has a
    valid shape for that field -- see `_VALID_HINT_FIELD`, below);
    otherwise the storefront's per-model config default (if one is
    configured for this model); otherwise the storefront's flat config
    default. A field left unset all the way through every tier stays
    ``None`` -- callers already treat a ``None`` price as "priceless,"
    matching every other publish flow's existing handling, not a new
    failure mode this resolver invents.
    """
    hint_fields = _hint_fields_for_model(policy_tags, gpu_model)
    config_fields = config_defaults_by_model.get(gpu_model) if gpu_model else None

    def _resolve(field: str) -> Any:
        override_value = getattr(storefront_override, field)
        if override_value is not None:
            return override_value
        if hint_fields is not None:
            hint_value = hint_fields.get(field)
            # A hint field with the wrong shape (e.g. a dict where a
            # price string is expected) is treated the same as an
            # absent one -- this domain, not `kit/resource-pools`, owns
            # validating the shape it accepts (see this module's own
            # docstring); silently propagating a malformed value into a
            # commercial candidate is worse than falling through to a
            # lower tier the same way a missing value already does.
            if hint_value is not None and _VALID_HINT_FIELD[field](hint_value):
                return hint_value
        if config_fields is not None:
            config_value = getattr(config_fields, field)
            if config_value is not None:
                return config_value
        return getattr(flat_default, field)

    return GpuPricingFields(**{field: _resolve(field) for field in _FIELD_NAMES})


def _is_nonnegative_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


_VALID_HINT_FIELD: Mapping[str, Any] = {
    "min_price": lambda v: isinstance(v, str),
    "token": lambda v: isinstance(v, str),
    "max_duration_seconds": _is_nonnegative_int,
    "accepted_escrows": lambda v: isinstance(v, list),
    "settlements": lambda v: isinstance(v, list),
}


def _hint_fields_for_model(
    policy_tags: Mapping[str, Any],
    gpu_model: str | None,
) -> Mapping[str, Any] | None:
    if not gpu_model:
        return None
    # Local import -- see resolve_vm_listing_mode's own comment in
    # domains.vms.listings.listing_mode for the reason (kept out of any
    # consumer that imports this module's signatures without calling it).
    from market_resource_pools.hints import raw_pricing

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
