from __future__ import annotations

import pytest
from market_identity import Ed25519Signer

from src.api.filter_spec import FilterSpec, SchemaIdentity
from src.registry_descriptor import build_registry_descriptor


def _filter_spec() -> FilterSpec:
    return FilterSpec(
        version=1,
        schema=SchemaIdentity(id="api_credits", version=1),
        listing_shape={},
        filters=[],
    )


def test_descriptor_derives_authority_schema_and_public_posture() -> None:
    signer = Ed25519Signer(bytes(range(32)))

    descriptor = build_registry_descriptor(
        base_url="https://registry.example/credits/",
        display_name="API Credits Registry",
        operator_identity="Example Operator",
        authority_name="credits-registry",
        authority_principal=signer.identity,
        filter_spec=_filter_spec(),
        require_read_api_key=False,
        acquisition_pointer=None,
    )

    assert descriptor.to_wire() == {
        "access": {"posture": "public"},
        "authority": {
            "name": "credits-registry",
            "principals": [signer.identity.model_dump(mode="json")],
        },
        "baseUrl": "https://registry.example/credits",
        "displayName": "API Credits Registry",
        "operatorIdentity": "Example Operator",
        "schema": {"id": "api_credits", "version": "1"},
    }


def test_key_gated_descriptor_requires_acquisition_pointer() -> None:
    signer = Ed25519Signer(bytes(range(32)))

    with pytest.raises(RuntimeError, match="requires.*ACQUISITION_POINTER"):
        build_registry_descriptor(
            base_url="https://registry.example",
            display_name="Private Registry",
            operator_identity="Example Operator",
            authority_name="private-registry",
            authority_principal=signer.identity,
            filter_spec=_filter_spec(),
            require_read_api_key=True,
            acquisition_pointer=None,
        )


def test_public_descriptor_rejects_acquisition_pointer() -> None:
    signer = Ed25519Signer(bytes(range(32)))

    with pytest.raises(RuntimeError, match="public registry descriptor"):
        build_registry_descriptor(
            base_url="https://registry.example",
            display_name="Public Registry",
            operator_identity="Example Operator",
            authority_name="public-registry",
            authority_principal=signer.identity,
            filter_spec=_filter_spec(),
            require_read_api_key=False,
            acquisition_pointer="https://registry.example/access",
        )
