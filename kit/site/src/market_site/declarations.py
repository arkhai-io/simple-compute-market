"""A capacity declaration: the one definition of its fields and their rules.

Every place that builds, stores, compares, or accepts a declaration — the
ledger, a capacity-definitions document, the registration request, the
derivation of declarations from legacy host capacity — uses this model, so a
field is added, renamed, or constrained here and nowhere else.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Any, ClassVar

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
)
from pydantic_core import PydanticCustomError

NonEmptyText = Annotated[str, StringConstraints(min_length=1)]


def _declared_amount(value: Any) -> Decimal:
    """One dimension's declared total: a finite, non-negative number.

    A string is refused even when it spells a number, so ``"8"`` in a
    document is an error rather than a quantity.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise PydanticCustomError(
            "invalid_amount", "must be a non-negative number, got {value}",
            {"value": repr(value)},
        )
    amount = Decimal(str(value))
    if not amount.is_finite() or amount < 0:
        raise PydanticCustomError(
            "invalid_amount", "must be a non-negative number, got {value}",
            {"value": repr(value)},
        )
    return amount


DeclaredCapacity = dict[NonEmptyText, Annotated[Any, AfterValidator(_declared_amount)]]


class CapacityDeclarationFields(BaseModel):
    """The fields a declaration's body carries, without its resource id.

    Shared by the declaration itself and by the registration request, which
    takes the resource id from its path.
    """

    IDENTITY_FIELDS: ClassVar[frozenset[str]] = frozenset(
        {"resource_id", "pool_id", "host_id", "resource_type", "resource_subtype"}
    )

    pool_id: NonEmptyText = Field(
        description=(
            "The Resource Pool this declaration belongs to. Required: a "
            "declaration is replaced whole, so a defaulted pool would move it."
        ),
    )
    resource_type: NonEmptyText
    resource_subtype: NonEmptyText | None = Field(
        default=None, description="e.g. the GPU model slug ('h200')."
    )
    host_id: NonEmptyText | None = Field(
        default=None,
        description=(
            "The host this capacity is delivered through, if any. At most one "
            "declaration may name a given host."
        ),
    )
    attributes: dict[NonEmptyText, Any] = Field(
        default_factory=dict,
        description=(
            "Categorical facts claims match by equality (gpu_model, region, "
            "…). None may name one of the declaration's own identity fields."
        ),
    )
    enabled: bool = True

    @field_validator("attributes")
    @classmethod
    def _attributes_do_not_restate_identity(
        cls, attributes: dict[str, Any]
    ) -> dict[str, Any]:
        # An attribute of the same name would be a second, possibly
        # disagreeing statement of the field, and claims match fields and
        # attributes in one namespace.
        restated = sorted(cls.IDENTITY_FIELDS.intersection(attributes))
        if restated:
            raise PydanticCustomError(
                "reserved_attribute",
                "attributes may not name declaration fields {restated}; pass "
                "them as the declaration's own fields",
                {"restated": restated},
            )
        return attributes


class CapacityDeclaration(CapacityDeclarationFields):
    """One capacity resource's whole declaration.

    Authoritative for exactly the dimensions ``capacity`` names; every other
    field is replaced along with it when the declaration is registered.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    resource_id: NonEmptyText
    capacity: DeclaredCapacity = Field(
        min_length=1,
        description="Total capacity per dimension; at least one dimension.",
    )
