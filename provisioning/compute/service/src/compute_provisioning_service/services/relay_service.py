"""Administration of tunnel rendezvous points.

A relay is a first-class resource rather than pool configuration because its
address, allocation window, and admission token are shared by every pool that
points at it. Held per pool, the window could differ between two pools drawing
from one listening namespace, and the token would be duplicated state whose
rotation is one write per pool with a missed one failing asynchronously in a
tunnel client's log.

The token is encrypted at rest under the deployment's ``ssh_decryption_key``,
the same key that protects embedded host key material. Nothing here returns it:
callers learn whether a token is configured, never what it is.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Iterable, Optional

from sqlalchemy.orm import Session

from compute_provisioning_service.crypto import encrypt_key
from compute_provisioning_service.db.models import Relay, RelayPortLease


class _Unset:
    """Distinguishes "not supplied" from an explicit ``None``.

    A partial update needs both: omitting a label leaves it alone, while
    supplying ``None`` clears it. Collapsing the two would make a field
    impossible to clear, and a reconciliation that cannot reach the state its
    document declares reports the same row changed on every pass without ever
    converging.
    """

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "<unset>"


UNSET = _Unset()


class RelayNotFoundError(LookupError):
    """No relay with the requested identifier."""


class RelayEndpointConflictError(ValueError):
    """Another relay already records this rendezvous.

    The unique constraint would catch it, but a constraint violation surfacing
    as a server error is not an administration surface, so the conflict is
    detected and reported with both identifiers named.
    """


class RelayValidationError(ValueError):
    """A supplied relay field is unusable."""


@dataclass(frozen=True)
class RelayView:
    """What a caller may see of a relay.

    Deliberately not the ORM row: ``relay_token_encrypted`` has no member here,
    so no serializer added later can reach a credential through this type.
    ``token_configured`` answers the question an operator actually has — is this
    relay usable — without disclosing the value.
    """

    id: str
    label: str | None
    relay_addr: str
    relay_port: int
    vm_port_range_start: int
    vm_port_range_count: int
    enabled: bool
    token_configured: bool

    @classmethod
    def of(cls, row: Relay) -> "RelayView":
        return cls(
            id=row.id,
            label=row.label,
            relay_addr=row.relay_addr,
            relay_port=row.relay_port,
            vm_port_range_start=row.vm_port_range_start,
            vm_port_range_count=row.vm_port_range_count,
            enabled=bool(row.enabled),
            token_configured=bool(row.relay_token_encrypted),
        )


class RelayService:
    def __init__(self, session_factory: Any, settings: Any | None = None) -> None:
        self._session_factory = session_factory
        self._settings = settings

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    def list_relays(self) -> list[RelayView]:
        with self._session_factory() as db:
            rows = db.query(Relay).order_by(Relay.id).all()
            return [RelayView.of(row) for row in rows]

    def get_relay(self, relay_id: str) -> RelayView:
        with self._session_factory() as db:
            return RelayView.of(self._require(db, relay_id))

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------

    def create_relay(
        self,
        *,
        relay_addr: str,
        relay_port: int,
        vm_port_range_start: int,
        vm_port_range_count: int,
        relay_id: str | None = None,
        label: str | None = None,
        token: str | None = None,
        enabled: bool = True,
    ) -> RelayView:
        with self._session_factory() as db, db.begin():
            addr = self._validated_addr(relay_addr)
            self._validate_window(vm_port_range_start, vm_port_range_count)
            self._reject_duplicate_endpoint(db, addr, relay_port, excluding=None)
            row = Relay(
                id=relay_id or str(uuid.uuid4()),
                label=label,
                relay_addr=addr,
                relay_port=int(relay_port),
                vm_port_range_start=int(vm_port_range_start),
                vm_port_range_count=int(vm_port_range_count),
                enabled=enabled,
            )
            if token:
                row.relay_token_encrypted = self._encrypt(token)
            db.add(row)
            db.flush()
            return RelayView.of(row)

    def update_relay(
        self,
        relay_id: str,
        *,
        label: str | None | _Unset = UNSET,
        relay_addr: str | None = None,
        relay_port: int | None = None,
        vm_port_range_start: int | None = None,
        vm_port_range_count: int | None = None,
        enabled: bool | None = None,
    ) -> RelayView:
        """Change a relay's location, window, or availability.

        An omitted field is unchanged. There is deliberately no token parameter:
        rotation is its own operation, because it is the one write whose effect
        is invisible in every subsequent read and should be requested rather
        than carried along by an edit to something else.
        """
        with self._session_factory() as db, db.begin():
            row = self._require(db, relay_id)
            addr = row.relay_addr if relay_addr is None else self._validated_addr(relay_addr)
            port = row.relay_port if relay_port is None else int(relay_port)
            if addr != row.relay_addr or port != row.relay_port:
                self._reject_duplicate_endpoint(db, addr, port, excluding=row.id)
            start = (
                row.vm_port_range_start
                if vm_port_range_start is None
                else int(vm_port_range_start)
            )
            count = (
                row.vm_port_range_count
                if vm_port_range_count is None
                else int(vm_port_range_count)
            )
            self._validate_window(start, count)

            row.relay_addr = addr
            row.relay_port = port
            row.vm_port_range_start = start
            row.vm_port_range_count = count
            if not isinstance(label, _Unset):
                row.label = label
            if enabled is not None:
                row.enabled = enabled
            db.flush()
            return RelayView.of(row)

    def rotate_token(self, relay_id: str, token: str) -> RelayView:
        """Replace a relay's admission token.

        There is no way to clear a token through this interface. Clearing one
        disables every VM path on that relay, so it is not something a partial
        write should be able to express by omission.
        """
        if not token or not token.strip():
            raise RelayValidationError("relay token must be a non-empty string")
        with self._session_factory() as db, db.begin():
            row = self._require(db, relay_id)
            row.relay_token_encrypted = self._encrypt(token)
            db.flush()
            return RelayView.of(row)

    def set_enabled(self, relay_id: str, enabled: bool) -> RelayView:
        return self.update_relay(relay_id, enabled=enabled)

    # ------------------------------------------------------------------
    # Seeding support
    # ------------------------------------------------------------------

    def find_by_endpoint(
        self, db: Session, relay_addr: str, relay_port: int
    ) -> Optional[Relay]:
        return (
            db.query(Relay)
            .filter(
                Relay.relay_addr == Relay.normalize_addr(relay_addr),
                Relay.relay_port == int(relay_port),
            )
            .one_or_none()
        )

    def held_ports(self, relay_id: str) -> list[int]:
        """Remote ports currently leased on a relay.

        Exposed because deciding what deletion should do to a relay with live
        leases needs the answer, and because an operator asking "what is this
        relay carrying" should not have to read the database.
        """
        with self._session_factory() as db:
            rows = (
                db.query(RelayPortLease)
                .filter(
                    RelayPortLease.relay_id == relay_id,
                    RelayPortLease.released_at.is_(None),
                )
                .all()
            )
            return sorted(row.remote_port for row in rows)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _require(db: Session, relay_id: str) -> Relay:
        row = db.get(Relay, relay_id)
        if row is None:
            raise RelayNotFoundError(f"Relay '{relay_id}' not found")
        return row

    @staticmethod
    def _validated_addr(relay_addr: str) -> str:
        if not isinstance(relay_addr, str) or not relay_addr.strip():
            raise RelayValidationError("relay_addr must be a non-empty string")
        return Relay.normalize_addr(relay_addr)

    @staticmethod
    def _validate_window(start: Any, count: Any) -> None:
        for name, value in (("vm_port_range_start", start), ("vm_port_range_count", count)):
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise RelayValidationError(f"{name} must be a positive integer")
        if int(start) + int(count) - 1 > 65535:
            raise RelayValidationError(
                "vm_port_range_start and vm_port_range_count describe ports above 65535"
            )

    def _reject_duplicate_endpoint(
        self, db: Session, addr: str, port: int, *, excluding: str | None
    ) -> None:
        existing: Iterable[Relay] = (
            db.query(Relay)
            .filter(Relay.relay_addr == addr, Relay.relay_port == int(port))
            .all()
        )
        for row in existing:
            if row.id != excluding:
                raise RelayEndpointConflictError(
                    f"Relay '{row.id}' already records rendezvous {addr}:{port}"
                )

    def _encrypt(self, token: str) -> str:
        secret = str(getattr(self._settings, "ssh_decryption_key", "") or "")
        return encrypt_key(token, secret)
