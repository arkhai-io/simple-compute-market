"""Main API router that aggregates all route modules."""

from fastapi import APIRouter, Depends

from src.api.admin_routes import router as admin_router
from src.api.agent_routes import router as agent_router
from src.api.api_key_auth import require_valid_api_key
from src.api.listing_routes import router as listing_router
from src.api.system_routes import make_health_router, make_system_router
from src.api.validate_routes import router as validate_router

# Aggregate router — included by main.py under no prefix
router = APIRouter()

# Public surface: health + admin endpoints stay outside the
# bearer-token gate. Health is by definition unauthenticated; admin
# endpoints carry their own require_admin_api_key dependency
# attached at the admin router (a separate shared secret).
router.include_router(make_health_router())
router.include_router(admin_router)

# Gated surface: every non-admin / non-health route carries the
# api-key dependency. The dependency no-ops when
# ``settings.require_api_key`` is False, so public registries see
# no behaviour change.
_gate = [Depends(require_valid_api_key)]
router.include_router(make_system_router(), dependencies=_gate)
router.include_router(agent_router, dependencies=_gate)
router.include_router(listing_router, dependencies=_gate)
router.include_router(validate_router, dependencies=_gate)
