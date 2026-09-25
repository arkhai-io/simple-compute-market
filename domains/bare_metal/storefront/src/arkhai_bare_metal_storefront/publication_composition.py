"""How one bare-metal publication cycle is composed from a running storefront.

The publication command and the administrator's publication step both compose
their cycle here, so the two cannot run different cycles. Each trusted site's
own capacity client and the one configured registry come from the storefront
runtime and the process environment; terms of sale come only from durable
configuration.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from typing import Any

from core_storefront.publication_runner import PublicationPayload
from market_settlement_runtime import SettlementPublicationClause

from .publication import BareMetalPublicationCycle
from .publication_service import BareMetalRegistryConfiguration
from .runtime import BareMetalStorefrontRuntime
from .storefront_registry import build_bare_metal_storefront_registry


def _json_env(environ: Mapping[str, str], name: str) -> Any:
    try:
        return json.loads(environ[name])
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeError(f"{name} must contain valid JSON") from exc


def _instant(environ: Mapping[str, str], name: str) -> datetime:
    value = environ.get(name, "")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise RuntimeError(f"{name} must include a timezone")
    return parsed.astimezone(timezone.utc)


def publication_payload_builder(
    runtime: BareMetalStorefrontRuntime,
    environ: Mapping[str, str],
) -> Callable[[dict[str, Any]], Any]:
    """Build each candidate's payload from the configured publication inputs."""
    composition = runtime.settlement_composition
    if composition is None:
        raise RuntimeError(
            "shared settlement configuration is required for publication"
        )
    clauses_raw = _json_env(environ, "BARE_METAL_STOREFRONT_PUBLICATION_CLAUSES")
    deadlines_raw = _json_env(environ, "BARE_METAL_STOREFRONT_FUNDING_DEADLINES")
    if not isinstance(clauses_raw, list) or not isinstance(deadlines_raw, dict):
        raise RuntimeError("publication clauses/deadlines have invalid JSON shapes")
    clauses = tuple(
        SettlementPublicationClause.model_validate(item) for item in clauses_raw
    )
    funding_deadlines = {
        str(profile): datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        for profile, value in deadlines_raw.items()
    }
    demands = _json_env(environ, "BARE_METAL_STOREFRONT_DEMANDS")
    if not isinstance(demands, list):
        raise RuntimeError("BARE_METAL_STOREFRONT_DEMANDS must be a JSON list")
    option_expiry = _instant(environ, "BARE_METAL_STOREFRONT_OPTION_EXPIRES_AT")
    fulfillment_deadline = _instant(
        environ, "BARE_METAL_STOREFRONT_FULFILLMENT_DEADLINE"
    )
    max_duration = int(environ["BARE_METAL_STOREFRONT_MAX_DURATION_SECONDS"])

    async def build(candidate: dict[str, Any]) -> PublicationPayload:
        return await composition.publication_payload(
            candidate=candidate,
            clauses=clauses,
            option_expires_at=option_expiry,
            funding_deadlines=funding_deadlines,
            fulfillment_deadline=fulfillment_deadline,
            demands=demands,
            max_duration_seconds=max_duration,
        )

    return build


def build_publication_cycle(
    runtime: BareMetalStorefrontRuntime,
    *,
    registry_configuration: BareMetalRegistryConfiguration,
    environ: Mapping[str, str],
    cycle_factory: Callable[..., BareMetalPublicationCycle] = BareMetalPublicationCycle,
) -> BareMetalPublicationCycle:
    """Compose one cycle from the runtime's own trusted per-site clients.

    Each site's client is the one the runtime composed for that site, never
    the aggregate client, whose snapshot cannot tell an unreachable site from
    an empty one.
    """
    if runtime.capacity_client is None:
        raise RuntimeError("trusted site capacity clients are unavailable")
    return cycle_factory(
        sqlite_client=runtime.db,
        registry=build_bare_metal_storefront_registry(domain=runtime.domain),
        site_clients={
            binding.site_id: runtime.capacity_client.site(binding.site_id)
            for binding in runtime.site_bindings
        },
        registry_client_factory=registry_configuration.client_factory(
            runtime.marketplace_signer
        ),
        registry_url=registry_configuration.url,
        storefront_url=runtime.storefront_url,
        seller_principal=runtime.seller_principal,
        build_payload=publication_payload_builder(runtime, environ),
    )


def compose_publication_cycle(
    runtime: BareMetalStorefrontRuntime,
    *,
    environ: Mapping[str, str] | None = None,
    cycle_factory: Callable[..., BareMetalPublicationCycle] = BareMetalPublicationCycle,
) -> BareMetalPublicationCycle:
    """Compose one cycle from the runtime and the configured environment."""
    env = os.environ if environ is None else environ
    return build_publication_cycle(
        runtime,
        registry_configuration=BareMetalRegistryConfiguration.from_environment(env),
        environ=env,
        cycle_factory=cycle_factory,
    )


__all__ = [
    "build_publication_cycle",
    "compose_publication_cycle",
    "publication_payload_builder",
]
