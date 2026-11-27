"""The registry's self-description, a public operation answered signed.

The descriptor is a trust bootstrap: a client adding a registry by its URL knows
no registry principal, so its request carries only a request identity, and the
registry answers it with a version 3 response signed over that identity, which
the client verifies against the principals the descriptor names. The read needs
no read key, whatever the registry's read gate.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from market_authenticated_requests import PublicAdmission, PublicAdmitted
from market_core import RegistryDescriptor

from core_registry.api.admission import registry_core

router = APIRouter(tags=["registry-descriptor"])

DESCRIPTOR_OPERATION = "registry.descriptor.read"


@router.get(
    "/.well-known/arkhai/registry-descriptor.json",
    summary="Registry authority, schema, and access descriptor",
)
async def get_registry_descriptor(
    request: Request,
    admitted: PublicAdmitted = Depends(PublicAdmission(registry_core, operation=DESCRIPTOR_OPERATION)),
) -> dict:
    descriptor = getattr(request.app.state, "registry_descriptor", None)
    if not isinstance(descriptor, RegistryDescriptor):
        raise HTTPException(status_code=503, detail="Registry descriptor unavailable")
    return descriptor.to_wire()
