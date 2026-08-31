"""Buyer-owned bounded off-session policy and aggregate reservation journal."""

from __future__ import annotations

import fcntl
import json
import os
import stat
import tempfile
from contextlib import contextmanager
from enum import Enum
from pathlib import Path
from typing import Annotated, Any, Iterator, Literal, Mapping

from hosted_settlement_client import FundingMode, FundingProfile
from market_identity import Identity
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class AutomationModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class OffSessionPolicy(AutomationModel):
    """Disabled-by-default exact consent bounds for saved-instrument use."""

    enabled: bool = False
    authority_id: str | None = Field(default=None, min_length=1, max_length=256)
    environment: str | None = Field(default=None, min_length=1, max_length=64)
    funding_profile: Annotated[FundingProfile | None, Field(strict=False)] = None
    currency: Literal["usd"] | None = None
    max_purchase_minor_units: int | None = Field(default=None, gt=0)
    max_aggregate_minor_units: int | None = Field(default=None, gt=0)
    window_kind: Literal["rolling", "fixed"] = "rolling"
    window_seconds: int | None = Field(default=None, gt=0)
    fixed_window_anchor_unix: int | None = Field(default=None, ge=0)
    seller_principals: tuple[Identity, ...] = ()
    mode: Literal["saved_instrument"] = "saved_instrument"

    @field_validator("seller_principals", mode="before")
    @classmethod
    def accept_toml_sellers(cls, value: Any) -> Any:
        return tuple(value) if isinstance(value, list) else value

    @model_validator(mode="after")
    def validate_bounds(self) -> OffSessionPolicy:
        required = (
            self.authority_id,
            self.environment,
            self.funding_profile,
            self.currency,
            self.max_purchase_minor_units,
            self.max_aggregate_minor_units,
            self.window_seconds,
        )
        if self.enabled and any(value is None for value in required):
            raise ValueError("enabled off-session policy requires every exact bound")
        if (
            self.max_purchase_minor_units is not None
            and self.max_aggregate_minor_units is not None
            and self.max_aggregate_minor_units < self.max_purchase_minor_units
        ):
            raise ValueError("aggregate bound cannot be below the purchase bound")
        if self.window_kind == "fixed" and self.fixed_window_anchor_unix is None:
            raise ValueError("fixed aggregate window requires an explicit anchor")
        if self.window_kind == "rolling" and self.fixed_window_anchor_unix is not None:
            raise ValueError("rolling aggregate window cannot carry a fixed anchor")
        if len(set(self.seller_principals)) != len(self.seller_principals):
            raise ValueError("seller principal bounds must be unique")
        return self


class AutomationCandidate(AutomationModel):
    """Safe accepted facts used by the pure local policy evaluator."""

    authority_id: str = Field(min_length=1, max_length=256)
    environment: str = Field(min_length=1, max_length=64)
    funding_profile: Annotated[FundingProfile, Field(strict=False)]
    currency: Literal["usd"]
    amount: int = Field(gt=0)
    seller_principal: Identity
    mode: Annotated[FundingMode, Field(strict=False)]
    binding_ready: bool
    instrument_ready: bool
    mandate_or_consent_ready: bool


class AutomationDecision(AutomationModel):
    allowed: bool
    reason: str


_DECISION_REASONS = {
    "allowed",
    "disabled",
    "authority_mismatch",
    "environment_mismatch",
    "profile_mismatch",
    "currency_mismatch",
    "mode_not_saved",
    "purchase_bound_exceeded",
    "aggregate_bound_exceeded",
    "seller_excluded",
    "binding_unready",
    "instrument_unready",
    "consent_unready",
}


def evaluate_off_session_policy(
    policy: OffSessionPolicy,
    candidate: AutomationCandidate,
    *,
    aggregate_reserved_minor_units: int,
) -> AutomationDecision:
    """Decide only whether this exact accepted authorization may be automated."""

    if aggregate_reserved_minor_units < 0:
        raise ValueError("aggregate reservation total cannot be negative")
    reason = "allowed"
    if not policy.enabled:
        reason = "disabled"
    elif candidate.authority_id != policy.authority_id:
        reason = "authority_mismatch"
    elif candidate.environment != policy.environment:
        reason = "environment_mismatch"
    elif candidate.funding_profile != policy.funding_profile:
        reason = "profile_mismatch"
    elif candidate.currency != policy.currency:
        reason = "currency_mismatch"
    elif candidate.mode is not FundingMode.SAVED_INSTRUMENT:
        reason = "mode_not_saved"
    elif candidate.amount > (policy.max_purchase_minor_units or 0):
        reason = "purchase_bound_exceeded"
    elif (
        aggregate_reserved_minor_units + candidate.amount
        > (policy.max_aggregate_minor_units or 0)
    ):
        reason = "aggregate_bound_exceeded"
    elif (
        policy.seller_principals
        and candidate.seller_principal not in policy.seller_principals
    ):
        reason = "seller_excluded"
    elif not candidate.binding_ready:
        reason = "binding_unready"
    elif not candidate.instrument_ready:
        reason = "instrument_unready"
    elif not candidate.mandate_or_consent_ready:
        reason = "consent_unready"
    assert reason in _DECISION_REASONS
    return AutomationDecision(allowed=reason == "allowed", reason=reason)


class ReservationState(str, Enum):
    RESERVED = "reserved"
    AUTHORIZED = "authorized"
    RELEASED = "released"


class ReservationRecord(AutomationModel):
    marketplace_operation_id: str = Field(min_length=1, max_length=256)
    input_fingerprint: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    authority_id: str = Field(min_length=1, max_length=256)
    environment: str = Field(min_length=1, max_length=64)
    funding_profile: Annotated[FundingProfile, Field(strict=False)]
    currency: Literal["usd"]
    amount: int = Field(gt=0)
    reserved_at_unix: int = Field(ge=0)
    expires_at_unix: int = Field(gt=0)
    window_key: str = Field(min_length=1, max_length=128)
    state: Annotated[ReservationState, Field(strict=False)]
    funding_authorization_ref: str | None = Field(
        default=None,
        min_length=1,
        max_length=256,
    )


class _JournalState(AutomationModel):
    schema_version: Literal[1] = 1
    records: tuple[ReservationRecord, ...] = ()


class AutomationPolicyRefused(RuntimeError):
    def __init__(self, decision: AutomationDecision) -> None:
        self.decision = decision
        super().__init__(f"off-session automation requires interaction: {decision.reason}")


class AuthorizationReservationConflict(RuntimeError):
    """An operation ID was already bound to different accepted authorization input."""


class AuthorizationReservationJournal:
    """Owner-only atomic aggregate reservations keyed by accepted operation ID."""

    def __init__(self, path: Path) -> None:
        if not path.is_absolute():
            raise ValueError("authorization journal path must be absolute")
        self.path = path
        self.lock_path = path.with_suffix(path.suffix + ".lock")

    def _window_key(self, policy: OffSessionPolicy, now_unix: int) -> str:
        assert policy.window_seconds is not None
        if policy.window_kind == "rolling":
            return "rolling"
        anchor = policy.fixed_window_anchor_unix or 0
        return f"fixed:{(now_unix - anchor) // policy.window_seconds}"

    def _within_window(
        self,
        record: ReservationRecord,
        policy: OffSessionPolicy,
        *,
        now_unix: int,
        window_key: str,
    ) -> bool:
        if record.state is ReservationState.RELEASED:
            return False
        if (
            record.state is ReservationState.RESERVED
            and record.expires_at_unix <= now_unix
        ):
            return False
        if policy.window_kind == "fixed":
            return record.window_key == window_key
        assert policy.window_seconds is not None
        return record.reserved_at_unix >= now_unix - policy.window_seconds

    @contextmanager
    def _locked(self) -> Iterator[_JournalState]:
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(self.path.parent, 0o700)
        descriptor = os.open(self.lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            os.fchmod(descriptor, 0o600)
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            if self.path.exists():
                mode = stat.S_IMODE(self.path.stat().st_mode)
                if mode & 0o077:
                    raise PermissionError("authorization journal must be owner-only")
                try:
                    state = _JournalState.model_validate_json(
                        self.path.read_text(encoding="utf-8")
                    )
                except (OSError, ValueError):
                    raise ValueError("authorization journal is malformed") from None
            else:
                state = _JournalState()
            yield state
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)

    def _write(self, state: _JournalState) -> None:
        payload = json.dumps(
            state.model_dump(mode="json"),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        descriptor, temporary = tempfile.mkstemp(
            dir=self.path.parent,
            prefix=f".{self.path.name}.",
        )
        try:
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
            directory = os.open(self.path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def reserve(
        self,
        *,
        policy: OffSessionPolicy,
        candidate: AutomationCandidate,
        marketplace_operation_id: str,
        input_fingerprint: str,
        expires_at_unix: int,
        now_unix: int,
    ) -> ReservationRecord:
        window_key = self._window_key(policy, now_unix)
        with self._locked() as state:
            existing = next(
                (
                    record
                    for record in state.records
                    if record.marketplace_operation_id == marketplace_operation_id
                ),
                None,
            )
            if existing is not None and existing.input_fingerprint != input_fingerprint:
                raise AuthorizationReservationConflict(
                    "marketplace operation is bound to different authorization input"
                )
            if existing is not None and (
                existing.state is ReservationState.AUTHORIZED
                or (
                    existing.state is ReservationState.RESERVED
                    and existing.expires_at_unix > now_unix
                )
            ):
                return existing
            active_total = sum(
                record.amount
                for record in state.records
                if self._within_window(
                    record,
                    policy,
                    now_unix=now_unix,
                    window_key=window_key,
                )
                and record.marketplace_operation_id != marketplace_operation_id
            )
            decision = evaluate_off_session_policy(
                policy,
                candidate,
                aggregate_reserved_minor_units=active_total,
            )
            if not decision.allowed:
                raise AutomationPolicyRefused(decision)
            record = ReservationRecord(
                marketplace_operation_id=marketplace_operation_id,
                input_fingerprint=input_fingerprint,
                authority_id=candidate.authority_id,
                environment=candidate.environment,
                funding_profile=candidate.funding_profile,
                currency=candidate.currency,
                amount=candidate.amount,
                reserved_at_unix=now_unix,
                expires_at_unix=expires_at_unix,
                window_key=window_key,
                state=ReservationState.RESERVED,
            )
            records = tuple(
                item
                for item in state.records
                if item.marketplace_operation_id != marketplace_operation_id
            ) + (record,)
            self._write(_JournalState(records=records))
            return record

    def record_authorized(
        self,
        *,
        marketplace_operation_id: str,
        input_fingerprint: str,
        funding_authorization_ref: str,
    ) -> ReservationRecord:
        with self._locked() as state:
            existing = next(
                (
                    record
                    for record in state.records
                    if record.marketplace_operation_id == marketplace_operation_id
                ),
                None,
            )
            if existing is None or existing.input_fingerprint != input_fingerprint:
                raise AuthorizationReservationConflict(
                    "authorization acknowledgement has no exact reservation"
                )
            if (
                existing.funding_authorization_ref is not None
                and existing.funding_authorization_ref != funding_authorization_ref
            ):
                raise AuthorizationReservationConflict(
                    "exact reservation returned another authorization reference"
                )
            updated = existing.model_copy(
                update={
                    "state": ReservationState.AUTHORIZED,
                    "funding_authorization_ref": funding_authorization_ref,
                }
            )
            records = tuple(
                updated
                if record.marketplace_operation_id == marketplace_operation_id
                else record
                for record in state.records
            )
            self._write(_JournalState(records=records))
            return updated

    def release(
        self,
        *,
        marketplace_operation_id: str,
        input_fingerprint: str,
    ) -> None:
        with self._locked() as state:
            existing = next(
                (
                    record
                    for record in state.records
                    if record.marketplace_operation_id == marketplace_operation_id
                ),
                None,
            )
            if existing is None:
                return
            if existing.input_fingerprint != input_fingerprint:
                raise AuthorizationReservationConflict(
                    "release input does not match the exact reservation"
                )
            records = tuple(
                record.model_copy(update={"state": ReservationState.RELEASED})
                if record.marketplace_operation_id == marketplace_operation_id
                else record
                for record in state.records
            )
            self._write(_JournalState(records=records))

    def snapshot(self) -> tuple[ReservationRecord, ...]:
        with self._locked() as state:
            return state.records


def authorization_journal_path(
    configured: str | None = None,
    *,
    environ: Mapping[str, str] | None = None,
) -> Path:
    """Resolve an explicit absolute path or the buyer's XDG data location."""

    if configured is not None:
        path = Path(configured)
        if not path.is_absolute():
            raise ValueError("authorization journal path must be absolute")
        return path
    values = os.environ if environ is None else environ
    xdg = values.get("XDG_DATA_HOME")
    base = Path(xdg) if xdg else Path.home() / ".local" / "share"
    return (base / "arkhai" / "buyer" / "stripe-authorizations.json").absolute()


__all__ = [
    "AuthorizationReservationConflict",
    "AuthorizationReservationJournal",
    "AutomationCandidate",
    "AutomationDecision",
    "AutomationPolicyRefused",
    "OffSessionPolicy",
    "ReservationRecord",
    "ReservationState",
    "authorization_journal_path",
    "evaluate_off_session_policy",
]
