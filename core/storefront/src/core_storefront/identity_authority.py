"""Storefront-owned principal bindings, rotation, and service-peer trust."""

from __future__ import annotations

import asyncio
import hashlib
import sqlite3
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from market_identity import (
    Identity,
    RotationRequest,
    canonical_rotation_bytes,
    verify_rotation,
)

ADMINISTRATOR_AUTHORITY = "storefront.administrator"
SERVICE_PEER_AUTHORITY = "storefront.service-peer"


@dataclass(frozen=True)
class IdentityBindingStatus:
    principal: Identity
    status: str
    overlap_until: int | None

    def active_at(self, now: int) -> bool:
        return self.status == "primary" or (
            self.status == "overlap"
            and self.overlap_until is not None
            and self.overlap_until > now
        )


@dataclass(frozen=True)
class IdentitySubjectStatus:
    authority: str
    subject: str
    role: str
    bindings: tuple[IdentityBindingStatus, ...]

    def active_principals(self, now: int) -> frozenset[Identity]:
        return frozenset(
            binding.principal for binding in self.bindings if binding.active_at(now)
        )

    @property
    def primary(self) -> Identity | None:
        return next(
            (
                binding.principal
                for binding in self.bindings
                if binding.status == "primary"
            ),
            None,
        )


class IdentityAuthorityError(ValueError):
    """Rejected identity-authority operation."""


class RotationConvergenceError(RuntimeError):
    """Rotation did not converge, so retirement was not attempted."""


class StorefrontIdentityAuthority:
    """Transactional authority over stable storefront-owned identity subjects."""

    def __init__(self, db_path: str, *, max_overlap_seconds: int = 86_400) -> None:
        if max_overlap_seconds <= 0:
            raise ValueError("max_overlap_seconds must be positive")
        self._db_path = db_path
        self._max_overlap_seconds = max_overlap_seconds

    def register_subject(
        self,
        *,
        authority: str,
        subject: str,
        role: str,
        principal: Identity,
        now: int,
    ) -> IdentitySubjectStatus:
        """Create an initial binding idempotently without replacing ownership."""

        scheme, identifier = principal.scheme.value, principal.identifier
        conn = sqlite3.connect(self._db_path)
        try:
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                "SELECT role FROM identity_subjects WHERE authority=? AND subject=?",
                (authority, subject),
            ).fetchone()
            if existing is None:
                conn.execute(
                    """
                    INSERT INTO identity_subjects (
                      authority, subject, role, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (authority, subject, role, now, now),
                )
            elif existing[0] != role:
                raise IdentityAuthorityError("identity subject role cannot change")

            rows = conn.execute(
                """
                SELECT principal_scheme, principal_identifier, status
                FROM identity_bindings
                WHERE authority=? AND subject=?
                """,
                (authority, subject),
            ).fetchall()
            primary_rows = [row for row in rows if row[2] == "primary"]
            if rows and len(primary_rows) != 1:
                raise IdentityAuthorityError(
                    "identity subject must retain exactly one primary principal"
                )
            if not rows:
                try:
                    conn.execute(
                        """
                        INSERT INTO identity_bindings (
                          authority, subject, principal_scheme,
                          principal_identifier, status, overlap_until,
                          created_at, updated_at
                        ) VALUES (?, ?, ?, ?, 'primary', NULL, ?, ?)
                        """,
                        (authority, subject, scheme, identifier, now, now),
                    )
                except sqlite3.IntegrityError as exc:
                    raise IdentityAuthorityError(
                        "principal is active for another subject at this authority"
                    ) from exc
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        return self.status(authority=authority, subject=subject)

    def register_service_peer(
        self,
        *,
        peer_id: str,
        role: str,
        site_id: str,
        principal: Identity,
        now: int,
    ) -> IdentitySubjectStatus:
        """Seed one service peer without overwriting durable rotation state."""
        if role != "service":
            raise IdentityAuthorityError("service peer role must be 'service'")
        if (
            not isinstance(peer_id, str)
            or not peer_id.strip()
            or not isinstance(site_id, str)
            or not site_id.strip()
        ):
            raise IdentityAuthorityError("service peer and site identifiers are required")

        expected_site = (role, site_id)
        conn = sqlite3.connect(self._db_path)
        try:
            conn.execute("BEGIN IMMEDIATE")
            peer = conn.execute(
                "SELECT role, site_id, principal_scheme, principal_identifier "
                "FROM service_peers WHERE peer_id=?",
                (peer_id,),
            ).fetchone()
            if peer is not None and peer[:2] != expected_site:
                raise IdentityAuthorityError(
                    "service peer role or site is already bound differently"
                )
            subject = conn.execute(
                "SELECT role FROM identity_subjects "
                "WHERE authority=? AND subject=?",
                (SERVICE_PEER_AUTHORITY, peer_id),
            ).fetchone()
            if subject is not None and subject[0] != role:
                raise IdentityAuthorityError("service peer role cannot change")
            bindings = conn.execute(
                """
                SELECT principal_scheme, principal_identifier, status
                FROM identity_bindings
                WHERE authority=? AND subject=?
                """,
                (SERVICE_PEER_AUTHORITY, peer_id),
            ).fetchall()
            primary_bindings = [
                binding for binding in bindings if binding[2] == "primary"
            ]
            if bindings and len(primary_bindings) != 1:
                raise IdentityAuthorityError(
                    "service peer must retain exactly one primary principal"
                )
            if (
                peer is not None
                and primary_bindings
                and peer[2:4] != primary_bindings[0][:2]
            ):
                raise IdentityAuthorityError(
                    "service peer durable principal differs from its primary binding"
                )
            if subject is None:
                conn.execute(
                    """
                    INSERT INTO identity_subjects (
                      authority, subject, role, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (SERVICE_PEER_AUTHORITY, peer_id, role, now, now),
                )
            if not bindings:
                conn.execute(
                    """
                    INSERT INTO identity_bindings (
                      authority, subject, principal_scheme,
                      principal_identifier, status, overlap_until,
                      created_at, updated_at
                    ) VALUES (?, ?, ?, ?, 'primary', NULL, ?, ?)
                    """,
                    (
                        SERVICE_PEER_AUTHORITY,
                        peer_id,
                        principal.scheme.value,
                        principal.identifier,
                        now,
                        now,
                    ),
                )
            if peer is None:
                conn.execute(
                    """
                    INSERT INTO service_peers (
                      peer_id, role, site_id, principal_scheme,
                      principal_identifier, status, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, 'active', ?, ?)
                    """,
                    (
                        peer_id,
                        role,
                        site_id,
                        principal.scheme.value,
                        principal.identifier,
                        now,
                        now,
                    ),
                )
            conn.commit()
        except sqlite3.IntegrityError as exc:
            conn.rollback()
            raise IdentityAuthorityError(
                "service peer identity, role, or site conflicts with another peer"
            ) from exc
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        return self.status(
            authority=SERVICE_PEER_AUTHORITY,
            subject=peer_id,
        )

    def status(self, *, authority: str, subject: str) -> IdentitySubjectStatus:
        conn = sqlite3.connect(self._db_path)
        try:
            row = conn.execute(
                "SELECT role FROM identity_subjects WHERE authority=? AND subject=?",
                (authority, subject),
            ).fetchone()
            if row is None:
                raise KeyError(f"unknown identity subject {authority!r}/{subject!r}")
            bindings = tuple(
                IdentityBindingStatus(
                    principal=Identity(scheme=item[0], identifier=item[1]),
                    status=item[2],
                    overlap_until=item[3],
                )
                for item in conn.execute(
                    """
                    SELECT principal_scheme, principal_identifier,
                           status, overlap_until
                    FROM identity_bindings
                    WHERE authority=? AND subject=?
                    ORDER BY created_at, principal_scheme, principal_identifier
                    """,
                    (authority, subject),
                ).fetchall()
            )
            return IdentitySubjectStatus(
                authority=authority,
                subject=subject,
                role=row[0],
                bindings=bindings,
            )
        finally:
            conn.close()

    def apply_rotation(
        self,
        request: RotationRequest,
        *,
        operator: Identity,
        now: int,
    ) -> IdentitySubjectStatus:
        """Verify and atomically apply one two-proof rotation intent."""

        verification = verify_rotation(request, now=now)
        if not verification.verified:
            raise IdentityAuthorityError("rotation requires two valid unexpired proofs")
        intent = request.intent
        if intent.overlap_seconds > self._max_overlap_seconds:
            raise IdentityAuthorityError("requested identity overlap exceeds authority bound")
        intent_hash = hashlib.sha256(canonical_rotation_bytes(intent)).hexdigest()
        overlap_until = now + intent.overlap_seconds
        current = (intent.current.scheme.value, intent.current.identifier)
        replacement = (intent.replacement.scheme.value, intent.replacement.identifier)

        conn = sqlite3.connect(self._db_path)
        try:
            conn.execute("BEGIN IMMEDIATE")
            prior = conn.execute(
                """
                SELECT intent_hash FROM identity_rotations
                WHERE authority=? AND subject=? AND nonce=?
                """,
                (intent.authority, intent.subject, intent.nonce),
            ).fetchone()
            if prior is not None:
                if prior[0] != intent_hash:
                    raise IdentityAuthorityError(
                        "rotation nonce was reused with a different intent"
                    )
                conn.commit()
                return self.status(authority=intent.authority, subject=intent.subject)

            subject = conn.execute(
                "SELECT 1 FROM identity_subjects WHERE authority=? AND subject=?",
                (intent.authority, intent.subject),
            ).fetchone()
            if subject is None:
                raise IdentityAuthorityError("rotation subject is not registered")
            active_current = conn.execute(
                """
                SELECT status, overlap_until FROM identity_bindings
                WHERE authority=? AND subject=?
                  AND principal_scheme=? AND principal_identifier=?
                """,
                (intent.authority, intent.subject, *current),
            ).fetchone()
            if active_current is None or active_current[0] != "primary":
                raise IdentityAuthorityError(
                    "rotation current principal is not the active primary"
                )
            active_overlap = conn.execute(
                """
                SELECT COUNT(*) FROM identity_bindings
                WHERE authority=? AND subject=?
                  AND status='overlap' AND overlap_until > ?
                """,
                (intent.authority, intent.subject, now),
            ).fetchone()[0]
            if int(active_overlap):
                raise IdentityAuthorityError(
                    "active identity overlap must expire or retire before another rotation"
                )

            replacement_row = conn.execute(
                """
                SELECT status FROM identity_bindings
                WHERE authority=? AND subject=?
                  AND principal_scheme=? AND principal_identifier=?
                """,
                (intent.authority, intent.subject, *replacement),
            ).fetchone()
            if replacement_row is not None:
                raise IdentityAuthorityError(
                    "retired, disabled, or previously bound identities cannot be replacements"
                )
            owner = conn.execute(
                """
                SELECT subject FROM identity_bindings
                WHERE authority=? AND principal_scheme=?
                  AND principal_identifier=?
                  AND status IN ('primary', 'overlap')
                """,
                (intent.authority, *replacement),
            ).fetchone()
            if owner is not None and owner[0] != intent.subject:
                raise IdentityAuthorityError(
                    "replacement principal is active for another subject"
                )

            old_status = "overlap" if intent.overlap_seconds else "retired"
            conn.execute(
                """
                UPDATE identity_bindings
                SET status=?, overlap_until=?, updated_at=?
                WHERE authority=? AND subject=?
                  AND principal_scheme=? AND principal_identifier=?
                """,
                (
                    old_status,
                    overlap_until if intent.overlap_seconds else None,
                    now,
                    intent.authority,
                    intent.subject,
                    *current,
                ),
            )
            conn.execute(
                """
                INSERT INTO identity_bindings (
                  authority, subject, principal_scheme, principal_identifier,
                  status, overlap_until, created_at, updated_at
                ) VALUES (?, ?, ?, ?, 'primary', NULL, ?, ?)
                ON CONFLICT (
                  authority, subject, principal_scheme, principal_identifier
                ) DO UPDATE SET
                  status='primary', overlap_until=NULL, updated_at=excluded.updated_at
                """,
                (intent.authority, intent.subject, *replacement, now, now),
            )
            conn.execute(
                """
                INSERT INTO identity_rotations (
                  authority, subject, nonce, intent_hash,
                  current_scheme, current_identifier,
                  replacement_scheme, replacement_identifier,
                  overlap_until, applied_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    intent.authority,
                    intent.subject,
                    intent.nonce,
                    intent_hash,
                    *current,
                    *replacement,
                    overlap_until,
                    now,
                ),
            )
            conn.execute(
                """
                UPDATE identity_subjects SET updated_at=?
                WHERE authority=? AND subject=?
                """,
                (now, intent.authority, intent.subject),
            )
            if intent.authority == SERVICE_PEER_AUTHORITY:
                conn.execute(
                    """
                    UPDATE service_peers
                    SET principal_scheme=?, principal_identifier=?, updated_at=?
                    WHERE peer_id=?
                    """,
                    (*replacement, now, intent.subject),
                )
            self._audit(
                conn,
                authority=intent.authority,
                subject=intent.subject,
                action="rotate",
                actor=operator,
                target=intent.replacement,
                operation_id=intent.nonce,
                now=now,
            )
            conn.commit()
        except sqlite3.IntegrityError as exc:
            conn.rollback()
            raise IdentityAuthorityError("rotation conflicts with an active binding") from exc
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        return self.status(authority=intent.authority, subject=intent.subject)

    def complete_rotation(
        self,
        *,
        authority: str,
        subject: str,
        rotation_nonce: str,
        principal: Identity,
        operator: Identity,
        now: int,
    ) -> IdentitySubjectStatus:
        """Retire the old identity named by an applied two-proof rotation."""

        conn = sqlite3.connect(self._db_path)
        try:
            conn.execute("BEGIN IMMEDIATE")
            rotation = conn.execute(
                """
                SELECT current_scheme, current_identifier,
                       replacement_scheme, replacement_identifier
                FROM identity_rotations
                WHERE authority=? AND subject=? AND nonce=?
                """,
                (authority, subject, rotation_nonce),
            ).fetchone()
            if rotation is None:
                raise IdentityAuthorityError(
                    "rotation nonce does not reference an applied two-proof rotation"
                )
            current = Identity(scheme=rotation[0], identifier=rotation[1])
            replacement = Identity(scheme=rotation[2], identifier=rotation[3])
            if principal != current:
                raise IdentityAuthorityError(
                    "retirement principal does not match the rotation current identity"
                )
            replacement_status = conn.execute(
                """
                SELECT status FROM identity_bindings
                WHERE authority=? AND subject=?
                  AND principal_scheme=? AND principal_identifier=?
                """,
                (
                    authority,
                    subject,
                    replacement.scheme.value,
                    replacement.identifier,
                ),
            ).fetchone()
            if replacement_status != ("primary",):
                raise IdentityAuthorityError(
                    "rotation replacement is no longer the subject primary"
                )
            current_status = conn.execute(
                """
                SELECT status FROM identity_bindings
                WHERE authority=? AND subject=?
                  AND principal_scheme=? AND principal_identifier=?
                """,
                (
                    authority,
                    subject,
                    principal.scheme.value,
                    principal.identifier,
                ),
            ).fetchone()
            if current_status is None:
                raise IdentityAuthorityError("retirement target is not bound")
            if current_status == ("retired",):
                conn.commit()
                return self.status(authority=authority, subject=subject)
            if current_status[0] not in {"overlap", "disabled"}:
                raise IdentityAuthorityError(
                    "only the prior rotation identity can be retired"
                )
            conn.execute(
                """
                UPDATE identity_bindings
                SET status='retired', overlap_until=NULL, updated_at=?
                WHERE authority=? AND subject=?
                  AND principal_scheme=? AND principal_identifier=?
                """,
                (
                    now,
                    authority,
                    subject,
                    principal.scheme.value,
                    principal.identifier,
                ),
            )
            self._audit(
                conn,
                authority=authority,
                subject=subject,
                action="retire",
                actor=operator,
                target=principal,
                operation_id=f"{rotation_nonce}:retire",
                now=now,
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        return self.status(authority=authority, subject=subject)

    def retire(
        self,
        *,
        authority: str,
        subject: str,
        principal: Identity,
        actor: Identity,
        operation_id: str,
        now: int,
    ) -> IdentitySubjectStatus:
        """Retire a non-primary credential while refusing to remove the last active one."""

        conn = sqlite3.connect(self._db_path)
        try:
            conn.execute("BEGIN IMMEDIATE")
            actor_row = conn.execute(
                """
                SELECT status FROM identity_bindings
                WHERE authority=? AND subject=?
                  AND principal_scheme=? AND principal_identifier=?
                """,
                (authority, subject, actor.scheme.value, actor.identifier),
            ).fetchone()
            if actor_row is None or actor_row[0] != "primary":
                raise IdentityAuthorityError("retirement actor is not the primary principal")
            target_row = conn.execute(
                """
                SELECT status, overlap_until FROM identity_bindings
                WHERE authority=? AND subject=?
                  AND principal_scheme=? AND principal_identifier=?
                """,
                (authority, subject, principal.scheme.value, principal.identifier),
            ).fetchone()
            if target_row is None:
                raise IdentityAuthorityError("retirement target is not bound")
            if target_row[0] == "retired":
                conn.commit()
                return self.status(authority=authority, subject=subject)
            if principal == actor or target_row[0] == "primary":
                raise IdentityAuthorityError("the primary or last identity cannot be retired")
            active_count = conn.execute(
                """
                SELECT COUNT(*) FROM identity_bindings
                WHERE authority=? AND subject=?
                  AND (
                    status='primary'
                    OR (status='overlap' AND overlap_until > ?)
                  )
                """,
                (authority, subject, now),
            ).fetchone()[0]
            target_is_active = (
                target_row[0] == "overlap"
                and target_row[1] is not None
                and int(target_row[1]) > now
            )
            if target_is_active and int(active_count) <= 1:
                raise IdentityAuthorityError("the last active identity cannot be retired")
            conn.execute(
                """
                UPDATE identity_bindings
                SET status='retired', overlap_until=NULL, updated_at=?
                WHERE authority=? AND subject=?
                  AND principal_scheme=? AND principal_identifier=?
                """,
                (
                    now,
                    authority,
                    subject,
                    principal.scheme.value,
                    principal.identifier,
                ),
            )
            self._audit(
                conn,
                authority=authority,
                subject=subject,
                action="retire",
                actor=actor,
                target=principal,
                operation_id=operation_id,
                now=now,
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        return self.status(authority=authority, subject=subject)

    def disable(
        self,
        *,
        authority: str,
        subject: str,
        principal: Identity,
        operator: Identity,
        operation_id: str,
        now: int,
    ) -> IdentitySubjectStatus:
        """Disable a compromised credential without transferring ownership."""

        conn = sqlite3.connect(self._db_path)
        try:
            conn.execute("BEGIN IMMEDIATE")
            cursor = conn.execute(
                """
                UPDATE identity_bindings
                SET status='disabled', overlap_until=NULL, updated_at=?
                WHERE authority=? AND subject=?
                  AND principal_scheme=? AND principal_identifier=?
                  AND status != 'retired'
                """,
                (
                    now,
                    authority,
                    subject,
                    principal.scheme.value,
                    principal.identifier,
                ),
            )
            if cursor.rowcount == 0:
                row = conn.execute(
                    """
                    SELECT status FROM identity_bindings
                    WHERE authority=? AND subject=?
                      AND principal_scheme=? AND principal_identifier=?
                    """,
                    (
                        authority,
                        subject,
                        principal.scheme.value,
                        principal.identifier,
                    ),
                ).fetchone()
                if row is None or row[0] != "disabled":
                    raise IdentityAuthorityError("disable target is not an active binding")
            if authority == SERVICE_PEER_AUTHORITY:
                remaining_active = conn.execute(
                    """
                    SELECT COUNT(*) FROM identity_bindings
                    WHERE authority=? AND subject=?
                      AND (
                        status='primary'
                        OR (status='overlap' AND overlap_until > ?)
                      )
                    """,
                    (authority, subject, now),
                ).fetchone()[0]
                peer_status = "active" if int(remaining_active) else "disabled"
                conn.execute(
                    "UPDATE service_peers SET status=?, updated_at=? WHERE peer_id=?",
                    (peer_status, now, subject),
                )
            self._audit(
                conn,
                authority=authority,
                subject=subject,
                action="disable",
                actor=operator,
                target=principal,
                operation_id=operation_id,
                now=now,
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        return self.status(authority=authority, subject=subject)

    @staticmethod
    def _audit(
        conn: sqlite3.Connection,
        *,
        authority: str,
        subject: str,
        action: str,
        actor: Identity,
        target: Identity | None,
        operation_id: str,
        now: int,
    ) -> None:
        conn.execute(
            """
            INSERT INTO identity_audit (
              authority, subject, action, actor_scheme, actor_identifier,
              target_scheme, target_identifier, operation_id, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                authority,
                subject,
                action,
                actor.scheme.value,
                actor.identifier,
                target.scheme.value if target is not None else None,
                target.identifier if target is not None else None,
                operation_id,
                now,
            ),
        )


@runtime_checkable
class RotationAuthorityClient(Protocol):
    async def apply_rotation(self, request: RotationRequest) -> IdentitySubjectStatus: ...

    async def rotation_status(
        self,
        authority: str,
        subject: str,
    ) -> IdentitySubjectStatus: ...

    async def retire_identity(
        self,
        *,
        authority: str,
        subject: str,
        rotation_nonce: str,
        principal: Identity,
    ) -> IdentitySubjectStatus: ...


async def coordinate_rotation(
    clients: tuple[RotationAuthorityClient, ...],
    request: RotationRequest,
) -> tuple[IdentitySubjectStatus, ...]:
    """Apply everywhere, prove convergence, then retire the old principal everywhere."""

    if not clients:
        raise ValueError("rotation requires at least one authority")
    try:
        await asyncio.gather(*(client.apply_rotation(request) for client in clients))
        statuses = await asyncio.gather(
            *(
                client.rotation_status(
                    request.intent.authority,
                    request.intent.subject,
                )
                for client in clients
            )
        )
    except Exception as exc:
        raise RotationConvergenceError(
            "rotation did not converge; current principal remains in overlap"
        ) from exc
    if any(status.primary != request.intent.replacement for status in statuses):
        raise RotationConvergenceError(
            "rotation status did not converge; current principal remains in overlap"
        )
    return tuple(
        await asyncio.gather(
            *(
                client.retire_identity(
                    authority=request.intent.authority,
                    subject=request.intent.subject,
                    rotation_nonce=request.intent.nonce,
                    principal=request.intent.current,
                )
                for client in clients
            )
        )
    )
