"""Integration test for GET /filter-spec.

Exercises the full HTTP path through the gated router: spec loads from
the shipped YAML, body+ETag are present, and the etag is stable across
two reads. It also queries listings under the shipped spec's GPU filters,
which a listing stating no GPU fails. The loader's structural validation
(invalid YAML, dup filter names, etc.) is covered in
``tests/unit/test_filter_spec.py``.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import httpx
import pytest
from market_identity import TrustedIdentitySet
from registry_client import ListingRequest, RegistryClient, RegistryClientError, compile_resource_query

from core_registry.api import filter_spec as fs_mod
from core_registry.config import Settings
from core_registry.main import app


@pytest.mark.asyncio
async def test_filter_spec_endpoint_returns_loaded_spec(registry_client) -> None:

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as raw:
        resp = await raw.get("/filter-spec")
    assert resp.status_code == 200

    body = resp.json()
    assert isinstance(body["version"], int) and body["version"] >= 1
    assert isinstance(body["etag"], str) and len(body["etag"]) == 64  # sha256 hex
    assert resp.headers["etag"].strip('"') == body["etag"]

    assert body["listing_shape"]["type"] == "object"
    required = set(body["listing_shape"].get("required") or [])
    assert {"listing_id", "listing_resource", "storefront_url"} <= required
    settlement_requirements = {
        tuple(branch.get("required") or [])
        for branch in body["listing_shape"].get("anyOf") or []
    }
    assert ("accepted_escrows",) in settlement_requirements
    assert ("settlement_options",) in settlement_requirements

    names = {f["name"] for f in body["filters"]}
    assert {"gpu_model", "region", "ram_gb_min", "token"} <= names

    # Numeric-min filters are sugared with alias_kind so URL parsing layer
    # in (a1b)'s filter eval can map `?ram_gb_min=16` → range form.
    ram_min = next(f for f in body["filters"] if f["name"] == "ram_gb_min")
    assert ram_min["op"] == "range"
    assert ram_min["alias_kind"] == "lower_bound"

    # The token filter must be underreport-friendly — sellers advertising no
    # tokens shouldn't be invisible to a `?token=...` query.
    token = next(f for f in body["filters"] if f["name"] == "token")
    assert token["on_missing"] == "pass"

    # The shipped spec declares its schema identity; the buyer matches
    # plugins to registries on this id.
    assert body["schema"]["id"] == "compute.market"
    assert body["schema"]["version"] >= 1


def _listing(listing_id: str, **resource: object) -> ListingRequest:
    return ListingRequest(
        listing_id=listing_id,
        listing_resource={"region": "us-west", "offering_mode": "vm", **resource},
        accepted_escrows=[
            {
                "chain_name": "anvil",
                # Development fixture addresses; never used on a public network.
                "escrow_address": "0x" + "11" * 20,
                "literal_fields": {"token": "0x" + "22" * 20},
            }
        ],
        storefront_url="http://seller",
    )


async def _ids(registry_client, **filters) -> set[str]:
    page = await registry_client.list_listings(limit=100, **filters)
    return {str(row.id) for row in page.listings}


@pytest.mark.asyncio
async def test_gpu_filters_exclude_a_listing_stating_no_gpu(registry_client) -> None:
    """A GPU filter fails on a missing value, so a listing stating no GPU is
    found only by queries that bound no GPU field."""
    await registry_client.publish_listing(_listing("cpu-only", vcpu_count=16, ram_gb=64))
    await registry_client.publish_listing(
        _listing("gpu", gpu_model="GB10", gpu_count=1, vcpu_count=16, ram_gb=64)
    )

    assert await _ids(registry_client, gpu_count_min=1) == {"gpu"}
    assert await _ids(registry_client, gpu_model="GB10") == {"gpu"}
    assert await _ids(registry_client, vcpu_count_min=16) == {"cpu-only", "gpu"}


@pytest.mark.asyncio
async def test_filter_spec_etag_stable_across_requests(registry_client) -> None:

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as raw:
        r1 = await raw.get("/filter-spec")
        r2 = await raw.get("/filter-spec")
    assert r1.headers["etag"] == r2.headers["etag"]
    assert r1.json()["etag"] == r2.json()["etag"]


@pytest.fixture
def served_spec(tmp_path: Path):
    """Serve a specification the test writes, restoring the configured one after."""

    def serve(body: str) -> None:
        path = tmp_path / "spec.yaml"
        path.write_text(textwrap.dedent(body).strip() + "\n")
        fs_mod.reset_cache(Settings(_env_file=None, REGISTRY_FILTER_SPEC_PATH=str(path)))

    yield serve
    fs_mod.reset_cache()


@pytest.mark.asyncio
async def test_the_etag_header_mirrors_the_served_spec_s_etag(registry_client, served_spec) -> None:

    served_spec(
        """
        version: 1
        listing_shape:
          type: object
        filters:
          - {name: region, path: $.listing_resource.region, op: in, value_type: string, on_missing: fail}
        """
    )
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as raw:
        response = await raw.get("/filter-spec")
    spec = await registry_client.get_filter_spec()

    body = response.json()
    assert response.headers["etag"].strip('"') == body["etag"] == spec.etag
    assert body["version"] == 1
    assert body["filters"][0]["name"] == "region"
    assert "schema" not in body  # spec declares none → key absent


@pytest.mark.asyncio
async def test_the_endpoint_serves_the_spec_s_schema_identity(registry_client, served_spec) -> None:
    served_spec(
        """
        version: 1
        schema:
          id: tokens.api
          version: 2
        listing_shape:
          type: object
        filters:
          - {name: region, path: $.listing_resource.region, op: in, value_type: string}
        """
    )

    spec = await registry_client.get_filter_spec()

    assert (spec.schema_id, spec.schema_version) == ("tokens.api", 2)


_SPEC_V1 = """
    version: 1
    listing_shape:
      type: object
    filters:
      - {name: region, path: $.listing_resource.region, op: in, value_type: string, on_missing: fail}
    """


@pytest.mark.asyncio
async def test_a_query_compiled_under_a_replaced_spec_is_refused_412(registry_client, served_spec) -> None:
    """registry-discovery "Filter specification changes during query
    construction": the compiled query carries the ETag it was compiled under,
    which the registry refuses once it serves another specification."""

    served_spec(_SPEC_V1)
    compiled = compile_resource_query(
        "region=us-west", filter_spec=await registry_client.get_filter_spec(), registry_url="http://test"
    )
    served_spec(_SPEC_V1.replace("version: 1", "version: 2"))

    with pytest.raises(RegistryClientError) as stale:
        await registry_client.list_listings(etag=compiled.etag, **compiled.as_params())

    assert stale.value.status_code == 412


@pytest.mark.asyncio
async def test_a_listing_read_whose_query_an_intermediary_changed_is_refused(
    maker_signer, registry_authority
) -> None:
    """A transport rewriting the signed query, as an intermediary could: the
    registry verifies the query it received, so the read is refused as an
    invalid proof, signed, and runs nothing."""

    registry = httpx.ASGITransport(app=app)
    seen: list[str] = []

    class _Rewriting(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            rewritten = request.url.copy_with(query=request.url.query.replace(b"limit=50", b"limit=200"))
            seen.append(rewritten.query.decode())
            forwarded = httpx.Request(request.method, rewritten, headers=request.headers, content=request.content)
            return await registry.handle_async_request(forwarded)

    async with RegistryClient(
        "http://test",
        transport=_Rewriting(),
        signer=maker_signer,
        caller_role="buyer",
        expected_registries=TrustedIdentitySet(identities=(registry_authority.identity,)),
        registry_authority="test-registry",
    ) as client:
        with pytest.raises(RegistryClientError) as refused:
            await client.list_listings()

    assert refused.value.status_code == 401
    assert "Invalid request proof" in refused.value.body
    assert "limit=200" in seen[0]
