from __future__ import annotations

import asyncio

from unittest.mock import AsyncMock, Mock

import pytest

from market_core import QueryValidationError
from registry_client import (
    FilterSpecResponse,
    FilterVocabularyError,
    RegistryClient,
    RegistryClientError,
    ResourceQueryCompilationError,
    SyncRegistryClient,
    compile_resource_query,
    resource_query_descriptors,
)


def _spec(*, etag: str = "spec-7") -> FilterSpecResponse:
    return FilterSpecResponse.from_dict(
        {
            "version": 4,
            "etag": etag,
            "schema": {"id": "vms.compute", "version": 3},
            "listing_shape": {"type": "object"},
            "filters": [
                {
                    "name": "gpu_model",
                    "path": "$.offer_resource.gpu_model",
                    "op": "in",
                    "value_type": "string",
                    "on_missing": "fail",
                },
                {
                    "name": "ram_gb_min",
                    "query_name": "ram_gb",
                    "query_aliases": ["ram_gb_min"],
                    "path": "$.offer_resource.ram_gb",
                    "op": "range",
                    "value_type": "integer",
                    "alias_kind": "lower_bound",
                    "on_missing": "fail",
                },
                {
                    "name": "utilization",
                    "path": "$.utilization",
                    "op": "range",
                    "value_type": "number",
                    "on_missing": "pass",
                },
                {
                    "name": "active",
                    "path": "$.active",
                    "op": "exists",
                    "value_type": "boolean",
                },
                {
                    "name": "excluded",
                    "path": "$.class",
                    "op": "not_in",
                    "value_type": "string",
                },
            ],
        }
    )


def test_compiles_heterogeneous_spec_to_canonical_registry_parameters() -> None:
    compiled = compile_resource_query(
        "gpu_model in [H200,A100] ram_gb>=64 utilization<0.75 "
        "active=true excluded!=retired",
        filter_spec=_spec(),
        registry_url="https://registry.example/",
    )

    assert compiled.registry_url == "https://registry.example"
    assert compiled.etag == "spec-7"
    assert compiled.schema_id == "vms.compute"
    assert compiled.schema_version == 3
    assert compiled.canonical_query == (
        "gpu_modelin[H200,A100] ram_gb>=64 utilization<0.75 "
        "active=true excluded!=retired"
    )
    assert compiled.parameters == (
        ("gpu_model", "in:[H200,A100]"),
        ("ram_gb_min", "64"),
        ("utilization", "range:(,0.75)"),
        ("active", "exists:true"),
        ("excluded", "not_in:[retired]"),
    )
    assert compiled.as_params()["ram_gb_min"] == "64"


def test_friendly_and_canonical_aliases_compile_to_same_parameter() -> None:
    friendly = compile_resource_query(
        "ram_gb>64", filter_spec=_spec(), registry_url="https://registry.example"
    )
    canonical_alias = compile_resource_query(
        "ram_gb_min>64",
        filter_spec=_spec(),
        registry_url="https://registry.example",
    )

    assert (
        friendly.parameters
        == canonical_alias.parameters
        == (("ram_gb_min", "range:(64,)"),)
    )
    assert canonical_alias.canonical_query == "ram_gb>64"


def test_descriptors_preserve_declared_type_operators_and_missing_rule() -> None:
    descriptors = {item.name: item for item in resource_query_descriptors(_spec())}

    assert descriptors["ram_gb"].aliases == ("ram_gb_min",)
    assert {operator.value for operator in descriptors["ram_gb"].operators} == {
        ">",
        ">=",
    }
    assert descriptors["utilization"].value_type.value == "decimal"
    assert descriptors["utilization"].on_missing.value == "pass"


def test_rejects_fields_and_operators_not_declared_by_this_registry() -> None:
    with pytest.raises(QueryValidationError) as caught:
        compile_resource_query(
            "region=us-east ram_gb<64",
            filter_spec=_spec(),
            registry_url="https://registry.example",
        )

    assert caught.value.code == "unknown_field"
    assert caught.value.field == "region"
    assert "us-east" not in str(caught.value)


def test_rejects_unrepresentable_set_values_without_echoing_them() -> None:
    secret = "private,value"
    with pytest.raises(ResourceQueryCompilationError) as caught:
        compile_resource_query(
            f'gpu_model in ["{secret}"]',
            filter_spec=_spec(),
            registry_url="https://registry.example",
        )

    assert secret not in str(caught.value)


@pytest.mark.parametrize(
    "literal",
    [
        "in:[A100]",
        "not_in:[A100]",
        "range:(1,2]",
        "exists:true",
    ],
)
def test_rejects_scalar_equality_values_that_collide_with_wire_set_form(
    literal: str,
) -> None:
    with pytest.raises(ResourceQueryCompilationError) as caught:
        compile_resource_query(
            f'gpu_model="{literal}"',
            filter_spec=_spec(),
            registry_url="https://registry.example",
        )

    assert literal not in str(caught.value)


def test_scalar_equality_without_set_form_shape_preserves_literal_value() -> None:
    compiled = compile_resource_query(
        'gpu_model="in:thing"',
        filter_spec=_spec(),
        registry_url="https://registry.example",
    )

    assert compiled.parameters == (("gpu_model", "in:thing"),)


@pytest.mark.parametrize(
    "filters",
    [
        [{"name": "x", "op": "in", "value_type": "opaque"}],
        [{"name": "x", "query_name": "bad name", "op": "in", "value_type": "string"}],
        [
            {"name": "one", "query_name": "same", "op": "in", "value_type": "string"},
            {"name": "two", "query_name": "same", "op": "in", "value_type": "string"},
        ],
    ],
)
def test_malformed_registry_vocabulary_fails_closed(filters: list[dict]) -> None:
    spec = _spec()
    spec.filters = filters

    with pytest.raises((FilterVocabularyError, ValueError)):
        resource_query_descriptors(spec)


def test_missing_etag_fails_before_query_compilation() -> None:
    with pytest.raises(FilterVocabularyError, match="missing its etag"):
        compile_resource_query(
            "unknown=secret",
            filter_spec=_spec(etag=""),
            registry_url="https://registry.example",
        )


def test_async_client_binds_compiled_params_to_etag_and_surfaces_412() -> None:
    async def run() -> None:
        client = object.__new__(RegistryClient)
        request = AsyncMock(
            side_effect=[
                {
                    "version": 4,
                    "etag": "rotated-from-this",
                    "filters": _spec().filters,
                },
                RegistryClientError(
                    "GET", "https://registry.example/listings", 412, "rotated"
                ),
            ]
        )
        client._request = request

        spec = await client.get_filter_spec()
        compiled = compile_resource_query(
            "ram_gb>=64",
            filter_spec=spec,
            registry_url="https://registry.example",
        )
        with pytest.raises(RegistryClientError) as caught:
            await client.list_listings(etag=compiled.etag, **compiled.as_params())

        assert caught.value.status_code == 412
        assert request.await_args.kwargs["headers"] == {
            "If-Match": '"rotated-from-this"'
        }
        assert request.await_args.kwargs["params"]["ram_gb_min"] == "64"

    asyncio.run(run())


def test_sync_client_binds_compiled_params_to_etag_and_surfaces_412() -> None:
    client = object.__new__(SyncRegistryClient)
    request = Mock(
        side_effect=[
            {
                "version": 4,
                "etag": "rotated-from-this",
                "filters": _spec().filters,
            },
            RegistryClientError(
                "GET", "https://registry.example/listings", 412, "rotated"
            ),
        ]
    )
    client._request = request

    spec = client.get_filter_spec()
    compiled = compile_resource_query(
        "ram_gb>=64",
        filter_spec=spec,
        registry_url="https://registry.example",
    )
    with pytest.raises(RegistryClientError) as caught:
        client.list_listings(etag=compiled.etag, **compiled.as_params())

    assert caught.value.status_code == 412
    assert request.call_args.kwargs["headers"] == {"If-Match": '"rotated-from-this"'}
    assert request.call_args.kwargs["params"]["ram_gb_min"] == "64"
