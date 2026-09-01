"""Authority-authenticated registry self-description route."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from market_core import RegistryDescriptor
from sqlalchemy.orm import Session

from src.api.publisher_auth import (
    authenticate_publisher_request,
    cached_response,
    canonical_query_body,
    complete_authenticated_request,
    registry_authority_signer,
    signed_response,
)
from src.db.database import get_db

router = APIRouter(tags=["registry-descriptor"])


@router.get(
    "/.well-known/arkhai/registry-descriptor.json",
    summary="Registry authority, schema, and access descriptor",
)
async def get_registry_descriptor(
    request: Request,
    db: Session = Depends(get_db),
) -> Response:
    authenticated = authenticate_publisher_request(
        request=request,
        db=db,
        method="GET",
        operation="registry.descriptor.read",
        resource="registry-descriptor",
        body=canonical_query_body(request),
        allowed_roles=frozenset({"buyer", "seller", "service"}),
    )
    signer = registry_authority_signer(request)
    replay = cached_response(authenticated, signer=signer)
    if replay is not None:
        return replay
    descriptor = getattr(request.app.state, "registry_descriptor", None)
    if not isinstance(descriptor, RegistryDescriptor):
        raise HTTPException(status_code=503, detail="Registry descriptor unavailable")
    body = descriptor.to_wire()
    complete_authenticated_request(
        authenticated=authenticated,
        db=db,
        status=200,
        body=body,
    )
    db.commit()
    return signed_response(
        authenticated=authenticated,
        signer=signer,
        status=200,
        body=body,
    )
