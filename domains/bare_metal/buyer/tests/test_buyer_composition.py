from __future__ import annotations

from pathlib import Path
import json

import pytest
import typer
from typer.testing import CliRunner
from arkhai_bare_metal_buyer.cli import (
    _json,
    _safe_projection,
    _validate_hosted_option_binding,
    register_commands,
)
from arkhai_bare_metal_buyer.config import load_bare_metal_buyer_config
from arkhai_bare_metal_buyer.plugin import domain
from market_core import DomainCapability
from arkhai_bare_metal import BareMetalListing

from arkhai_bare_metal_buyer.fulfillment import BareMetalFulfillmentTransport
from market_identity import IdentityScheme, TrustedIdentitySet, create_signer
from pydantic import BaseModel

PRINCIPAL = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"


def test_config_is_secret_free_and_strict(tmp_path: Path) -> None:
    path = tmp_path / "buyer.toml"
    path.write_text(
        """
[bare_metal]
registry_url = "https://registry.example"
registry_authority = "registry-prod"
registry_principals = [{scheme = "ed25519", identifier = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"}]
default_duration_seconds = 7200
""".strip(),
        encoding="utf-8",
    )
    config = load_bare_metal_buyer_config(path)
    assert config.default_duration_seconds == 7200
    assert config.registry_trust.identities[0].identifier == PRINCIPAL

    path.write_text(
        path.read_text() + '\nprivate_key = "forbidden"\n', encoding="utf-8"
    )
    with pytest.raises(ValueError):
        load_bare_metal_buyer_config(path)


def test_transient_action_material_is_not_rendered() -> None:
    safe = _safe_projection(
        {
            "status": "awaiting_action",
            "action": {
                "kind": "redirect",
                "expires_at_unix": 123,
                "url": "https://provider.example/secret",
                "bank_instructions": {"account": "123"},
            },
        }
    )
    assert safe == {
        "status": "awaiting_action",
        "action_required": {"kind": "redirect", "expires_at_unix": 123},
    }


def test_plugin_declares_real_buyer_capability() -> None:
    contract = domain
    assert DomainCapability.BUYER in contract.declared_capabilities
    assert contract.buyer is not None
    assert contract.buyer.register_commands is not None


def test_hosted_payer_commands_are_available() -> None:
    app = typer.Typer()
    register_commands(app)

    result = CliRunner().invoke(
        app,
        ["settlement", "stripe", "payer", "--help"],
    )

    assert result.exit_code == 0, result.output
    assert "create" in result.output


def test_physical_transport_uses_signed_buyer_routes(monkeypatch) -> None:
    calls = []

    def signed(url, body, **kwargs):
        calls.append((url, body, kwargs))
        return {"ok": True}

    monkeypatch.setattr(
        "arkhai_bare_metal_buyer.fulfillment.signed_storefront_json",
        signed,
    )
    signer = create_signer(IdentityScheme.ED25519, bytes(range(32)))
    trust = TrustedIdentitySet(
        identities=(create_signer(IdentityScheme.ED25519, bytes([1]) * 32).identity,)
    )
    transport = BareMetalFulfillmentTransport(
        seller_url="https://seller.example/",
        principal=signer.identity,
        signer=signer,
        resolve_seller_principals=lambda: trust,
    )

    assert transport.result("neg-1") == {"ok": True}
    assert transport.access("neg-1") == {"ok": True}
    assert transport.teardown("neg-1") == {"ok": True}

    assert [
        (url, kwargs["method"], kwargs["operation"], kwargs["resource"])
        for url, _body, kwargs in calls
    ] == [
        (
            "https://seller.example/api/v1/fulfillments/neg-1/result",
            "GET",
            "bare_metal_fulfillment_result",
            "neg-1",
        ),
        (
            "https://seller.example/api/v1/fulfillments/neg-1/access",
            "GET",
            "bare_metal_fulfillment_access",
            "neg-1",
        ),
        (
            "https://seller.example/api/v1/fulfillments/neg-1/teardown",
            "POST",
            "bare_metal_fulfillment_teardown",
            "neg-1",
        ),
    ]
    assert all(body is None for _url, body, _kwargs in calls)


def test_json_output_serializes_nested_wire_models(capsys) -> None:
    class NestedWireModel(BaseModel):
        value: str

    class WireResponse:
        def to_dict(self):
            return {"results": [NestedWireModel(value="ready")]}

    _json(WireResponse())

    assert json.loads(capsys.readouterr().out) == {
        "results": [{"value": "ready"}],
    }


def test_hosted_option_binding_compares_physical_host_identity() -> None:
    listing = BareMetalListing(
        machine_id="machine-1",
        physical_host_id="physical-host-1",
        access_methods=["ssh"],
    )

    _validate_hosted_option_binding(
        listing,
        physical_host_id="physical-host-1",
    )
    with pytest.raises(typer.BadParameter, match="conflicts with trusted listing"):
        _validate_hosted_option_binding(
            listing,
            physical_host_id="different-host",
        )
