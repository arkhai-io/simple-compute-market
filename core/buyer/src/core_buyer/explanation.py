"""Deterministic public explanation payloads for buyer discovery and selection."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from market_core import parse_query

from core_buyer.orchestrator import RegistryDiscovery
from core_buyer.settlement import BuyerSettlementExplanation

EXPLANATION_SCHEMA_VERSION = 1


def _json_literal(value: Any) -> Any:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, tuple):
        return [_json_literal(item) for item in value]
    return value


def _canonical_ast(source: str | None) -> list[dict[str, Any]]:
    if source is None:
        return []
    parsed = parse_query(source)
    return [
        {
            "field": comparison.field,
            "operator": comparison.operator.value,
            "value": _json_literal(comparison.literal.value),
        }
        for comparison in parsed.comparisons
    ]


def build_buyer_explanation(
    discovery: RegistryDiscovery,
    settlement: BuyerSettlementExplanation,
) -> dict[str, Any]:
    """Build one stable payload without provider calls or mutable state."""

    registry_plans = [plan.to_dict() for plan in discovery.query_plans]
    canonical_resource_queries = {
        plan.canonical_query
        for plan in discovery.query_plans
        if plan.canonical_query is not None
    }
    canonical_resource_query = (
        next(iter(canonical_resource_queries))
        if len(canonical_resource_queries) == 1
        else None
    )
    settlement_payload = settlement.to_dict()
    clause_payload = [
        {
            "index": stage.index,
            "canonical_query": stage.clause,
            "canonical_ast": _canonical_ast(stage.clause),
        }
        for stage in settlement.clauses
    ]
    return {
        "schema_version": EXPLANATION_SCHEMA_VERSION,
        "kind": "buyer_selection_explanation",
        "registries": registry_plans,
        "resource": {
            "canonical_query": canonical_resource_query,
            "canonical_ast": _canonical_ast(canonical_resource_query),
            "pushed_predicates": [
                {
                    "registry_url": plan.registry_url,
                    "parameters": dict(plan.parameters),
                }
                for plan in discovery.query_plans
            ],
            "survivor_count": settlement.resource_listing_count,
        },
        "settlement": {
            "canonical_clauses": clause_payload,
            "predicates_evaluated_locally": True,
            **settlement_payload,
        },
        "mutation_boundary": {
            "performed": [
                "authenticated_filter_spec_read",
                "authenticated_listing_read",
                "local_public_compatibility",
            ],
            "stopped_before": [
                "negotiation",
                "prerequisite_resolution",
                "buyer_action_retrieval",
                "chain_or_provider_call",
                "run_persistence",
            ],
        },
    }


def format_buyer_explanation(payload: dict[str, Any]) -> tuple[str, ...]:
    """Render concise human evidence from the same machine payload."""

    lines = ["Buyer selection explanation"]
    for registry in payload["registries"]:
        spec = registry["filter_spec"]
        lines.append(
            "Registry "
            f"{registry['registry_url']}: filter_version={spec['version']} "
            f"schema={spec['schema_id'] or '-'} "
            f"schema_version={spec['schema_version']} etag={spec['etag']}"
        )
    resource = payload["resource"]
    lines.append(f"Resource query: {resource['canonical_query'] or '<none>'}")
    lines.append(f"Resource survivors: {resource['survivor_count']}")
    settlement = payload["settlement"]
    compatibility = settlement["installed_enabled_compatibility"]
    lines.append(
        "Settlement compatibility: "
        f"{compatibility['listing_count']} listings / "
        f"{compatibility['option_count']} options"
    )
    for stage in settlement["clause_survivors"]:
        lines.append(
            f"Clause {stage['index']}: {stage['clause']} -> "
            f"{stage['listing_count']} listings / {stage['option_count']} options"
        )
    ordering = settlement["policy_ordering"]
    lines.append(
        "Policy ordering: "
        f"mechanism={ordering['mechanism'] or '-'} "
        f"listings={ordering['listing_count']}"
    )
    lines.append(
        f"Selected option: {settlement['selected_option_id'] or '<not singular>'}"
    )
    rejected = ", ".join(
        f"{name}={count}"
        for name, count in settlement["rejection_categories"].items()
        if count
    )
    lines.append(f"Rejections: {rejected or 'none'}")
    lines.append("Stopped before negotiation and all settlement mutations.")
    return tuple(lines)
