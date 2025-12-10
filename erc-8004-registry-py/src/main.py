import asyncio
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from src.api.routes import router
from src.services.event_sync import EventSyncService
from src.services.health_check import HealthCheckService
from src.config import settings
from src.db.database import init_db
from src.types import NetworkConfig

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper()),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Initialize services
event_sync: EventSyncService | None = None
health_check: HealthCheckService | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for startup and shutdown"""
    global event_sync, health_check
    
    # Startup
    logger.info("Starting ERC-8004 Indexer service...")
    
    # Initialize database
    init_db()
    logger.info("Database initialized")
    
    # Create network config
    network_config = NetworkConfig(
        chain_id=settings.chain_id,
        rpc_url=settings.rpc_url,
        identity_registry=settings.identity_registry_address,
        reputation_registry=settings.reputation_registry_address,
        validation_registry=settings.validation_registry_address,
    )
    
    # Start event sync service
    event_sync = EventSyncService(network_config)
    if settings.enable_health_checks:
        await event_sync.start(60000)  # Sync every minute
        logger.info("Event sync service started")
    
    # Start health check service (opt-in)
    health_check = HealthCheckService()
    if settings.enable_health_checks:
        await health_check.start(settings.health_check_interval)
        logger.info("Health check service started (Indexer-initiated health checks enabled)")
    else:
        logger.info("Health check service disabled (Agent-initiated heartbeats are the default)")
    
    logger.info(f"🚀 ERC-8004 Indexer server ready on {settings.host}:{settings.port}")
    
    yield
    
    # Shutdown
    logger.info("Shutting down...")
    if event_sync:
        await event_sync.stop()
    if health_check:
        await health_check.stop()
    logger.info("Shutdown complete")


# Create FastAPI app
app = FastAPI(
    title="ERC-8004 Indexer",
    version="0.1.0",
    lifespan=lifespan,
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routes
app.include_router(router)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "src.main:app",
        host=settings.host,
        port=settings.port,
        reload=True,
    )

