"""Durable provisioning caller trust pins and two-proof rotation authority."""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

from market_identity import (
    Identity,
    RotationRequest,
    TrustedIdentitySet,
    verify_rotation,
)
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from compute_provisioning_service.db.models import (
    ProvisioningIdentityRotationAudit,
    ProvisioningTrustedPrincipal,
)
from compute_provisioning_service.identity import ProvisioningIdentityContext


class PrincipalRotationError(ValueError):
    pass


class SqlAlchemyProvisioningPrincipalAuthority:
    """Versioned role bindings whose bootstrap config never overwrites state."""

    _SUBJECTS = {
        "admin": "provisioning:admin",
        "seller": "provisioning:storefront",
    }
    _AUTHORITY = "provisioning"

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        bootstrap: ProvisioningIdentityContext,
    ) -> None:
        self._session_factory = session_factory
        self._bootstrap("admin", bootstrap.admin_principal)
        self._bootstrap("seller", bootstrap.storefront_principal)

    def _bootstrap(self, role: str, principal: Identity) -> None:
        try:
            with self._session_factory() as session:
                existing = (
                    session.query(ProvisioningTrustedPrincipal)
                    .filter(ProvisioningTrustedPrincipal.role == role)
                    .first()
                )
                if existing is not None:
                    return
                session.add(
                    ProvisioningTrustedPrincipal(
                        role=role,
                        principal_scheme=principal.scheme.value,
                        principal_identifier=principal.identifier,
                        generation=1,
                    )
                )
                session.commit()
        except IntegrityError:
            return

    def active_principals(
        self,
        role: str,
        *,
        now: datetime | None = None,
    ) -> TrustedIdentitySet:
        current_time = now or datetime.now(timezone.utc)
        with self._session_factory() as session:
            rows = (
                session.query(ProvisioningTrustedPrincipal)
                .filter(ProvisioningTrustedPrincipal.role == role)
                .order_by(ProvisioningTrustedPrincipal.generation.desc())
                .all()
            )
            identities: list[Identity] = []
            for row in rows:
                valid_until = row.valid_until
                if valid_until is not None:
                    if valid_until.tzinfo is None:
                        valid_until = valid_until.replace(tzinfo=timezone.utc)
                    if valid_until < current_time:
                        continue
                identities.append(
                    Identity(
                        scheme=row.principal_scheme,
                        identifier=row.principal_identifier,
                    )
                )
            return TrustedIdentitySet(identities=tuple(identities))

    def is_authorized(
        self,
        role: str,
        principal: Identity,
        *,
        now: datetime | None = None,
    ) -> bool:
        return principal in self.active_principals(role, now=now)

    def rotate(
        self,
        role: str,
        request: RotationRequest,
        *,
        actor: Identity,
    ) -> dict[str, object]:
        if role not in self._SUBJECTS:
            raise PrincipalRotationError("unsupported provisioning principal role")
        if not self.is_authorized("admin", actor):
            raise PrincipalRotationError("rotation actor is not an active administrator")
        intent = request.intent
        if intent.subject != self._SUBJECTS[role] or intent.authority != self._AUTHORITY:
            raise PrincipalRotationError("rotation subject or authority does not match")
        if not self.is_authorized(role, intent.current):
            raise PrincipalRotationError("rotation current principal is not active")
        verification = verify_rotation(request, now=int(time.time()))
        if not verification.verified:
            raise PrincipalRotationError("both current and replacement proofs are required")

        now = datetime.now(timezone.utc)
        valid_until = now + timedelta(seconds=intent.overlap_seconds)
        try:
            with self._session_factory() as session:
                if session.get(ProvisioningIdentityRotationAudit, intent.nonce) is not None:
                    raise PrincipalRotationError("rotation nonce was already used")
                current = session.get(
                    ProvisioningTrustedPrincipal,
                    (role, intent.current.scheme.value, intent.current.identifier),
                )
                if current is None:
                    raise PrincipalRotationError("rotation current principal disappeared")
                current.valid_until = valid_until
                for stale in (
                    session.query(ProvisioningTrustedPrincipal)
                    .filter(ProvisioningTrustedPrincipal.role == role)
                    .all()
                ):
                    stale_identity = (
                        stale.principal_scheme,
                        stale.principal_identifier,
                    )
                    if stale_identity not in {
                        (
                            intent.current.scheme.value,
                            intent.current.identifier,
                        ),
                        (
                            intent.replacement.scheme.value,
                            intent.replacement.identifier,
                        ),
                    }:
                        stale.valid_until = now
                generation = int(
                    session.query(func.max(ProvisioningTrustedPrincipal.generation))
                    .filter(ProvisioningTrustedPrincipal.role == role)
                    .scalar()
                    or 0
                ) + 1
                replacement = session.get(
                    ProvisioningTrustedPrincipal,
                    (role, intent.replacement.scheme.value, intent.replacement.identifier),
                )
                if replacement is None:
                    session.add(
                        ProvisioningTrustedPrincipal(
                            role=role,
                            principal_scheme=intent.replacement.scheme.value,
                            principal_identifier=intent.replacement.identifier,
                            generation=generation,
                            valid_until=None,
                        )
                    )
                else:
                    replacement.generation = generation
                    replacement.valid_until = None
                session.add(
                    ProvisioningIdentityRotationAudit(
                        nonce=intent.nonce,
                        role=role,
                        current_scheme=intent.current.scheme.value,
                        current_identifier=intent.current.identifier,
                        replacement_scheme=intent.replacement.scheme.value,
                        replacement_identifier=intent.replacement.identifier,
                        overlap_seconds=intent.overlap_seconds,
                        intent_expires_at=intent.expires_at,
                    )
                )
                session.commit()
        except IntegrityError as exc:
            raise PrincipalRotationError("rotation nonce or replacement conflicts") from exc

        return {
            "role": role,
            "generation": generation,
            "current_valid_until": valid_until.isoformat(),
            "replacement": intent.replacement.model_dump(mode="json"),
        }
