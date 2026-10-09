"""The host registry's persistence: one row per registered host.

The table keeps its name, ``hosts``. A row holds the host's identity, pool,
enabled state, legacy capacity hint, and its connection as an envelope: the kind,
its version, the public fields, and the protected values exactly as the kind's
codec produced them. No column holds secret material in any other form.
"""

from __future__ import annotations

from sqlalchemy import JSON, Boolean, Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import declarative_base
from sqlalchemy.sql import func

from market_resource_pools import DEFAULT_POOL_ID, ResourcePool

from .connection import ConnectionEnvelope, ProtectedValue

Base = declarative_base()


class Host(Base):
    """A registered provisioning host.

    The single source of truth for host inventory: every lookup before
    execution reads this table, never an inventory file. Hosts are never
    hard-deleted, so job history naming a ``host_id`` stays resolvable; a
    disabled host is excluded from listings and lookups for new work.

    Every host has a pool; new rows default to the system-created ``default``
    pool at both the ORM and database layers.
    """

    __tablename__ = "hosts"

    host_id = Column(String, primary_key=True)
    connection_kind = Column(String, nullable=False)
    connection_version = Column(Integer, nullable=False, default=1, server_default="1")
    connection_public = Column(JSON, nullable=False, default=dict)
    connection_protected = Column(JSON, nullable=False, default=dict)
    gpu_count = Column(Integer, nullable=False, default=0)
    # Descriptive hardware identity (e.g. "H100"), matched by equality.
    # Nullable: a host with no GPU has none to report.
    gpu_model = Column(String, nullable=True)
    enabled = Column(Boolean, nullable=False, default=True)
    pool_id = Column(
        String,
        ForeignKey(ResourcePool.__table__.c.id),
        nullable=False,
        default=DEFAULT_POOL_ID,
        server_default=DEFAULT_POOL_ID,
    )
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    def connection(self) -> ConnectionEnvelope:
        return ConnectionEnvelope(
            kind=self.connection_kind,
            version=int(self.connection_version),
            public=dict(self.connection_public or {}),
            protected={
                name: ProtectedValue.from_stored(value)
                for name, value in (self.connection_protected or {}).items()
            },
        )

    def set_connection(self, envelope: ConnectionEnvelope) -> None:
        self.connection_kind = envelope.kind
        self.connection_version = envelope.version
        self.connection_public = dict(envelope.public)
        self.connection_protected = envelope.stored_protected()


__all__ = ["Base", "Host"]
