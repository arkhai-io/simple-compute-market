"""Durable account request bindings and contact-free mutation replay."""

from collections.abc import Callable
import hmac
from pathlib import Path
from typing import Any

from market_core.rfq import RfqMutationReceipt, RfqReference
from market_identity import canonical_json
from pydantic import BaseModel, ConfigDict, SecretStr, model_validator
from sqlalchemy import update
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from core_registry.db.models import RfqReplayReservation
from core_registry.rfq_context import VerifiedRfqRequest


class RfqReplayConflict(Exception):
    """An account reused a request ID with different logical input."""


class RfqReplayKeyUnavailable(Exception):
    """The digest key needed to compare a durable binding is unavailable."""


class RfqReplayKeys(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    current: RfqReference
    keys: dict[RfqReference, SecretStr]

    @model_validator(mode="after")
    def validate_keys(self) -> "RfqReplayKeys":
        if self.current not in self.keys:
            raise ValueError("RFQ receipt digest writer key is missing")
        for secret in self.keys.values():
            value = secret.get_secret_value()
            if len(value) != 64 or len(bytes.fromhex(value)) != 32:
                raise ValueError("RFQ receipt digest keys require 32 bytes")
        return self

    @classmethod
    def load(cls, path: str) -> "RfqReplayKeys":
        try:
            return cls.model_validate_json(Path(path).read_bytes())
        except (OSError, ValueError):
            raise RuntimeError("cannot load REGISTRY_RFQ_REPLAY_KEYS_FILE") from None

    def digest(self, request: VerifiedRfqRequest, key_id: str) -> str:
        secret = self.keys.get(key_id)
        if secret is None:
            raise RfqReplayKeyUnavailable
        logical_request = canonical_json({
            "protocol": "arkhai.rfq-receipt.v1",
            # The public pin is checked before replay lookup. A registry can
            # rotate it while keeping its name and existing request bindings.
            "audience": request.invocation.audience.name,
            "operation": request.target.operation.value,
            "resource": request.target.resource,
            "inputs": request.invocation.inputs,
        })
        return hmac.digest(
            bytes.fromhex(secret.get_secret_value()), logical_request, "sha256"
        ).hex()


def _request_key(verified: VerifiedRfqRequest) -> tuple[str, str, str]:
    account = verified.invocation.account
    return account.namespace, account.subject, verified.request_id


def _reserve(
    session: Session,
    verified: VerifiedRfqRequest,
    keys: RfqReplayKeys,
) -> None:
    namespace, subject, request_id = key = _request_key(verified)
    insert = {
        "postgresql": postgres_insert,
        "sqlite": sqlite_insert,
    }[session.get_bind().dialect.name]
    # Bind the ID even when the subsequent domain action refuses or rolls back.
    session.execute(insert(RfqReplayReservation).values(
        namespace=namespace,
        subject=subject,
        request_id=request_id,
        key_id=keys.current,
        input_digest=keys.digest(verified, keys.current),
    ).on_conflict_do_nothing(index_elements=[
        RfqReplayReservation.namespace,
        RfqReplayReservation.subject,
        RfqReplayReservation.request_id,
    ]))
    reservation = session.get(RfqReplayReservation, key, populate_existing=True)
    assert reservation is not None
    expected = keys.digest(verified, reservation.key_id)
    if not hmac.compare_digest(reservation.input_digest, expected):
        raise RfqReplayConflict
    session.commit()


def _lock_for_mutation(
    session: Session, key: tuple[str, str, str]
) -> RfqReplayReservation:
    namespace, subject, request_id = key
    # A write locks the row on PostgreSQL and acquires SQLite's writer slot.
    # Hold it until the domain mutation and receipt commit together.
    session.execute(update(RfqReplayReservation).where(
        RfqReplayReservation.namespace == namespace,
        RfqReplayReservation.subject == subject,
        RfqReplayReservation.request_id == request_id,
    ).values(input_digest=RfqReplayReservation.input_digest))
    reservation = session.get(RfqReplayReservation, key, populate_existing=True)
    assert reservation is not None
    return reservation


def execute_rfq_request(
    session: Session,
    verified: VerifiedRfqRequest,
    keys: RfqReplayKeys,
    dispatch: Callable[[], Any],
) -> Any:
    """Dispatch in the request's session and keep only a typed mutation receipt."""
    try:
        _reserve(session, verified, keys)
        if verified.target.operation.is_read:
            return dispatch()

        reservation = _lock_for_mutation(session, _request_key(verified))
        if reservation.receipt is not None:
            receipt = RfqMutationReceipt.model_validate(reservation.receipt)
        else:
            receipt = dispatch()
            if not isinstance(receipt, RfqMutationReceipt):
                raise TypeError("an RFQ mutation must return a contact-free receipt")
            reservation.receipt = receipt.model_dump(mode="json", exclude_none=True)
        session.commit()
    except Exception:
        session.rollback()
        raise
    return receipt
