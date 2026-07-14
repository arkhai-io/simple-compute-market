"""Provider-neutral resource-pool persistence model.

Owns its own declarative ``Base``/metadata, matching the shape
``market_site`` already uses for the site-authority ledger: a domain
service composes this package's ``Base.metadata`` alongside its own at
``create_all`` time, and re-exports the ORM classes it needs through its
own ``db.models`` module so existing call sites keep working unchanged.
"""

from __future__ import annotations

from sqlalchemy import JSON, Boolean, Column, DateTime, String, func
from sqlalchemy.orm import declarative_base

Base = declarative_base()

DEFAULT_POOL_ID = "default"


class ResourcePool(Base):
    """A provider-neutral resource pool: identity, lifecycle, and policy tags.

    id:
        Operator-chosen slug (e.g. "hetzner-eu-central"). Not a UUID — pool
        ids appear in YAML definitions and are meant to be human-legible.
    enabled:
        False pools are excluded from scheduling eligibility. Delete is
        soft — disable — by default; pools are never hard-deleted by the
        admin API so that ``hosts.pool_id`` and any settlement records
        referencing this id remain resolvable.
    policy_tags:
        Free-form tag map (e.g. {"region": "eu", "provider": "hetzner"})
        used for tag-filtered pool lookup.

    Provider-specific configuration lives in a provider-owned side table
    (e.g. ``ansible_pool_configs``, domain-owned), resolved through the
    ``PoolConfigHandler`` protocol by explicit ``pool_id`` lookup — this
    model intentionally carries no ORM relationship to any provider-specific
    table, since a provider's config table lives in a different service's
    declarative registry.
    """

    __tablename__ = "resource_pools"

    id = Column(String, primary_key=True)
    label = Column(String, nullable=False)
    provider = Column(String, nullable=False)
    enabled = Column(Boolean, nullable=False, default=True)
    policy_tags = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
