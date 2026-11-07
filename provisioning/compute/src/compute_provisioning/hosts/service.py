"""The host authority: the compute family's registry of hosts jobs run against.

It owns each host's identity, pool, enabled state, and connection envelope, the
lookup made immediately before execution, and applying an imported inventory or
a host definitions document. It knows no connection kind: a submitted connection
is validated, and its secrets protected, by the kind's codec, and what it stores
is the resulting envelope.

A write either runs in a transaction of its own or, as ``put_host_in_session``,
joins a caller's session and leaves committing to the caller, so several hosts
and a caller's own records, such as a document's digest, commit or roll back
together.

A host is connection identity and placement, never capacity or hardware: no
host write declares anything a site sells, and a host records nothing about the
machine's hardware. Both are declared through the site's own administration.

Every ordinary read returns a ``HostResponse``, which names each protected value
and its scheme but never carries its ciphertext; the persistence row never leaves
this module. Only the internal reads return the full protected envelope, inside
an ``ExecutionHost``: ``lookup``, made immediately before execution, and
``execution_hosts``, which an executor's readiness reads to check each host as
execution would. No route serves either, and every API, log, and error surface
carries a protected value's scheme only.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Literal, Optional

from market_resource_pools import ResourcePool
from sqlalchemy.orm import Session, sessionmaker

from .connection import ConnectionCodecs, ConnectionEnvelope
from .db import Host
from .execution import ExecutionHost
from compute_provisioning_contracts import (
    ConnectionSubmission,
    ConnectionView,
    HostCreate,
    HostDefinition,
    HostDefinitionConnection,
    HostResponse,
    HostUpdate,
)

logger = logging.getLogger(__name__)


class HostNotFoundError(Exception):
    """Raised when a requested host_id does not exist."""


class UnknownPoolError(ValueError):
    """A host write named a pool that does not exist."""


class PoolChangeRefusedError(ValueError):
    """A pool-change hook refused moving a host to another pool, or to none.

    The request is well formed and may succeed once whatever the subscriber
    protects is gone, so it is a conflict with current state rather than a bad
    request.
    """


class ConnectionChangeRefusedError(PoolChangeRefusedError):
    """A connection-change hook refused a new connection for a placed host.

    A pool-change refusal's kind, because both refuse a write that a rule
    about a pool's hosts forbids, and every caller answers them alike: as a
    conflict with current state.
    """


#: Called inside the transaction moving a host between pools, before it
#: commits, with ``(db, host_id, current_pool_id, new_pool_id)``; either pool is
#: ``None`` for an unplaced host, so unplacing a host is a move like any other.
#: A hook refuses the move by raising ``PoolChangeRefusedError``, which rolls
#: back the whole transaction. Every pool assignment goes through the hooks,
#: whether it comes from a registration, an update, an imported inventory, or a
#: host definitions document, so no path moves a host around a subscriber.
PoolChangeHook = Callable[[Session, str, Optional[str], Optional[str]], None]

#: Called inside the transaction that gives a placed host a new connection,
#: before it commits, with ``(db, host_id, pool_id)``; the session already holds
#: the new connection. A hook refuses it by raising
#: ``ConnectionChangeRefusedError``, which rolls back the whole transaction. A
#: write that also moves the host runs the pool-change hooks instead, which see
#: the new connection, so each write runs one set of checks. With the
#: pool-change hooks, a rule about which connections a pool's hosts may have
#: sees every host write that could break it.
ConnectionChangeHook = Callable[[Session, str, str], None]


class PoolUnstated(Enum):
    """The type of :data:`POOL_UNSTATED`."""

    POOL_UNSTATED = "pool-unstated"


#: An inventory entry that says nothing about its host's pool. It differs from
#: ``None``, which unplaces the host: an entry that does not mention a pool
#: leaves an existing host where it is, so re-importing an older inventory
#: never unplaces hosts placed since through the API.
POOL_UNSTATED = PoolUnstated.POOL_UNSTATED

#: What a session-scoped write did to the host it names.
HostChange = Literal["created", "updated", "unchanged"]


@dataclass(frozen=True)
class InventoryHost:
    """One host an imported inventory declares.

    ``pool_id`` names the pool to place or move the host in, is ``None`` to
    unplace it, or is :data:`POOL_UNSTATED` to leave an existing host's pool
    as it is; a new host with no pool stated is created unplaced.
    """

    host_id: str
    connection: ConnectionSubmission
    pool_id: Optional[str] | Literal[PoolUnstated.POOL_UNSTATED] = POOL_UNSTATED


def _same_connection(built: ConnectionEnvelope, stored: ConnectionEnvelope) -> bool:
    """Whether a connection its codec built states exactly the stored one.

    Compared after the codec, so a field the codec defaults equals a stored
    default; protected values compare by scheme, since a kept value is carried
    forward as it is and a resubmitted one is never equal ciphertext. So this
    answers only for a submission carrying no secret: one that carries a secret
    cannot be compared with what is stored, and its caller replaces the stored
    connection instead.
    """
    return (
        built.kind == stored.kind
        and built.version == stored.version
        and dict(built.public) == dict(stored.public)
        and built.protected_schemes() == stored.protected_schemes()
    )


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
        enabled=host.enabled,
        pool_id=host.pool_id,
        created_at=host.created_at,
        updated_at=host.updated_at,
    )


def _execution_host(host: Host) -> ExecutionHost:
    """A host as an internal read returns it: its full protected envelope."""
    return ExecutionHost(host_id=host.host_id, pool_id=host.pool_id, connection=host.connection())


class HostAuthority:
    """CRUD, the internal reads for execution and readiness, inventory
    application, and the session-scoped write a host definitions document
    applies through, for the ``hosts`` registry."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        codecs: ConnectionCodecs,
        pool_change_hooks: Sequence[PoolChangeHook] = (),
        connection_change_hooks: Sequence[ConnectionChangeHook] = (),
    ) -> None:
        self._session_factory = session_factory
        self._codecs = codecs
        self._pool_change_hooks = tuple(pool_change_hooks)
        self._connection_change_hooks = tuple(connection_change_hooks)

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
            return _execution_host(host)

    def execution_hosts(self, *, enabled_only: bool = True) -> list[ExecutionHost]:
        """Every host as an executor reads it, for that executor's readiness.

        One query, ordered by ``host_id``; with ``enabled_only``, disabled hosts
        are left out. Each host carries its full connection envelope, protected
        values included, so the executor can check each connection exactly as it
        would execute against it. No route serves this read.
        """
        with self._session_factory() as db:
            query = db.query(Host)
            if enabled_only:
                query = query.filter(Host.enabled.is_(True))
            return [_execution_host(host) for host in query.order_by(Host.host_id)]

    @staticmethod
    def host_ids_in_session(db: Session) -> list[str]:
        """Every registered host's id, in the caller's session, ordered."""
        return [host_id for (host_id,) in db.query(Host.host_id).order_by(Host.host_id)]

    def deliverable_host_ids(self, db: Session) -> frozenset[str]:
        """The hosts taking new delivery: every registered, enabled host's id.

        Read in the caller's session, so site admission, scheduling, and the
        site's offered read judge a declaration against the host state of the
        transaction that decides. A host with no record is never in it, so a
        declaration naming an unregistered host has no usable host. This is
        the only host fact those layers learn: identifiers, never a
        connection.
        """
        return frozenset(
            host_id
            for (host_id,) in db.query(Host.host_id).filter(Host.enabled.is_(True))
        )

    def host_definitions(self) -> list[HostDefinition]:
        """Every host a host definitions entry can state, ordered by ``host_id``.

        An entry states the host's pool, enabled state, and its connection's
        kind, version, and canonical public fields, never a protected value: a
        host whose key is protected states no key path, which an entry reads as
        keeping the stored key. A host whose connection kind no codec serves, or
        whose stored version its codec does not serve, cannot be stated at a
        version this service would accept, so it is left out; a document built
        from these entries then does not name it, and leaves it as it is.

        Every other host is stated as stored, even where an import would refuse
        the entry, such as a connection its codec now refuses: the entries are
        constructed without validation, so one such host neither fails the
        export nor goes missing from it, and importing the export reports it.
        """
        definitions: list[HostDefinition] = []
        with self._session_factory() as db:
            for host in db.query(Host).order_by(Host.host_id):
                canonical = self._codecs.canonical(host.connection())
                if canonical is None:
                    continue
                definitions.append(
                    HostDefinition.model_construct(
                        host_id=host.host_id,
                        pool_id=host.pool_id,
                        enabled=host.enabled,
                        connection=HostDefinitionConnection.model_construct(
                            kind=canonical.kind, version=canonical.version, public=dict(canonical.public)
                        ),
                    )
                )
        return definitions

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------

    def session(self) -> Session:
        """A new session over the registry's database.

        For a caller composing several session-scoped writes into one
        transaction it decides to commit or roll back; the caller owns the
        session and closes it.
        """
        return self._session_factory()

    def put_host_in_session(
        self,
        db: Session,
        host_id: str,
        connection: ConnectionSubmission,
        *,
        pool_id: Optional[str] | Literal[PoolUnstated.POOL_UNSTATED] = POOL_UNSTATED,
        enabled: Optional[bool] = None,
    ) -> HostChange:
        """Register a host or replace what the arguments state, in ``db``.

        Never commits: the caller commits or rolls back the whole session. The
        connection is built through its kind's codec, with the stored one as
        the previous connection, so a stored protected value it still needs is
        kept. ``pool_id`` places or moves the host, ``None`` unplaces it, and
        :data:`POOL_UNSTATED` leaves an existing host's pool alone; ``enabled``
        set replaces the enabled state, and ``None`` leaves an existing host's
        alone. A new host is created enabled unless ``enabled`` says otherwise,
        and unplaced unless a pool is stated.

        A host whose built connection, pool, and enabled state equal the stored
        ones is written nothing and runs no hook. A connection submitted with a
        secret never equals the stored one, since newly protected material
        cannot be compared with stored ciphertext: an imported inventory
        embedding a rotated key replaces the stored key rather than keeping it.
        A new host stating a pool is placed as a move from no pool, and a moved
        host's new connection is in the session before the pool-change hooks
        run, so a rule about which connections a pool's hosts may have sees the
        host as it will be; a placed host given a new connection without a move
        runs the connection-change hooks instead.

        Raises ``UnknownPoolError`` for a stated pool that does not exist and
        ``ValueError`` for a connection the codec refuses, both before writing,
        and ``PoolChangeRefusedError`` when a hook refuses the move or the new
        connection.
        """
        stated = pool_id is not POOL_UNSTATED
        if stated and pool_id is not None:
            self._require_pool_exists(db, pool_id)
        existing = db.query(Host).filter(Host.host_id == host_id).one_or_none()
        if existing is None:
            host = Host(
                host_id=host_id,
                enabled=True if enabled is None else enabled,
                pool_id=None,
            )
            host.set_connection(self._build(connection, previous=None))
            db.add(host)
            if stated and pool_id is not None:
                # Flushed so a hook's query of the host finds it: the service's
                # sessions do not autoflush.
                db.flush()
                self._move_to_pool(db, host, pool_id)
            return "created"
        stored = existing.connection()
        built = self._build(connection, previous=stored)
        target_pool = pool_id if stated else existing.pool_id
        target_enabled = existing.enabled if enabled is None else enabled
        # The stored side is compared in its codec's canonical form too, so a
        # row stored before its codec's current normalization still equals an
        # entry stating it.
        canonical = self._codecs.canonical(stored)
        same_connection = (
            not connection.secrets
            and canonical is not None
            and _same_connection(built, canonical)
        )
        if (
            same_connection
            and target_pool == existing.pool_id
            and target_enabled == existing.enabled
        ):
            return "unchanged"
        if not same_connection:
            existing.set_connection(built)
        moved = self._move_to_pool(db, existing, target_pool)
        if not same_connection and not moved:
            self._connection_changed(db, existing)
        existing.enabled = target_enabled
        return "updated"

    def register_host(self, data: HostCreate) -> HostResponse:
        """Register a host in the pool it names, or unplaced when it names none."""
        connection = self._build(data.connection, previous=None)
        host = Host(host_id=data.host_id, enabled=data.enabled, pool_id=None)
        host.set_connection(connection)
        with self._session_factory() as db:
            db.add(host)
            db.flush()
            # Placed as a move from no pool, so a rule about which hosts a pool
            # may hold sees a host registered into it as it sees one moved in.
            self._move_to_pool(db, host, data.pool_id)
            db.commit()
            db.refresh(host)
            return _view(host)

    def update_host(self, host_id: str, data: HostUpdate) -> HostResponse:
        """Apply the fields ``data`` sets; an omitted field is left as it is.

        ``pool_id`` is the one field whose ``None`` means something: set
        explicitly, it unplaces the host, through the pool-change hooks.
        """
        with self._session_factory() as db:
            host = self._require_host(db, host_id)
            if data.connection is not None:
                host.set_connection(
                    self._build(data.connection, previous=host.connection())
                )
            if data.enabled is not None:
                host.enabled = data.enabled
            moved = False
            if "pool_id" in data.model_fields_set:
                moved = self._move_to_pool(db, host, data.pool_id)
            if data.connection is not None and not moved:
                self._connection_changed(db, host)
            db.commit()
            db.refresh(host)
            return _view(host)

    def enable_host(self, host_id: str) -> HostResponse:
        return self._set_enabled(host_id, True)

    def disable_host(self, host_id: str) -> HostResponse:
        """Exclude a host from new work; it is never deleted, so job history
        naming it stays resolvable.

        A disabled host leaves ``deliverable_host_ids``, so no declaration
        naming it, in a backed pool whose provider needs a host, is admitted,
        placed, or offered; work already placed on it keeps it, and its create
        is refused at submission until it is enabled.
        """
        return self._set_enabled(host_id, False)

    def apply_inventory(self, entries: Sequence[InventoryHost]) -> list[HostResponse]:
        """Upsert the hosts an imported inventory declares; leave the rest alone.

        Idempotent for the same input, and one transaction. An entry stating a
        pool places or moves its host and one stating ``None`` unplaces it,
        through the pool-change hooks, as an update does; an entry stating none
        leaves an existing host's pool alone and creates a new host unplaced. A
        hook's refusal rolls back the whole inventory.
        """
        if not entries:
            logger.warning("apply_inventory: no host entries to apply")
            return []
        applied: list[str] = []
        with self._session_factory() as db:
            for entry in entries:
                # An inventory entry cannot state ``enabled``, so an existing
                # host keeps its own.
                self.put_host_in_session(
                    db, entry.host_id, entry.connection, pool_id=entry.pool_id
                )
                applied.append(entry.host_id)
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

    def _move_to_pool(self, db: Session, host: Host, pool_id: Optional[str]) -> bool:
        """Assign ``pool_id`` to a host, or unplace it for ``None``; a real move
        runs the hooks, and is reported as ``True``. A host placed as it is
        registered moves from no pool, so the hooks see it in the session, with
        its connection."""
        if pool_id is not None:
            self._require_pool_exists(db, pool_id)
        if host.pool_id == pool_id:
            return False
        for hook in self._pool_change_hooks:
            hook(db, host.host_id, host.pool_id, pool_id)
        host.pool_id = pool_id
        return True

    def _connection_changed(self, db: Session, host: Host) -> None:
        """Run the connection-change hooks for a host given a new connection
        in place: an unplaced host has no pool whose rule could refuse it."""
        if host.pool_id is None:
            return
        for hook in self._connection_change_hooks:
            hook(db, host.host_id, host.pool_id)

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
            raise UnknownPoolError(f"Pool '{pool_id}' does not exist")


__all__ = [
    "ConnectionChangeHook",
    "ConnectionChangeRefusedError",
    "HostAuthority",
    "HostChange",
    "HostNotFoundError",
    "InventoryHost",
    "POOL_UNSTATED",
    "PoolChangeHook",
    "PoolChangeRefusedError",
    "PoolUnstated",
    "UnknownPoolError",
]
