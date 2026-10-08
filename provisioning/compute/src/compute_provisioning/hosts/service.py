"""The host authority: the compute family's registry of hosts jobs run against.

It owns each host's identity, pool, enabled state, and connection envelope, the
lookup made immediately before execution, and applying an imported inventory. It
knows no connection kind: a submitted connection is validated, and its secrets
protected, by the kind's codec, and what it stores is the resulting envelope.

Every ordinary read returns a ``HostResponse``, which names each protected value
and its scheme but never carries its ciphertext; the persistence row never leaves
this module. Only ``lookup``, the read made immediately before execution, returns
the full protected envelope, inside an ``ExecutionHost``.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Optional, Protocol

from market_resource_pools import DEFAULT_POOL_ID, ResourcePool
from sqlalchemy.orm import Session, sessionmaker

from .connection import ConnectionCodecs, ConnectionEnvelope
from .db import Host
from .execution import ExecutionHost
from compute_provisioning_contracts import ConnectionSubmission, ConnectionView, HostCreate, HostResponse, HostUpdate

logger = logging.getLogger(__name__)


class HostNotFoundError(Exception):
    """Raised when a requested host_id does not exist."""


class PoolChangeRefusedError(ValueError):
    """A pool-change hook refused moving a host to another pool.

    The request is well formed and may succeed once whatever the subscriber
    protects is gone, so it is a conflict with current state rather than a bad
    request.
    """


class HostCapacityDerivation(Protocol):
    """Derives capacity declarations from hosts' legacy capacity.

    Supplied by the composition root. Host inventory is connection identity;
    what a site sells is declared elsewhere, so the authority applies imported
    hosts and leaves deciding their declarations to the port.
    """

    def serialized(self) -> AbstractContextManager[None]:
        """The capacity authority's serialization lock, held around the whole
        transaction a derivation writes into, through its commit."""
        ...

    def derive_in_session(
        self, db: Session, host_ids: Sequence[str] | None = None
    ) -> Sequence[str]:
        """Derive declarations for ``host_ids`` inside ``db``'s transaction."""
        ...


#: Called inside the transaction moving a host between pools, before it
#: commits, with ``(db, host_id, current_pool_id, new_pool_id)``. A hook refuses
#: the move by raising ``PoolChangeRefusedError``, which rolls back the whole
#: transaction. Every pool assignment of an existing host goes through the hooks,
#: whether it comes from an update or an imported inventory, so no path moves a
#: host around a subscriber.
PoolChangeHook = Callable[[Session, str, str, str], None]


@dataclass(frozen=True)
class InventoryHost:
    """One host an imported inventory declares."""

    host_id: str
    connection: ConnectionSubmission
    gpu_count: int = 0
    gpu_model: Optional[str] = None
    pool_id: str = DEFAULT_POOL_ID


def _view(host: Host) -> HostResponse:
    """A host as every ordinary read returns it: protected values by scheme only."""
    connection = host.connection()
    return HostResponse(
        host_id=host.host_id,
        connection=ConnectionView(
            kind=connection.kind,
            version=connection.version,
            public=dict(connection.public),
            protected=connection.protected_schemes(),
        ),
        gpu_count=host.gpu_count,
        gpu_model=host.gpu_model,
        enabled=host.enabled,
        pool_id=host.pool_id,
        created_at=host.created_at,
        updated_at=host.updated_at,
    )


class HostAuthority:
    """CRUD, lookup, and inventory application for the ``hosts`` registry."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        codecs: ConnectionCodecs,
        capacity_derivation: HostCapacityDerivation,
        pool_change_hooks: Sequence[PoolChangeHook] = (),
    ) -> None:
        self._session_factory = session_factory
        self._codecs = codecs
        self._capacity_derivation = capacity_derivation
        self._pool_change_hooks = tuple(pool_change_hooks)

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    def list_hosts(
        self, search: Optional[str] = None, enabled_only: bool = True
    ) -> list[HostResponse]:
        """Hosts ordered by ``host_id``, optionally only enabled ones, optionally
        filtered by a case-insensitive substring of ``host_id``."""
        with self._session_factory() as db:
            query = db.query(Host)
            if enabled_only:
                query = query.filter(Host.enabled.is_(True))
            if search:
                query = query.filter(Host.host_id.ilike(f"%{search}%"))
            return [_view(host) for host in query.order_by(Host.host_id).all()]

    def get_host(self, host_id: str) -> Optional[HostResponse]:
        with self._session_factory() as db:
            host = db.query(Host).filter(Host.host_id == host_id).one_or_none()
            return _view(host) if host is not None else None

    def lookup(self, host_id: str) -> Optional[ExecutionHost]:
        """The host a job runs against, read immediately before execution.

        ``None`` when no such host is registered: a job then fails before any
        executor runs, because there is no fallback inventory to run against.
        """
        with self._session_factory() as db:
            host = db.query(Host).filter(Host.host_id == host_id).one_or_none()
            if host is None:
                return None
            return ExecutionHost(
                host_id=host.host_id, pool_id=host.pool_id, connection=host.connection()
            )

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------

    def register_host(self, data: HostCreate) -> HostResponse:
        connection = self._build(data.connection, previous=None)
        pool_id = data.pool_id or DEFAULT_POOL_ID
        host = Host(
            host_id=data.host_id,
            gpu_count=data.gpu_count,
            gpu_model=data.gpu_model,
            enabled=data.enabled,
            pool_id=pool_id,
        )
        host.set_connection(connection)
        with self._session_factory() as db:
            self._require_pool_exists(db, pool_id)
            db.add(host)
            db.commit()
            db.refresh(host)
            return _view(host)

    def update_host(self, host_id: str, data: HostUpdate) -> HostResponse:
        with self._session_factory() as db:
            host = self._require_host(db, host_id)
            if data.connection is not None:
                host.set_connection(
                    self._build(data.connection, previous=host.connection())
                )
            if data.gpu_count is not None:
                host.gpu_count = data.gpu_count
            if data.gpu_model is not None:
                host.gpu_model = data.gpu_model
            if data.enabled is not None:
                host.enabled = data.enabled
            if data.pool_id is not None:
                self._move_to_pool(db, host, data.pool_id)
            db.commit()
            db.refresh(host)
            return _view(host)

    def enable_host(self, host_id: str) -> HostResponse:
        return self._set_enabled(host_id, True)

    def disable_host(self, host_id: str) -> HostResponse:
        """Exclude a host from new work; it is never deleted, so job history
        naming it stays resolvable."""
        return self._set_enabled(host_id, False)

    def apply_inventory(self, entries: Sequence[InventoryHost]) -> list[HostResponse]:
        """Upsert the hosts an imported inventory declares; leave the rest alone.

        Idempotent for the same input. Capacity is derived for the upserted
        hosts in the same transaction, so a host applied from an inventory and
        the declaration derived from its legacy capacity land together. A
        declaration already naming a host keeps it. An existing host's pool
        changes through the pool-change hooks, as an update's does; a hook's
        refusal rolls back the whole inventory.
        """
        if not entries:
            logger.warning("apply_inventory: no host entries to apply")
            return []
        applied: list[str] = []
        with self._capacity_derivation.serialized(), self._session_factory() as db:
            for entry in entries:
                self._require_pool_exists(db, entry.pool_id)
                existing = db.query(Host).filter(Host.host_id == entry.host_id).one_or_none()
                if existing is None:
                    host = Host(host_id=entry.host_id, enabled=True, pool_id=entry.pool_id)
                    host.set_connection(self._build(entry.connection, previous=None))
                    db.add(host)
                else:
                    host = existing
                    host.set_connection(
                        self._build(entry.connection, previous=existing.connection())
                    )
                    self._move_to_pool(db, host, entry.pool_id)
                host.gpu_count = entry.gpu_count
                host.gpu_model = entry.gpu_model
                applied.append(entry.host_id)
            self._capacity_derivation.derive_in_session(db, applied)
            db.commit()

        hosts: list[HostResponse] = []
        with self._session_factory() as db:
            for host_id in applied:
                host = db.query(Host).filter(Host.host_id == host_id).one_or_none()
                if host is not None:
                    hosts.append(_view(host))
        # Every entry of an inventory is registered whatever its section, so
        # name them: an infrastructure server in the file shows up here.
        logger.info(
            "apply_inventory: applied %d host(s): %s",
            len(hosts),
            ", ".join(sorted(host.host_id for host in hosts)),
        )
        return hosts

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _build(
        self, submission: ConnectionSubmission, *, previous: ConnectionEnvelope | None
    ) -> ConnectionEnvelope:
        return self._codecs.build(
            submission.kind,
            submission.version,
            submission.public,
            submission.secrets,
            previous=previous,
        )

    def _move_to_pool(self, db: Session, host: Host, pool_id: str) -> None:
        """Assign ``pool_id`` to an existing host; a real move runs the hooks."""
        self._require_pool_exists(db, pool_id)
        if host.pool_id == pool_id:
            return
        for hook in self._pool_change_hooks:
            hook(db, host.host_id, host.pool_id, pool_id)
        host.pool_id = pool_id

    def _set_enabled(self, host_id: str, enabled: bool) -> HostResponse:
        with self._session_factory() as db:
            host = self._require_host(db, host_id)
            host.enabled = enabled
            db.commit()
            db.refresh(host)
            return _view(host)

    @staticmethod
    def _require_host(db: Session, host_id: str) -> Host:
        host = db.query(Host).filter(Host.host_id == host_id).one_or_none()
        if host is None:
            raise HostNotFoundError(f"Host '{host_id}' not found")
        return host

    @staticmethod
    def _require_pool_exists(db: Session, pool_id: str) -> None:
        if db.query(ResourcePool).filter(ResourcePool.id == pool_id).one_or_none() is None:
            raise ValueError(f"Pool '{pool_id}' does not exist")


__all__ = [
    "HostAuthority",
    "HostCapacityDerivation",
    "HostNotFoundError",
    "InventoryHost",
    "PoolChangeHook",
]
