import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from src.api.routes import router
from src.config import settings
from src.db.database import init_db

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper()),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for startup and shutdown.

    Publishers and their identities are created lazily on first signed
    publish via ``api/utils.py::ensure_publisher_for_identity``; there is
    no background indexer or chain probe.
    """
    logger.info("Starting registry indexer service...")

    init_db()
    logger.info("Database initialized")

    # Bootstrap a single API key from env if configured AND the table
    # is empty. Lets a private registry start with a known operator
    # secret on a fresh deploy without an admin POST. Idempotent: a
    # restart with the same env var is a no-op once the row exists.
    if settings.bootstrap_api_key:
        from src.api.api_key_auth import _hash_key
        from src.db.database import SessionLocal
        from src.db.models import ApiKey
        with SessionLocal() as session:
            if session.query(ApiKey).count() == 0:
                # Write scope: the bootstrap key is the operator's own
                # full-access credential (write implies read).
                seed = ApiKey(
                    name="bootstrap",
                    key_hash=_hash_key(settings.bootstrap_api_key),
                    scope="write",
                )
                session.add(seed)
                session.commit()
                logger.info("[BOOTSTRAP] seeded api_keys with the env-provided write key")
            else:
                logger.info("[BOOTSTRAP] api_keys table not empty; bootstrap key ignored")

    logger.info(f"🚀 Registry indexer server ready on {settings.host}:{settings.port}")

    yield

    logger.info("Shutting down...")
    logger.info("Shutdown complete")


# Create FastAPI app
app = FastAPI(
    title="Registry Indexer",
    version="0.1.0",
    lifespan=lifespan,
    root_path=settings.root_path,
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


def _custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    from fastapi.openapi.utils import get_openapi
    schema = get_openapi(
        title=app.title,
        version=app.version,
        routes=app.routes,
    )
    # Inject gateway path prefix as the OpenAPI server URL so Swagger UI
    # generates correct curl examples. The FastAPI app root_path above drives
    # the docs page's OpenAPI URL; this servers block drives "try it out".
    if settings.root_path:
        schema["servers"] = [{"url": settings.root_path}]
    app.openapi_schema = schema
    return schema


app.openapi = _custom_openapi


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "src.main:app",
        host=settings.host,
        port=settings.port,
        reload=True,
    )

