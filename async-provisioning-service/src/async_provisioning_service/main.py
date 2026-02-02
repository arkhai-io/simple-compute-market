import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from async_provisioning_service.api.auth import AgentAuthMiddleware
from async_provisioning_service.api.routes import router
from async_provisioning_service.config import settings
from async_provisioning_service.db.database import init_db


logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    logger.info("Starting async provisioning service...")
    init_db()
    logger.info("Database initialized")
    yield
    logger.info("Shutdown complete")


app = FastAPI(
    title="Async Provisioning Service",
    version="0.1.0",
    lifespan=lifespan,
)

# Add authentication middleware
app.add_middleware(
    AgentAuthMiddleware,
    registry_url=settings.registry_url,
    enabled=settings.enable_auth,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "async_provisioning_service.main:app",
        host=settings.host,
        port=settings.port,
        reload=True,
    )
