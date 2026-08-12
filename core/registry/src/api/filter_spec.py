"""Filter-spec loader and `/filter-spec` endpoint.

The registry self-describes via a YAML file (``filter-spec.yaml`` by
default, path overridable through ``REGISTRY_FILTER_SPEC_PATH``).  The
spec carries two things:

* ``listing_shape`` — JSON Schema (draft 2020-12) for a publishable
  listing.  Drives the structural check on ``POST /agents/{id}/listings``
  and ``POST /api/v1/listings/validate-publish``.
* ``filters`` — vocabulary the registry honours at ``GET /listings``
  query time.  Each filter is `{name, path (JSONPath), op, value_type,
  alias_kind?, on_missing}`.

The endpoint returns the spec verbatim plus an ``etag`` (sha256 over
canonical-JSON-encoded ``{version, listing_shape, filters}``).  Buyers
cache by URL+etag and send ``If-Match: <etag>`` on every query; a spec
rotation surfaces as 412 instead of a silent shape change.
"""

from __future__ import annotations

import hashlib
import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml
from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from src.api.api_key_auth import require_read_access
from src.api.publisher_auth import (
    authenticate_publisher_request,
    cached_response,
    canonical_query_body,
    complete_authenticated_request,
    registry_authority_signer,
    signed_response,
)
from src.db.database import get_db


# ---------------------------------------------------------------------------
# Spec models
# ---------------------------------------------------------------------------

ValueType = Literal["string", "integer", "number", "boolean", "address"]
Op = Literal["in", "range", "not_in", "exists"]
AliasKind = Literal["lower_bound", "upper_bound"]
OnMissing = Literal["fail", "pass"]


class FilterDecl(BaseModel):
    """One filter declaration in the registry's filter spec."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    path: str = Field(
        min_length=1,
        description="JSONPath (RFC 9535) into the listing document.",
    )
    op: Op
    value_type: ValueType
    alias_kind: AliasKind | None = None
    on_missing: OnMissing = "fail"
    indexed: bool = False  # reserved for (a2); registry ignores today


class SchemaIdentity(BaseModel):
    """Stable identity of the listing schema this registry serves.

    ``id`` is the stable listing-schema name that buyer-domain commands
    declare compatibility with (for example, ``"vms.compute"``). With several
    registries configured, a domain queries only registries whose declared id
    matches. ``version`` is the schema-contract version; buyers match on id
    alone today, and the version remains advisory until a second schema
    version exists.
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    version: int = Field(default=1, ge=1)


class FilterSpec(BaseModel):
    """Parsed filter spec ready to serve."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    version: int = Field(ge=1)
    #: Optional schema identity (YAML key ``schema``). Absent on legacy
    #: specs — buyers treat an undeclared registry as matching any
    #: plugin, so adding the header is opt-in per deployment.
    schema_identity: SchemaIdentity | None = Field(default=None, alias="schema")
    listing_shape: dict[str, Any]
    filters: list[FilterDecl]


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------

_DEFAULT_SPEC_PATH = Path(__file__).resolve().parents[2] / "filter-spec.yaml"


def _resolve_spec_path() -> Path:
    override = os.environ.get("REGISTRY_FILTER_SPEC_PATH")
    return Path(override) if override else _DEFAULT_SPEC_PATH


def compute_etag(spec: FilterSpec) -> str:
    """sha256 hex over canonical-JSON encoding of the spec body.

    The schema identity participates only when declared, so etags of
    pre-identity specs are unchanged by this code knowing about it.
    """
    body: dict[str, Any] = {
        "version": spec.version,
        "listing_shape": spec.listing_shape,
        "filters": [f.model_dump(exclude_none=False) for f in spec.filters],
    }
    if spec.schema_identity is not None:
        body["schema"] = spec.schema_identity.model_dump()
    payload = json.dumps(
        body,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def load_filter_spec(path: Path | None = None) -> FilterSpec:
    """Load and validate the spec from ``path`` (or the configured default).

    Raises ``FileNotFoundError`` if the file is missing, ``yaml.YAMLError``
    on parse failure, ``pydantic.ValidationError`` on shape problems, and
    ``ValueError`` on duplicate filter names.
    """
    target = path or _resolve_spec_path()
    with open(target, encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    spec = FilterSpec.model_validate(raw)

    seen: set[str] = set()
    for f in spec.filters:
        if f.name in seen:
            raise ValueError(f"duplicate filter name in spec: {f.name!r}")
        seen.add(f.name)
    return spec


@lru_cache(maxsize=1)
def get_loaded_spec() -> FilterSpec:
    """Module-level cache of the loaded spec (one read per process)."""
    return load_filter_spec()


def reset_cache() -> None:
    """Drop the cached spec — called from tests that swap the spec file."""
    get_loaded_spec.cache_clear()


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------

router = APIRouter(tags=["filter-spec"])


def _spec_body(spec: FilterSpec) -> dict[str, Any]:
    body: dict[str, Any] = {
        "version": spec.version,
        "etag": compute_etag(spec),
        "listing_shape": spec.listing_shape,
        "filters": [f.model_dump(exclude_none=False) for f in spec.filters],
    }
    if spec.schema_identity is not None:
        body["schema"] = spec.schema_identity.model_dump()
    return body


@router.get(
    "/filter-spec",
    summary="Registry self-description: listing shape + filter vocabulary",
    description=(
        "Returns the JSON Schema for publishable listings and the filter set "
        "the registry honours at GET /listings.  The `etag` is a stable hash of "
        "{version, listing_shape, filters}; buyers should cache by URL+etag and "
        "send `If-Match: <etag>` on every /listings query so a spec rotation "
        "surfaces as 412 Precondition Failed instead of a silent shape change."
    ),
)
async def get_filter_spec(
    request: Request,
    db: Session = Depends(get_db),
) -> Response:
    authenticated = authenticate_publisher_request(
        request=request,
        db=db,
        method="GET",
        operation="filter.get",
        resource="filter-spec",
        body=canonical_query_body(request),
        allowed_roles=frozenset({"buyer", "seller", "service"}),
    )
    require_read_access(request, db)
    signer = registry_authority_signer(request)
    replay = cached_response(authenticated, signer=signer)
    if replay is not None:
        return replay
    spec = get_loaded_spec()
    body = _spec_body(spec)
    complete_authenticated_request(
        authenticated=authenticated,
        db=db,
        status=200,
        body=body,
    )
    db.commit()
    response = signed_response(
        authenticated=authenticated,
        signer=signer,
        status=200,
        body=body,
    )
    response.headers["ETag"] = f'"{body["etag"]}"'
    return response
