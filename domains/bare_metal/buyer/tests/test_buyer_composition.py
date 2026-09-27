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
from arkhai_bare_metal.fixtures.listing import LISTING_HARDWARE
from registry_client import FilterSpecResponse
from arkhai_bare_metal_buyer.cli import bare_metal_listing_params

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
        capacity_backing="backed",
        host_id="machine-1",
        physical_host_id="physical-host-1",
        access_methods=["ssh"],
        **LISTING_HARDWARE,
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

def test_contact_entries_parse_as_bounded_pairs() -> None:
    from arkhai_bare_metal_buyer.cli import _parse_contact

    assert _parse_contact(["telegram=@buyer", "email= me@example.com "]) == {
        "telegram": "@buyer",
        "email": "me@example.com",
    }
    import typer

    with pytest.raises(typer.BadParameter):
        _parse_contact(["telegram"])
    with pytest.raises(typer.BadParameter):
        _parse_contact(["=value"])


def test_introduction_commands_are_registered() -> None:
    from arkhai_bare_metal_buyer.cli import bare_metal_app

    names = {command.name for command in bare_metal_app.registered_commands}
    assert {"request-introduction", "introduce", "introduction"} <= names


def test_the_reveal_is_printed_before_it_is_delivered(capsys, tmp_path) -> None:
    """A slow sink must never delay or obscure the answer the buyer came for."""

    from types import SimpleNamespace

    from arkhai_bare_metal_buyer import cli

    order: list[str] = []

    class Sinks:
        warnings = ()
        sinks = ("one",)

    def fake_deliver(projection, *, sinks, agreement_ref, counterparty):
        order.append("delivered")
        return ()

    original_json = cli._json

    def watching_json(value):
        order.append("printed")
        original_json(value)

    monkey = pytest.MonkeyPatch()
    monkey.setattr(cli, "_json", watching_json)
    monkey.setattr(cli, "deliver_introduction", fake_deliver)
    monkey.setattr(cli, "report_delivery", lambda *args, **kwargs: None)
    try:
        projection = {"obligation_ref": "a" * 64, "revealed": True}
        cli._json(projection)
        cli._deliver_locally(
            projection,
            SimpleNamespace(negotiation_id="neg-1", seller_principals=None),
            Sinks(),
            SimpleNamespace(event=lambda *args, **kwargs: None),
        )
    finally:
        monkey.undo()

    assert order == ["printed", "delivered"]


def test_the_read_command_can_redeliver() -> None:
    from arkhai_bare_metal_buyer.cli import bare_metal_app

    command = next(
        item
        for item in bare_metal_app.registered_commands
        if item.name == "introduction"
    )
    assert "deliver" in command.callback.__code__.co_varnames


# The two compute-schema filters these tests query, declared as a registry does.
_FILTER_SPEC = FilterSpecResponse(
    version=6,
    etag="spec-etag-1",
    listing_shape={},
    filters=[
        {"name": "gpu_model", "path": "$.listing_resource.gpu_model", "op": "in",
         "value_type": "string", "on_missing": "fail"},
        {"name": "gpu_count_min", "query_name": "gpu_count", "query_aliases": ["gpu_count_min"],
         "path": "$.listing_resource.gpu_count", "op": "range", "value_type": "integer",
         "alias_kind": "lower_bound", "on_missing": "fail"},
    ],
    schema_id="compute.market",
    schema_version=2,
)


class _SpecClient:
    def __init__(self) -> None:
        self.spec_reads = 0

    def get_filter_spec(self) -> FilterSpecResponse:
        self.spec_reads += 1
        return _FILTER_SPEC


def test_a_listing_read_is_always_restricted_to_bare_metal() -> None:
    client = _SpecClient()

    assert bare_metal_listing_params(client, None, registry_url="https://registry") == {
        "offering_mode": "bare_metal"
    }
    assert client.spec_reads == 0


def test_a_resource_query_compiles_against_the_registry_and_carries_its_etag() -> None:
    params = bare_metal_listing_params(
        _SpecClient(), "gpu_model=H200 gpu_count>=8", registry_url="https://registry"
    )

    assert params["offering_mode"] == "bare_metal"
    assert params["etag"] == "spec-etag-1"
    assert {key for key in params} >= {"gpu_model", "gpu_count_min"}


def test_a_field_the_registry_does_not_declare_is_refused_before_any_read() -> None:
    with pytest.raises(typer.BadParameter, match="--resource|region"):
        bare_metal_listing_params(
            _SpecClient(), "region=us-west", registry_url="https://registry"
        )
