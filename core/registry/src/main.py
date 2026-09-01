import logging
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from market_identity import Identity, create_signer
from src.api.routes import router
from src.api.publisher_auth import (
    complete_authenticated_error,
    registry_authority_signer,
    signed_response,
)
from src.config import settings
from src.db.database import init_db
from src.api.filter_spec import get_loaded_spec
from src.registry_descriptor import build_registry_descriptor

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper()),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for startup and shutdown.

    Publishers and their identities are created lazily on first signed
    publish via ``api/utils.py::ensure_publisher_for_identity``; there is
    no background indexer or chain probe.
    """
    logger.info("Starting listing registry service...")

    init_db()
    if not (
        settings.registry_authority_id
        and settings.registry_authority_scheme
        and settings.registry_authority_identifier
        and settings.registry_authority_credential_file
    ):
        raise RuntimeError(
            "registry authority principal and credential file are required"
        )
    expected_registry = Identity(
        scheme=settings.registry_authority_scheme,
        identifier=settings.registry_authority_identifier,
    )
    credential = (
        Path(settings.registry_authority_credential_file)
        .read_text(encoding="utf-8")
        .strip()
    )
    registry_signer = create_signer(expected_registry.scheme, credential)
    if registry_signer.identity != expected_registry:
        raise RuntimeError(
            "registry authority credential does not match configured principal"
        )
    app.state.registry_authority_signer = registry_signer
    app.state.registry_descriptor = build_registry_descriptor(
        base_url=settings.registry_descriptor_base_url,
        display_name=settings.registry_descriptor_display_name,
        operator_identity=settings.registry_descriptor_operator_identity,
        authority_name=settings.registry_authority_id,
        authority_principal=registry_signer.identity,
        filter_spec=get_loaded_spec(),
        require_read_api_key=settings.require_read_api_key,
        acquisition_pointer=(settings.registry_descriptor_access_acquisition_pointer),
    )
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
                logger.info(
                    "[BOOTSTRAP] seeded api_keys with the env-provided write key"
                )
            else:
                logger.info(
                    "[BOOTSTRAP] api_keys table not empty; bootstrap key ignored"
                )

    logger.info(f"Listing registry server ready on {settings.host}:{settings.port}")

    yield

    logger.info("Shutting down...")
    logger.info("Shutdown complete")


# Create FastAPI app
app = FastAPI(
    title="Listing Registry",
    version="0.2.0",
    lifespan=lifespan,
    root_path=settings.root_path,
)


@app.exception_handler(HTTPException)
async def authenticated_http_error(request: Request, error: HTTPException):
    authenticated = getattr(
        request.state,
        "authenticated_registry_request",
        None,
    )
    if authenticated is None:
        return JSONResponse(
            status_code=error.status_code,
            content={"detail": error.detail},
            headers=error.headers,
        )
    db = request.state.authenticated_registry_db
    complete_authenticated_error(
        authenticated=authenticated,
        db=db,
        error=error,
    )
    return signed_response(
        authenticated=authenticated,
        signer=registry_authority_signer(request),
        status=error.status_code,
        body={"detail": error.detail},
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
