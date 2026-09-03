"""Main API router that aggregates all route modules."""

from fastapi import APIRouter

from src.api.admin_routes import router as admin_router
from src.api.descriptor_routes import router as descriptor_router
from src.api.filter_spec import router as filter_spec_router
from src.api.listing_routes import router as listing_router
from src.api.publisher_routes import router as publisher_router
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
router.include_router(descriptor_router)

router.include_router(make_system_router())
router.include_router(filter_spec_router)
router.include_router(validate_router)
router.include_router(publisher_router)

# The listing router mixes reads and writes, so each endpoint carries its
# own read- or write-scoped dependency.
router.include_router(listing_router)
