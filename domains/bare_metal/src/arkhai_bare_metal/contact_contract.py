"""Public seller declarations and frozen non-access introduction context."""

from __future__ import annotations

import json
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Identifier = Annotated[str, Field(strict=True, pattern=r"^[A-Za-z0-9_-]{1,128}$")]
Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
PositiveInteger = Annotated[int, Field(gt=0, le=9007199254740991)]


class ContactContextCarrier(BaseModel):
    model_config = ConfigDict(
        extra="forbid", strict=True, frozen=True, hide_input_in_errors=True
    )

    @field_validator("schema_version", mode="before", check_fields=False)
    @classmethod
    def integer_version(cls, value: object) -> object:
        if type(value) is not int:
            raise ValueError("integer version required")
        return value

    @field_validator("name", "region", "gpu_model", check_fields=False)
    @classmethod
    def scalar_text(cls, value: str) -> str:
        if not value.strip() or any(0xD800 <= ord(c) <= 0xDFFF for c in value):
            raise ValueError("nonblank scalar text required")
        return value


class ContactMachineDetails(ContactContextCarrier):
    gpu_model: str = Field(min_length=1, max_length=128)
    gpu_count: PositiveInteger
    vcpu_count: PositiveInteger
    ram_gb: PositiveInteger
    disk_gb: PositiveInteger
    region: str = Field(min_length=1, max_length=128)


class ContactDeclaration(ContactContextCarrier):
    schema_version: Literal[1]
    listing_id: Identifier
    declaration_id: Identifier
    name: str = Field(min_length=1, max_length=160)
    machine_details: ContactMachineDetails


class ContactAcceptedTerms(ContactContextCarrier):
    duration_seconds: PositiveInteger
    access_method: Literal["none"]


class AcceptedContactContext(ContactContextCarrier):
    schema_version: Literal[1]
    discovery_schema: Literal["vms.compute"]
    negotiation_schema: Literal["bare_metal.v1"]
    declaration: ContactDeclaration
    accepted_terms: ContactAcceptedTerms
    option_id: Digest
    publication_intent_digest: Digest
    source_envelope_digest: Digest
    listing_binding_digest: Digest


MAX_DECLARATION_FILE_BYTES = 1048576
MAX_DECLARATION_OFFERS = 256


class ContactDeclarationOffer(ContactContextCarrier):
    declaration: ContactDeclaration
    profile: str = Field(min_length=1, max_length=128, pattern=r"^[a-z0-9][a-z0-9_.-]*$")

    @model_validator(mode="after")
    def general_listing_namespace(self) -> ContactDeclarationOffer:
        listing_id = self.declaration.listing_id
        if not listing_id.startswith("declared-contact-") or listing_id == "declared-contact-":
            raise ValueError("invalid declaration listing namespace")
        return self


class ContactDeclarationOffers(ContactContextCarrier):
    schema_version: Literal[3]
    offers: list[ContactDeclarationOffer] = Field(min_length=1, max_length=MAX_DECLARATION_OFFERS)

    @model_validator(mode="after")
    def unique_ids(self) -> ContactDeclarationOffers:
        for field in ("listing_id", "declaration_id"):
            ids = [getattr(offer.declaration, field) for offer in self.offers]
            if len(ids) != len(set(ids)):
                raise ValueError("duplicate declaration identity")
        return self


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError("nonfinite JSON number")


def parse_contact_declaration_offers(data: bytes) -> ContactDeclarationOffers:
    """Validate bounded UTF-8 input without opening files or exposing values."""
    try:
        if type(data) is not bytes or len(data) > MAX_DECLARATION_FILE_BYTES:
            raise ValueError("invalid file bytes")
        value = json.loads(
            data.decode("utf-8"), object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
        return ContactDeclarationOffers.model_validate(value)
    except (TypeError, ValueError, RecursionError):
        raise ValueError("invalid_contact_declaration_file") from None
