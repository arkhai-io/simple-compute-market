"""Render the API-credit stack with Compose and read the order its pair migrates in.

The credits service and the credits storefront hold one pair of databases: the
storefront's issued credentials refer to the service's keys and grants. Each
container runs its migration command before its application, and the
storefront starts only once the service is healthy, which the service is only
once its migration has succeeded and its application answers. So the service's
database migrates first, and a failed service migration leaves the storefront
not started and its database untouched.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

STACKS = {
    # The documented bring-up: the base topology and its development overlay.
    "operator": ("compose.apicredits.yml", "compose.apicredits-local.yml"),
    # The files the API-credit lane composes (e2e-tests/Makefile).
    "lane": (
        "compose.apicredits.yml",
        "compose.apicredits-local.yml",
        "compose.payments-double.yml",
        "compose.apicredits-lane.yml",
    ),
}


def _render(stack: str) -> dict:
    binary = os.environ.get("E2E_COMPOSE_BINARY")
    command = [binary] if binary else ["docker", "compose"]
    if not shutil.which(command[0]):
        # CI's packaging job sets COMPOSE_REQUIRED=1, where a skip is a failure.
        if os.environ.get("COMPOSE_REQUIRED") == "1":
            pytest.fail("Docker Compose is required for deployment rendering")
        pytest.skip("Docker Compose is required for deployment rendering")
    command += ["-p", "apicredits-render"]
    for name in STACKS[stack]:
        command += ["-f", name]
    result = subprocess.run(
        [*command, "config", "--format", "json"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout)["services"]


def _script(service: dict) -> str:
    command = service["command"]
    assert command[:2] == ["sh", "-c"], command
    return command[2]


@pytest.mark.parametrize("stack", sorted(STACKS))
def test_the_storefront_migrates_only_once_the_service_is_healthy(stack: str) -> None:
    services = _render(stack)
    service, storefront = services["credits-service"], services["credits-storefront"]

    assert storefront["depends_on"]["credits-service"]["condition"] == "service_healthy"
    # The service answers its health route only once the application runs,
    # which its command starts only after the migration succeeds.
    script = _script(service)
    port = script.rsplit("--port", 1)[1].split()[0]
    assert f"http://localhost:{port}/health" in " ".join(service["healthcheck"]["test"])
    assert script.startswith("apicredits-service-migrate && exec ")
    assert _script(storefront).startswith("apicredits-storefront-migrate && exec ")
    assert service.get("entrypoint") is None
    assert storefront.get("entrypoint") is None
