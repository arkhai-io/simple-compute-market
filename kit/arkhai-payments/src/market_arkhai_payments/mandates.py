"""Seller mandate derivation and buyer-side exact policy checks."""

from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from market_arkhai_payments.canonical import agreement_hash
from market_arkhai_payments.errors import MandatePolicyError
from market_arkhai_payments.models import Mandate


MAX_SAFE_INTEGER = 9_007_199_254_740_991
DEFAULT_WINDOW = "P7D"
PAYMENTS_NONCE = "arkhai.payments.v1"
_ACCOUNT_ID = r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
_ASSET = r"^[A-Z][A-Z0-9]{0,16}(\/\d{1,6})?$"
_FIXED_DURATION = re.compile(
    r"^P(?:(?P<weeks>\d+)W)?(?:(?P<days>\d+)D)?"
    r"(?:T(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+)S)?)?$"
)


def duration_seconds(value: str) -> int:
    """Convert a fixed-unit ISO 8601 duration to seconds.

    Calendar years and months are intentionally excluded because their length
    depends on the instant where a hold begins.
    """

    if not isinstance(value, str):
        raise ValueError("duration must be ISO 8601 text")
    match = _FIXED_DURATION.fullmatch(value)
    if match is None:
        raise ValueError("duration must use fixed week, day, hour, minute, or second units")
    fields = match.groupdict()
    if not any(part is not None for part in fields.values()):
        raise ValueError("duration must contain at least one unit")
    result = (
        int(fields["weeks"] or 0) * 7 * 24 * 60 * 60
        + int(fields["days"] or 0) * 24 * 60 * 60
        + int(fields["hours"] or 0) * 60 * 60
        + int(fields["minutes"] or 0) * 60
        + int(fields["seconds"] or 0)
    )
    if result > MAX_SAFE_INTEGER:
        raise ValueError("duration exceeds the JSON wire integer range")
    return result


def format_duration(value: int) -> str:
    """Format a nonnegative whole-second duration as ISO 8601."""

    if isinstance(value, bool) or not isinstance(value, int) or value < 0 or value > MAX_SAFE_INTEGER:
        raise ValueError("duration_seconds must be a nonnegative safe integer")
    days, remainder = divmod(value, 86_400)
    hours, remainder = divmod(remainder, 3_600)
    minutes, seconds = divmod(remainder, 60)
    date_part = f"{days}D" if days else ""
    time_part = "".join(
        part
        for amount, unit in ((hours, "H"), (minutes, "M"), (seconds, "S"))
        if amount
        for part in (f"{amount}{unit}",)
    )
    if not date_part and not time_part:
        time_part = "0S"
    return "P" + date_part + ("T" + time_part if time_part else "")


class PaymentsOptionParams(BaseModel):
    """Public `arkhai.payments.v1` listing parameters."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, validate_default=True)

    payee_account: str = Field(pattern=_ACCOUNT_ID)
    asset: str = Field(pattern=_ASSET)
    window: str = DEFAULT_WINDOW
    deposit_agreement: bool = False

    @model_validator(mode="after")
    def window_is_fixed(self) -> PaymentsOptionParams:
        try:
            duration_seconds(self.window)
        except ValueError as exc:
            raise ValueError("window must be a fixed-unit ISO 8601 duration") from exc
        return self


class MandatePolicy(BaseModel):
    """Expected payment terms sourced from an accepted Agreement and its option."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    buyer_account: str = Field(pattern=_ACCOUNT_ID)
    option: PaymentsOptionParams
    accepted_at: int | str | datetime
    start_utc: int | str | datetime
    duration_seconds: int = Field(ge=0, le=MAX_SAFE_INTEGER)
    amount: int | str
    asset: str = Field(pattern=_ASSET)
    fee_bps: int = Field(ge=0, le=10_000)
    dispute_authority: str = Field(pattern=_ACCOUNT_ID)

    @model_validator(mode="after")
    def payment_asset_matches_option(self) -> MandatePolicy:
        if self.asset != self.option.asset:
            raise ValueError("accepted asset must match the selected payments option")
        return self


def derive_mandate(agreement_json: dict[str, Any], policy: MandatePolicy) -> Mandate:
    """Derive one deterministic charge-first mandate from the opaque Agreement."""

    if not isinstance(agreement_json, dict):
        raise MandatePolicyError("agreement must be a JSON object")
    try:
        accepted_at = _utc_seconds(policy.accepted_at, "accepted_at")
        start_utc = _utc_seconds(policy.start_utc, "start_utc")
        window = duration_seconds(policy.option.window)
        amount = _amount_text(policy.amount)
    except (TypeError, ValueError) as exc:
        raise MandatePolicyError(str(exc)) from exc
    if start_utc < accepted_at:
        raise MandatePolicyError("start_utc precedes accepted_at")
    hold_seconds = start_utc - accepted_at + policy.duration_seconds + window
    if hold_seconds > MAX_SAFE_INTEGER:
        raise MandatePolicyError("hold duration exceeds the JSON wire integer range")
    expires = accepted_at + window
    if expires <= accepted_at or expires > MAX_SAFE_INTEGER:
        raise MandatePolicyError("mandate expiry must follow acceptance and fit the wire range")

    reverse = list(dict.fromkeys((policy.option.payee_account, policy.dispute_authority)))
    mandate = {
        "from": policy.buyer_account,
        "to": policy.option.payee_account,
        "parts": [
            {
                "kind": "once",
                "asset": policy.asset,
                "amount": amount,
                "hold": {"for": format_duration(hold_seconds)},
            }
        ],
        "deal": agreement_hash(agreement_json),
        "fee": {"bps": policy.fee_bps},
        "authorities": {"start": [], "stop": [], "reverse": reverse},
        "nonce": PAYMENTS_NONCE,
        "expires": expires,
    }
    try:
        return Mandate.model_validate(mandate)
    except Exception as exc:
        raise MandatePolicyError("derived mandate does not satisfy the published wire schema") from exc


def check(
    mandate: Mandate | dict[str, Any],
    agreement_json: dict[str, Any],
    policy: MandatePolicy,
) -> Mandate:
    """Require a seller mandate to equal the buyer's exact expected terms."""

    try:
        actual = Mandate.model_validate(mandate)
        expected = derive_mandate(agreement_json, policy)
    except Exception as exc:
        if isinstance(exc, MandatePolicyError):
            raise
        raise MandatePolicyError("mandate is invalid under the published wire schema") from exc
    actual_values = actual.model_dump(mode="json", by_alias=True, exclude_none=True)
    expected_values = expected.model_dump(mode="json", by_alias=True, exclude_none=True)
    mismatched = sorted(
        key for key in expected_values if actual_values.get(key) != expected_values[key]
    )
    if mismatched:
        raise MandatePolicyError(
            "mandate differs from the accepted Agreement and buyer policy: "
            + ", ".join(mismatched)
        )
    return actual


def _amount_text(value: int | str) -> str:
    if isinstance(value, bool):
        raise ValueError("amount must be a positive integer minor-unit value")
    if isinstance(value, int):
        text = str(value)
    elif isinstance(value, str):
        text = value
    else:
        raise ValueError("amount must be a positive integer minor-unit value")
    if not re.fullmatch(r"[1-9][0-9]{0,37}", text):
        raise ValueError("amount must be a positive canonical minor-unit integer")
    return text


def _utc_seconds(value: int | str | datetime, name: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a UTC timestamp")
    if isinstance(value, int):
        timestamp = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{name} must be an ISO 8601 timestamp") from exc
        timestamp = _datetime_seconds(parsed, name)
    elif isinstance(value, datetime):
        timestamp = _datetime_seconds(value, name)
    else:
        raise ValueError(f"{name} must be a UTC timestamp")
    if timestamp < 0 or timestamp > MAX_SAFE_INTEGER:
        raise ValueError(f"{name} is outside the JSON wire integer range")
    return timestamp


def _datetime_seconds(value: datetime, name: str) -> int:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must include a timezone")
    if value.microsecond:
        raise ValueError(f"{name} must have whole-second precision")
    return int(value.astimezone(timezone.utc).timestamp())
