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

from arkhai_vms import price_vm_shape, vm_family_rate
from arkhai_vms.storefront_adapter import vm_listing_resource_for_listing
from arkhai_vms_listings.pricing_resolution import (
    GPU_FAMILY_KEY,
    RETIRED_PRICING_KEYS,
    GpuPricingFields,
    configured_family_rate_problems as _configured_family_rate_problems,
)
from arkhai_vms_listings.reconciler import PoolHintResolutionSettings
from market_alkahest.alkahest import (
    get_erc20_splitter,
    get_recipient_arbiter,
    get_trusted_oracle_arbiter,
)
from market_settlement_runtime import (
    SettlementPublicationClause,
    compile_settlement_publication_clause,
)
from market_storefront.settlement_composition import (
    build_storefront_settlement_registry,
)
from market_storefront.utils.config import (
    CHAINS,
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


def pool_hint_resolution_settings() -> PoolHintResolutionSettings:
    """Pool-hint policy with whole-list settlement precedence.

    A pool's own clauses — its storefront override or its declared pricing hint
    — replace the configured defaults as a whole list: per-model
    ``[pricing.defaults.gpu.<model>].settlements``, then ``[pricing].settlements``.
    Configured family rates — ``[pricing.defaults.gpu.<model>].rates`` and
    ``[pricing.defaults.<family>].rates`` — are the lowest tier of family-rate
    resolution.
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


def _recipient_demands_for_chains(
    chains: dict[str, Any],
    chain_names: set[str],
    recipient_address: str,
) -> list[dict[str, Any]]:

    demands: list[dict[str, Any]] = []
    for name in sorted(chain_names):
        chain = chains.get(name)
        if chain is None:
            continue
        arbiter = get_recipient_arbiter(
            chain.name,
            config_path=chain.alkahest_address_config_path,
        )
        demands.append(
            {
                "chain_name": chain.name,
                "arbiter": arbiter.lower(),
                "demand_data": {"recipient": recipient_address.lower()},
            }
        )
    return demands


def _heartbeat_oracle_demands_for_chains(
    chains: dict[str, Any],
    chain_names: set[str],
    oracle_address: str,
) -> list[dict[str, Any]]:
    """Oracle-gated plan shape: TrustedOracleArbiter demands.

    Collection through these listings waits for the named third-party
    oracle to ``arbitrate()`` true. First instantiation of lifecycle
    work item I.5: the oracle is assumed to arbitrate true at end of
    lease unless a dispute is raised (manual for now; the buyer's
    signed heartbeats and the seller's persisted evidence inform
    dispute handling). A plan shape, not a code path: only the
    advertised demand changes; negotiation, materialization, and the
    claims engine all flow through the same codec registry.
    """

    demands: list[dict[str, Any]] = []
    for name in sorted(chain_names):
        chain = chains.get(name)
        if chain is None:
            continue
        arbiter = get_trusted_oracle_arbiter(
            chain.name,
            config_path=chain.alkahest_address_config_path,
        )
        demands.append(
            {
                "chain_name": chain.name,
                "arbiter": arbiter.lower(),
                "demand_data": {"oracle": oracle_address.lower(), "data": "0x"},
            }
        )
    return demands


def _splitter_demands_for_chains(
    chains: dict[str, Any],
    chain_names: set[str],
    oracle_address: str,
) -> list[dict[str, Any]]:
    """Interruptible plan shape: splitter demands.

    The splitter demand identifies who may declare the eventual refund
    split. For the current VM spot MVP that can be the seller wallet;
    the split itself is applied later on-chain when an interruption
    occurs.
    """

    demands: list[dict[str, Any]] = []
    for name in sorted(chain_names):
        chain = chains.get(name)
        if chain is None:
            continue
        arbiter = get_erc20_splitter(
            chain.name,
            config_path=chain.alkahest_address_config_path,
        )
        demands.append(
            {
                "chain_name": chain.name,
                "arbiter": arbiter.lower(),
                "demand_data": {"oracle": oracle_address.lower(), "data": "0x"},
            }
        )
    return demands


def _demands_for_chains(
    chains: dict[str, Any],
    chain_names: set[str],
    wallet_address: str,
) -> list[dict[str, Any]]:
    """Published demand set per the seller's settlement posture."""

    alkahest = settlement_config_mapping().get("alkahest", {})
    if not isinstance(alkahest, dict):
        alkahest = {}
    interruptible = bool(alkahest.get("interruptible", False))
    if alkahest.get("oracle_gated", False):
        if interruptible:
            raise ValueError(
                "Settlement.alkahest oracle and interruptible policies "
                "are mutually exclusive"
            )
        trusted = alkahest.get("trusted_oracle_addresses", [])
        oracle = str(trusted[0] if isinstance(trusted, list) and trusted else "")
        if not oracle:
            raise ValueError(
                "Settlement.alkahest.oracle_gated requires a trusted oracle"
            )
        if oracle.lower() == wallet_address.lower():
            raise ValueError(
                "Settlement.alkahest trusted oracle equals the storefront wallet"
            )
        return _heartbeat_oracle_demands_for_chains(chains, chain_names, oracle)
    if interruptible:
        trusted = alkahest.get("interruptible_oracle_addresses", [])
        oracle = str(trusted[0] if isinstance(trusted, list) and trusted else "")
        return _splitter_demands_for_chains(
            chains,
            chain_names,
            oracle or wallet_address,
        )
    return _recipient_demands_for_chains(chains, chain_names, wallet_address)


def listing_resource_for_candidate(res: dict[str, Any]) -> dict[str, Any]:

    alkahest = settlement_config_mapping().get("alkahest", {})
    interruptible = isinstance(alkahest, dict) and bool(
        alkahest.get("interruptible", False)
    )
    listing_resource = vm_listing_resource_for_listing(res, interruptible=interruptible)
    listing_resource["offering_mode"] = "vm"
    return listing_resource


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


def demands_for_publication_clauses(
    clauses: tuple[SettlementPublicationClause, ...],
    *,
    wallet_address: str,
) -> list[dict[str, Any]]:
    chain_names = {
        str(clause.mechanism_input["chain"])
        for clause in clauses
        if clause.mechanism == "alkahest.v1"
        and isinstance(clause.mechanism_input.get("chain"), str)
    }
    if not chain_names:
        return []

    unknown = chain_names.difference(CHAINS)
    if unknown:
        raise ValueError(
            f"settlement clause references unknown chain {sorted(unknown)[0]!r}"
        )
    return _demands_for_chains(CHAINS, chain_names, wallet_address)


