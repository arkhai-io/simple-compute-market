import asyncio
import logging

import uvicorn
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from async_provisioning_service.config import settings
from async_provisioning_service.services.job_processor import process_jobs
from async_provisioning_service.services.queue import get_redis


logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Minimal health API — exposes /health on a dedicated port so Kubernetes
# and helm tests can verify the worker process is alive and Redis is reachable.
# Intentionally kept separate from the main API (main.py) so the worker
# container has no dependency on the API's routes, middleware, or database.
# ---------------------------------------------------------------------------
health_app = FastAPI(title="Provisioning Worker Health", version="0.1.0")


@health_app.get("/health", summary="Worker health check")
async def health() -> JSONResponse:
    """Verifies the worker process is running and Redis is reachable.

    Returns **200** when Redis responds to PING,
    **503** when Redis is unreachable.
    """
    checks: dict[str, str] = {"worker": "ok"}

    try:
        redis = await get_redis()
        await redis.ping()
        checks["redis"] = "ok"
    except Exception as exc:
        checks["redis"] = f"error: {exc}"

    all_ok = all(v == "ok" for v in checks.values())
    return JSONResponse(
        content={"status": "ok" if all_ok else "degraded", "checks": checks},
        status_code=200 if all_ok else 503,
    )


async def run_health_server() -> None:
    config = uvicorn.Config(
        health_app,
        host=settings.host,
        port=settings.worker_health_port,
        log_level=settings.log_level.lower(),
    )
    server = uvicorn.Server(config)
    await server.serve()


async def run_all() -> None:
    """Run the job processor and health server concurrently.

    If either task exits (e.g. unhandled exception in the job loop or
    the health server fails to bind), the other is cancelled so the
    process exits non-zero and Kubernetes restarts the pod.
    """
    job_task = asyncio.create_task(process_jobs(), name="job-processor")
    health_task = asyncio.create_task(run_health_server(), name="health-server")

    done, pending = await asyncio.wait(
        {job_task, health_task},
        return_when=asyncio.FIRST_COMPLETED,
    )

    for task in done:
        if task.exception():
            logger.error("Task %s failed: %s", task.get_name(), task.exception())

    for task in pending:
        logger.warning("Cancelling %s due to sibling task exit", task.get_name())
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


def main() -> None:
    asyncio.run(run_all())


if __name__ == "__main__":
    main()