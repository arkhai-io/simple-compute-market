"""The negotiation and delivery carriers each api-family domain binds to its kind literal.

They live here rather than in the selling library because a domain's codecs
bind them and its buyer plugin installs those codecs; a buyer installs this
package and never the storefront machinery beneath ``selling``.
"""

from __future__ import annotations

from functools import cache
from typing import Any, Literal, Self

from arkhai_api.purchase import ProvisionTerms
from market_core.schemas import SettlementSelection
from market_identity import Identity
from pydantic import BaseModel, ConfigDict, Field, create_model, model_validator

_OBLIGATION_REF = r"^[0-9a-f]{64}$"


class Message(ProvisionTerms):
    """A negotiation message: the purchase terms plus the selection and principals recorded with them."""

    model_config = ConfigDict(extra="forbid")

    settlement_selection: SettlementSelection | None = None
    buyer_principal: Identity | None = None
    seller_principal: Identity | None = None

    @model_validator(mode="after")
    def _validate_message(self) -> Self:
        if self.quantity is None or self.quantity < 1:
            raise ValueError("payload.quantity must be >= 1")
        if self.key_mode not in {"new", "existing"}:
            raise ValueError("payload.key.mode must be 'new' or 'existing'")
        if self.key_mode == "existing" and not self.key_id:
            raise ValueError("payload.key.key_id is required for existing keys")
        selected_fields = (
            self.settlement_selection,
            self.buyer_principal,
            self.seller_principal,
        )
        if any(value is not None for value in selected_fields) and any(
            value is None for value in selected_fields
        ):
            raise ValueError(
                "settlement selection and canonical buyer/seller principals "
                "must be recorded together"
            )
        return self


class Materialization(BaseModel):
    """Settlement-to-fulfillment handoff for one agreement."""

    model_config = ConfigDict(extra="forbid")

    kind: str
    escrow_uid: str | None = None
    quantity: int = Field(ge=1)
    key_mode: Literal["new", "existing"] = "new"
    key_id: str | None = None
    listing_resource: dict[str, Any] | None = None
    settlement_ref: dict[str, Any] | None = None
    obligation_ref: str | None = Field(default=None, pattern=_OBLIGATION_REF)
    fulfillment_id: str | None = Field(default=None, min_length=1)
    mechanism: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def _validate_materialization(self) -> Self:
        if self.escrow_uid is not None and not self.escrow_uid.strip():
            raise ValueError("escrow_uid must be non-empty")
        if self.escrow_uid is None and self.obligation_ref is None:
            raise ValueError("materialization requires escrow_uid or obligation_ref")
        if self.obligation_ref is not None and (
            self.mechanism is None or self.fulfillment_id is None
        ):
            raise ValueError(
                "mechanism-neutral materialization requires mechanism and fulfillment_id"
            )
        if self.key_mode == "existing" and not self.key_id:
            raise ValueError("key_id is required for existing keys")
        return self


class Receipt(BaseModel):
    """Domain receipt for issuance and fulfillment state."""

    model_config = ConfigDict(extra="forbid")

    kind: str
    status: str
    escrow_uid: str | None = None
    obligation_ref: str | None = Field(default=None, pattern=_OBLIGATION_REF)
    mechanism: str | None = None
    capacity_reservation_id: str | None = None
    key_id: str | None = None
    fulfillment_uid: str | None = None
    fulfillment_id: str | None = None
    credentials_ref: dict[str, Any] | None = None
    result_ref: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _validate_receipt(self) -> Self:
        if self.escrow_uid is None and self.obligation_ref is None:
            raise ValueError("receipt requires escrow_uid or obligation_ref")
        if not self.status.strip():
            raise ValueError("status must be non-empty")
        return self


class Result(BaseModel):
    """Result shape for issuance and fulfillment slots."""

    model_config = ConfigDict(extra="forbid")

    kind: str
    action: str
    status: str = "success"
    fulfillment_uid: str | None = None
    obligation_ref: str | None = Field(default=None, pattern=_OBLIGATION_REF)
    mechanism: str | None = None
    fulfillment_id: str | None = None
    credentials_ref: dict[str, Any] | None = None
    details: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _validate_result(self) -> Self:
        if not self.action.strip():
            raise ValueError("action must be non-empty")
        if not self.status.strip():
            raise ValueError("status must be non-empty")
        return self


def _kind(kind: str) -> tuple[Any, str]:
    return (Literal[kind], kind)  # type: ignore[valid-type]


# Cached, so one kind yields one class. create_model, because a nested class
# cannot name the base it shadows.


@cache
def message_model(kind: str) -> type[Message]:
    return create_model("Message", __base__=Message, kind=_kind(kind))


@cache
def terms_model(kind: str) -> type[Message]:
    """The agreed terms: the bound message plus the listing they were agreed against."""

    return create_model(
        "Terms", __base__=message_model(kind), listing_ref=(str | None, None)
    )


@cache
def materialization_model(
    kind: str, listing_resource: type[BaseModel]
) -> type[Materialization]:
    """The handoff bound to ``kind``, carrying the domain's own listing resource model."""

    return create_model(
        "Materialization",
        __base__=Materialization,
        kind=_kind(kind),
        listing_resource=(listing_resource | None, None),
    )


@cache
def receipt_model(kind: str) -> type[Receipt]:
    return create_model("Receipt", __base__=Receipt, kind=_kind(kind))


@cache
def result_model(kind: str) -> type[Result]:
    return create_model("Result", __base__=Result, kind=_kind(kind))
