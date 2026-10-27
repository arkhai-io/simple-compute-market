"""Trusted specific-resource projection carriers for bare-metal publication."""

from __future__ import annotations

from typing import Any, Literal

from market_resource_pools_contracts.backing import CapacityBackingLabel
from market_resource_pools_contracts.backing import capacity_backing as backing_of
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .schema import BARE_METAL_VIEW_DELIVERY_TERMS, EXCLUSIVE_ALLOCATION_MODE

_PRIVATE_KEY_PARTS = (
    "credential",
    "password",
    "private_key",
    "provider_config",
    "secret",
    "service_url",
    "authority_url",
)


def _assert_public_value(value: Any, *, path: str) -> None:
    if isinstance(value, dict):
        for raw_key, child in value.items():
            key = str(raw_key).strip().lower()
            if (
                key == "url"
                or key.endswith("_url")
                or any(part in key for part in _PRIVATE_KEY_PARTS)
            ):
                raise ValueError(f"private projection field is forbidden: {path}.{key}")
            _assert_public_value(child, path=f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _assert_public_value(child, path=f"{path}[{index}]")


class BareMetalResourceProjection(BaseModel):
    """One explicitly publishable Physical Resource from a complete generation.

    Its delivery terms (:data:`BARE_METAL_VIEW_DELIVERY_TERMS`) are optional
    and checked here only for structure. Whether a view must carry them or must
    not depends on its pool's backing, which the view does not state, so the
    rule is :class:`TrustedBareMetalResource`'s, given the backing.
    """

    model_config = ConfigDict(extra="forbid")

    physical_resource_id: str = Field(min_length=1)
    pool_id: str | None = Field(default=None, min_length=1)
    physical_host_id: str | None = None
    host_id: str | None = None
    available: bool | None = None
    allocation_mode: Literal["exclusive"] = EXCLUSIVE_ALLOCATION_MODE
    access_methods: list[str] | None = None
    capacity: dict[str, Any] = Field(default_factory=dict)
    # Publication-only data a seller may still configure. A listing's hardware
    # comes from the capacity declaration, which admission matches, so this is
    # accepted from a site but never published; publication reports it ignored.
    capabilities: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_public_projection(self) -> "BareMetalResourceProjection":
        if not self.physical_resource_id.strip():
            raise ValueError("physical_resource_id must be non-empty")
        for field_name in ("physical_host_id", "host_id"):
            value = getattr(self, field_name)
            if value is not None and not value.strip():
                raise ValueError(f"{field_name} must be non-empty when stated")
        if self.access_methods is not None and any(
            not method.strip() for method in self.access_methods
        ):
            raise ValueError("access_methods must not contain blank values")
        _assert_public_value(self.capacity, path="capacity")
        _assert_public_value(self.capabilities, path="capabilities")
        return self


class TrustedBareMetalResource(BaseModel):
    """One Physical Resource's bare-metal view as its containing pool entry places it.

    ``pool_id`` is the containing pool entry's, which is authoritative for the
    resource's pool: a view repeating a different pool is refused. ``enabled``
    is the capacity declaration's own enablement, read from the projected
    resource rather than the view, because the view's ``available`` folds
    enablement and whole-resource availability together and publication must
    tell a withdrawn declaration from a leased machine.

    ``capacity_backing`` is the containing pool's declared label, which the
    caller resolved for the pool. Given one, the view's delivery terms are held
    to that backing's delegate: a backed view missing a term and an unbacked
    view carrying one are both malformed, as a view naming another pool is.
    With none -- a pool whose declarations do not resolve -- no term is
    checked, and the pool's resources are held by whoever reads them.
    """

    model_config = ConfigDict(extra="forbid")

    pool_id: str = Field(min_length=1)
    enabled: bool
    view: BareMetalResourceProjection
    capacity_backing: CapacityBackingLabel | None = None
    # The declaration's own capacity and attributes, read from the projected
    # resource rather than the view: they are what admission matches, so they
    # are the only source of the listing's shape.
    declared_capacity: dict[str, Any] = Field(default_factory=dict)
    declared_attributes: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_containment(self) -> "TrustedBareMetalResource":
        if not self.pool_id.strip():
            raise ValueError("pool_id must be non-empty")
        if self.view.pool_id is not None and self.view.pool_id != self.pool_id:
            raise ValueError(
                "bare-metal view pool_id conflicts with its containing pool"
            )
        if self.capacity_backing is not None:
            backing_of(self.capacity_backing).delivery_term_constraints(
                {name: getattr(self.view, name) for name in BARE_METAL_VIEW_DELIVERY_TERMS}
            )
        return self

    @property
    def physical_resource_id(self) -> str:
        return self.view.physical_resource_id


class BareMetalViewProblems(BaseModel):
    """Why the site built no bare-metal view for one projected resource.

    The site projects such a resource without the view and names each problem,
    so a storefront derives nothing from it and can say why. ``enabled`` is the
    declaration's own enablement, which still tells a withdrawn declaration
    from one the site cannot read.
    """

    model_config = ConfigDict(extra="forbid")

    pool_id: str = Field(min_length=1)
    physical_resource_id: str = Field(min_length=1)
    enabled: bool
    problems: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_problems(self) -> "BareMetalViewProblems":
        if any(not problem.strip() for problem in self.problems):
            raise ValueError("a bare-metal view problem must be non-empty text")
        return self


class TrustedBareMetalProjection(BaseModel):
    """One configured site's accepted resource-pool projection generation.

    A site whose projection could not be fetched, or whose generation was
    refused, has no value of this type: it is unknown, not empty.
    ``view_problems`` names each resource the site could build no bare-metal
    view for, which yields no listing.
    """

    model_config = ConfigDict(extra="forbid")

    site_id: str = Field(min_length=1)
    revision: int = Field(ge=0)
    digest: str = Field(min_length=1)
    resources: list[TrustedBareMetalResource] = Field(default_factory=list)
    view_problems: list[BareMetalViewProblems] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_generation(self) -> "TrustedBareMetalProjection":
        if not self.site_id.strip():
            raise ValueError("site_id must be non-empty")
        # A resource is either viewed or reported unbuildable, never both, and
        # never twice: classification places each in exactly one class.
        resource_ids = [item.physical_resource_id for item in self.resources] + [
            item.physical_resource_id for item in self.view_problems
        ]
        if len(resource_ids) != len(set(resource_ids)):
            raise ValueError("physical_resource_id must be unique within a site")
        return self
