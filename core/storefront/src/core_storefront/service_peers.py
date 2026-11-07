"""The service peer each site authority is trusted through.

A storefront's configuration names its service peers: each peer's role, the one
site it is bound to, and the principals that seed it. Seeding writes a peer into
the storefront's durable identity state once. From then on the principals that
authenticate the site are that state's, rotated through the two-proof rotation
operations, and configuration must keep covering them.

A site's callbacks and the responses its clients receive are verified against
the same active principals: :class:`ServicePeerTrust` holds each site's durable
records in memory, reloads them whenever an identity change commits, and
evaluates which are active at each verification, so a completed rotation reaches
both at once and needs no restart. See
openspec/specs/storefront-publication/spec.md#requirement-site-authority-principals-rotate-with-bounded-overlap.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
import time
from collections.abc import Callable, Iterable, Mapping
from functools import partial
from types import MappingProxyType
from typing import Any

from market_identity import Identity, RotationRequest, TrustedIdentitySet

from core_storefront.auth import AuthError
from core_storefront.identity_authority import (
    SERVICE_PEER_AUTHORITY,
    IdentitySubjectStatus,
    StorefrontIdentityAuthority,
)

logger = logging.getLogger(__name__)

#: The first wait before a background reload retries, and the longest; each
#: failure doubles the wait up to the longest.
RELOAD_RETRY_FIRST_SECONDS = 0.5
RELOAD_RETRY_MAX_SECONDS = 30.0

#: Peer ID to its role, the site it is bound to, and its configured principals,
#: as a storefront's configuration states its service peers.
ServicePeerConfigs = Mapping[str, tuple[str, str, TrustedIdentitySet]]

SERVICE_PEER_ROLE = "service"


class ServicePeerConfigurationError(ValueError):
    """Configured sites are not each bound to exactly one service peer."""


def _site_peer_ids(peers: ServicePeerConfigs, site_id: str) -> list[str]:
    return sorted(
        peer_id
        for peer_id, (role, peer_site, _principals) in peers.items()
        if role == SERVICE_PEER_ROLE and peer_site == site_id
    )


def require_one_service_peer_per_site(
    peers: ServicePeerConfigs, site_ids: Iterable[str]
) -> None:
    """Refuse configuration that binds a site to no service peer or to several.

    Every problem is named in one error, so an operator fixes them together.
    """

    problems: list[str] = []
    for site_id in sorted(set(site_ids)):
        bound = _site_peer_ids(peers, site_id)
        if not bound:
            problems.append(f"site {site_id!r} is bound to no service peer")
        elif len(bound) > 1:
            problems.append(
                f"site {site_id!r} is bound to {len(bound)} service peers "
                f"({', '.join(bound)}); exactly one is required"
            )
    if problems:
        raise ServicePeerConfigurationError("; ".join(problems))


def seed_service_peers(
    db_path: str, peers: ServicePeerConfigs, *, now: int | None = None
) -> None:
    """Write each configured service peer into durable identity state, idempotently.

    A peer seen for the first time needs exactly one configured principal, its
    primary. A peer already seeded keeps its durable principals, which may have
    rotated since; its configuration must still name its role and site and cover
    every principal durable state holds active.
    """

    timestamp = int(time.time()) if now is None else now
    authority = StorefrontIdentityAuthority(db_path)
    for peer_id, (role, site_id, principals) in peers.items():
        try:
            status = authority.status(
                authority=SERVICE_PEER_AUTHORITY,
                subject=peer_id,
            )
        except KeyError:
            if len(principals.identities) != 1:
                raise AuthError(
                    "A new service peer requires exactly one primary principal"
                ) from None
            status = authority.register_service_peer(
                peer_id=peer_id,
                role=role,
                site_id=site_id,
                principal=principals.identities[0],
                now=timestamp,
            )
        conn = sqlite3.connect(db_path)
        try:
            durable_peer = conn.execute(
                "SELECT role, site_id FROM service_peers WHERE peer_id=?",
                (peer_id,),
            ).fetchone()
        finally:
            conn.close()
        if durable_peer != (role, site_id):
            raise AuthError(
                "Service-peer config role/site differs from durable identity state"
            )
        configured = frozenset(principals.identities)
        active = status.active_principals(timestamp)
        if status.primary not in configured or not active.issubset(configured):
            raise AuthError(
                "Service-peer config does not cover durable active identities"
            )


def _site_peer_status(
    db_path: str, peers: ServicePeerConfigs, site_id: str
) -> IdentitySubjectStatus:
    """The durable identity status of the one service peer bound to a site.

    The peer's durable row must still carry its configured role and site, be
    active, and agree with its primary binding.
    """

    bound = _site_peer_ids(peers, site_id)
    if len(bound) != 1:
        raise AuthError(
            "Provisioning site must have exactly one configured service peer"
        )
    peer_id = bound[0]
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            """
            SELECT role, site_id, principal_scheme, principal_identifier, status
            FROM service_peers WHERE peer_id=?
            """,
            (peer_id,),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        raise AuthError("Configured provisioning service peer is not materialized")
    role, durable_site, scheme, identifier, peer_status = row
    if role != SERVICE_PEER_ROLE or durable_site != site_id:
        raise AuthError("Provisioning service peer binding differs from public config")
    if peer_status != "active":
        raise AuthError("Provisioning service peer is not active")
    try:
        status = StorefrontIdentityAuthority(db_path).status(
            authority=SERVICE_PEER_AUTHORITY,
            subject=peer_id,
        )
    except KeyError as exc:
        raise AuthError("Provisioning service peer trust binding is incomplete") from exc
    if status.primary != Identity(scheme=scheme, identifier=identifier):
        raise AuthError(
            "Provisioning service peer row differs from its durable primary binding"
        )
    return status


def _active_principals(status: IdentitySubjectStatus, now: int) -> frozenset[Identity]:
    principals = status.active_principals(now)
    if not principals:
        raise AuthError("Provisioning service peer has no active principal")
    return principals


class _TrustReloadingAuthority(StorefrontIdentityAuthority):
    """An identity authority whose binding changes reload a service-peer trust.

    The reload follows each change whether or not it committed: a reload reads
    what is durable, so an extra one is harmless, and a change that committed
    before failing must not leave the trust behind it. A reload that fails never
    replaces the change's own result or refusal; the trust then holds nothing
    until a background reload succeeds (:meth:`ServicePeerTrust.reload_after_change`).
    """

    def __init__(
        self, db_path: str, trust: ServicePeerTrust, **kwargs: Any
    ) -> None:
        super().__init__(db_path, **kwargs)
        self._trust = trust

    def register_subject(self, **kwargs: Any) -> IdentitySubjectStatus:
        try:
            return super().register_subject(**kwargs)
        finally:
            self._trust.reload_after_change()

    def register_service_peer(self, **kwargs: Any) -> IdentitySubjectStatus:
        try:
            return super().register_service_peer(**kwargs)
        finally:
            self._trust.reload_after_change()

    def apply_rotation(
        self, request: RotationRequest, **kwargs: Any
    ) -> IdentitySubjectStatus:
        try:
            return super().apply_rotation(request, **kwargs)
        finally:
            self._trust.reload_after_change()

    def complete_rotation(self, **kwargs: Any) -> IdentitySubjectStatus:
        try:
            return super().complete_rotation(**kwargs)
        finally:
            self._trust.reload_after_change()

    def retire(self, **kwargs: Any) -> IdentitySubjectStatus:
        try:
            return super().retire(**kwargs)
        finally:
            self._trust.reload_after_change()

    def disable(self, **kwargs: Any) -> IdentitySubjectStatus:
        try:
            return super().disable(**kwargs)
        finally:
            self._trust.reload_after_change()


class ServicePeerTrust:
    """Each configured site's service-peer principal records, held in memory.

    A site client verifies every response synchronously on the event loop, so
    the principals it verifies against must not be read from SQLite there: a
    read that meets a writer's commit can wait out SQLite's busy timeout and
    stall the loop. The trust therefore holds each site's durable binding
    records, loaded when the peers are seeded and reloaded whenever an identity
    change commits through :meth:`identity_authority`, and evaluates which of
    them are active at each verification. An overlap therefore ends on time with
    no reload, and a completed rotation or retirement reaches responses and
    callbacks alike without a restart.

    A site that durable state does not bind to exactly one active peer, or whose
    peer disagrees with its configuration, authenticates nothing: reading its
    trust raises the reason as an :class:`AuthError`.

    A reload that fails after a change committed does not fail the change. The
    records the trust held predate a change durable state already has, such as
    a disabled principal, so it drops them and holds nothing: every read refuses
    with a 503 :class:`AuthError` from memory, never retrying SQLite on the
    caller's thread, where a busy database would stall the event loop. A
    background reload retries off the loop, waiting longer after each failure,
    until one succeeds and the trust answers again.

    Reloads take one lock, and each reads durable state while holding it, so
    they install their loads in the order they ran: a slow reload never
    installs an older load over a newer one.

    ``retry_wait`` is how a background reload waits before each attempt, and
    ``start_retry`` how one is started; by default the retry runs on a daemon
    thread and waits with :func:`time.sleep`.
    """

    def __init__(
        self,
        db_path: str,
        peers: ServicePeerConfigs,
        *,
        clock: Callable[[], float] = time.time,
        retry_wait: Callable[[float], object] = time.sleep,
        start_retry: Callable[[Callable[[], None]], object] | None = None,
    ) -> None:
        self._db_path = db_path
        self._peers: ServicePeerConfigs = MappingProxyType(dict(peers))
        self._clock = clock
        self._retry_wait = retry_wait
        self._start_retry = start_retry or _start_daemon_thread
        self._reload_lock = threading.Lock()
        # Replaced whole by each reload, so a reader on another thread sees one
        # complete load or the next, never a mixture. None until the first load,
        # and again from a failed reload after a change until a retry succeeds.
        self._sites: Mapping[str, IdentitySubjectStatus | AuthError] | None = None
        # Whether a background reload is pending; read and set under the reload
        # lock, so a burst of failed reloads starts one retry.
        self._retrying = False

    @property
    def peers(self) -> ServicePeerConfigs:
        """The configured service peers this trust was built from."""
        return self._peers

    def seed(self, *, now: int | None = None) -> None:
        """Seed the configured peers into durable state, then load them."""
        seed_service_peers(self._db_path, self._peers, now=now)
        self.reload()

    def reload(self) -> None:
        """Read every configured site's peer records from durable state.

        Blocking: run it off the event loop once the storefront is serving.
        """
        with self._reload_lock:
            self._load_locked()

    def reload_after_change(self) -> None:
        """Reload after an identity change, never raising.

        A failure is logged, the trust drops what it held, and a background
        reload retries until one succeeds; the change itself stands as it
        committed or was refused.
        """
        with self._reload_lock:
            try:
                self._load_locked()
            except Exception:
                self._sites = None
                logger.exception(
                    "[IDENTITY] Service-peer trust could not be reloaded after an "
                    "identity change; it trusts no site until a retry succeeds"
                )
                if not self._retrying:
                    self._retrying = True
                    self._start_retry(self._retry_until_loaded)

    def _load_locked(self) -> None:
        self._sites = MappingProxyType(dict(self._read_sites()))

    def _read_sites(self) -> Mapping[str, IdentitySubjectStatus | AuthError]:
        """Each configured site's durable peer status, or why it has none."""
        loaded: dict[str, IdentitySubjectStatus | AuthError] = {}
        for site_id in {site_id for _role, site_id, _principals in self._peers.values()}:
            try:
                loaded[site_id] = _site_peer_status(self._db_path, self._peers, site_id)
            except AuthError as exc:
                loaded[site_id] = exc
        return loaded

    def _retry_until_loaded(self) -> None:
        """Reload, waiting longer after each failure, until one succeeds."""
        delay = RELOAD_RETRY_FIRST_SECONDS
        while True:
            self._retry_wait(delay)
            with self._reload_lock:
                try:
                    self._load_locked()
                except Exception as exc:
                    logger.warning(
                        "[IDENTITY] Service-peer trust reload failed again; "
                        "retrying in %.1fs: %s",
                        min(delay * 2, RELOAD_RETRY_MAX_SECONDS),
                        exc,
                    )
                else:
                    self._retrying = False
                    logger.info("[IDENTITY] Service-peer trust reloaded")
                    return
            delay = min(delay * 2, RELOAD_RETRY_MAX_SECONDS)

    def identity_authority(self, **kwargs: Any) -> StorefrontIdentityAuthority:
        """The identity authority whose every binding change reloads this trust."""
        return _TrustReloadingAuthority(self._db_path, self, **kwargs)

    def _site_status(self, site_id: str) -> IdentitySubjectStatus:
        sites = self._sites
        if sites is None:
            raise AuthError(
                "Service-peer trust is not loaded", status_code=503
            )
        status = sites.get(site_id)
        if status is None:
            raise AuthError(
                "Provisioning site must have exactly one configured service peer"
            )
        if isinstance(status, AuthError):
            raise AuthError(status.detail, status_code=status.status_code)
        return status

    def site_active_principals(self, site_id: str, *, now: int) -> frozenset[Identity]:
        """The principals that authenticate a site's callbacks at ``now``."""
        return _active_principals(self._site_status(site_id), now)

    def site_trusted_set(self, site_id: str) -> TrustedIdentitySet:
        """The site's active principals now, primary first, for a site client."""
        status = self._site_status(site_id)
        ordered = sorted(
            _active_principals(status, int(self._clock())),
            key=lambda principal: (
                principal != status.primary,
                principal.scheme.value,
                principal.identifier,
            ),
        )
        return TrustedIdentitySet(identities=tuple(ordered))

    def site_authorities(self, site_id: str) -> Callable[[], TrustedIdentitySet]:
        """A provider of the site's active principals, read at each call.

        A site client verifies each response against what it returns, so a
        response follows the site's rotation as its callbacks do. It reads only
        memory, never SQLite, so it may run on the event loop; while the trust
        holds nothing -- before its first load, or after a reload that failed
        until a retry succeeds -- it refuses with a 503 :class:`AuthError`.
        """
        return partial(self.site_trusted_set, site_id)


def _start_daemon_thread(run: Callable[[], None]) -> None:
    threading.Thread(target=run, name="service-peer-trust-reload", daemon=True).start()


__all__ = [
    "RELOAD_RETRY_FIRST_SECONDS",
    "RELOAD_RETRY_MAX_SECONDS",
    "SERVICE_PEER_ROLE",
    "ServicePeerConfigs",
    "ServicePeerConfigurationError",
    "require_one_service_peer_per_site",
    "seed_service_peers",
    "ServicePeerTrust",
]
