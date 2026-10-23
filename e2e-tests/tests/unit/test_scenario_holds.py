"""No scenario or stage pauses or resumes a shared service itself.

A scenario that needs a service's timer held takes its lane's hold fixture for
the whole module; the fixtures, in each lane's ``conftest.py``, are built on the
hold helpers in ``helpers/compute_deal.py``, which release the hold in a
``finally``. A pause sent anywhere else is released only if the module reaches
its resume, and a persistent deployment keeps whatever a stopped module left.
Read from source, so every scenario module is checked without its lane's
services.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

TESTS = Path(__file__).resolve().parents[1]
ROLES = TESTS / "e2e" / "roles"
HOLD_HELPERS = ROLES / "helpers" / "compute_deal.py"

#: The pause and resume operations of every shared service a scenario holds.
PAUSE_OPERATIONS = frozenset(
    {
        "admin_pause_lifecycle_loops",
        "admin_resume_lifecycle_loops",
        "pause_fulfillment_convergence",
        "resume_fulfillment_convergence",
        "pause_lease_watchdog",
        "resume_lease_watchdog",
    }
)
#: The same operations' routes, for a call that posts to one without the
#: typed client.
PAUSE_ROUTES = (
    "lifecycle/pause",
    "lifecycle/resume",
    "fulfillment-convergence/pause",
    "fulfillment-convergence/resume",
    "lease-watchdog/pause",
    "lease-watchdog/resume",
)
#: The hold helpers, which only a lane's conftest calls, to build its fixtures.
HOLD_HELPER_NAMES = frozenset(
    {"storefront_loops_held", "fulfillment_convergence_held", "lease_watchdog_held"}
)
#: The lane conftests' hold fixtures, each built on one hold helper.
HOLD_FIXTURE_NAMES = HOLD_HELPER_NAMES | {"alice_loops_held"}


def _checked_sources() -> list[Path]:
    """Every Python file under the roles' scenarios and helpers. The hold
    helpers' own file is checked outside the hold helpers' bodies, and each
    conftest outside its hold fixtures'."""
    sources = [
        path
        for directory in (ROLES / "scenarios", ROLES / "helpers")
        for path in sorted(directory.rglob("*.py"))
    ]
    assert HOLD_HELPERS in sources, "the hold helpers' file is not checked"
    return sources


def _exempt_functions(path: Path) -> frozenset[str]:
    if path == HOLD_HELPERS:
        return HOLD_HELPER_NAMES
    if path.name == "conftest.py":
        return HOLD_FIXTURE_NAMES
    return frozenset()


def _referenced_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Name):
        return node.id
    return None


def _docstrings(tree: ast.Module) -> set[int]:
    """The ids of the module's, classes', and functions' docstring nodes, which
    may name a route without posting to it."""
    owners = [tree, *(
        node for node in ast.walk(tree)
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
    )]
    return {
        id(owner.body[0].value)
        for owner in owners
        if owner.body
        and isinstance(owner.body[0], ast.Expr)
        and isinstance(owner.body[0].value, ast.Constant)
    }


def forbidden_calls(
    source: str, filename: str, *, exempt: frozenset[str] = frozenset()
) -> list[str]:
    """``file:line name`` for each reference to a pause operation or hold
    helper, and each string naming a pause route (in a call, a constant, or an
    f-string; docstrings aside), outside the top-level functions named in
    ``exempt``."""
    tree = ast.parse(source, filename=filename)
    skipped = _docstrings(tree) | {
        id(inner)
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in exempt
        for inner in ast.walk(node)
    }
    found: set[tuple[int, str]] = set()
    for node in ast.walk(tree):
        if id(node) in skipped:
            continue
        name = _referenced_name(node)
        if name in PAUSE_OPERATIONS or name in HOLD_HELPER_NAMES:
            found.add((node.lineno, name))
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            found.update((node.lineno, route) for route in PAUSE_ROUTES if route in node.value)
    return [f"{filename}:{line} {name}" for line, name in sorted(found)]


@pytest.mark.parametrize("path", _checked_sources(), ids=lambda path: str(path.relative_to(ROLES)))
def test_no_scenario_or_stage_pauses_a_shared_service(path: Path):
    found = forbidden_calls(
        path.read_text(), str(path.relative_to(TESTS)), exempt=_exempt_functions(path)
    )
    assert not found, (
        "a scenario or stage pauses or resumes a shared service itself; take the "
        f"lane's hold fixture with `usefixtures` instead: {found}"
    )


def test_the_check_names_a_direct_pause_a_route_and_a_hold_helper_call():
    planted = (
        "def test_stage(admin, provisioning, http):\n"
        "    admin.admin_pause_lifecycle_loops()\n"
        "    with storefront_loops_held(admin):\n"
        "        provisioning.resume_lease_watchdog()\n"
        "    http.post(f'{base}/api/v1/system/lease-watchdog/pause')\n"
        "RESUME = '/api/v1/admin/lifecycle/resume'\n"
        "def helper():\n"
        "    '''Never posts to /api/v1/admin/lifecycle/pause itself.'''\n"
    )

    assert forbidden_calls(planted, "planted.py") == [
        "planted.py:2 admin_pause_lifecycle_loops",
        "planted.py:3 storefront_loops_held",
        "planted.py:4 resume_lease_watchdog",
        "planted.py:5 lease-watchdog/pause",
        "planted.py:6 lifecycle/resume",
    ]


def test_only_the_hold_helpers_bodies_are_exempt():
    planted = (
        "def storefront_loops_held(admin):\n"
        "    admin.admin_pause_lifecycle_loops()\n"
        "def advance(admin):\n"
        "    admin.admin_resume_lifecycle_loops()\n"
    )

    assert forbidden_calls(planted, "planted.py", exempt=HOLD_HELPER_NAMES) == [
        "planted.py:4 admin_resume_lifecycle_loops",
    ]


def test_each_lane_conftest_holds_through_the_helpers():
    """The fixtures every held module names are the lanes' own, built on the
    hold helpers, so a module's ``usefixtures`` reaches the one mechanism."""
    for lane, fixtures in (
        ("vms", {"storefront_loops_held", "alice_loops_held", "fulfillment_convergence_held", "lease_watchdog_held"}),
        ("bare_metal", {"storefront_loops_held", "fulfillment_convergence_held", "lease_watchdog_held"}),
    ):
        conftest = ROLES / "scenarios" / lane / "conftest.py"
        tree = ast.parse(conftest.read_text(), filename=str(conftest))
        defined = {
            node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)
        }
        assert fixtures <= set(defined), (lane, sorted(fixtures - set(defined)))
        for name in fixtures:
            helpers = {
                _referenced_name(node.func)
                for node in ast.walk(defined[name])
                if isinstance(node, ast.Call)
            }
            assert helpers & HOLD_HELPER_NAMES, (lane, name)
