"""Keys, immutable credit grants, and consumption.

The credits authority owns quota, key ownership, bearer hashes, balances, and
grant idempotency. Issuance compares the complete canonical command before any
new mutation; an exact retry converges on the committed grant while changed
reuse conflicts.
"""

from __future__ import annotations

import hashlib
import secrets as _secrets
import threading
from datetime import timezone
from typing import Any, Mapping, Optional

from market_identity import Identity, IdentityScheme
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from market_site.ledger import CapacityConflictError, CapacityLedgerService
from db.models import ApiKey, ConsumptionEvent, CreditGrant
from models.keys_model import (
    LEGACY_ISSUANCE_RESOURCE_ID,
    LEGACY_ISSUANCE_SERVICE,
    KeyDisposition,
    derive_credit_fulfillment_id,
    issuance_request_digest,
    legacy_issuance_request_digest,
)

KEY_NOT_FOUND = "key_not_found"
KEY_NOT_OWNED = "key_not_owned"
KEY_REVOKED = "key_revoked"
QUOTA_EXHAUSTED = "quota_exhausted"
FULFILLMENT_CONFLICT = "fulfillment_conflict"
INSUFFICIENT_CREDITS = "insufficient_credits"

_GLOBAL_MUTATION_LOCK = threading.RLock()


class IssuanceError(Exception):
    """Issuance refused; ``reason`` is the machine-readable code."""

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason
        self.message = message


def _hash_secret(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def _new_secret(key_id: str) -> str:
    """Bearer secret, self-describing so middlewares can derive the key id
    from the Authorization header alone: ``<key_id>.<random>``."""
    return f"{key_id}.{_secrets.token_urlsafe(32)}"


def derive_key_id(fulfillment_id: str) -> str:
    """Derive one stable new-key identifier from the immutable grant key."""

    digest = hashlib.sha256(f"key:{fulfillment_id}".encode("utf-8")).hexdigest()
    return f"ak_{digest[:16]}"


def _principal(
    scheme: str | None,
    identifier: str | None,
    *,
    field: str,
) -> Identity | None:
    if scheme is None and identifier is None:
        return None
    if scheme is None or identifier is None:
        raise ValueError(f"{field} requires both scheme and identifier")
    return Identity(scheme=IdentityScheme(scheme), identifier=identifier)


def _owner_admits(
    key: ApiKey,
    buyer: Identity | None,
) -> tuple[bool, str]:
    """Authorize an exact canonical principal against the key owner."""
    owner = _principal(key.owner_scheme, key.owner_id, field="stored owner")
    if owner is None:
        return True, ""
    if buyer == owner:
        return True, ""
    return False, "key is bound to a different marketplace principal"


class KeysService:
    """Key/grant/consumption operations over the credits tables."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        capacity_ledger: CapacityLedgerService,
    ) -> None:
        self._session_factory = session_factory
        self._ledger = capacity_ledger
        self._lock = _GLOBAL_MUTATION_LOCK

    # ------------------------------------------------------------------
    # Issuance (settlement fulfillment)
    # ------------------------------------------------------------------

    def issue(
        self,
        *,
        fulfillment_id: str,
        obligation_ref: str,
        mechanism: str,
        owner_scheme: str,
        owner_id: str,
        service: str,
        resource_id: str,
        quantity: int,
        key_mode: str,
        request_digest: str,
        key_id: str | None = None,
        capacity_reservation_id: str | None = None,
    ) -> dict[str, Any]:
        """Atomically commit one immutable grant under ``fulfillment_id``."""

        owner = _principal(owner_scheme, owner_id, field="owner")
        if owner is None:
            raise ValueError("owner is required")
        key_target = KeyDisposition(mode=key_mode, key_id=key_id)
        if mechanism not in {"alkahest.v1", "fiat.stripe.v1"}:
            raise ValueError(f"unsupported settlement mechanism {mechanism!r}")
        if fulfillment_id != derive_credit_fulfillment_id(obligation_ref):
            raise ValueError("fulfillment_id does not match obligation_ref")
        expected_digest = issuance_request_digest(
            fulfillment_id=fulfillment_id,
            obligation_ref=obligation_ref,
            mechanism=mechanism,
            owner=owner,
            service=service,
            resource_id=resource_id,
            quantity=quantity,
            key=key_target,
        )
        if request_digest != expected_digest:
            raise ValueError("request_digest does not match issuance request")

        with self._lock, self._session_factory() as db:
            prior = (
                db.query(CreditGrant)
                .filter(CreditGrant.fulfillment_id == fulfillment_id)
                .first()
            )
            if prior is not None:
                self._assert_or_adopt_legacy_replay(
                    db,
                    prior,
                    obligation_ref=obligation_ref,
                    mechanism=mechanism,
                    owner=owner,
                    service=service,
                    resource_id=resource_id,
                    quantity=quantity,
                    key=key_target,
                    request_digest=request_digest,
                )
                return self._reissue(db, prior)

            secret: str | None = None
            if key_target.mode == "existing":
                key = db.get(ApiKey, key_target.key_id)
                if key is None:
                    raise IssuanceError(
                        KEY_NOT_FOUND,
                        f"key {key_target.key_id!r} not found",
                    )
                if key.status != "active":
                    raise IssuanceError(
                        KEY_REVOKED,
                        f"key {key_target.key_id!r} is {key.status}",
                    )
                admitted, why = _owner_admits(key, owner)
                if not admitted:
                    raise IssuanceError(KEY_NOT_OWNED, why)
            else:
                new_id = derive_key_id(fulfillment_id)
                key = db.get(ApiKey, new_id)
                if key is None:
                    secret = _new_secret(new_id)
                    key = ApiKey(
                        key_id=new_id,
                        secret_hash=_hash_secret(secret),
                        owner_scheme=owner.scheme.value,
                        owner_id=owner.identifier,
                        status="active",
                        balance=0,
                    )
                    db.add(key)
                else:
                    stored_owner = _principal(
                        key.owner_scheme,
                        key.owner_id,
                        field="stored owner",
                    )
                    if stored_owner != owner:
                        raise IssuanceError(
                            FULFILLMENT_CONFLICT,
                            "derived key is bound to another canonical owner",
                        )
                    if key.status != "active":
                        raise IssuanceError(
                            KEY_REVOKED,
                            f"key {new_id!r} is {key.status}",
                        )
                    secret = _new_secret(key.key_id)
                    key.secret_hash = _hash_secret(secret)

            committed_reservation = self._commit_quota(
                fulfillment_id=fulfillment_id,
                quantity=quantity,
                capacity_reservation_id=capacity_reservation_id,
                resource_id=resource_id,
            )
            new_balance = int(key.balance or 0) + int(quantity)
            grant = CreditGrant(
                key_id=key.key_id,
                fulfillment_id=fulfillment_id,
                obligation_ref=obligation_ref,
                mechanism=mechanism,
                service=service,
                resource_id=resource_id,
                key_mode=key_target.mode,
                key_target_id=key_target.key_id,
                owner_scheme=owner.scheme.value,
                owner_id=owner.identifier,
                request_digest=request_digest,
                capacity_reservation_id=committed_reservation,
                result_balance=new_balance,
                escrow_uid=obligation_ref if mechanism == "alkahest.v1" else None,
                quantity=int(quantity),
                reason="issuance",
            )
            db.add(grant)
            key.balance = new_balance
            try:
                db.commit()
            except IntegrityError:
                db.rollback()
                prior = (
                    db.query(CreditGrant)
                    .filter(CreditGrant.fulfillment_id == fulfillment_id)
                    .first()
                )
                if prior is None:
                    raise
                self._assert_or_adopt_legacy_replay(
                    db,
                    prior,
                    obligation_ref=obligation_ref,
                    mechanism=mechanism,
                    owner=owner,
                    service=service,
                    resource_id=resource_id,
                    quantity=quantity,
                    key=key_target,
                    request_digest=request_digest,
                )
                return self._reissue(db, prior)
            db.refresh(grant)
            return self._grant_result(
                grant,
                key,
                secret=secret,
                already_issued=False,
            )

    def _assert_or_adopt_legacy_replay(
        self,
        db: Session,
        prior: CreditGrant,
        *,
        obligation_ref: str,
        mechanism: str,
        owner: Identity,
        service: str,
        resource_id: str,
        quantity: int,
        key: KeyDisposition,
        request_digest: str,
    ) -> None:
        expected = (
            obligation_ref,
            mechanism,
            owner.scheme.value,
            owner.identifier,
            service,
            resource_id,
            int(quantity),
            key.mode,
            key.key_id,
            request_digest,
        )
        stored = (
            prior.obligation_ref,
            prior.mechanism,
            prior.owner_scheme,
            prior.owner_id,
            prior.service,
            prior.resource_id,
            int(prior.quantity),
            prior.key_mode,
            prior.key_target_id,
            prior.request_digest,
        )
        if stored == expected:
            return
        stored_owner = _principal(
            prior.owner_scheme,
            prior.owner_id,
            field="legacy grant owner",
        )
        legacy_digest = (
            legacy_issuance_request_digest(
                fulfillment_id=str(prior.fulfillment_id),
                obligation_ref=str(prior.obligation_ref),
                key_id=prior.key_id,
                key_mode=str(prior.key_mode),
                owner=stored_owner,
                quantity=int(prior.quantity),
            )
            if prior.fulfillment_id is not None
            and prior.obligation_ref is not None
            and prior.key_mode in {"new", "existing"}
            else None
        )
        reconstructable = (
            prior.obligation_ref,
            prior.mechanism,
            stored_owner,
            int(prior.quantity),
            prior.key_mode,
            prior.key_target_id,
        )
        requested = (
            obligation_ref,
            mechanism,
            owner,
            int(quantity),
            key.mode,
            key.key_id,
        )
        if not (
            mechanism == "alkahest.v1"
            and reconstructable == requested
            and prior.service == LEGACY_ISSUANCE_SERVICE
            and prior.resource_id == LEGACY_ISSUANCE_RESOURCE_ID
            and prior.request_digest == legacy_digest
        ):
            raise IssuanceError(
                FULFILLMENT_CONFLICT,
                "fulfillment_id is already bound to a different issuance request",
            )
        prior.service = service
        prior.resource_id = resource_id
        prior.request_digest = request_digest
        db.commit()

    def _reissue(self, db: Session, prior: CreditGrant) -> dict[str, Any]:
        """Return the committed grant and rotate only an unused new-key secret."""

        key = db.get(ApiKey, prior.key_id)
        if key is None:
            raise RuntimeError("committed grant references a missing API key")
        secret: str | None = None
        if prior.key_mode == "new" and key.status == "active":
            consumed = (
                db.query(ConsumptionEvent)
                .filter(ConsumptionEvent.key_id == key.key_id)
                .first()
            )
            if consumed is None:
                secret = _new_secret(key.key_id)
                key.secret_hash = _hash_secret(secret)
                db.commit()
        return self._grant_result(
            prior,
            key,
            secret=secret,
            already_issued=True,
        )

    @staticmethod
    def _grant_result(
        grant: CreditGrant,
        key: ApiKey,
        *,
        secret: str | None,
        already_issued: bool,
    ) -> dict[str, Any]:
        owner = _principal(grant.owner_scheme, grant.owner_id, field="grant owner")
        committed_at = grant.granted_at
        if committed_at.tzinfo is None:
            committed_at = committed_at.replace(tzinfo=timezone.utc)
        return {
            "schema": "arkhai.api-credits.issuance-result.v1",
            "fulfillment_id": grant.fulfillment_id,
            "grant_id": grant.fulfillment_id,
            "obligation_ref": grant.obligation_ref,
            "mechanism": grant.mechanism,
            "owner": owner.model_dump(mode="json") if owner else None,
            "service": grant.service,
            "resource_id": grant.resource_id,
            "quantity": int(grant.quantity),
            "key_mode": grant.key_mode,
            "key_id": key.key_id,
            "balance": int(
                grant.result_balance
                if grant.result_balance is not None
                else key.balance or 0
            ),
            "request_digest": grant.request_digest,
            "committed_at_unix": int(committed_at.timestamp()),
            "capacity_reservation_id": grant.capacity_reservation_id,
            "already_issued": already_issued,
            "secret": secret,
        }

    def _commit_quota(
        self,
        *,
        fulfillment_id: str,
        quantity: int,
        capacity_reservation_id: str | None,
        resource_id: str,
    ) -> str | None:
        reservation = None
        if capacity_reservation_id:
            reservation = self._ledger.get_reservation(capacity_reservation_id)
        if reservation is None:
            reservation = self._ledger.get_reservation_by_escrow(fulfillment_id)
        if reservation is not None:
            try:
                committed = self._ledger.commit(
                    resource_id=None,
                    capacity_reservation_id=reservation["capacity_reservation_id"],
                    lease_end_utc=None,
                    idempotency_ref=fulfillment_id,
                )
            except CapacityConflictError:
                committed = None
            if committed is not None:
                return str(committed["capacity_reservation_id"])

        claim: dict[str, Any] = {
            "executor_kind": "api_credits",
            "resource_id": resource_id,
            "units": int(quantity),
        }
        reserved = self._ledger.reserve(
            claim=claim,
            deal_ref={"escrow_uid": fulfillment_id},
        )
        if reserved is None:
            raise IssuanceError(
                QUOTA_EXHAUSTED,
                f"no quota resource can cover {quantity} units",
            )
        committed = self._ledger.commit(
            resource_id=None,
            capacity_reservation_id=reserved["capacity_reservation_id"],
            lease_end_utc=None,
            idempotency_ref=fulfillment_id,
        )
        return str(committed["capacity_reservation_id"]) if committed else None

    def get_credit_issuance(self, fulfillment_id: str) -> dict[str, Any] | None:
        """Return a committed grant projection without bearer material."""

        with self._lock, self._session_factory() as db:
            grant = (
                db.query(CreditGrant)
                .filter(CreditGrant.fulfillment_id == fulfillment_id)
                .first()
            )
            if grant is None:
                return None
            key = db.get(ApiKey, grant.key_id)
            if key is None:
                raise RuntimeError("committed grant references a missing API key")
            return self._grant_result(
                grant,
                key,
                secret=None,
                already_issued=True,
            )

    # ------------------------------------------------------------------
    # Middleware-facing: consume / verify
    # ------------------------------------------------------------------

    def consume(
        self,
        *,
        key_id: str,
        amount: int,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Decrement ``amount`` credits. Outcome dict, never raises for
        market-state conditions:

        - ``{"ok": True, "consumed": N, "balance": B}``
        - ``{"ok": True, "consumed": 0, "balance": B, "duplicate": True}``
          — the idempotency key was already applied
        - ``{"ok": False, "reason": ..., "balance": B}`` — not found /
          revoked / insufficient credits
        """
        if amount < 1:
            raise ValueError(f"amount must be >= 1, got {amount}")
        with self._lock, self._session_factory() as db:
            key = db.get(ApiKey, key_id)
            if key is None:
                return {"ok": False, "reason": KEY_NOT_FOUND, "balance": 0}
            if key.status != "active":
                return {
                    "ok": False,
                    "reason": KEY_REVOKED,
                    "balance": int(key.balance or 0),
                }
            if idempotency_key is not None:
                seen = (
                    db.query(ConsumptionEvent)
                    .filter(
                        ConsumptionEvent.key_id == key_id,
                        ConsumptionEvent.idempotency_key == idempotency_key,
                    )
                    .first()
                )
                if seen is not None:
                    return {
                        "ok": True,
                        "consumed": 0,
                        "duplicate": True,
                        "balance": int(key.balance or 0),
                    }
            balance = int(key.balance or 0)
            if balance < amount:
                return {
                    "ok": False,
                    "reason": INSUFFICIENT_CREDITS,
                    "balance": balance,
                }
            db.add(
                ConsumptionEvent(
                    key_id=key_id,
                    amount=int(amount),
                    idempotency_key=idempotency_key,
                )
            )
            key.balance = balance - int(amount)
            db.commit()
            return {"ok": True, "consumed": int(amount), "balance": int(key.balance)}

    def consume_batch(self, items: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
        """Apply a middleware flush; items are independent, order kept."""
        return [
            self.consume(
                key_id=str(item["key_id"]),
                amount=int(item["amount"]),
                idempotency_key=item.get("idempotency_key"),
            )
            for item in items
        ]

    def verify(self, *, key_id: str, secret: str) -> dict[str, Any]:
        """Check a presented bearer secret. Constant-time hash compare;
        ``valid`` only for an active key with a matching secret."""
        with self._lock, self._session_factory() as db:
            key = db.get(ApiKey, key_id)
            if key is None:
                return {"valid": False, "status": None, "balance": 0}
            matches = _secrets.compare_digest(
                _hash_secret(secret),
                str(key.secret_hash),
            )
            return {
                "valid": bool(matches and key.status == "active"),
                "status": key.status,
                "balance": int(key.balance or 0),
            }

    # ------------------------------------------------------------------
    # Admin / guard lookups
    # ------------------------------------------------------------------

    def get_key(self, key_id: str) -> Optional[dict[str, Any]]:
        with self._lock, self._session_factory() as db:
            key = db.get(ApiKey, key_id)
            return self._key_payload(key) if key else None

    def list_keys(
        self,
        *,
        status: str | None = None,
        owner_id: str | None = None,
    ) -> list[dict[str, Any]]:
        with self._lock, self._session_factory() as db:
            q = db.query(ApiKey)
            if status is not None:
                q = q.filter(ApiKey.status == status)
            if owner_id is not None:
                q = q.filter(ApiKey.owner_id == owner_id)
            return [self._key_payload(k) for k in q.order_by(ApiKey.created_at.asc())]

    def revoke(self, key_id: str) -> Optional[dict[str, Any]]:
        """Idempotent: revoking a revoked key returns it unchanged."""
        with self._lock, self._session_factory() as db:
            key = db.get(ApiKey, key_id)
            if key is None:
                return None
            key.status = "revoked"
            db.commit()
            return self._key_payload(key)

    def adjust(
        self,
        *,
        key_id: str,
        delta: int,
        reason: str | None = None,
    ) -> Optional[dict[str, Any]]:
        """Operator credit adjustment, recorded as a grant row (no
        escrow). Refuses to take the balance below zero."""
        if delta == 0:
            raise ValueError("delta must be non-zero")
        with self._lock, self._session_factory() as db:
            key = db.get(ApiKey, key_id)
            if key is None:
                return None
            balance = int(key.balance or 0)
            if balance + delta < 0:
                raise ValueError(
                    f"adjustment {delta} would take balance {balance} below zero"
                )
            db.add(
                CreditGrant(
                    key_id=key_id,
                    escrow_uid=None,
                    quantity=int(delta),
                    reason=reason or "admin_adjustment",
                )
            )
            key.balance = balance + int(delta)
            db.commit()
            return self._key_payload(key)

    def list_grants(self, key_id: str) -> list[dict[str, Any]]:
        with self._lock, self._session_factory() as db:
            rows = (
                db.query(CreditGrant)
                .filter(CreditGrant.key_id == key_id)
                .order_by(CreditGrant.id.asc())
                .all()
            )
            return [
                {
                    "id": row.id,
                    "key_id": row.key_id,
                    "escrow_uid": row.escrow_uid,
                    "fulfillment_id": row.fulfillment_id,
                    "obligation_ref": row.obligation_ref,
                    "mechanism": row.mechanism,
                    "service": row.service,
                    "resource_id": row.resource_id,
                    "key_mode": row.key_mode,
                    "key_target_id": row.key_target_id,
                    "owner_scheme": row.owner_scheme,
                    "owner_id": row.owner_id,
                    "request_digest": row.request_digest,
                    "quantity": int(row.quantity),
                    "reason": row.reason,
                    "granted_at": row.granted_at.isoformat()
                    if row.granted_at
                    else None,
                }
                for row in rows
            ]

    def list_usage(
        self,
        key_id: str,
        *,
        after_id: int = 0,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        with self._lock, self._session_factory() as db:
            rows = (
                db.query(ConsumptionEvent)
                .filter(
                    ConsumptionEvent.key_id == key_id,
                    ConsumptionEvent.id > int(after_id),
                )
                .order_by(ConsumptionEvent.id.asc())
                .limit(int(limit))
                .all()
            )
            return [
                {
                    "id": row.id,
                    "key_id": row.key_id,
                    "amount": int(row.amount),
                    "idempotency_key": row.idempotency_key,
                    "occurred_at": row.occurred_at.isoformat()
                    if row.occurred_at
                    else None,
                }
                for row in rows
            ]

    @staticmethod
    def _key_payload(key: ApiKey) -> dict[str, Any]:
        """Public key shape — never includes the secret hash."""
        return {
            "key_id": key.key_id,
            "status": key.status,
            "owner_scheme": key.owner_scheme,
            "owner_id": key.owner_id,
            "balance": int(key.balance or 0),
            "created_at": key.created_at.isoformat() if key.created_at else None,
        }
