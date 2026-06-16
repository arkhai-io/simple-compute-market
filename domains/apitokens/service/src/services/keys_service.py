"""Keys, credit grants, and consumption — the tokens service's core.

Issuance is the settlement-side fulfillment job
(ARCHITECTURE.md, "API-tokens market domain — Market shape"): it re-checks the
ownership claim authoritatively (the negotiation guard is advisory —
it works off a snapshot, and force-accept bypasses the chain), commits
the quota hold in the site ledger, creates or locates the key, and
writes the credit grant. ``escrow_uid`` uniqueness on grants makes the
whole job idempotent under storefront retry:

- the new-mode key id derives from the escrow uid, so a retry after a
  partial failure finds the half-issued key instead of minting another;
- the quota commit is idempotent at the ledger;
- a retry that finds the grant already written returns the prior
  issuance — and if the (new-mode) key has never consumed, it rotates
  the bearer secret so a lost response doesn't strand the buyer
  without credentials (rotation can't break a working integration:
  zero consumption means nothing is using the old secret; once the key
  has consumed, the buyer evidently holds it and no secret is
  returned).

Consume/verify are the middleware-facing surface: bearer secrets are
hashed at rest, balances are maintained transactionally on the key row
(O(1) checks), and per-key idempotency keys make batched middleware
flushes safe to replay.

Mutations serialize on a process-level lock for the same reason the
site ledger's do: SQLite is single-writer, and in-memory test engines
share one connection.
"""

from __future__ import annotations

import hashlib
import secrets as _secrets
import threading
from typing import Any, Mapping, Optional

from sqlalchemy.orm import Session, sessionmaker

from core_site.ledger import CapacityConflictError, CapacityLedgerService
from db.models import ApiKey, ConsumptionEvent, CreditGrant

#: Reject vocabulary shared with the negotiation guards
#: (ARCHITECTURE.md, "API-tokens market domain — Key ownership").
KEY_NOT_FOUND = "key_not_found"
KEY_NOT_OWNED = "key_not_owned"
KEY_REVOKED = "key_revoked"
QUOTA_EXHAUSTED = "quota_exhausted"
INSUFFICIENT_CREDITS = "insufficient_credits"


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


def derive_key_id(escrow_uid: str) -> str:
    """Deterministic new-mode key id, so issuance retries reuse the key
    a partial earlier attempt created instead of minting another."""
    digest = hashlib.sha256(f"key:{escrow_uid}".encode("utf-8")).hexdigest()
    return f"ak_{digest[:16]}"


def _owner_admits(
    key: ApiKey, buyer_scheme: str | None, buyer_id: str | None,
) -> tuple[bool, str]:
    """Authoritative ownership check. Returns (admitted, reason)."""
    if key.owner_scheme is None:
        return True, ""  # open top-up: no ownership guard on the key
    if key.owner_scheme == "wallet":
        if (
            buyer_scheme == "wallet"
            and buyer_id
            and key.owner_id
            and buyer_id.lower() == key.owner_id.lower()
        ):
            return True, ""
        return False, "key is wallet-bound to a different owner"
    # ed25519 (and any future scheme) needs a possession proof the v1
    # issuance request doesn't carry; the negotiation challenge
    # middleware is the planned path.
    return False, f"ownership scheme {key.owner_scheme!r} is not verifiable at issuance in v1"


class KeysService:
    """Key/grant/consumption operations over the tokens tables."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        capacity_ledger: CapacityLedgerService,
    ) -> None:
        self._session_factory = session_factory
        self._ledger = capacity_ledger
        self._lock = threading.RLock()

    # ------------------------------------------------------------------
    # Issuance (settlement fulfillment)
    # ------------------------------------------------------------------

    def issue(
        self,
        *,
        escrow_uid: str,
        quantity: int,
        key_mode: str,
        key_id: str | None = None,
        buyer_scheme: str | None = None,
        buyer_id: str | None = None,
        owner_scheme: str | None = None,
        owner_id: str | None = None,
        allocation_id: str | None = None,
        resource_id: str | None = None,
    ) -> dict[str, Any]:
        """Fulfill one deal: quota commit + key + grant, idempotently.

        ``owner_scheme``/``owner_id`` override the ownership claim bound
        to a *new* key; the default binds the purchasing wallet
        (``buyer_*``). Existing-mode issuance re-checks the target key's
        claim against ``buyer_*`` and refuses with the shared reject
        vocabulary on mismatch.
        """
        if quantity < 1:
            raise ValueError(f"quantity must be >= 1, got {quantity}")
        if key_mode not in ("new", "existing"):
            raise ValueError(f"key.mode must be 'new' or 'existing', got {key_mode!r}")
        if key_mode == "existing" and not key_id:
            raise ValueError("key.mode 'existing' requires key.key_id")

        with self._lock, self._session_factory() as db:
            prior = (
                db.query(CreditGrant).filter(CreditGrant.escrow_uid == escrow_uid).first()
            )
            if prior is not None:
                return self._reissue(db, prior)

            # 1. Resolve the key and re-check ownership authoritatively.
            secret: str | None = None
            if key_mode == "existing":
                key = db.get(ApiKey, key_id)
                if key is None:
                    raise IssuanceError(KEY_NOT_FOUND, f"key {key_id!r} not found")
                if key.status != "active":
                    raise IssuanceError(KEY_REVOKED, f"key {key_id!r} is {key.status}")
                admitted, why = _owner_admits(key, buyer_scheme, buyer_id)
                if not admitted:
                    raise IssuanceError(KEY_NOT_OWNED, why)
            else:
                new_id = derive_key_id(escrow_uid)
                key = db.get(ApiKey, new_id)
                if key is None:
                    secret = _new_secret(new_id)
                    bind_scheme = owner_scheme if owner_scheme else buyer_scheme
                    bind_id = owner_id if owner_scheme else buyer_id
                    key = ApiKey(
                        key_id=new_id,
                        secret_hash=_hash_secret(secret),
                        owner_scheme=bind_scheme,
                        owner_id=bind_id,
                        status="active",
                        balance=0,
                    )
                    db.add(key)
                else:
                    # A prior attempt created the key but failed before
                    # the grant: rotate so this response carries a
                    # usable secret (nothing consumed = nothing breaks).
                    secret = _new_secret(key.key_id)
                    key.secret_hash = _hash_secret(secret)

            # 2. Commit the quota hold (idempotent at the ledger); fall
            #    back to a plain atomic reserve when the hold lapsed.
            committed_allocation = self._commit_quota(
                escrow_uid=escrow_uid,
                quantity=quantity,
                allocation_id=allocation_id,
                resource_id=resource_id,
            )

            # 3. The grant. escrow_uid UNIQUE is the idempotency anchor.
            db.add(CreditGrant(
                key_id=key.key_id,
                escrow_uid=escrow_uid,
                quantity=int(quantity),
                reason="issuance",
            ))
            key.balance = int(key.balance or 0) + int(quantity)
            db.commit()
            return {
                "key_id": key.key_id,
                "secret": secret,
                "quantity": int(quantity),
                "balance": int(key.balance),
                "allocation_id": committed_allocation,
                "already_issued": False,
            }

    def _reissue(self, db: Session, prior: CreditGrant) -> dict[str, Any]:
        """A retry found the grant already written: return the prior
        issuance. New-mode keys that have never consumed get a rotated
        secret so a lost first response doesn't strand the buyer."""
        key = db.get(ApiKey, prior.key_id)
        secret: str | None = None
        was_new_mode = prior.escrow_uid and key.key_id == derive_key_id(prior.escrow_uid)
        if was_new_mode and key.status == "active":
            consumed = (
                db.query(ConsumptionEvent)
                .filter(ConsumptionEvent.key_id == key.key_id)
                .first()
            )
            if consumed is None:
                secret = _new_secret(key.key_id)
                key.secret_hash = _hash_secret(secret)
                db.commit()
        return {
            "key_id": key.key_id,
            "secret": secret,
            "quantity": int(prior.quantity),
            "balance": int(key.balance or 0),
            "allocation_id": None,
            "already_issued": True,
        }

    def _commit_quota(
        self,
        *,
        escrow_uid: str,
        quantity: int,
        allocation_id: str | None,
        resource_id: str | None,
    ) -> str | None:
        """Commit the negotiation-time hold, or atomically reserve when
        no live hold exists (it lapsed, or holds are disabled)."""
        allocation = None
        if allocation_id:
            allocation = self._ledger.get_allocation(allocation_id)
        if allocation is None:
            allocation = self._ledger.get_allocation_by_escrow(escrow_uid)
        if allocation is not None:
            try:
                committed = self._ledger.commit(
                    resource_id=allocation["resource_id"],
                    allocation_id=allocation["allocation_id"],
                    lease_end_utc=None,  # credits don't expire: no lease tail
                    idempotency_ref=escrow_uid,
                )
            except CapacityConflictError:
                committed = None  # hold lapsed/released; fall through to reserve
            if committed is not None:
                return str(committed["allocation_id"])

        claim: dict[str, Any] = {"units": int(quantity)}
        if resource_id:
            claim["resource_id"] = resource_id
        reserved = self._ledger.reserve(claim=claim, deal_ref={"escrow_uid": escrow_uid})
        if reserved is None:
            raise IssuanceError(
                QUOTA_EXHAUSTED,
                f"no quota resource can cover {quantity} units",
            )
        committed = self._ledger.commit(
            resource_id=reserved["resource_id"],
            allocation_id=reserved["allocation_id"],
            lease_end_utc=None,
            idempotency_ref=escrow_uid,
        )
        return str(committed["allocation_id"]) if committed else None

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
                    "ok": False, "reason": KEY_REVOKED,
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
                        "ok": True, "consumed": 0, "duplicate": True,
                        "balance": int(key.balance or 0),
                    }
            balance = int(key.balance or 0)
            if balance < amount:
                return {
                    "ok": False, "reason": INSUFFICIENT_CREDITS, "balance": balance,
                }
            db.add(ConsumptionEvent(
                key_id=key_id, amount=int(amount), idempotency_key=idempotency_key,
            ))
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
                _hash_secret(secret), str(key.secret_hash),
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
        self, *, status: str | None = None, owner_id: str | None = None,
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
        self, *, key_id: str, delta: int, reason: str | None = None,
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
            db.add(CreditGrant(
                key_id=key_id, escrow_uid=None, quantity=int(delta),
                reason=reason or "admin_adjustment",
            ))
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
                    "quantity": int(row.quantity),
                    "reason": row.reason,
                    "granted_at": row.granted_at.isoformat() if row.granted_at else None,
                }
                for row in rows
            ]

    def list_usage(
        self, key_id: str, *, after_id: int = 0, limit: int = 500,
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
                    "occurred_at": row.occurred_at.isoformat() if row.occurred_at else None,
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
