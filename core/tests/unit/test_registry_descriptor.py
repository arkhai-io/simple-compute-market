from __future__ import annotations

import pytest
from pydantic import ValidationError

from market_core import RegistryDescriptor

_ED25519 = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"


def _descriptor(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "access": {"posture": "public"},
        "authority": {
            "name": "registry-a",
            "principals": [{"scheme": "ed25519", "identifier": _ED25519}],
        },
        "baseUrl": "https://registry.example/",
        "displayName": " Example Compute Registry ",
        "operatorIdentity": " Example Operator ",
        "schema": {"id": "vms.compute", "version": "1"},
    }
    value.update(overrides)
    return value


def test_descriptor_emits_exact_portable_wire_shape() -> None:
    descriptor = RegistryDescriptor.model_validate(_descriptor())

    assert descriptor.to_wire() == {
        "access": {"posture": "public"},
        "authority": {
            "name": "registry-a",
            "principals": [{"scheme": "ed25519", "identifier": _ED25519}],
        },
        "baseUrl": "https://registry.example",
        "displayName": "Example Compute Registry",
        "operatorIdentity": "Example Operator",
        "schema": {"id": "vms.compute", "version": "1"},
    }


def test_key_gated_descriptor_requires_http_acquisition_pointer() -> None:
    descriptor = RegistryDescriptor.model_validate(
        _descriptor(
            access={
                "posture": "key-gated",
                "acquisitionPointer": "https://registry.example/access",
            }
        )
    )

    assert descriptor.to_wire()["access"] == {
        "posture": "key-gated",
        "acquisitionPointer": "https://registry.example/access",
    }
    with pytest.raises(ValidationError, match="HTTP or HTTPS"):
        RegistryDescriptor.model_validate(
            _descriptor(
                access={
                    "posture": "key-gated",
                    "acquisitionPointer": "mailto:operator@example.com",
                }
            )
        )


@pytest.mark.parametrize(
    "authority",
    [
        {"name": "registry-a", "principals": []},
        {
            "name": "registry-a",
            "principals": [
                {"scheme": "ed25519", "identifier": _ED25519},
                {"scheme": "ed25519", "identifier": _ED25519},
            ],
        },
        {
            "name": "registry-a",
            "principals": [{"scheme": "eip191", "identifier": "0x" + "AB" * 20}],
        },
        {
            "name": "registry-a",
            "principals": [{"scheme": "ed25519", "identifier": "A" * 42 + "B"}],
        },
    ],
)
def test_descriptor_rejects_invalid_authority_pins(authority: object) -> None:
    with pytest.raises(ValidationError):
        RegistryDescriptor.model_validate(_descriptor(authority=authority))


def test_descriptor_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        RegistryDescriptor.model_validate(_descriptor(contact="operator@example.com"))
