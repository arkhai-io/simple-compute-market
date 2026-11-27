"""The registry's admission core, through which every signed route admits its requests.

The registry authenticates inside its routes, in the core's dependency form: each
route takes a :class:`~market_authenticated_requests.RouteAdmission` naming its
operation, the roles it admits, how an exact retry is resolved, and, for an
operation acting on one object, how that object's identifier is derived. The
descriptor read is the one public operation.

The core is built as the routes are imported, but the registry opens its database
only once startup has found it compatible with the migrations, and loads its
signing credential only then. So the signer and the replay store are bound at
startup (:func:`bind`): the store over an engine of its own on the registry's
database, since the application's SQLite engine shares one connection between its
sessions, and a replay step's transaction must not interleave with a request's.

Trust admits any principal whose signature verifies, under any role a route
admits: the registry is open to every publisher, and each write route checks that
the principal owns what it acts on.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from market_authenticated_requests import AdmissionCore, AuthenticatedRequestsSettings
from market_identity import Identity, Signer
from request_replay import Entry, Outcome, ReplayStore, Row

from core_registry.config import settings

#: The roles a read admits; a write admits only a seller.
READ_ROLES = frozenset({"buyer", "seller", "service"})
WRITE_ROLES = frozenset({"seller"})


class AnyVerifiedPrincipal:
    """Trusts every principal whose signature verified."""

    def allows(self, identity: Identity) -> bool:
        return True


_TRUST = AnyVerifiedPrincipal()


@dataclass
class _Binding:
    signer: Signer | None = None
    store: ReplayStore | None = field(default=None, repr=False)


_bound = _Binding()


def bind(*, signer: Signer, store: ReplayStore) -> None:
    """Bind the registry's signing identity and its replay store, at startup."""

    _bound.signer = signer
    _bound.store = store


def bound_signer() -> Signer:
    """The registry's signing identity, once startup has bound it."""

    if _bound.signer is None:
        raise RuntimeError("the registry's signing identity is not bound")
    return _bound.signer


class _BoundStore:
    """The replay store startup bound, step by step."""

    def _store(self) -> ReplayStore:
        if _bound.store is None:
            raise RuntimeError("the registry's replay store is not bound")
        return _bound.store

    def claim(self, entry: Entry, *, now: int, expires_at: int, lease_until: int, owner: str) -> Row | None:
        return self._store().claim(entry, now=now, expires_at=expires_at, lease_until=lease_until, owner=owner)

    def reclaim(self, entry: Entry, *, now: int, expires_at: int, lease_until: int, owner: str) -> bool:
        return self._store().reclaim(entry, now=now, expires_at=expires_at, lease_until=lease_until, owner=owner)

    def renew(self, principal: str, request_id: str, owner: str, *, now: int, lease_until: int) -> bool:
        return self._store().renew(principal, request_id, owner, now=now, lease_until=lease_until)

    def conclude(self, entry: Entry, *, now: int) -> Row | None:
        return self._store().conclude(entry, now=now)

    def record(self, principal: str, request_id: str, owner: str, outcome: Outcome) -> bool:
        return self._store().record(principal, request_id, owner, outcome)

    def release(self, principal: str, request_id: str, owner: str) -> bool:
        return self._store().release(principal, request_id, owner)

    def get(self, principal: str, request_id: str, *, now: int) -> Row | None:
        return self._store().get(principal, request_id, now=now)

    def sweep_batch(self, *, now: int, limit: int) -> int:
        return self._store().sweep_batch(now=now, limit=limit)


registry_core = AdmissionCore(
    signer=bound_signer,
    trust=lambda role: _TRUST,
    store=_BoundStore(),
    settings=AuthenticatedRequestsSettings.model_validate(settings.authenticated_requests.model_dump()),
)
