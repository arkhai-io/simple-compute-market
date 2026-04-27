"""Main API router that aggregates all route modules."""

from fastapi import APIRouter

from src.api.agent_routes import router as agent_router
from src.api.order_routes import router as order_router
from src.api.system_routes import make_health_router, make_system_router

# Aggregate router — included by main.py under no prefix
router = APIRouter()

router.include_router(make_health_router())
router.include_router(make_system_router())
router.include_router(agent_router)
router.include_router(order_router)
