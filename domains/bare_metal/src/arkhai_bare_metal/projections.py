"""Trusted specific-resource projection carriers for bare-metal publication."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .schema import EXCLUSIVE_ALLOCATION_MODE, SSH_ACCESS_METHOD

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
    """One explicitly publishable Physical Resource from a complete generation."""

    model_config = ConfigDict(extra="forbid")

    physical_resource_id: str = Field(min_length=1)
    pool_id: str | None = Field(default=None, min_length=1)
    physical_host_id: str = Field(min_length=1)
    host_id: str = Field(min_length=1)
    available: bool
    allocation_mode: Literal["exclusive"] = EXCLUSIVE_ALLOCATION_MODE
    access_methods: list[str] = Field(
        default_factory=lambda: [SSH_ACCESS_METHOD],
        min_length=1,
    )
    capacity: dict[str, Any] = Field(default_factory=dict)
    capabilities: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_public_projection(self) -> "BareMetalResourceProjection":
        for field_name in (
            "physical_resource_id",
            "physical_host_id",
            "host_id",
        ):
            if not getattr(self, field_name).strip():
                raise ValueError(f"{field_name} must be non-empty")
        if any(not method.strip() for method in self.access_methods):
            raise ValueError("access_methods must not contain blank values")
        _assert_public_value(self.capacity, path="capacity")
        _assert_public_value(self.capabilities, path="capabilities")
        conflicts = {
            key
            for key in self.capacity.keys() & self.capabilities.keys()
            if self.capacity[key] != self.capabilities[key]
        }
        if conflicts:
            names = ", ".join(sorted(conflicts))
            raise ValueError(
                f"capacity and capabilities conflict for: {names}",
            )
        return self


class TrustedBareMetalResource(BaseModel):
    """One Physical Resource's bare-metal view as its containing pool entry places it.

    ``pool_id`` is the containing pool entry's, which is authoritative for the
    resource's pool: a view repeating a different pool is refused. ``enabled``
    is the capacity declaration's own enablement, read from the projected
    resource rather than the view, because the view's ``available`` folds
    enablement and whole-resource availability together and publication must
    tell a withdrawn declaration from a leased machine.
    """

    model_config = ConfigDict(extra="forbid")

    pool_id: str = Field(min_length=1)
    enabled: bool
    view: BareMetalResourceProjection

    @model_validator(mode="after")
    def _validate_containment(self) -> "TrustedBareMetalResource":
        if not self.pool_id.strip():
            raise ValueError("pool_id must be non-empty")
        if self.view.pool_id is not None and self.view.pool_id != self.pool_id:
            raise ValueError(
                "bare-metal view pool_id conflicts with its containing pool"
            )
        return self

    @property
    def physical_resource_id(self) -> str:
        return self.view.physical_resource_id


class TrustedBareMetalProjection(BaseModel):
    """One configured site's accepted resource-pool projection generation.

    A site whose projection could not be fetched, or whose generation was
    refused, has no value of this type: it is unknown, not empty.
    """

    model_config = ConfigDict(extra="forbid")

    site_id: str = Field(min_length=1)
    revision: int = Field(ge=0)
    digest: str = Field(min_length=1)
    resources: list[TrustedBareMetalResource] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_generation(self) -> "TrustedBareMetalProjection":
        if not self.site_id.strip():
            raise ValueError("site_id must be non-empty")
        resource_ids = [item.physical_resource_id for item in self.resources]
        if len(resource_ids) != len(set(resource_ids)):
            raise ValueError("physical_resource_id must be unique within a site")
        return self
