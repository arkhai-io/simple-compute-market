"""Unit tests for the filter-spec loader.

The endpoint is exercised in the integration tests; here we cover the
loader's structural validation, etag stability, and the explicit error
modes (duplicate filter names, malformed YAML).
"""

from __future__ import annotations

import textwrap
import time
from pathlib import Path

import pytest
from pydantic import ValidationError

from src.api.filter_spec import (
    FilterSpec,
    compute_etag,
    load_filter_spec,
)


@pytest.fixture(autouse=True)
def _isolate_filter_spec_cache():
    from src.api import filter_spec as fs_mod

    fs_mod.reset_cache()
    yield
    fs_mod.reset_cache()


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
    # The shipped spec declares its schema identity — buyer plugins match
    # registries to schemas on this id.
    assert spec.schema_identity is not None
    assert spec.schema_identity.id == "vms.compute"
    assert spec.schema_identity.version >= 1


def test_schema_identity_parses_and_defaults_version(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
        version: 1
        schema:
          id: tokens.api
        listing_shape:
          type: object
        filters:
          - {name: service_name, path: $.offer_resource.service_name, op: in, value_type: string}
        """,
    )
    spec = load_filter_spec(path)
    assert spec.schema_identity is not None
    assert spec.schema_identity.id == "tokens.api"
    assert spec.schema_identity.version == 1


def test_schema_identity_is_optional(tmp_path: Path) -> None:
    """Pre-identity specs (no `schema:` key) keep loading unchanged."""
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
    assert load_filter_spec(path).schema_identity is None


def test_schema_identity_rejects_unknown_keys(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
        version: 1
        schema:
          id: tokens.api
          vesion: 2
        listing_shape:
          type: object
        filters:
          - {name: region, path: $.offer_resource.region, op: in, value_type: string}
        """,
    )
    with pytest.raises(ValidationError):
        load_filter_spec(path)


def test_etag_unchanged_for_specs_without_schema_identity(tmp_path: Path) -> None:
    """Knowing about schema identity must not rotate pre-identity etags.

    Pinned against the literal sha256 of the canonical {version,
    listing_shape, filters} payload — the etag contract before the
    schema header existed.
    """
    import hashlib
    import json

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
    spec = load_filter_spec(path)
    legacy_payload = json.dumps(
        {
            "version": 1,
            "listing_shape": {"type": "object"},
            "filters": [spec.filters[0].model_dump(exclude_none=False)],
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    assert compute_etag(spec) == hashlib.sha256(legacy_payload).hexdigest()


def test_etag_changes_when_schema_identity_added(tmp_path: Path) -> None:
    without = """
    version: 1
    listing_shape:
      type: object
    filters:
      - {name: region, path: $.offer_resource.region, op: in, value_type: string}
    """
    with_schema = """
    version: 1
    schema:
      id: tokens.api
    listing_shape:
      type: object
    filters:
      - {name: region, path: $.offer_resource.region, op: in, value_type: string}
    """
    assert compute_etag(load_filter_spec(_write(tmp_path, without))) != \
        compute_etag(load_filter_spec(_write(tmp_path, with_schema)))


def _authenticated_filter_client(app, db_session):
    from fastapi.testclient import TestClient
    from market_identity import (
        Ed25519Signer,
        RequestEnvelope,
        TrustedIdentitySet,
        canonical_body_hash,
        sign_request,
    )
    from src.db.database import get_db

    caller = Ed25519Signer(bytes(range(32)))
    registry = Ed25519Signer(bytes(range(1, 33)))
    app.state.registry_authority_signer = registry

    def override_db():
        yield db_session

    app.dependency_overrides[get_db] = override_db
    request = sign_request(
        signer=caller,
        envelope=RequestEnvelope(
            role="buyer",
            principal=caller.identity,
            method="GET",
            operation="filter.get",
            resource="filter-spec",
            request_id="filter-spec-unit",
            timestamp=int(time.time()),
            body_hash=canonical_body_hash({"query": []}),
        ),
    )
    headers = {
        "X-Market-Signature-Version": request.protocol,
        "X-Market-Identity-Scheme": request.principal.scheme.value,
        "X-Market-Identity-Identifier": request.principal.identifier,
        "X-Market-Role": request.role,
        "X-Market-Request-ID": request.request_id,
        "X-Market-Timestamp": str(request.timestamp),
        "X-Market-Signature": request.proof.value,
    }
    return TestClient(app), request, headers, TrustedIdentitySet(
        identities=(registry.identity,)
    )


def _assert_signed_filter_response(response, request, registry_principals) -> None:
    from market_identity import VerificationCode, canonical_body_hash, verify_response

    scheme = response.headers["X-Market-Identity-Scheme"]
    result = verify_response(
        {
            "protocol": response.headers["X-Market-Signature-Version"],
            "role": response.headers["X-Market-Role"],
            "principal": {
                "scheme": scheme,
                "identifier": response.headers["X-Market-Identity-Identifier"],
            },
            "method": request.method,
            "operation": request.operation,
            "resource": request.resource,
            "request_id": response.headers["X-Market-Request-ID"],
            "timestamp": int(response.headers["X-Market-Timestamp"]),
            "status": response.status_code,
            "body_hash": canonical_body_hash(response.json()),
            "proof": {
                "scheme": scheme,
                "value": response.headers["X-Market-Signature"],
            },
        },
        body=response.json(),
        now=int(time.time()),
        max_skew=300,
        expected_role="registry",
        expected_method=request.method,
        expected_operation=request.operation,
        expected_resource=request.resource,
        expected_request_id=request.request_id,
        expected_principals=registry_principals,
    )
    assert result.code == VerificationCode.VERIFIED


def test_etag_present_on_endpoint(
    monkeypatch,
    tmp_path: Path,
    db_session,
) -> None:
    """ETag header on GET /filter-spec mirrors the body etag."""

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
    client, request, headers, registry_principals = _authenticated_filter_client(
        app,
        db_session,
    )
    resp = client.get("/filter-spec", headers=headers)
    assert resp.status_code == 200
    _assert_signed_filter_response(resp, request, registry_principals)
    body = resp.json()
    assert resp.headers["etag"].strip('"') == body["etag"]
    assert body["version"] == 1
    assert body["filters"][0]["name"] == "region"
    assert "schema" not in body  # spec declares none → key absent


def test_endpoint_serves_schema_identity(
    monkeypatch,
    tmp_path: Path,
    db_session,
) -> None:

    path = _write(
        tmp_path,
        """
        version: 1
        schema:
          id: tokens.api
          version: 2
        listing_shape:
          type: object
        filters:
          - {name: region, path: $.offer_resource.region, op: in, value_type: string}
        """,
    )
    monkeypatch.setenv("REGISTRY_FILTER_SPEC_PATH", str(path))
    from src.api import filter_spec as fs_mod
    fs_mod.reset_cache()

    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(fs_mod.router)
    client, request, headers, registry_principals = _authenticated_filter_client(
        app,
        db_session,
    )
    response = client.get("/filter-spec", headers=headers)
    _assert_signed_filter_response(response, request, registry_principals)
    body = response.json()
    assert body["schema"] == {"id": "tokens.api", "version": 2}
