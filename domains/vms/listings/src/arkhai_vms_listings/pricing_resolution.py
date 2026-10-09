"""VM-domain three-tier resolution of commercial terms.

`kit/resource-pools.hints.raw_pricing` owns the domain-neutral `pricing`
key and its bare read; this module owns the VM domain's family-grouped
form and how it resolves against the storefront's own configured and
overridden values. Two kinds of term resolve here:

- **Per-model listing terms** (`max_duration_seconds`, `accepted_escrows`,
  `settlements`), keyed by GPU model under `pricing.gpu.<model>` and resolved
  independently per field, so a tier that sets one field does not block the
  others from falling through.
- **Family rates**: for each capacity family, a list of rates per unit of the
  family per time unit, one per asset. The GPU family is keyed by model, the
  others are not. Each family resolves independently, and within a family the
  highest tier stating a `rates` list supplies the whole list: merging per asset
  across tiers would price one asset from an override and another from a
  default, a combination nobody stated. An explicitly empty list is a statement,
  so it stops lower tiers from supplying that family. Unlike a malformed listing
  term, an unreadable rate never falls through: a lower tier's rate is a price
  nobody stated for this pool, so the resolution is unreadable and the pool is
  held (see openspec/specs/storefront-publication/spec.md, "An unreadable family
  rate holds its pool").

Three tiers, highest to lowest precedence:

1. The storefront's own per-pool override: the site-scoped override store
   (and, for per-model listing terms only, the legacy home-site
   `compute_capacity_pools` row), merged before this resolver sees it.
2. A resource-pool-declared pricing hint.
3. The storefront's own `[pricing]` configuration default.

A listing for which any family resolves a non-empty rate list is shape-priced; see
openspec/specs/storefront-publication/spec.md, "Shape-resolvable commercial
rates". `min_price` and `token` are not pricing terms; a hint that states them
is reported, never read.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from arkhai_vms import VM_PRICING_PROJECTION, vm_family_rate

GPU_FAMILY_KEY = "gpu"

#: Pricing keys a hint or configuration may still state that mean nothing: they
#: are reported to the operator and never read.
RETIRED_PRICING_KEYS: tuple[str, ...] = ("min_price", "token")

#: The families a VM rate may be stated for, and those priced per GPU model --
#: both from the VM domain's pricing projection, never from the schema.
PRICED_FAMILIES: tuple[str, ...] = tuple(sorted(VM_PRICING_PROJECTION.families))
KEYED_FAMILIES: frozenset[str] = frozenset(
    family
    for family, priced in VM_PRICING_PROJECTION.families.items()
    if priced.key is not None
)

_FIELD_NAMES = (
    "max_duration_seconds",
    "accepted_escrows",
    "settlements",
)


@dataclass(frozen=True)
class GpuPricingFields:
    """One tier's contribution to a GPU model's resolved listing terms.
    ``None`` on any field means "this tier has no opinion," not "the
    field is empty" -- resolution falls through to the next tier for
    that field alone.
    """

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
    """Resolve one GPU model's listing terms through the three-tier chain.

    Each field is resolved independently: storefront
    override (if set) wins outright; otherwise the pool's own pricing
    hint for this model (if the hint declares that field *and* it has a
    valid shape for that field -- see `_VALID_HINT_FIELD`, below);
    otherwise the storefront's per-model config default (if one is
    configured for this model); otherwise the storefront's flat config
    default. A field left unset all the way through every tier stays
    ``None``.
    """
    hint_fields = _hint_fields_for_model(policy_tags, gpu_model)
    config_fields = config_defaults_by_model.get(gpu_model) if gpu_model else None

    def _resolve(field_name: str) -> Any:
        override_value = getattr(storefront_override, field_name)
        if override_value is not None:
            return override_value
        if hint_fields is not None:
            hint_value = hint_fields.get(field_name)
            # A hint field with the wrong shape is treated the same as an
            # absent one -- this domain, not `kit/resource-pools`, owns
            # validating the shape it accepts; silently propagating a
            # malformed value into a commercial candidate is worse than
            # falling through to a lower tier the same way a missing value
            # already does.
            if hint_value is not None and _VALID_HINT_FIELD[field_name](hint_value):
                return hint_value
        if config_fields is not None:
            config_value = getattr(config_fields, field_name)
            if config_value is not None:
                return config_value
        return getattr(flat_default, field_name)

    return GpuPricingFields(**{name: _resolve(name) for name in _FIELD_NAMES})


def _is_nonnegative_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


_VALID_HINT_FIELD: Mapping[str, Any] = {
    "max_duration_seconds": _is_nonnegative_int,
    "accepted_escrows": lambda v: isinstance(v, list),
    "settlements": lambda v: isinstance(v, list),
}


def _pool_pricing(policy_tags: Mapping[str, Any]) -> Mapping[str, Any] | None:
    # Local import -- see resolve_vm_listing_cardinality_mode's own comment
    # in arkhai_vms_listings.listing_cardinality_mode for the reason (kept
    # out of any consumer that imports this module's signatures without
    # calling it).
    from market_resource_pools_contracts.hints import raw_pricing

    pricing = raw_pricing(policy_tags)
    return pricing if isinstance(pricing, Mapping) else None


def _hint_fields_for_model(
    policy_tags: Mapping[str, Any],
    gpu_model: str | None,
) -> Mapping[str, Any] | None:
    if not gpu_model:
        return None
    pricing = _pool_pricing(policy_tags)
    if pricing is None:
        return None
    gpu_family = pricing.get(GPU_FAMILY_KEY)
    if not isinstance(gpu_family, Mapping):
        return None
    model_fields = gpu_family.get(gpu_model)
    if not isinstance(model_fields, Mapping):
        return None
    return model_fields


# ---------------------------------------------------------------------------
# Family rates
# ---------------------------------------------------------------------------

_RATE_ENTRY_KEYS = frozenset({"asset", "rate", "per"})


def parse_family_rate_list(value: Any) -> tuple[dict[str, str], ...]:
    """Validate one family's ``rates`` list into normalized entries.

    Each entry names an ``asset``, a positive decimal-text ``rate`` in that
    asset's display units per unit of the family, and the time unit ``per`` the
    rate is charged by; an asset appears at most once. Raises ``ValueError``
    naming the first problem.
    """
    if not isinstance(value, list):
        raise ValueError("rates must be a list")
    entries: list[dict[str, str]] = []
    seen: set[str] = set()
    for index, entry in enumerate(value):
        where = f"rates[{index}]"
        if not isinstance(entry, Mapping):
            raise ValueError(f"{where} must be a mapping of asset, rate, and per")
        keys = set(entry)
        if keys != _RATE_ENTRY_KEYS:
            unknown = sorted(str(key) for key in keys - _RATE_ENTRY_KEYS)
            missing = sorted(_RATE_ENTRY_KEYS - keys)
            raise ValueError(
                f"{where} must state exactly asset, rate, and per"
                + (f"; unknown {unknown}" if unknown else "")
                + (f"; missing {missing}" if missing else "")
            )
        asset = entry["asset"]
        if not isinstance(asset, str) or not asset or asset != asset.strip():
            raise ValueError(f"{where}.asset must be a non-empty trimmed string")
        if asset in seen:
            raise ValueError(f"{where}.asset {asset!r} appears more than once")
        seen.add(asset)
        try:
            rate = vm_family_rate(entry["rate"], entry["per"])
        except ValueError as exc:
            raise ValueError(f"{where}: {exc}") from exc
        entries.append({"asset": asset, "rate": rate.rate, "per": rate.per})
    return tuple(entries)


def family_rate_terms_problems(pricing: Any) -> list[str]:
    """Every problem with a site-scoped override's ``pricing`` term.

    Stricter than a hint: an override states rates and nothing else, so the GPU
    family maps each model to ``{"rates": [...]}``, every other known family is
    ``{"rates": [...]}``, and a family the schema does not define is refused.
    """
    if not isinstance(pricing, Mapping):
        return ["pricing must be a mapping of family to rates"]
    problems: list[str] = []
    for family, body in pricing.items():
        path = f"pricing.{family}"
        if family not in PRICED_FAMILIES:
            problems.append(f"{path}: family is not defined by the compute schema")
            continue
        if not isinstance(body, Mapping):
            problems.append(f"{path} must be a mapping")
            continue
        if family in KEYED_FAMILIES:
            if "rates" in body:
                problems.append(f"{path} must be keyed by model")
                continue
            items = [(f"{path}.{key}", value) for key, value in body.items()]
        else:
            items = [(path, body)]
        for item_path, item in items:
            if not isinstance(item, Mapping) or set(item) != {"rates"}:
                problems.append(f"{item_path} must state exactly rates")
                continue
            try:
                parse_family_rate_list(item["rates"])
            except ValueError as exc:
                problems.append(f"{item_path}.{exc}")
    return problems


def _tier_rates(
    tier: Mapping[str, Any] | None,
    family: str,
    gpu_model: str | None,
) -> Any:
    """The raw ``rates`` value one tier states for a family, or None."""
    if not isinstance(tier, Mapping):
        return None
    body = tier.get(family)
    if not isinstance(body, Mapping):
        return None
    if family in KEYED_FAMILIES:
        if not gpu_model:
            return None
        body = body.get(gpu_model)
        if not isinstance(body, Mapping):
            return None
    return body.get("rates")


def _tier_structure_problems(tier: Mapping[str, Any] | None) -> list[str]:
    """Rates a tier states where no VM family is priced by them.

    A rate list under a family the pricing projection does not name, or stated
    for the GPU family without a model, would otherwise be silently ignored: a
    price the seller believes they published.
    """
    if not isinstance(tier, Mapping):
        return []
    problems: list[str] = []
    for family, body in tier.items():
        if not isinstance(body, Mapping):
            continue
        if family not in PRICED_FAMILIES:
            if "rates" in body or any(
                isinstance(item, Mapping) and "rates" in item for item in body.values()
            ):
                problems.append(f"pricing.{family}: no VM family is priced by it")
        elif family in KEYED_FAMILIES and "rates" in body:
            problems.append(f"pricing.{family}.rates: must be stated per model")
    return problems


@dataclass(frozen=True)
class FamilyRateResolution:
    """One listing model's resolved family rates and what resolution found.

    ``rates`` maps each family with a resolved, non-empty list to its entries; a
    family no tier states is absent. ``problems`` names every tier value that
    could not be read; any problem makes the resolution ``unreadable``, and the
    caller must hold the pool rather than price it from what remains.
    ``retired_keys`` names retired pricing keys the pool's hint still states.
    """

    rates: Mapping[str, tuple[dict[str, str], ...]] = field(default_factory=dict)
    problems: tuple[str, ...] = ()
    retired_keys: tuple[str, ...] = ()

    @property
    def unreadable(self) -> bool:
        return bool(self.problems)

    @property
    def shape_priced(self) -> bool:
        return bool(self.rates)


def resolve_family_rates(
    policy_tags: Mapping[str, Any],
    *,
    gpu_model: str | None,
    storefront_override: Mapping[str, Any] | None,
    config_defaults: Mapping[str, Any] | None,
) -> FamilyRateResolution:
    """Resolve every family's rates for one GPU model through the three tiers.

    ``storefront_override`` and ``config_defaults`` use the hint's nesting:
    ``{"gpu": {"<model>": {"rates": [...]}}, "cpu": {"rates": [...]}, ...}``.
    The highest tier stating a family's list supplies it whole, and an unreadable
    value never falls through to a lower tier: a lower tier's rate is a price
    nobody stated for this pool. The storefront also refuses to start with an
    unreadable configured default (`configured_family_rate_problems`).
    """
    hint = _pool_pricing(policy_tags)
    tiers = (
        ("override", storefront_override),
        ("hint", hint),
        ("default", config_defaults),
    )
    rates: dict[str, tuple[dict[str, str], ...]] = {}
    problems: list[str] = []
    for tier_name, tier in tiers[:2]:
        problems.extend(
            f"{tier_name} {problem}" for problem in _tier_structure_problems(tier)
        )
    for family in PRICED_FAMILIES:
        for tier_name, tier in tiers:
            raw = _tier_rates(tier, family, gpu_model)
            if raw is None:
                continue
            try:
                rates[family] = parse_family_rate_list(raw)
            except ValueError as exc:
                problems.append(f"{tier_name} pricing.{family}: {exc}")
            break
    return FamilyRateResolution(
        rates={family: entries for family, entries in rates.items() if entries},
        problems=tuple(problems),
        retired_keys=retired_hint_pricing_keys(policy_tags),
    )


def configured_family_rate_problems(config_defaults: Mapping[str, Any] | None) -> list[str]:
    """Every problem with the storefront's configured family-rate defaults.

    Configuration nests like a hint, beside per-model listing terms, so only its
    ``rates`` lists are checked: each must parse, belong to a priced family, and
    be stated per model for the GPU family.
    """
    if not isinstance(config_defaults, Mapping):
        return []
    problems = [f"defaults {problem}" for problem in _tier_structure_problems(config_defaults)]
    for family in PRICED_FAMILIES:
        body = config_defaults.get(family)
        if not isinstance(body, Mapping):
            continue
        if family in KEYED_FAMILIES:
            lists = [
                (f"pricing.defaults.{family}.{key}", item.get("rates"))
                for key, item in body.items()
                if isinstance(item, Mapping) and "rates" in item
            ]
        else:
            lists = [(f"pricing.defaults.{family}", body.get("rates"))] if "rates" in body else []
        for path, raw in lists:
            try:
                parse_family_rate_list(raw)
            except ValueError as exc:
                problems.append(f"{path}.{exc}")
    return problems


def retired_hint_pricing_keys(policy_tags: Mapping[str, Any]) -> tuple[str, ...]:
    """Retired pricing keys a pool's hint still states, as dotted paths."""
    pricing = _pool_pricing(policy_tags)
    if pricing is None:
        return ()
    gpu_family = pricing.get(GPU_FAMILY_KEY)
    if not isinstance(gpu_family, Mapping):
        return ()
    return tuple(
        f"pricing.{GPU_FAMILY_KEY}.{model}.{key}"
        for model, fields in sorted(gpu_family.items(), key=lambda item: str(item[0]))
        if isinstance(fields, Mapping)
        for key in RETIRED_PRICING_KEYS
        if key in fields
    )
