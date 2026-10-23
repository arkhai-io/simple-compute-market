"""Startup initialization from the profile: the seeded pool, its declarations, and the pool directory."""

from __future__ import annotations

from typing import Any

from market_resource_pools import ResourcePool
from market_resource_pools_contracts import PoolDeclarationError, resolve_pool_declarations
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from arkhai_api_authority.profile import CapacityProfile


def initialize(engine: Engine, profile: CapacityProfile) -> None:
    """Seed the profile's pool when absent, then refuse any stored pool without valid declarations.

    Runs after the migration chain on every start, so a pool an operator
    changed is kept as it is and a pool from before the declarations existed
    stops the service rather than being served.
    """

    with Session(engine) as session, session.begin():
        if session.get(ResourcePool, profile.pool_id) is None:
            session.add(
                ResourcePool(
                    id=profile.pool_id,
                    label=profile.pool_label,
                    provider=profile.pool_provider,
                    enabled=True,
                    policy_tags=profile.pool_policy_tags(),
                )
            )
    _require_valid_pool_declarations(engine)


def _require_valid_pool_declarations(engine: Engine) -> None:
    failures: list[str] = []
    with Session(engine) as session:
        for pool in session.query(ResourcePool).order_by(ResourcePool.id):
            try:
                resolve_pool_declarations(pool.policy_tags or {})
            except PoolDeclarationError as exc:
                failures.append(f"pool '{pool.id}': {exc}")
    if failures:
        raise RuntimeError(
            "stored resource pools carry invalid declarations: " + "; ".join(failures)
        )


def load_pool_directory(
    session_factory: sessionmaker[Session],
) -> dict[str, dict[str, Any]]:
    """Each stored pool's metadata, as the resource-pool projection carries it."""

    with session_factory() as session:
        return {
            pool.id: {
                "label": pool.label,
                "enabled": bool(pool.enabled),
                "mechanism": pool.provider,
                "policy_tags": dict(pool.policy_tags or {}),
            }
            for pool in session.query(ResourcePool).all()
        }
