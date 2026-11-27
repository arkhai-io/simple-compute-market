"""Wire declarations for shared registry filters and schema selection."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

ValueType = Literal["string", "integer", "number", "boolean", "address", "decimal_text"]
Op = Literal["in", "range", "not_in", "exists"]
AliasKind = Literal["lower_bound", "upper_bound"]
OnMissing = Literal["fail", "pass"]

class FilterDecl(BaseModel):
    """One filter declaration in the registry's filter spec."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    path: str = Field(
        min_length=1,
        description="JSONPath (RFC 9535) into the listing document.",
    )
    query_name: str | None = Field(
        default=None,
        min_length=1,
        description="Primary field name exposed by the buyer resource DSL.",
    )
    query_aliases: list[str] = Field(
        default_factory=list,
        description="Additional explicit buyer resource DSL field names.",
    )
    op: Op
    value_type: ValueType
    alias_kind: AliasKind | None = None
    on_missing: OnMissing = "fail"
    indexed: bool = False
    requires: list[str] = Field(
        default_factory=list,
        description=(
            "Other declared filter names that must accompany this one in a "
            "query. One-directional: a co-requirement target may be supplied "
            "alone. Omitted from the served body and the etag input when "
            "empty, so declaring no co-requirement never changes a spec's "
            "serialization or etag."
        ),
    )


class SchemaIdentity(BaseModel):
    """Stable identity of the listing schema this registry serves.

    ``id`` is the stable listing-schema name that buyer-domain commands
    declare compatibility with (for example, ``"compute.market"``). With several
    registries configured, a domain queries only registries whose declared id
    matches. ``version`` is the schema-contract version; buyers match on id
    alone today, and the version remains advisory until a second schema
    version exists.
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    version: int = Field(default=1, ge=1)


class FilterSpec(BaseModel):
    """Parsed filter spec ready to serve."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    version: int = Field(ge=1)
    #: Optional schema identity (YAML key ``schema``). Absent on legacy
    #: specs — buyers treat an undeclared registry as matching any
    #: plugin, so adding the header is opt-in per deployment.
    schema_identity: SchemaIdentity | None = Field(default=None, alias="schema")
    listing_shape: dict[str, Any]
    filters: list[FilterDecl]
