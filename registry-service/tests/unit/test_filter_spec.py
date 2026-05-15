"""Unit tests for the filter-spec loader.

The endpoint is exercised in the integration tests; here we cover the
loader's structural validation, etag stability, and the explicit error
modes (duplicate filter names, malformed YAML).
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
from pydantic import ValidationError

from src.api.filter_spec import (
    FilterSpec,
    compute_etag,
    load_filter_spec,
)


def _write(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "spec.yaml"
    p.write_text(textwrap.dedent(body).strip() + "\n")
    return p


def test_loads_minimal_valid_spec(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
        version: 1
        listing_shape:
          type: object
          required: [listing_id]
          properties:
            listing_id: {type: string}
        filters:
          - {name: region, path: $.offer_resource.region, op: in, value_type: string, on_missing: fail}
        """,
    )
    spec = load_filter_spec(path)
    assert spec.version == 1
    assert spec.filters[0].name == "region"
    assert spec.filters[0].on_missing == "fail"


def test_etag_stable_across_loads(tmp_path: Path) -> None:
    body = """
    version: 1
    listing_shape:
      type: object
      properties:
        listing_id: {type: string}
    filters:
      - {name: gpu_model, path: $.offer_resource.gpu_model, op: in, value_type: string, on_missing: fail}
    """
    spec1 = load_filter_spec(_write(tmp_path, body))
    spec2 = load_filter_spec(_write(tmp_path, body))
    assert compute_etag(spec1) == compute_etag(spec2)


def test_etag_changes_when_filter_added(tmp_path: Path) -> None:
    one_filter = """
    version: 1
    listing_shape:
      type: object
    filters:
      - {name: gpu_model, path: $.offer_resource.gpu_model, op: in, value_type: string, on_missing: fail}
    """
    two_filters = """
    version: 1
    listing_shape:
      type: object
    filters:
      - {name: gpu_model, path: $.offer_resource.gpu_model, op: in, value_type: string, on_missing: fail}
      - {name: region,    path: $.offer_resource.region,    op: in, value_type: string, on_missing: fail}
    """
    assert compute_etag(load_filter_spec(_write(tmp_path, one_filter))) != \
        compute_etag(load_filter_spec(_write(tmp_path, two_filters)))


def test_duplicate_filter_names_rejected(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
        version: 1
        listing_shape:
          type: object
        filters:
          - {name: region, path: $.offer_resource.region, op: in, value_type: string, on_missing: fail}
          - {name: region, path: $.offer_resource.region, op: in, value_type: string, on_missing: fail}
        """,
    )
    with pytest.raises(ValueError, match="duplicate filter name"):
        load_filter_spec(path)


def test_unknown_op_rejected(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
        version: 1
        listing_shape:
          type: object
        filters:
          - {name: gpu_model, path: $.offer_resource.gpu_model, op: contains, value_type: string, on_missing: fail}
        """,
    )
    with pytest.raises(ValidationError):
        load_filter_spec(path)


def test_unknown_field_in_filter_rejected(tmp_path: Path) -> None:
    """Spec uses ``extra='forbid'`` so typos surface at load time."""
    path = _write(
        tmp_path,
        """
        version: 1
        listing_shape:
          type: object
        filters:
          - {name: region, path: $.offer_resource.region, op: in, value_type: string, on_missing: fail, indexd: true}
        """,
    )
    with pytest.raises(ValidationError):
        load_filter_spec(path)


def test_default_on_missing_is_fail(tmp_path: Path) -> None:
    """on_missing defaults so common case stays terse in the YAML."""
    path = _write(
        tmp_path,
        """
        version: 1
        listing_shape:
          type: object
        filters:
          - {name: region, path: $.offer_resource.region, op: in, value_type: string}
        """,
    )
    spec = load_filter_spec(path)
    assert spec.filters[0].on_missing == "fail"


def test_repo_default_spec_loads() -> None:
    """The shipped filter-spec.yaml at the registry root is valid."""
    spec = load_filter_spec()
    assert spec.version >= 1
    names = {f.name for f in spec.filters}
    # Sanity: spec must cover the discovery axes the storefront used to
    # mirror, otherwise we've regressed query reach.
    assert {"gpu_model", "region", "ram_gb_min", "token"} <= names
    assert isinstance(spec.listing_shape, dict)
    assert spec.listing_shape.get("type") == "object"


def test_etag_present_on_endpoint(monkeypatch, tmp_path: Path) -> None:
    """ETag header on GET /filter-spec mirrors the body etag."""
    from fastapi.testclient import TestClient

    path = _write(
        tmp_path,
        """
        version: 1
        listing_shape:
          type: object
        filters:
          - {name: region, path: $.offer_resource.region, op: in, value_type: string, on_missing: fail}
        """,
    )
    monkeypatch.setenv("REGISTRY_FILTER_SPEC_PATH", str(path))
    from src.api import filter_spec as fs_mod
    fs_mod.reset_cache()

    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(fs_mod.router)
    client = TestClient(app)

    resp = client.get("/filter-spec")
    assert resp.status_code == 200
    body = resp.json()
    assert resp.headers["etag"].strip('"') == body["etag"]
    assert body["version"] == 1
    assert body["filters"][0]["name"] == "region"
