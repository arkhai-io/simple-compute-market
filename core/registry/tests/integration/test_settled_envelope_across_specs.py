"""The renamed listing envelope is generic, not compute-specific.

`listing_resource` replaced `offer_resource` in all three deployed filter
specifications. The compute one is covered by
`test_settled_listing_vocabulary.py`; this closes 5.5 and 9.6 for the other
two, which have their own schema identities and publish no offering mode at
all — so the envelope rename has to hold for them independently.

Each case runs the real registry app against the real specification file with
its database, through the canonical `RegistryClient` over `ASGITransport`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from registry_client import ListingRequest
from src.api import filter_spec as filter_spec_module

pytestmark = pytest.mark.asyncio

_REPO_ROOT = Path(__file__).resolve().parents[4]
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
    "mechanism": "introduction.contact.v1",
    "asset": "usd",
    "rates": [{"field": "flat", "per": "deal", "value": "100"}],
    "params": {"channel": "email"},
}


@pytest.fixture
def served_spec(monkeypatch):
    """Point the app at one specification file for the duration of a test.

    `reset_cache` exists for exactly this: the loader memoizes one spec per
    process, so swapping the file without clearing the cache would silently
    keep serving the compute schema and the test would prove nothing.
    """

    def _use(path: Path):
        monkeypatch.setenv("REGISTRY_FILTER_SPEC_PATH", str(path))
        filter_spec_module.reset_cache()
        return filter_spec_module.get_loaded_spec()

    yield _use
    monkeypatch.delenv("REGISTRY_FILTER_SPEC_PATH", raising=False)
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
            _REPO_ROOT / "core/registry/filter-spec.yaml",
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
                _REPO_ROOT / "core/registry/filter-spec.yaml",
                _API_CREDITS_SPEC,
                _INTRODUCTIONS_SPEC,
            )
        }
        assert identities == {
            "compute.market",
            "api_credits",
            "introductions.market",
        }
