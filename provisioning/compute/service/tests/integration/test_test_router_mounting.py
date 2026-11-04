"""The suite's fixtures mount the test routers on the shared app at most once.

Every fixture that serves the test routes asks ``mount_unless_served`` to mount
them on the module-level app, which ``main.py`` may already have done. Mounting
again would wrap the app's lifespan once per test, so a fixture repeated across
the suite would leave the lifespan nested deeper than the stack allows.
"""

from __future__ import annotations

import re

import pytest
from starlette.routing import Match

from compute_provisioning_service.controllers import test_jobs_controller
from compute_provisioning_service.main import _bare_metal_mock_router, _vm_mock_router, app

from .conftest import mount_unless_served


def _matching(path: str, method: str) -> int:
    scope = {"type": "http", "path": path, "method": method, "root_path": ""}
    return sum(1 for route in app.routes if route.matches(scope)[0] is Match.FULL)


@pytest.mark.parametrize(
    "router_factory",
    [lambda: test_jobs_controller.router, _vm_mock_router, _bare_metal_mock_router],
    ids=["jobs", "vm-mock", "bare-metal-mock"],
)
def test_a_router_already_served_is_not_mounted_again(router_factory) -> None:
    mount_unless_served(app, router_factory())
    lifespan = app.router.lifespan_context

    for _ in range(3):
        mount_unless_served(app, router_factory())

    assert app.router.lifespan_context is lifespan
    for route in router_factory().routes:
        path = re.sub(r"\{[^}]+\}", "x", route.path)
        for method in route.methods:
            assert _matching(path, method) == 1, (method, route.path)
