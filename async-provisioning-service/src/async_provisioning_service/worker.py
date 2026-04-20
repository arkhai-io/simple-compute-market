import asyncio
import logging
import subprocess
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from async_provisioning_service.config import settings
from async_provisioning_service.services.job_processor import process_jobs
from async_provisioning_service.services.queue import get_redis


logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Worker API — health, inventory, and Ansible diagnostic endpoints.
# Runs on worker_health_port alongside the job processing loop.
# ---------------------------------------------------------------------------
worker_api = FastAPI(title="Provisioning Worker API", version="0.1.0")


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------

class InventoryHost(BaseModel):
    name: str
    ansible_host: str | None = None
    vars: dict[str, str] = {}


class InventoryResponse(BaseModel):
    inventory_path: str
    hosts: list[InventoryHost]


class ConnectivityResult(BaseModel):
    host: str
    reachable: bool
    detail: str


# ---------------------------------------------------------------------------
# Inventory parsing
# ---------------------------------------------------------------------------

def _parse_inventory(search: str | None = None) -> list[InventoryHost]:
    """Parse the Ansible INI inventory and return a list of hosts.

    Skips group headers ([group_name]) and comment lines.
    Each host line has the format:
        hostname  var1=val1  var2=val2  ...

    If search is provided, filters to hosts whose name contains the string
    (case-insensitive).
    """
    inventory_path = settings.resolved_inventory_path
    if not inventory_path.exists():
        raise FileNotFoundError(f"Inventory not found at {inventory_path}")

    hosts: list[InventoryHost] = []
    for line in inventory_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith("["):
            continue

        parts = stripped.split()
        name = parts[0]

        if search and search.lower() not in name.lower():
            continue

        host_vars: dict[str, str] = {}
        for part in parts[1:]:
            if "=" in part:
                k, _, v = part.partition("=")
                host_vars[k] = v

        hosts.append(InventoryHost(
            name=name,
            ansible_host=host_vars.pop("ansible_host", None),
            vars=host_vars,
        ))

    return hosts


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@worker_api.get("/health", summary="Worker health check")
async def health() -> JSONResponse:
    """Verifies the worker process is running and Redis is reachable.

    Returns **200** when all checks pass, **503** when any dependency
    is unreachable.
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


@worker_api.get(
    "/inventory",
    response_model=InventoryResponse,
    summary="Search Ansible inventory",
)
async def inventory(
    search: str | None = Query(
        default=None,
        description="Filter hosts by name (case-insensitive substring match). "
                    "Omit to return all hosts.",
    )
) -> InventoryResponse:
    """Return hosts from the Ansible inventory file.

    Parses the INI-format inventory at the path resolved by
    ``settings.resolved_inventory_path``. Each host entry includes its
    ``ansible_host`` value (if set) and any other inline variables.

    Returns **404** if the inventory file does not exist.
    """
    try:
        hosts = _parse_inventory(search=search)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    return InventoryResponse(
        inventory_path=str(settings.resolved_inventory_path),
        hosts=hosts,
    )


@worker_api.get(
    "/inventory/{host}/connectivity",
    response_model=ConnectivityResult,
    summary="Check Ansible connectivity to an inventory host",
)
async def check_connectivity(host: str) -> ConnectivityResult:
    """Run ``ansible -m ping`` against a single inventory host.

    This exercises the full Ansible auth path: inventory file parses
    correctly, the host entry exists, the SSH key is valid, and Ansible
    can authenticate and execute on the target.

    The check runs in a thread pool so it does not block the event loop.
    Times out after ``settings.ansible_timeout_seconds`` seconds.

    Returns **404** if the host is not found in the inventory.
    Returns **200** with ``reachable: false`` if the host is unreachable
    or the ping fails — the caller can distinguish this from a 404.
    """
    # Verify the host exists in the inventory before attempting a connection.
    try:
        hosts = _parse_inventory(search=host)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    # Exact match required — search returns substring matches.
    if not any(h.name == host for h in hosts):
        raise HTTPException(
            status_code=404,
            detail=f"Host '{host}' not found in inventory at "
                   f"{settings.resolved_inventory_path}",
        )

    cmd = [
        "ansible",
        "-i", str(settings.resolved_inventory_path),
        host,
        "-m", "ping",
    ]

    logger.info("Running connectivity check: %s", " ".join(cmd))

    def _run() -> tuple[int, str, str]:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=settings.ansible_timeout_seconds,
            cwd=str(settings.repo_root),
        )
        return result.returncode, result.stdout, result.stderr

    try:
        returncode, stdout, stderr = await asyncio.wait_for(
            asyncio.to_thread(_run),
            timeout=settings.ansible_timeout_seconds + 5,
        )
    except asyncio.TimeoutError:
        return ConnectivityResult(
            host=host,
            reachable=False,
            detail="Connectivity check timed out",
        )
    except Exception as exc:
        return ConnectivityResult(
            host=host,
            reachable=False,
            detail=f"Failed to run ansible ping: {exc}",
        )

    reachable = returncode == 0
    detail = stdout.strip() if reachable else (stderr.strip() or stdout.strip())

    logger.info(
        "Connectivity check for %s: reachable=%s", host, reachable
    )

    return ConnectivityResult(host=host, reachable=reachable, detail=detail)


# ---------------------------------------------------------------------------
# Server entrypoint
# ---------------------------------------------------------------------------

async def run_worker_api_server() -> None:
    config = uvicorn.Config(
        worker_api,
        host=settings.host,
        port=settings.worker_health_port,
        log_level=settings.log_level.lower(),
    )
    server = uvicorn.Server(config)
    await server.serve()


async def run_all() -> None:
    """Run the job processor and worker API server concurrently.

    If either task exits, the other is cancelled so the process exits
    non-zero and Kubernetes restarts the pod.
    """
    job_task = asyncio.create_task(process_jobs(), name="job-processor")
    api_task = asyncio.create_task(run_worker_api_server(), name="worker-api-server")

    done, pending = await asyncio.wait(
        {job_task, api_task},
        return_when=asyncio.FIRST_COMPLETED,
    )

    for task in done:
        if task.exception():
            logger.error(
                "Task %s failed: %s", task.get_name(), task.exception()
            )

    for task in pending:
        logger.warning(
            "Cancelling %s due to sibling task exit", task.get_name()
        )
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


def main() -> None:
    asyncio.run(run_all())


if __name__ == "__main__":
    main()