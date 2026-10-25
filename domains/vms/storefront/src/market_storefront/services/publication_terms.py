"""Terms of sale the storefront derives for a VM publication candidate.

Every input here is durable: the pool's own pricing hint, the storefront's
per-pool override, and its configured defaults. Reconciliation re-derives a
listing's terms from these on every publication cycle and compares them with what
is published, so a term supplied only for one invocation could never be
reproduced and would be reverted on the next cycle.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from arkhai_vms import VM_CAPABILITY_SCHEMA, price_vm_shape, vm_family_rate
from arkhai_vms.storefront_adapter import vm_listing_resource_for_listing
from arkhai_vms_listings.listing_shapes import CONFIGURED_DEFAULT_TIER
from arkhai_vms_listings.pricing_resolution import (
    GPU_FAMILY_KEY,
    RETIRED_PRICING_KEYS,
    GpuPricingFields,
    configured_family_rate_problems as _configured_family_rate_problems,
)
from arkhai_vms_listings.reconciler import PoolHintResolutionSettings
from market_alkahest import ALKAHEST_CONFIG_KEY, AlkahestSettlementConfig
from market_capability_admissibility import Declaration, parse_declaration
from market_settlement_runtime import (
    SettlementConfigurationError,
    SettlementPublicationClause,
    compile_settlement_publication_clause,
    parse_settlement_publication_clause,
)
from market_storefront.settlement_composition import (
    build_storefront_settlement_registry,
)
from market_storefront.utils.config import (
    settings,
    settlement_config_mapping,
    settlement_publication_defaults,
)


def _plain_pricing(value: Any) -> Any:
    """Detach Dynaconf containers, keeping keys' case: GPU models are keys."""
    if hasattr(value, "items"):
        return {str(key): _plain_pricing(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain_pricing(item) for item in value]
    return value


#: Storefront-wide pricing keys that configure nothing. The pricing
#: migration still reads ``default_token_address`` from a legacy configuration.
RETIRED_PRICING_CONFIGURATION_KEYS: tuple[str, ...] = ("default_token_address",)


def normalize_max_duration_seconds(value: Any) -> int | None:
    """Return a positive lease-duration ceiling, or None for unlimited."""
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    seconds = int(value)
    return seconds if seconds > 0 else None


def parse_configured_admissibility_default() -> Declaration | None:
    """Parse ``[admissibility.defaults.vm]``, or ``None`` when it states nothing.

    Absent and empty both mean no default. The table is the operator's own
    file, so one the admissibility kit cannot read is a configuration error
    rather than a listing to close: it raises ``RuntimeError`` naming every
    problem, and the storefront does not start. Parse it once and hand the
    result to every consumer, so publication, the default generator, and the
    override write check judge against one declaration.
    """
    def refused(detail: str) -> RuntimeError:
        return RuntimeError(f"configured admissibility default cannot be read: {detail}")

    admissibility = _plain_pricing(settings.get("admissibility"))
    if admissibility is None:
        return None
    if not isinstance(admissibility, dict):
        raise refused("admissibility must be a table")
    defaults = admissibility.get("defaults")
    if defaults is None:
        return None
    if not isinstance(defaults, dict):
        raise refused("admissibility.defaults must be a table keyed by offering mode")
    raw = defaults.get("vm")
    if raw is None or raw == {}:
        return None
    if not isinstance(raw, dict):
        raise refused("admissibility.defaults.vm must be a table")
    parsed = parse_declaration(
        raw, tier=CONFIGURED_DEFAULT_TIER, schema=VM_CAPABILITY_SCHEMA
    )
    if parsed.declaration is None:
        raise RuntimeError(
            "configured admissibility default cannot be read: "
            + "; ".join(
                f"admissibility.defaults.vm.{problem}" if problem.paths
                else f"admissibility.defaults.vm: {problem}"
                for problem in parsed.problems
            )
        )
    return parsed.declaration


def pool_hint_resolution_settings(
    *, admissibility_default: Declaration | None
) -> PoolHintResolutionSettings:
    """Pool-hint policy with whole-list settlement precedence.

    A pool's own clauses — its storefront override or its declared pricing hint
    — replace the configured defaults as a whole list: per-model
    ``[pricing.defaults.gpu.<model>].settlements``, then ``[pricing].settlements``.
    Configured family rates — ``[pricing.defaults.gpu.<model>].rates`` and
    ``[pricing.defaults.<family>].rates`` — are the lowest tier of family-rate
    resolution. ``admissibility_default`` is the parsed
    ``[admissibility.defaults.vm]`` composition holds.
    """

    pricing = getattr(settings, "pricing", None)
    flat_default = GpuPricingFields(
        max_duration_seconds=(
            getattr(pricing, "default_max_duration_seconds", 0) or None
        ),
        accepted_escrows=None,
        settlements=[
            clause.model_dump(mode="json", exclude_defaults=True)
            for clause in settlement_publication_defaults()
        ],
    )

    defaults = _plain_pricing(getattr(pricing, "defaults", None)) or {}
    defaults = defaults if isinstance(defaults, dict) else {}
    defaults_by_model: dict[str, GpuPricingFields] = {}
    gpu_defaults = defaults.get(GPU_FAMILY_KEY)
    if isinstance(gpu_defaults, dict):
        for model, fields in gpu_defaults.items():
            fields = fields if isinstance(fields, dict) else {}
            defaults_by_model[str(model)] = GpuPricingFields(
                max_duration_seconds=fields.get("max_duration_seconds"),
                accepted_escrows=fields.get("accepted_escrows"),
                settlements=fields.get("settlements"),
            )

    return PoolHintResolutionSettings(
        accept_pool_declared_sla=bool(
            getattr(pricing, "accept_pool_declared_sla", False),
        ),
        default_sla=float(getattr(pricing, "default_sla", 0.0) or 0.0),
        gpu_pricing_defaults_by_model=defaults_by_model,
        gpu_pricing_flat_default=flat_default,
        family_rate_defaults=defaults,
        admissibility_default=admissibility_default,
    )


def retired_pricing_configuration_keys() -> list[str]:
    """Retired pricing keys the storefront's configuration still states."""
    pricing = _plain_pricing(getattr(settings, "pricing", None)) or {}
    if not isinstance(pricing, dict):
        return []
    found = [
        f"pricing.{name}"
        for name in RETIRED_PRICING_CONFIGURATION_KEYS
        if pricing.get(name) not in (None, "")
    ]
    defaults = pricing.get("defaults")
    gpu = defaults.get(GPU_FAMILY_KEY) if isinstance(defaults, dict) else None
    if isinstance(gpu, dict):
        for model, fields in sorted(gpu.items(), key=lambda item: str(item[0])):
            if isinstance(fields, dict):
                found.extend(
                    f"pricing.defaults.{GPU_FAMILY_KEY}.{model}.{key}"
                    for key in RETIRED_PRICING_KEYS
                    if key in fields
                )
    return found


def listing_resource_for_candidate(res: dict[str, Any]) -> dict[str, Any]:

    alkahest = settlement_config_mapping().get("alkahest", {})
    interruptible = isinstance(alkahest, dict) and bool(
        alkahest.get("interruptible", False)
    )
    listing_resource = vm_listing_resource_for_listing(res, interruptible=interruptible)
    listing_resource["offering_mode"] = "vm"
    return listing_resource


def enabled_publication_clauses(
    values: list[str] | list[dict[str, Any]],
) -> tuple[list[str] | list[dict[str, Any]], tuple[str, ...]]:
    """The clauses whose mechanism the storefront enables, and the mechanisms
    of those it drops because their section is absent or disabled.

    Publication rejects a disabled mechanism's clause rather than letting it
    enable the mechanism, and keeps the candidate's other clauses: a disabled
    section is the storefront's configuration ruling that mechanism out. Only a
    clause that reads in full, DSL text or a mapping, is judged by its
    mechanism's section: one that cannot be read, whatever mechanism it names,
    is kept for compilation to refuse, so a malformed clause is a payload
    failure that leaves the candidate's listing as it is, never a mechanism
    ruled out that would close it.
    """
    registry = build_storefront_settlement_registry()
    config = registry.resolve(settlement_config_mapping(), role="seller")
    kept: list[Any] = []
    disabled: list[str] = []
    for value in values:
        try:
            mechanism = parse_settlement_publication_clause(
                value, registry=registry, role="seller"
            ).mechanism
        except SettlementConfigurationError:
            kept.append(value)
            continue
        config_key = registry.registration(mechanism).config_key
        section = config.mechanisms.get(config_key)
        if section is None or getattr(section, "enabled", False) is not True:
            disabled.append(mechanism)
        else:
            kept.append(value)
    return kept, tuple(dict.fromkeys(disabled))


def compile_publication_clauses(
    values: list[str] | list[dict[str, Any]],
) -> tuple[SettlementPublicationClause, ...]:


    registry = build_storefront_settlement_registry()
    config = registry.resolve(settlement_config_mapping(), role="seller")
    return tuple(
        compile_settlement_publication_clause(
            value,
            registry=registry,
            config=config,
            role="seller",
        )
        for value in values
    )


@dataclass(frozen=True)
class ComposedClauses:
    """A listing's settlement clauses with their rates, and its rate structure.

    ``rate_structure`` is ``None`` for a flat-priced listing, and otherwise maps
    every family with resolved rates for the listing's model to its entries.
    """

    clauses: tuple[SettlementPublicationClause, ...]
    rate_structure: dict[str, list[dict[str, str]]] | None


def compose_clause_rates(
    clauses: tuple[SettlementPublicationClause, ...],
    *,
    listing_shape: Mapping[str, Mapping[str, Any]],
    family_rates: Mapping[str, Any] | None,
    registry: Any = None,
) -> ComposedClauses:
    """Give each clause of a shape-priced listing its rate for the listing's shape.

    A listing for which no family resolves rates is flat-priced and its clauses
    are returned unchanged. A shape-priced listing's clauses state no rate; each
    whose mechanism negotiates a scalar amount gets the price of the listing's
    own shape under the family rates in that clause's asset, through the VM
    domain's aggregator, where a family without a rate in that asset is not
    charged. A clause whose mechanism declines the scalar carries no price and is
    passed through. See openspec/specs/storefront-publication/spec.md,
    "Shape-resolvable commercial rates".

    ``registry`` answers which mechanisms negotiate a scalar amount; it defaults
    to the storefront's settlement registry.

    Raises ``ValueError`` naming the asset when a scalar clause's composed rate
    would be zero -- the listing would be free in that asset -- and when a
    shape-priced clause states its own rate.
    """
    rates = {
        family: [dict(entry) for entry in entries]
        for family, entries in (family_rates or {}).items()
        if entries
    }
    if not rates:
        return ComposedClauses(clauses=tuple(clauses), rate_structure=None)

    registry = registry or build_storefront_settlement_registry()
    composed: list[SettlementPublicationClause] = []
    for clause in clauses:
        if not registry.registration(clause.mechanism).negotiates_scalar_amount:
            composed.append(clause)
            continue
        if clause.rate is not None:
            raise ValueError(
                f"settlement clause for {clause.mechanism} in asset "
                f"{clause.asset!r} states its own rate, but the listing is "
                "shape-priced: its rate comes from the family rates"
            )
        asset_rates = {
            family: vm_family_rate(entry["rate"], entry["per"])
            for family, entries in rates.items()
            for entry in entries
            if entry.get("asset") == clause.asset
        }
        price = price_vm_shape(listing_shape, asset_rates)
        if price.is_zero:
            raise ValueError(
                f"listing would be free in asset {clause.asset!r}: no family its "
                "shape names has a rate in that asset"
            )
        composed.append(
            SettlementPublicationClause.model_validate(
                {
                    **clause.model_dump(mode="python"),
                    "rate": price.amount,
                    "per": price.per,
                }
            )
        )
    # Every resolved family, not only those this shape names: a revised shape
    # priced from this record may name a family the advertised one omits.
    return ComposedClauses(
        clauses=tuple(composed),
        rate_structure={family: rates[family] for family in sorted(rates)},
    )


def configured_family_rate_problems() -> list[str]:
    """Every problem with the configured family-rate defaults; empty when valid."""
    pricing = getattr(settings, "pricing", None)
    defaults = _plain_pricing(getattr(pricing, "defaults", None)) or {}
    return _configured_family_rate_problems(defaults if isinstance(defaults, dict) else {})


def configured_alkahest_section() -> AlkahestSettlementConfig | None:
    """The seller's ``[Settlement.alkahest]`` section, which a listing's
    release conditions derive from; ``None`` when none is configured."""
    registry = build_storefront_settlement_registry()
    config = registry.resolve(settlement_config_mapping(), role="seller")
    return config.mechanism_config(ALKAHEST_CONFIG_KEY)
