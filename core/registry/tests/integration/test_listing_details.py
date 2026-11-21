"""Seller-authored listing details, through the canonical client.

The real registry app and its database, with `RegistryClient` over
`ASGITransport` signing as the maker. A listing's `title`, `description` and
`metadata` live in the publication document the registry retains whole: they
read back as sent, inside the seller's own signed publication too; a
republication replaces them, so details a seller stops stating are gone and a
metadata filter then decides the listing by its `on_missing` rule; a value over
a limit is refused at publication and by the dry run alike, naming the field and
writing nothing. Each limit is the unit suites'; here one refusal shows the
routes apply them.

The typed client builds every body below, refused ones included: it carries the
details as plain values and leaves their limits to the registry, so each refusal
is the registry's own. An explicit null travels as a listing-level term the
client passes through unchanged, since the client omits an unstated detail.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest
import yaml
from market_core.listing_details import ListingDetails

from registry_client import ListingRequest, RegistryClientError, ValidatePublishRequest
from core_registry.api import filter_spec as filter_spec_module
from core_registry.config import load_settings

pytestmark = pytest.mark.asyncio

_REPO_ROOT = Path(__file__).resolve().parents[4]
_COMPUTE_SPEC = _REPO_ROOT / "core/registry/src/core_registry/filter-spec.yaml"
_API_CREDITS_SPEC = _REPO_ROOT / "domains/apicredits/registry/filter-spec.yaml"
_OPTION = {"option_id": "a" * 64, "settlement": {"schema": "example.payment.v1"}}
_DETAILS = {
    "title": "Eight GPUs, ready now",
    "description": "Dedicated hosts in one rack.\nSLA 99.9.",
    "metadata": {"acme.tier": "gold", "cooldown_hours": 0, "ratio": 0.5, "ipv4": True},
}
_DETAIL_FIELDS = ("title", "description", "metadata")


def _listing(listing_id: str, **details) -> ListingRequest:
    return ListingRequest(
        listing_id=listing_id,
        listing_resource={"region": "example", "offering_mode": "vm"},
        accepted_escrows=[],
        settlement_options=[_OPTION],
        storefront_url="http://localhost:8001/",
        **details,
    )


def _dry_run(listing_id: str, **details) -> ValidatePublishRequest:
    return ValidatePublishRequest(
        listing_id=listing_id,
        listing_resource={"region": "example", "offering_mode": "vm"},
        accepted_escrows=[],
        settlement_options=[_OPTION],
        storefront_url="http://localhost:8001/",
        **details,
    )


def _signed_body(listing) -> dict:
    return json.loads(base64.b64decode(listing.extra["publisher_publication"]["body_base64"]))


async def _searched(registry_client, listing_id: str):
    page = await registry_client.list_listings(status=None, limit=100)
    (listing,) = [row for row in page.listings if str(row.id) == listing_id]
    return listing


@pytest.fixture
def served_spec(monkeypatch, tmp_path):
    """Serve one specification file for the duration of a test.

    The file is named by a profile env file, as a deployment's profile names it,
    and the served-spec cache is reset to it; without the reset the process would
    keep serving the specification it loaded first.
    """
    monkeypatch.delenv("REGISTRY_FILTER_SPEC_PATH", raising=False)

    def _use(path: Path) -> None:
        (tmp_path / "config-spec.env").write_text(f"REGISTRY_FILTER_SPEC_PATH={path}\n")
        filter_spec_module.reset_cache(
            load_settings({"CONFIG_DIRECTORY": str(tmp_path), "ACTIVE_PROFILES": "spec"})
        )

    yield _use
    filter_spec_module.reset_cache()


@pytest.fixture
def tier_filter(served_spec, tmp_path):
    """Serve the compute specification with one filter on a metadata key."""
    spec = yaml.safe_load(_COMPUTE_SPEC.read_text())
    spec["filters"].append(
        {
            "name": "acme_tier",
            "path": '$.metadata["acme.tier"]',
            "op": "in",
            "value_type": "string",
            "on_missing": "fail",
        }
    )
    path = tmp_path / "filter-spec.yaml"
    path.write_text(yaml.safe_dump(spec, sort_keys=False))
    served_spec(path)
    return "acme_tier"


async def test_stated_details_read_back_unchanged_everywhere(registry_client):
    await registry_client.publish_listing(_listing("details-1", **_DETAILS))

    detail = await registry_client.get_listing("details-1")
    searched = await _searched(registry_client, "details-1")
    for listing in (detail, searched):
        assert (listing.title, listing.description, listing.metadata) == (
            _DETAILS["title"], _DETAILS["description"], _DETAILS["metadata"],
        )
    signed = _signed_body(detail)
    assert {field: signed[field] for field in _DETAIL_FIELDS} == _DETAILS


async def test_a_republication_replaces_and_then_withdraws_the_details(
    registry_client, tier_filter
):
    await registry_client.publish_listing(_listing("details-2", **_DETAILS))
    first = await registry_client.get_listing("details-2")
    gold = await registry_client.list_listings(**{tier_filter: "gold"})
    assert [str(row.id) for row in gold.listings] == ["details-2"]

    changed = {
        "title": "Four GPUs",
        "description": "Half the rack.",
        "metadata": {"acme.tier": "silver"},
    }
    await registry_client.publish_listing(_listing("details-2", **changed))
    second = await registry_client.get_listing("details-2")
    assert (second.title, second.description, second.metadata) == (
        changed["title"], changed["description"], changed["metadata"],
    )
    silver = await registry_client.list_listings(**{tier_filter: "silver"})
    gold = await registry_client.list_listings(**{tier_filter: "gold"})
    assert [str(row.id) for row in silver.listings] == ["details-2"]
    assert gold.listings == []

    await registry_client.publish_listing(_listing("details-2"))
    withdrawn = await registry_client.get_listing("details-2")
    searched = await _searched(registry_client, "details-2")
    for listing in (withdrawn, searched):
        assert (listing.title, listing.description, listing.metadata) == (None, None, None)
    assert not set(_DETAIL_FIELDS).intersection(_signed_body(withdrawn))
    assert (withdrawn.id, withdrawn.publisher_id, withdrawn.created_at) == (
        first.id, first.publisher_id, first.created_at,
    )

    # With the key gone, the filter decides by its on_missing rule: `fail`
    # excludes the listing, and the query loosening it to `pass` includes it.
    silver = await registry_client.list_listings(**{tier_filter: "silver"})
    assert silver.listings == []
    loosened = await registry_client.list_listings(
        **{tier_filter: "silver", f"strict.{tier_filter}": False}
    )
    assert [str(row.id) for row in loosened.listings] == ["details-2"]


async def test_a_detail_over_its_limit_is_refused_naming_it_with_nothing_written(
    registry_client,
):
    """One representative refusal: which values each limit refuses is the unit
    suites' (`core`'s model, the registry's `listing_validation_errors`)."""
    refused = {"metadata": {"k": None}}

    with pytest.raises(RegistryClientError) as caught:
        await registry_client.publish_listing(_listing("refused-new", **refused))

    assert caught.value.status_code == 422
    assert "metadata.k" in caught.value.body
    with pytest.raises(RegistryClientError) as missing:
        await registry_client.get_listing("refused-new")
    assert missing.value.status_code == 404

    # The dry run judges the same body the same way, writing nothing either.
    dry_run = await registry_client.validate_publish_listing(_dry_run("refused-new", **refused))
    assert not dry_run.valid
    assert dry_run.errors
    assert all(error.startswith("metadata.k") for error in dry_run.errors), dry_run.errors
    assert all(error in caught.value.body for error in dry_run.errors)


async def test_a_refused_republication_leaves_the_stored_details(registry_client):
    await registry_client.publish_listing(_listing("refused-kept", **_DETAILS))
    before = await registry_client.get_listing("refused-kept")

    with pytest.raises(RegistryClientError) as caught:
        await registry_client.publish_listing(
            _listing("refused-kept", title="t" * 201, metadata={"acme.tier": "bronze"})
        )

    assert caught.value.status_code == 422
    after = await registry_client.get_listing("refused-kept")
    assert (after.title, after.description, after.metadata) == (
        _DETAILS["title"], _DETAILS["description"], _DETAILS["metadata"],
    )
    assert after.extra["publisher_publication"] == before.extra["publisher_publication"]
    assert after.updated_at == before.updated_at


async def test_an_explicit_null_is_admitted_as_unstated_and_retained_as_sent(registry_client):
    request = _listing("details-null")
    request.extra = {"title": None, "description": None, "metadata": None}

    dry_run = await registry_client.validate_publish_listing(
        _dry_run("details-null", extra={"title": None, "description": None, "metadata": None})
    )
    await registry_client.publish_listing(request)

    assert dry_run.valid and dry_run.errors == []
    listing = await registry_client.get_listing("details-null")
    assert (listing.title, listing.description, listing.metadata) == (None, None, None)
    # The retained document keeps the nulls as sent.
    assert {field: _signed_body(listing)[field] for field in _DETAIL_FIELDS} == dict.fromkeys(
        _DETAIL_FIELDS
    )


async def test_the_dry_run_admits_stated_details_within_their_limits(registry_client):
    result = await registry_client.validate_publish_listing(_dry_run("dry-ok", **_DETAILS))

    assert result.valid and result.errors == []
    with pytest.raises(RegistryClientError) as missing:
        await registry_client.get_listing("dry-ok")
    assert missing.value.status_code == 404


@pytest.mark.parametrize(
    "spec_path", [_COMPUTE_SPEC, _API_CREDITS_SPEC], ids=["compute", "api-credits"]
)
async def test_the_served_listing_shape_declares_the_details(
    registry_client, served_spec, spec_path
):
    """Each shipped specification is served with the details, though neither
    file names them: the registry adds them to whatever specification it loads."""
    assert "metadata" not in yaml.safe_load(spec_path.read_text())["listing_shape"].get(
        "properties", {}
    )
    served_spec(spec_path)

    shape = (await registry_client.get_filter_spec()).listing_shape

    # Served as the shared model states each field, less the null an optional
    # field admits: a present detail must be a valid one.
    model = ListingDetails.model_json_schema()["properties"]
    for field in _DETAIL_FIELDS:
        (stated,) = [v for v in model[field]["anyOf"] if v.get("type") != "null"]
        assert shape["properties"][field] == stated
    # Closed, so a key outside the character class is refused by the schema as
    # by the publish boundary, not admitted with any value.
    assert shape["properties"]["metadata"]["additionalProperties"] is False
    assert not set(_DETAIL_FIELDS).intersection(shape.get("required", []))


async def test_a_listing_stating_no_details_publishes_and_reads_as_before(registry_client):
    request = _listing("details-none")
    assert not set(_DETAIL_FIELDS).intersection(request.to_dict())

    await registry_client.publish_listing(request)

    listing = await registry_client.get_listing("details-none")
    assert (listing.title, listing.description, listing.metadata) == (None, None, None)
    assert not set(_DETAIL_FIELDS).intersection(_signed_body(listing))
    assert listing.listing_resource == {"region": "example", "offering_mode": "vm"}
    assert listing.settlement_options == [_OPTION]
