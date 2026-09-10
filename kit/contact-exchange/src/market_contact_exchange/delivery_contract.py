"""Strict carriers for explicitly authorized two-recipient contact delivery."""

from __future__ import annotations

import base64
import re
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

ObligationRef = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
FinalizationId = Annotated[
    str,
    Field(
        pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
    ),
]
NegotiationId = Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{1,128}$")]
ReviewToken = Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{43}$")]


class StrictCarrier(BaseModel):
    model_config = ConfigDict(
        extra="forbid", strict=True, frozen=True, hide_input_in_errors=True
    )

    @field_validator(
        "schema_version", "timeout_seconds", mode="before", check_fields=False
    )
    @classmethod
    def integer_literal(cls, value: object) -> object:
        if type(value) is not int:
            raise ValueError("integer required")
        return value


class DeliveryPolicy(StrictCarrier):
    kind: Literal["contact-delivery.v1"]
    mode: Literal["two-sided-contact"]
    channel: Literal["email"]
    trigger: Literal["explicit-finalization"]
    recipient_authority: Literal["each-party-own-route"]


DELIVERY_POLICY = DeliveryPolicy(
    kind="contact-delivery.v1",
    mode="two-sided-contact",
    channel="email",
    trigger="explicit-finalization",
    recipient_authority="each-party-own-route",
)


def validate_mailbox(value: str) -> str:
    atom = r"[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+"
    label = r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
    if len(value) > 254 or not re.fullmatch(
        rf"{atom}(?:\.{atom})*@{label}(?:\.{label})+", value
    ):
        raise ValueError("invalid mailbox")
    if len(value.split("@")[0]) > 64:
        raise ValueError("invalid mailbox")
    return value


class EmailRoute(StrictCarrier):
    kind: Literal["email"]
    address: str = Field(repr=False)

    _address = field_validator("address")(validate_mailbox)


class SmtpConfig(StrictCarrier):
    host: str = Field(max_length=253, repr=False)
    port: int = Field(ge=1, le=65535)
    sender: str = Field(repr=False)
    username: str = Field(min_length=1, max_length=1024, repr=False)
    password: str = Field(min_length=1, max_length=1024, repr=False)
    timeout_seconds: Literal[10]

    _sender = field_validator("sender")(validate_mailbox)

    @field_validator("host")
    @classmethod
    def hostname(cls, value: str) -> str:
        label = r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
        if not re.fullmatch(rf"{label}(?:\.{label})*", value) or re.fullmatch(
            r"[0-9.]+", value
        ):
            raise ValueError("invalid SMTP host")
        return value

    @field_validator("username", "password")
    @classmethod
    def credential(cls, value: str) -> str:
        if any(c in value for c in "\x00\r\n"):
            raise ValueError("invalid SMTP credential")
        return value


class ContactDeliveryConfig(StrictCarrier):
    schema_version: Literal[2]
    mode: Literal["two-sided-contact"]
    seller_route: EmailRoute
    smtp: SmtpConfig


def bound_payload(value: dict[str, str]) -> dict[str, str]:
    if len(value) > 16:
        raise ValueError("contact payload is too large")
    for key, item in value.items():
        if not isinstance(key, str) or not 1 <= len(key) <= 64:
            raise ValueError("invalid contact key")
        if not isinstance(item, str) or not item.strip() or len(item) > 512:
            raise ValueError("invalid contact value")
        if any(0xD800 <= ord(c) <= 0xDFFF for c in key + item):
            raise ValueError("invalid contact scalar")
    return value


class ContactText(StrictCarrier):
    """One whole private blurb serialized as an existing contact payload."""

    text: str = Field(min_length=1, max_length=512, repr=False)

    @field_validator("text")
    @classmethod
    def whole_blurb(cls, value: str) -> str:
        bound_payload({"text": value})
        return value


def parse_contact_text(value: object) -> ContactText:
    """Validate the text profile without exposing input in diagnostics."""
    try:
        return ContactText.model_validate(value)
    except ValueError:
        raise ValueError("invalid_contact_text") from None


class IntroductionReview(StrictCarrier):
    schema_version: Literal[2]
    negotiation_id: NegotiationId
    obligation_ref: ObligationRef
    finalization_id: FinalizationId
    contact_payload: dict[str, str] = Field(min_length=1, repr=False)
    delivery_route: EmailRoute

    _payload = field_validator("contact_payload")(bound_payload)


class IntroductionFinalize(IntroductionReview):
    review_token: ReviewToken = Field(repr=False)
    consent: Literal["exchange-contacts-and-deliver.v1"]

    @field_validator("review_token")
    @classmethod
    def canonical_token(cls, value: str) -> str:
        decoded = base64.urlsafe_b64decode(value + "=")
        if (
            len(decoded) != 32
            or base64.urlsafe_b64encode(decoded).rstrip(b"=").decode() != value
        ):
            raise ValueError("invalid review token")
        return value


class FinalizationCancel(StrictCarrier):
    schema_version: Literal[2]
    obligation_ref: ObligationRef
    finalization_id: FinalizationId
    consent: Literal["fence-unresolved-finalization.v1"]


def finalization_resource(obligation_ref: str, finalization_id: str) -> str:
    return f"introduction-finalization:{obligation_ref}:{finalization_id}"
