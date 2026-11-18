"""Seller-authored fields shared by market listing envelopes."""

from collections.abc import Mapping
from typing import Annotated, Any

from pydantic import BaseModel, Field, StrictBool, StrictFloat, StrictInt, StrictStr

ListingTitle = Annotated[StrictStr, Field(max_length=200)]
ListingDescription = Annotated[StrictStr, Field(max_length=4000)]
MetadataKey = Annotated[StrictStr, Field(min_length=1, max_length=40, pattern=r"^[A-Za-z0-9_.-]+$")]
MetadataValue = (
    Annotated[StrictStr, Field(max_length=500)]
    | StrictInt
    | Annotated[StrictFloat, Field(allow_inf_nan=False)]
    | StrictBool
)
ListingMetadata = Annotated[dict[MetadataKey, MetadataValue], Field(max_length=50, strict=True)]


class ListingDetails(BaseModel):
    """Optional seller claims about a listing, independent of its resource."""

    title: ListingTitle | None = None
    description: ListingDescription | None = None
    metadata: ListingMetadata | None = None


def supplied_listing_details(fields: Mapping[str, Any]) -> dict[str, Any]:
    """Project the stated details without populating fields the seller omitted."""
    return {key: fields[key] for key in ListingDetails.model_fields if fields.get(key) is not None}
