from __future__ import annotations

import asyncio

from dependency_injector import containers, providers

from config import settings
from db.database import create_db_engine, create_session_factory
from services.ansible_service import AnsibleService
from services.job_service import AnsibleJobService
from services.provisioning_service import ProvisioningService


async def _init_job_queue():
    """Async resource initialiser — creates the asyncio.Queue inside the event loop.

    Using a Resource provider (rather than Singleton) ensures the Queue is
    created after the event loop is running, which is required by asyncio.
    The generator protocol lets dependency-injector manage the lifecycle:
    ``await container.init_resources()`` creates it,
    ``await container.shutdown_resources()`` tears it down.
    """
    queue: asyncio.Queue = asyncio.Queue()
    yield queue
    # No teardown required for an in-memory queue.


def _make_engine():
    return create_db_engine(settings.database_url, settings.is_sqlite)


def _make_session_factory(engine):
    return create_session_factory(engine)


class Container(containers.DeclarativeContainer):
    """Application-level DI container.

    Wires providers into controller ``__init__`` methods annotated with
    ``@inject`` and ``Depends(Provide[Container.<provider>])``.
    """

    # ------------------------------------------------------------------
    # Config
    # ------------------------------------------------------------------
    config = providers.Object(settings)

    # ------------------------------------------------------------------
    # Database
    # ------------------------------------------------------------------
    db_engine = providers.Singleton(_make_engine)

    session_factory = providers.Singleton(
        _make_session_factory,
        engine=db_engine,
    )

    # ------------------------------------------------------------------
    # In-process job queue  (replaces Redis)
    # ------------------------------------------------------------------
    job_queue = providers.Resource(_init_job_queue)

    # ------------------------------------------------------------------
    # Services
    # ------------------------------------------------------------------
    ansible_service = providers.Singleton(
        AnsibleService,
        settings=config,
    )

    provisioning_service = providers.Singleton(
        ProvisioningService,
        settings=config,
        ansible_service=ansible_service,
    )

    job_service = providers.Singleton(
        AnsibleJobService,
        settings=config,
        session_factory=session_factory,
        job_queue=job_queue,
        provisioning_service=provisioning_service,
    )


# Shared container instance — imported by main.py and all controllers.
container = Container()

# ---------------------------------------------------------------------------
# Resolved service instances.
# Populated once during FastAPI lifespan startup after init_resources().
# Controllers reference these via Depends(lambda: resolved_X) so that
# dependency-injector's provider machinery is never invoked on the request
# path — avoiding asyncio.get_event_loop() calls inside AnyIO worker threads.
# ---------------------------------------------------------------------------
from sqlalchemy.orm import sessionmaker, Session  # noqa: E402

resolved_job_service: "AnsibleJobService | None" = None
resolved_session_factory: "sessionmaker[Session] | None" = None
resolved_ansible_service: "AnsibleService | None" = None