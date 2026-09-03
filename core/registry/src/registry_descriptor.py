"""Construct the registry descriptor from authoritative runtime inputs."""

from __future__ import annotations

from market_core import RegistryDescriptor
from market_identity import Identity

from src.api.filter_spec import FilterSpec


def build_registry_descriptor(
    *,
    base_url: str | None,
    display_name: str | None,
    operator_identity: str | None,
    authority_name: str | None,
    authority_principal: Identity,
    filter_spec: FilterSpec,
    require_read_api_key: bool,
    acquisition_pointer: str | None,
) -> RegistryDescriptor:
    """Build one descriptor without duplicating signer, schema, or gate state."""

    required = {
        "REGISTRY_DESCRIPTOR_BASE_URL": base_url,
        "REGISTRY_DESCRIPTOR_DISPLAY_NAME": display_name,
        "REGISTRY_DESCRIPTOR_OPERATOR_IDENTITY": operator_identity,
        "REGISTRY_AUTHORITY_ID": authority_name,
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        raise RuntimeError(
            "registry descriptor configuration is incomplete: " + ", ".join(missing)
        )
    if filter_spec.schema_identity is None:
        raise RuntimeError("registry descriptor requires a filter-spec schema identity")
    if require_read_api_key and not acquisition_pointer:
        raise RuntimeError(
            "a key-gated registry descriptor requires "
            "REGISTRY_DESCRIPTOR_ACCESS_ACQUISITION_POINTER"
        )
    if not require_read_api_key and acquisition_pointer:
        raise RuntimeError(
            "a public registry descriptor must not configure "
            "REGISTRY_DESCRIPTOR_ACCESS_ACQUISITION_POINTER"
        )

    access: dict[str, str]
    if require_read_api_key:
        access = {
            "posture": "key-gated",
            "acquisitionPointer": acquisition_pointer or "",
        }
    else:
        access = {"posture": "public"}
    return RegistryDescriptor.model_validate(
        {
            "access": access,
            "authority": {
                "name": authority_name,
                "principals": [authority_principal.model_dump(mode="json")],
            },
            "baseUrl": base_url,
            "displayName": display_name,
            "operatorIdentity": operator_identity,
            "schema": {
                "id": filter_spec.schema_identity.id,
                "version": str(filter_spec.schema_identity.version),
            },
        }
    )
