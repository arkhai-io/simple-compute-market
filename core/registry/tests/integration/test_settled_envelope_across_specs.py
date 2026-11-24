"""The renamed listing envelope is generic, not compute-specific.

All three deployed filter specifications name the listing envelope
`listing_resource`. The compute one is covered by
`test_settled_listing_vocabulary.py`; this module covers the other two, which
have their own schema identities and publish no offering mode at all, so the
envelope has to hold for them independently.

Each case runs the real registry app against the real specification file with
its database, through the canonical `RegistryClient` over `ASGITransport`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from registry_client import ListingRequest
from core_registry.api import filter_spec as filter_spec_module
from core_registry.config import load_settings

pytestmark = pytest.mark.asyncio

_REPO_ROOT = Path(__file__).resolve().parents[4]
_COMPUTE_SPEC = _REPO_ROOT / "core/registry/src/core_registry/filter-spec.yaml"
_API_CREDITS_SPEC = _REPO_ROOT / "domains/apicredits/registry/filter-spec.yaml"
_INTRODUCTIONS_SPEC = (
    _REPO_ROOT / "core/registry/filter-spec.introductions.yaml"
)

_ESCROW = {
    "chain_name": "anvil",
    "escrow_address": "0x" + "11" * 20,
    "literal_fields": {"token": "0x" + "22" * 20},
}
_OPTION = {
    "option_id": "a" * 64,
    "price": {
        "asset": "usd",
        "rates": [{"field": "flat", "per": "deal", "value": "100"}],
    },
    "settlement": {"schema": "introduction.contact.v1", **({"channel": "email"} or {})},
}


@pytest.fixture
def served_spec(monkeypatch, tmp_path):
    """Point the app at one specification file for the duration of a test.

    The file is named by a profile env file, as a lane registry's profile names
    its specification, with no ``REGISTRY_FILTER_SPEC_PATH`` in the process
    environment. `reset_cache` takes the settings that profile builds: the loader
    memoizes one spec per process, so swapping the file without clearing the
    cache would silently keep serving the compute schema and the test would
    prove nothing.
    """
    monkeypatch.delenv("REGISTRY_FILTER_SPEC_PATH", raising=False)

    def _use(path: Path):
        (tmp_path / "config-spec.env").write_text(f"REGISTRY_FILTER_SPEC_PATH={path}\n")
        filter_spec_module.reset_cache(
            load_settings({"CONFIG_DIRECTORY": str(tmp_path), "ACTIVE_PROFILES": "spec"})
        )
        return filter_spec_module.get_loaded_spec()

    yield _use
    filter_spec_module.reset_cache()


class TestApiCreditsEnvelope:
    async def test_the_shape_key_is_required_under_its_settled_name(
        self, served_spec
    ):
        spec = served_spec(_API_CREDITS_SPEC)

        assert "listing_resource" in spec.listing_shape["required"]
        assert "offer_resource" not in spec.listing_shape["required"]
        assert spec.schema_identity.id == "api_credits"

    async def test_a_credits_listing_publishes_and_is_queried(
        self, served_spec, registry_client
    ):
        served_spec(_API_CREDITS_SPEC)

        await registry_client.publish_listing(
            ListingRequest(
                listing_id="credits-1",
                listing_resource={"service_name": "embeddings"},
                accepted_escrows=[_ESCROW],
                storefront_url="http://seller",
            )
        )

        matched = await registry_client.list_listings(service_name="embeddings")

        ids = {str(row.id) for row in matched.listings}
        assert "credits-1" in ids
        fetched = await registry_client.get_listing("credits-1")
        assert fetched.listing_resource == {"service_name": "embeddings"}

    async def test_a_credits_listing_with_a_market_settlement_option_is_admitted(
        self, served_spec, registry_client
    ):
        """Publication validates the whole schema, so the option shape it
        declares must be the market's settlement option, which its own
        mechanism and asset filters read."""
        served_spec(_API_CREDITS_SPEC)
        option = {
            "option_id": "b" * 64,
            "price": {
                "asset": "0x" + "22" * 20,
                "rates": [{"field": "amount", "per": "token", "value": "1"}],
            },
            "settlement": {"schema": "arkhai.payments.v1", "interaction": "hosted"},
            "lifecycle": {"delivery_deadline_seconds": 600},
        }

        await registry_client.publish_listing(
            ListingRequest(
                listing_id="credits-option",
                listing_resource={"service_name": "completions"},
                accepted_escrows=[],
                settlement_options=[option],
                storefront_url="http://seller",
            )
        )

        matched = await registry_client.list_listings(
            service_name="completions", settlement_mechanism="arkhai.payments.v1"
        )
        assert {str(row.id) for row in matched.listings} == {"credits-option"}
        fetched = await registry_client.get_listing("credits-option")
        assert fetched.settlement_options == [option]

    async def test_its_filter_reads_the_settled_path(self, served_spec):
        spec = served_spec(_API_CREDITS_SPEC)

        paths = {f.name: f.path for f in spec.filters}
        assert paths["service_name"] == "$.listing_resource.service_name"

    async def test_it_publishes_no_offering_mode_field(self, served_spec):
        """The mode rename does not reach this domain; only the envelope does.
        Asserted so a later change cannot quietly add one here on the
        assumption that every schema carries it."""
        spec = served_spec(_API_CREDITS_SPEC)

        shape = spec.listing_shape["properties"]["listing_resource"]
        assert "offering_mode" not in shape.get("properties", {})
        assert "offering_mode" not in {f.name for f in spec.filters}


class TestIntroductionsEnvelope:
    async def test_the_shape_key_is_required_under_its_settled_name(
        self, served_spec
    ):
        spec = served_spec(_INTRODUCTIONS_SPEC)

        assert "listing_resource" in spec.listing_shape["required"]
        assert "offer_resource" not in spec.listing_shape["required"]
        assert spec.schema_identity.id == "introductions.market"

    async def test_an_introduction_listing_publishes_and_is_queried(
        self, served_spec, registry_client
    ):
        served_spec(_INTRODUCTIONS_SPEC)

        await registry_client.publish_listing(
            ListingRequest(
                listing_id="intro-1",
                listing_resource={"region": "us-west"},
                accepted_escrows=[],
                settlement_options=[_OPTION],
                storefront_url="http://broker",
            )
        )

        matched = await registry_client.list_listings(region="us-west")

        ids = {str(row.id) for row in matched.listings}
        assert "intro-1" in ids
        fetched = await registry_client.get_listing("intro-1")
        assert fetched.listing_resource == {"region": "us-west"}

    async def test_its_filter_reads_the_settled_path(self, served_spec):
        spec = served_spec(_INTRODUCTIONS_SPEC)

        paths = {f.name: f.path for f in spec.filters}
        assert paths["region"] == "$.listing_resource.region"


class TestAllThreeSpecificationsAgree:
    async def test_no_deployed_specification_names_the_retired_key(
        self, served_spec
    ):
        """The envelope is one field across every deployed registry. A single
        specification left behind would mean the same field had two names
        depending on which registry served it."""
        for path in (
            _COMPUTE_SPEC,
            _API_CREDITS_SPEC,
            _INTRODUCTIONS_SPEC,
        ):
            spec = served_spec(path)
            assert "offer_resource" not in spec.listing_shape["required"], path
            assert not [
                f.path for f in spec.filters if "offer_resource" in f.path
            ], path

    async def test_each_keeps_its_own_schema_identity(self, served_spec):
        identities = {
            served_spec(path).schema_identity.id
            for path in (
                _COMPUTE_SPEC,
                _API_CREDITS_SPEC,
                _INTRODUCTIONS_SPEC,
            )
        }
        assert identities == {
            "compute.market",
            "api_credits",
            "introductions.market",
        }
