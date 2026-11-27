import logging
from contextlib import asynccontextmanager
from pathlib import Path

import injected_time
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from market_authenticated_requests import Unauthenticated, install
from market_authenticated_requests.sqlalchemy_support import sqlalchemy_replay_store
from market_identity import Identity, create_signer
from sqlalchemy import create_engine
from core_registry.api import admission
from core_registry.api.admin_routes import make_time_router
from core_registry.api.routes import router
from core_registry.config import settings
from core_registry.db.migrations import require_compatible_database
from core_registry.api.filter_spec import get_loaded_spec
from core_registry.registry_descriptor import build_registry_descriptor

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper()),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# The process's time source, installed before the application is built and
# before anything reads the time: `TIME_SOURCE`, "wall" unless set "injected";
# any other value refuses startup naming the setting and the value.
injected_time.install(
    injected_time.source_for(
        injected_time.WALL if settings.time_source is None else settings.time_source,
        setting="TIME_SOURCE",
    )
)


def announce_time_source(source: injected_time.TimeSource) -> None:
    """Log an injected source at startup; a wall-time registry logs nothing here."""
    if source.name == injected_time.INJECTED:
        logger.info(
            '[STARTUP] TIME_SOURCE is "injected": time is held at %s until set '
            "through POST /admin/time",
            source.now(),
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for startup and shutdown.

    Publishers and their identities are created lazily on first signed
    publish via ``api/utils.py::ensure_publisher_for_identity``; there is
    no background indexer or chain probe.
    """
    logger.info("Starting listing registry service...")
    announce_time_source(injected_time.installed())

    # Before anything opens the database: the application issues no DDL, and
    # serves only a database `registry-migrate` brought to its script head.
    require_compatible_database(settings.database_url)
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
    # The replay store's own engine on the registry's database: the
    # application's SQLite engine shares one connection between its sessions,
    # and a replay step's transaction must not interleave with a request's.
    admission.bind(
        signer=registry_signer,
        store=sqlalchemy_replay_store(create_engine(settings.database_url)),
    )
    app.state.registry_descriptor = build_registry_descriptor(
        base_url=settings.registry_descriptor_base_url,
        display_name=settings.registry_descriptor_display_name,
        operator_identity=settings.registry_descriptor_operator_identity,
        authority_name=settings.registry_authority_id,
        authority_principal=registry_signer.identity,
        filter_spec=get_loaded_spec(),
        require_read_api_key=settings.require_read_api_key,
        acquisition_pointer=(settings.registry_descriptor_access_acquisition_pointer),
        recommended_dispute_authorities=(
            settings.registry_descriptor_recommended_dispute_authorities
        ),
    )
    logger.info("Database compatible with the registry's migrations")

    # Bootstrap a single API key from env if configured AND the table
    # is empty. Lets a private registry start with a known operator
    # secret on a fresh deploy without an admin POST. Idempotent: a
    # restart with the same env var is a no-op once the row exists.
    if settings.bootstrap_api_key:
        from core_registry.api.api_key_auth import _hash_key
        from core_registry.db.database import SessionLocal
        from core_registry.db.models import ApiKey

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

    async with admission.registry_core.sweeping():
        yield

    logger.info("Shutting down...")
    logger.info("Shutdown complete")


# Create FastAPI app; ``app``, below, is the application the admission core wraps.
api = FastAPI(
    title="Listing Registry",
    version="0.2.0",
    lifespan=lifespan,
    root_path=settings.root_path,
)


# Add CORS middleware
api.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routes
api.include_router(router)

# The time-setting route, mounted only while the source installed above is
# injected: a wall-time registry serves no such route, and its time is changed
# only by reconfiguring and restarting it.
if injected_time.TimeRouteService(injected_time.installed()).settable:
    api.include_router(make_time_router())


def _custom_openapi():
    if api.openapi_schema:
        return api.openapi_schema
    from fastapi.openapi.utils import get_openapi

    schema = get_openapi(
        title=api.title,
        version=api.version,
        routes=api.routes,
    )
    # Inject gateway path prefix as the OpenAPI server URL so Swagger UI
    # generates correct curl examples. The FastAPI app root_path above drives
    # the docs page's OpenAPI URL; this servers block drives "try it out".
    if settings.root_path:
        schema["servers"] = [{"url": settings.root_path}]
    api.openapi_schema = schema
    return schema


api.openapi = _custom_openapi

# Every signed route admits its requests through the admission core, which signs
# every answer naming a request, a path no route serves included, and refuses to
# start over a route that neither admits through it nor is marked here. Health,
# the OpenAPI document and the administrator routes, which take the shared
# administrator key rather than a signature, are served unauthenticated.
app = install(
    api,
    admission.registry_core,
    unauthenticated=Unauthenticated.of(
        "/health",
        "/admin/api-keys",
        "/admin/api-keys/{key_id}",
        "/admin/status",
        "/admin/time",
    ),
)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "core_registry.main:app",
        host=settings.host,
        port=settings.port,
        reload=True,
    )
