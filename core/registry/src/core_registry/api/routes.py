"""Main API router that aggregates all route modules."""

from fastapi import APIRouter

from core_registry.api.admin_routes import router as admin_router
from core_registry.api.descriptor_routes import router as descriptor_router
from core_registry.api.filter_spec import router as filter_spec_router
from core_registry.api.listing_routes import router as listing_router
from core_registry.api.publisher_routes import router as publisher_router
from core_registry.api.system_routes import make_health_router, make_system_router
from core_registry.api.validate_routes import router as validate_router

# Aggregate router — included by main.py under no prefix
router = APIRouter()

# Public surface: health + admin endpoints stay outside the
# bearer-token gate. Health is by definition unauthenticated; admin
# endpoints carry their own require_admin_api_key dependency
# attached at the admin router (a separate shared secret).
router.include_router(make_health_router())
router.include_router(admin_router)
router.include_router(descriptor_router)

router.include_router(make_system_router())
router.include_router(filter_spec_router)
router.include_router(validate_router)
router.include_router(publisher_router)

# The listing router mixes reads and writes, so each endpoint carries its
# own read- or write-scoped dependency.
router.include_router(listing_router)
