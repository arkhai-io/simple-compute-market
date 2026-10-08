"""How one bare-metal publication cycle is composed from a running storefront.

The publication command and the administrator's publication step both compose
their cycle here, so the two cannot run different cycles. Each trusted site's
own capacity client and the one configured registry come from the storefront
runtime and the process environment; terms of sale come from durable
configuration, replaced for one site's pool by the storefront's stored override.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Mapping
from typing import Any

from core_storefront.publication_runner import PublicationPayload
from market_settlement_runtime import SettlementPublicationClause

from .pool_overrides import (
    MAX_DURATION_SECONDS_ENV,
    compile_publication_clauses,
    configured_max_duration_seconds,
)
from .publication import BareMetalPublicationCycle
from .publication_service import BareMetalRegistryConfiguration
from .runtime import BareMetalStorefrontRuntime
from .storefront_registry import build_bare_metal_storefront_registry


def _json_env(environ: Mapping[str, str], name: str) -> Any:
    try:
        return json.loads(environ[name])
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeError(f"{name} must contain valid JSON") from exc


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
    if not isinstance(clauses_raw, list):
        raise RuntimeError("publication clauses have an invalid JSON shape")
    clauses = tuple(
        SettlementPublicationClause.model_validate(item) for item in clauses_raw
    )
    demands = _json_env(environ, "BARE_METAL_STOREFRONT_DEMANDS")
    if not isinstance(demands, list):
        raise RuntimeError("BARE_METAL_STOREFRONT_DEMANDS must be a JSON list")
    max_duration = configured_max_duration_seconds(environ)
    if max_duration is None:
        raise RuntimeError(f"{MAX_DURATION_SECONDS_ENV} is required for publication")

    async def build(candidate: dict[str, Any]) -> PublicationPayload:
        # A pool's storefront override replaces the configured clauses and
        # bound for that pool's listings only.
        override_clauses = candidate.get("override_clauses")
        return await composition.publication_payload(
            candidate=candidate,
            clauses=(
                compile_publication_clauses(override_clauses)
                if override_clauses is not None
                else clauses
            ),
            demands=demands,
            max_duration_seconds=candidate.get(
                "override_max_duration_seconds", max_duration
            ),
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
        configured_max_duration_seconds=configured_max_duration_seconds(environ),
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
