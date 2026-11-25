"""The inference specification served by the real registry app.

Runs the registry against the packaged inference filter specification with its
database, through the canonical `RegistryClient` over `ASGITransport`: a valid
model-card listing publishes and is found by every declared filter, and both
publication and the dry run refuse the shapes the specification exists to
refuse. The storefront's domain codec refuses more than the served shape can
express, the unit rate and the one-asset rule, and is proven in the domain's
own tests.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from registry_client import ListingRequest, RegistryClientError, ValidatePublishRequest
from core_registry.api import filter_spec as filter_spec_module
from core_registry.api import validate_routes
from core_registry.config import load_settings

pytestmark = pytest.mark.asyncio

_REPO_ROOT = Path(__file__).resolve().parents[4]
_INFERENCE_SPEC = _REPO_ROOT / "domains/inference/registry/filter-spec.yaml"
_ASSET = "0x" + "22" * 20
_ESCROW = {
    "chain_name": "anvil",
    "escrow_address": "0x" + "11" * 20,
    "literal_fields": {"token": _ASSET},
    "rates": [{"field": "amount", "per": "credit", "value": "1"}],
}
_OPTION = {
    "option_id": "a" * 64,
    "price": {
        "asset": _ASSET,
        "rates": [{"field": "amount", "per": "credit", "value": "1"}],
    },
    "settlement": {"schema": "alkahest.v1"},
}

# One query per declared filter, each matching `inference-1` as published
# below. The test refuses a specification that declares a filter this table
# does not query, so adding a filter means adding its proof here.
_QUERY_PER_FILTER = {
    "model_id": {"model_id": "meta-llama/llama-3.1-8b-instruct"},
    "model_family": {"model_family": "llama-3.1"},
    "quantization": {"quantization": "fp8"},
    "modality": {"modality": "text->text"},
    "supported_parameter": {"supported_parameter": "tools"},
    "provenance": {"provenance": "self-hosted"},
    "offering_mode": {"offering_mode": "inference"},
    "context_length_min": {"context_length_min": "65536"},
    "prompt_credits_max": {"prompt_credits_max": "600", "rate_card_asset": _ASSET},
    "completion_credits_max": {"completion_credits_max": "3000", "rate_card_asset": _ASSET},
    "rate_card_asset": {"rate_card_asset": _ASSET},
    "token": {"token": _ASSET},
    "token_exclude": {"token_exclude": "not_in:[0x" + "33" * 20 + "]"},
    "settlement_mechanism": {"settlement_mechanism": "alkahest.v1"},
    "settlement_asset": {"settlement_asset": _ASSET},
}


def _rate_card(prompt, completion, asset=_ASSET):
    # Decimal-digit strings: the registry stores the card as published and
    # compares the bounds as exact decimals.
    return {"asset": asset, "prompt_credits_per_million": str(prompt), "completion_credits_per_million": str(completion)}


def _card(**overrides):
    card = {
        "kind": "inference.v1",
        "model_id": "meta-llama/llama-3.1-8b-instruct",
        "artifact_ref": "hf://meta-llama/Llama-3.1-8B-Instruct@0e9e39f",
        "provenance": "self-hosted",
        "served_model_name": "llama-3.1-8b",
        "model_family": "llama-3.1",
        "context_length": 131072,
        "quantization": "fp8",
        "architecture": {"modality": "text->text"},
        "supported_parameters": ["tools", "response_format"],
        "endpoint": {"base_url": "https://inference.example/v1", "api_style": "openai.v1"},
        "rate_card": _rate_card(500, 1500),
        "capacity_site_id": "site-a",
        "offering_mode": "inference",
    }
    card.update(overrides)
    return card


def _serve(monkeypatch, tmp_path, spec_path):
    # Named by a profile env file, as a lane registry's profile names its
    # specification. The loader and the dry-run validator cache independently;
    # both must be cleared or a later test validates against this specification.
    monkeypatch.delenv("REGISTRY_FILTER_SPEC_PATH", raising=False)
    (tmp_path / "config-spec.env").write_text(f"REGISTRY_FILTER_SPEC_PATH={spec_path}\n")
    filter_spec_module.reset_cache(
        load_settings({"CONFIG_DIRECTORY": str(tmp_path), "ACTIVE_PROFILES": "spec"})
    )
    validate_routes._reset_cache()
    return filter_spec_module.get_loaded_spec()


def _stop_serving():
    filter_spec_module.reset_cache()
    validate_routes._reset_cache()


@pytest.fixture
def served_inference_spec(monkeypatch, tmp_path):
    yield _serve(monkeypatch, tmp_path, _INFERENCE_SPEC)
    _stop_serving()


@pytest.fixture
def served_narrowed_spec(monkeypatch, tmp_path):
    """The packaged specification with `model_id` narrowed to one identifier,
    as an operator enforcing its own vocabulary serves it."""
    document = yaml.safe_load(_INFERENCE_SPEC.read_text())
    properties = document["listing_shape"]["properties"]["listing_resource"]["properties"]
    properties["model_id"] = {"type": "string", "enum": [_card()["model_id"]]}
    narrowed = tmp_path / "narrowed-filter-spec.yaml"
    narrowed.write_text(yaml.safe_dump(document))
    yield _serve(monkeypatch, tmp_path, narrowed)
    _stop_serving()


async def _publish(registry_client, listing_id, card):
    await registry_client.publish_listing(
        ListingRequest(
            listing_id=listing_id,
            listing_resource=card,
            accepted_escrows=[_ESCROW],
            settlement_options=[_OPTION],
            storefront_url="http://seller",
        )
    )


async def _ids(registry_client, **query):
    matched = await registry_client.list_listings(**query)
    return {str(row.id) for row in matched.listings}


async def test_spec_identity(served_inference_spec):
    assert served_inference_spec.schema_identity.id == "inference"
    assert "listing_resource" in served_inference_spec.listing_shape["required"]


async def test_every_declared_filter_is_queried(served_inference_spec):
    declared = {declaration.name for declaration in served_inference_spec.filters}
    assert declared == set(_QUERY_PER_FILTER)


async def test_a_model_card_publishes_and_each_filter_finds_it(
    served_inference_spec, registry_client
):
    await _publish(registry_client, "inference-1", _card())
    await _publish(registry_client, "inference-2", _card(
        quantization="bf16",
        provenance="resold",
        context_length=8192,
        rate_card=_rate_card(900, 2700),
    ))

    for name, query in _QUERY_PER_FILTER.items():
        assert "inference-1" in await _ids(registry_client, **query), name

    assert await _ids(registry_client, model_id="meta-llama/llama-3.1-8b-instruct") == {"inference-1", "inference-2"}
    assert await _ids(registry_client, quantization="fp8") == {"inference-1"}
    assert await _ids(registry_client, provenance="resold") == {"inference-2"}
    assert await _ids(registry_client, context_length_min="65536") == {"inference-1"}
    assert await _ids(registry_client, prompt_credits_max="600", rate_card_asset=_ASSET) == {"inference-1"}
    assert await _ids(registry_client, completion_credits_max="3000", rate_card_asset=_ASSET) == {"inference-1", "inference-2"}
    assert await _ids(registry_client, prompt_credits_max="600", rate_card_asset="0x" + "33" * 20) == set()
    assert await _ids(registry_client, token_exclude=f"not_in:[{_ASSET}]") == set()
    assert await _ids(registry_client, settlement_mechanism="arkhai.payments.v1") == set()
    assert await _ids(registry_client, settlement_asset="0x" + "33" * 20) == set()

    fetched = await registry_client.get_listing("inference-1")
    assert fetched.listing_resource["rate_card"]["prompt_credits_per_million"] == "500"


async def test_a_rate_bound_without_its_asset_is_refused(served_inference_spec, registry_client):
    await _publish(registry_client, "inference-1", _card())
    with pytest.raises(RegistryClientError):
        await registry_client.list_listings(prompt_credits_max="600")
    with pytest.raises(RegistryClientError):
        await registry_client.list_listings(completion_credits_max="3000")
    # The option projection is not the card's asset: a bound paired with it
    # alone is still unpaired.
    with pytest.raises(RegistryClientError):
        await registry_client.list_listings(prompt_credits_max="600", settlement_asset=_ASSET)
    assert await _ids(registry_client, settlement_asset=_ASSET) == {"inference-1"}
    assert await _ids(registry_client, rate_card_asset=_ASSET) == {"inference-1"}


async def test_an_eighteen_decimal_rate_card_publishes_and_bounds_exactly(served_inference_spec, registry_client):
    # 7e21 base units is past 2**53-1; it publishes as decimal text under the
    # publisher's canonical signature and the bound compares it exactly.
    await _publish(registry_client, "big", _card(rate_card=_rate_card(7 * 10**21, 0)))
    assert await _ids(registry_client, prompt_credits_max=str(7 * 10**21), rate_card_asset=_ASSET) == {"big"}
    assert await _ids(registry_client, prompt_credits_max=str(7 * 10**21 - 1), rate_card_asset=_ASSET) == set()


async def test_attestation_is_admitted_and_not_filterable(served_inference_spec, registry_client):
    await _publish(registry_client, "attested", _card(
        attestation={"kind": "tee.example", "schema_version": 1, "payload": {"quote": "x"}}
    ))
    assert await _ids(registry_client, model_id="meta-llama/llama-3.1-8b-instruct") == {"attested"}
    assert "attestation" not in {f.name for f in served_inference_spec.filters}


async def _dry_run(registry_client, card):
    return await registry_client.validate_publish_listing(
        ValidatePublishRequest(
            listing_id="candidate",
            listing_resource=card,
            accepted_escrows=[_ESCROW],
            settlement_options=[_OPTION],
            storefront_url="http://seller",
        )
    )


async def test_a_complete_card_passes_the_dry_run(served_inference_spec, registry_client):
    response = await _dry_run(registry_client, _card())
    assert response.valid is True
    assert response.errors == []


@pytest.mark.parametrize(
    "card,field",
    [
        ({k: v for k, v in _card().items() if k != "rate_card"}, "rate_card"),
        ({k: v for k, v in _card().items() if k != "provenance"}, "provenance"),
        (_card(quantization="q4_k_m"), "quantization"),
        (_card(offering_mode="api_credits"), "offering_mode"),
        (_card(rate_card={"asset": _ASSET, "prompt_credits_per_million": 500, "completion_credits_per_million": "1500"}), "prompt_credits_per_million"),
        (_card(rate_card={"prompt_credits_per_million": "500", "completion_credits_per_million": "1500"}), "asset"),
        (_card(endpoint={"base_url": "https://inference.example/v1"}), "api_style"),
    ],
    ids=["no-rate-card", "no-provenance", "bad-quantization", "wrong-offering-mode", "numeric-rate", "no-rate-card-asset", "no-api-style"],
)
async def test_malformed_cards_fail_the_dry_run(served_inference_spec, registry_client, card, field):
    response = await _dry_run(registry_client, card)
    assert response.valid is False
    assert any(field in error for error in response.errors), response.errors


@pytest.mark.parametrize(
    "card,field",
    [
        ({k: v for k, v in _card().items() if k != "rate_card"}, "rate_card"),
        ({k: v for k, v in _card().items() if k != "context_length"}, "context_length"),
    ],
    ids=["no-rate-card", "no-context-length"],
)
async def test_a_malformed_card_is_refused_at_publication_and_not_stored(
    served_inference_spec, registry_client, card, field
):
    with pytest.raises(RegistryClientError) as refused:
        await _publish(registry_client, "malformed", card)

    assert refused.value.status_code == 422
    assert field in refused.value.body
    assert await _ids(registry_client, offering_mode="inference") == set()


async def test_a_narrowed_vocabulary_refuses_another_model_identifier(
    served_narrowed_spec, registry_client
):
    await _publish(registry_client, "listed", _card())
    other = _card(model_id="mistralai/mistral-7b-instruct")
    with pytest.raises(RegistryClientError) as refused:
        await _publish(registry_client, "unlisted", other)
    dry_run = await _dry_run(registry_client, other)

    assert refused.value.status_code == 422
    assert dry_run.valid is False
    assert await _ids(registry_client, offering_mode="inference") == {"listed"}
