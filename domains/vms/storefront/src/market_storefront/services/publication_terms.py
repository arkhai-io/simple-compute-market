"""Terms of sale the storefront derives for a VM publication candidate.

Every input here is durable: the pool's own pricing hint, the storefront's
per-pool override, and its configured defaults. Reconciliation re-derives a
listing's terms from these on every publication cycle and compares them with what
is published, so a term supplied only for one invocation could never be
reproduced and would be reverted on the next cycle.
"""

from __future__ import annotations

from typing import Any

from arkhai_vms.storefront_adapter import vm_listing_resource_for_listing
from domains.vms.listings.pricing_resolution import GpuPricingFields
from domains.vms.listings.reconciler import PoolHintResolutionSettings
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
    """

    pricing = getattr(settings, "pricing", None)
    flat_default = GpuPricingFields(
        min_price=(getattr(pricing, "default_min_price", "") or None),
        token=(getattr(pricing, "default_token_address", "") or None),
        max_duration_seconds=(
            getattr(pricing, "default_max_duration_seconds", 0) or None
        ),
        accepted_escrows=None,
        settlements=[
            clause.model_dump(mode="json", exclude_defaults=True)
            for clause in settlement_publication_defaults()
        ],
    )

    defaults_by_model: dict[str, GpuPricingFields] = {}
    gpu_defaults = getattr(getattr(pricing, "defaults", None), "gpu", None)
    if gpu_defaults:
        for model, fields in dict(gpu_defaults).items():
            fields = fields or {}
            defaults_by_model[str(model)] = GpuPricingFields(
                min_price=fields.get("min_price"),
                token=fields.get("token"),
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
    )


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


