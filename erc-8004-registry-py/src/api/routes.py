"""Main API router that aggregates all route modules."""

from fastapi import APIRouter
from src.config import settings
from src.api.agent_routes import router as agent_router
from src.api.order_routes import router as order_router

# Create main router
router = APIRouter()

# Include sub-routers
router.include_router(agent_router)
router.include_router(order_router)


@router.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": "erc-8004-indexer",
        "version": "0.1.0",
        "health_checks_enabled": settings.enable_health_checks,
    }
