"""A module's holds are released after the module's other cleanup.

A hold keeps a shared service's timers stopped while its module's cleanup runs,
so no timer cycle observes a half-cleaned deployment, such as a storefront whose
reservations are being released fleet-wide. pytest finalises module fixtures in
the reverse of the order it set them up, so the cleanup must be set up after the
holds. That order is pytest's, not the source's, so it is read from
``pytest --setup-plan`` over the real lane conftests and scenario modules, which
resolves every fixture without running one.
"""

from __future__ import annotations

import ast
import re
import subprocess
import sys
from pathlib import Path

import pytest

from tests.unit.test_scenario_holds import HOLD_FIXTURE_NAMES

TESTS = Path(__file__).resolve().parents[1]
PROJECT = TESTS.parent
SCENARIOS = TESTS / "e2e" / "roles" / "scenarios"
LANES = ("vms", "bare_metal")

#: The VM lane's module cleanup, which every mock-provisioned VM scenario module
#: takes.
VM_CLEANUP = ("ensure_storefront_resumed", "reap_buyer_settle_subprocess", "release_reserved_resources")
#: The real-provisioning VM module, and its cleanup in place of the lane's.
REAL_VM_MODULE = SCENARIOS / "vms" / "test_real_provisioning_deal.py"
REAL_VM_CLEANUP = ("ensure_storefront_resumed", "recover_failed_run")

_FIXTURE_LINE = re.compile(r"^\s+(SETUP|TEARDOWN)\s+M (\S+)(?: \(fixtures used: (.*)\))?$")
_TEST_LINE = re.compile(r"^\s{8}(\S+\.py)::")


def module_plans(plan: str) -> dict[str, dict]:
    """Each module's module-scoped setups (with the fixtures each uses) and
    teardowns, in pytest's order, from ``--setup-plan`` output."""
    modules: dict[str, dict] = {}
    pending: list[tuple[str, list[str]]] = []
    current: str | None = None
    for line in plan.splitlines():
        if match := _TEST_LINE.match(line):
            current = match.group(1)
            entry = modules.setdefault(current, {"setup": [], "teardown": []})
            entry["setup"].extend(pending)
            pending = []
        elif match := _FIXTURE_LINE.match(line):
            phase, name, used = match.groups()
            if phase == "SETUP":
                pending.append((name, [u.strip() for u in (used or "").split(",") if u.strip()]))
            else:
                assert current is not None, line
                modules[current]["teardown"].append(name)
    return modules


def _closes_only(yielded: ast.expr | None, statements: list[ast.stmt]) -> bool:
    """Whether a finaliser's statements only close the object the fixture
    yielded, called on the very name it yielded; anything else is cleanup."""
    if not isinstance(yielded, ast.Name):
        return False
    return all(
        isinstance(statement, ast.Expr)
        and isinstance(statement.value, ast.Call)
        and not statement.value.args
        and not statement.value.keywords
        and isinstance(statement.value.func, ast.Attribute)
        and statement.value.func.attr == "close"
        and isinstance(statement.value.func.value, ast.Name)
        and statement.value.func.value.id == yielded.id
        for statement in statements
    )


def _cleans_up(node: ast.FunctionDef) -> bool:
    if any(isinstance(inner, ast.Attribute) and inner.attr == "addfinalizer" for inner in ast.walk(node)):
        return True
    for index, statement in enumerate(node.body):
        if any(isinstance(inner, (ast.Yield, ast.YieldFrom)) for inner in ast.walk(statement)):
            if not (isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Yield)):
                # A yield inside a `with` or `try`, or a `yield from`,
                # finalises through it.
                return True
            return not _closes_only(statement.value.value, node.body[index + 1:])
    return False


def fixtures_with_finalisers(paths: list[Path]) -> dict[str, bool]:
    """Whether each fixture these files define cleans up when it is finalised:
    a generator fixture with work after its ``yield`` beyond closing its own
    clients, or one registering ``addfinalizer``."""
    found: dict[str, bool] = {}
    for path in paths:
        for node in ast.walk(ast.parse(path.read_text(), filename=str(path))):
            if not isinstance(node, ast.FunctionDef):
                continue
            if not any("fixture" in ast.unparse(d) for d in node.decorator_list):
                continue
            found[node.name] = _cleans_up(node)
    return found


def released_too_early(module: dict, finalisers: dict[str, bool]) -> list[str]:
    """Fixtures with a finaliser that tear down after the module's first hold is
    released and are neither holds nor something a hold is built on. A fixture
    no file here defines is taken to have a finaliser."""
    uses = dict(module["setup"])
    hold_inputs: set[str] = set()
    stack = [name for name in uses if name in HOLD_FIXTURE_NAMES]
    while stack:
        for used in uses.get(stack.pop(), []):
            if used not in hold_inputs:
                hold_inputs.add(used)
                stack.append(used)
    teardown = module["teardown"]
    first = next((i for i, name in enumerate(teardown) if name in HOLD_FIXTURE_NAMES), None)
    if first is None:
        return []
    return [
        name
        for name in teardown[first:]
        if name not in HOLD_FIXTURE_NAMES
        and name not in hold_inputs
        and finalisers.get(name, True)
    ]


def _scenario_modules() -> list[Path]:
    return [path for lane in LANES for path in sorted((SCENARIOS / lane).glob("test_*.py"))]


@pytest.fixture(scope="module")
def plans() -> dict[str, dict]:
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--setup-plan", "-q", "-p", "no:cacheprovider",
         *(str(path.relative_to(PROJECT)) for path in _scenario_modules())],
        cwd=PROJECT, capture_output=True, text=True, check=False,
    )
    assert result.returncode in (0, 5), result.stdout[-4000:] + result.stderr[-4000:]
    return module_plans(result.stdout)


@pytest.fixture(scope="module")
def finalisers() -> dict[str, bool]:
    return fixtures_with_finalisers([*TESTS.rglob("conftest.py"), *_scenario_modules()])


@pytest.mark.parametrize("path", _scenario_modules(), ids=lambda path: str(path.relative_to(SCENARIOS)))
def test_holds_are_released_after_the_modules_other_cleanup(path, plans, finalisers):
    module = plans.get(str(path.relative_to(PROJECT)))
    assert module is not None, f"{path.name} collected no test in the setup plan"
    early = released_too_early(module, finalisers)
    assert not early, (
        f"{path.name} releases its holds before {early}; list the module's cleanup "
        "fixtures after its holds in `usefixtures`, and make none autouse"
    )


@pytest.mark.parametrize(
    "path",
    sorted(path for path in (SCENARIOS / "vms").glob("test_*.py") if path != REAL_VM_MODULE),
    ids=lambda path: path.name,
)
def test_every_vm_module_still_runs_the_lane_cleanup(path, plans):
    set_up = {name for name, _ in plans[str(path.relative_to(PROJECT))]["setup"]}
    assert set(VM_CLEANUP) <= set_up, (path.name, sorted(set(VM_CLEANUP) - set_up))


def test_the_real_vm_module_recovers_its_own_guest_and_releases_nothing_fleet_wide(plans):
    """The real-provisioning module tears down only its own deal's guest. A
    fleet-wide release would return the host's capacity to the market while a
    failed run's guest may still run on it."""
    set_up = {name for name, _ in plans[str(REAL_VM_MODULE.relative_to(PROJECT))]["setup"]}
    assert set(REAL_VM_CLEANUP) <= set_up, sorted(set(REAL_VM_CLEANUP) - set_up)
    assert "release_reserved_resources" not in set_up


def test_the_real_vm_module_checks_its_target_and_execution_before_any_hold(plans):
    """A hold pauses a shared service when it is set up, so the module writes
    nothing to the stack only if its target is validated and its VM execution
    found real first."""
    order = [name for name, _ in plans[str(REAL_VM_MODULE.relative_to(PROJECT))]["setup"]]
    holds = [order.index(name) for name in order if name in HOLD_FIXTURE_NAMES]
    assert holds, order
    assert order.index("real_vm_target") < order.index("real_vm_execution") < min(holds), order


def _planted(setups: list[str], teardowns: list[str]) -> str:
    return (
        "".join(f"    SETUP    M {line}\n" for line in setups)
        + "        tests/m.py::test_a\n"
        + "".join(f"    TEARDOWN M {name}\n" for name in teardowns)
    )


def test_the_check_names_cleanup_released_after_a_hold():
    finalisers = {"client": True, "storefront_loops_held": True, "cleanup": True, "noop": False}
    held_first = module_plans(_planted(
        ["client", "noop", "cleanup (fixtures used: client)",
         "storefront_loops_held (fixtures used: client)"],
        ["storefront_loops_held", "cleanup", "noop", "client"],
    ))["tests/m.py"]
    cleanup_first = module_plans(_planted(
        ["client", "noop", "storefront_loops_held (fixtures used: client)",
         "cleanup (fixtures used: client)"],
        ["cleanup", "storefront_loops_held", "noop", "client"],
    ))["tests/m.py"]

    assert released_too_early(held_first, finalisers) == ["cleanup"]
    assert released_too_early(cleanup_first, finalisers) == []


def test_closing_a_client_is_not_cleanup_and_other_finalisers_are():
    source = (
        "import pytest\n"
        "@pytest.fixture\n"
        "def client():\n"
        "    c = make()\n"
        "    yield c\n"
        "    c.close()\n"
        "@pytest.fixture\n"
        "def release(client):\n"
        "    yield\n"
        "    client.release_everything()\n"
        "@pytest.fixture\n"
        "def held(client):\n"
        "    with hold(client) as h:\n"
        "        yield h\n"
        "@pytest.fixture\n"
        "def plain():\n"
        "    return 1\n"
    )
    tree = ast.parse(source)
    found = {node.name: _cleans_up(node) for node in tree.body if isinstance(node, ast.FunctionDef)}

    assert found == {"client": False, "release": True, "held": True, "plain": False}


def test_only_closing_the_yielded_client_is_exempt():
    """A ``close()`` on anything but the object the fixture yielded is cleanup:
    a fixture yielding nothing, or another object, that closes something shared
    acts on more than its own connection."""
    source = (
        "import pytest\n"
        "@pytest.fixture\n"
        "def yields_nothing(client):\n"
        "    yield\n"
        "    client.close()\n"
        "@pytest.fixture\n"
        "def closes_another(shared):\n"
        "    c = make()\n"
        "    yield c\n"
        "    shared.close()\n"
        "@pytest.fixture\n"
        "def closes_own_then_more():\n"
        "    c = make()\n"
        "    yield c\n"
        "    c.close()\n"
        "    c.release_everything()\n"
        "@pytest.fixture\n"
        "def closes_own_attribute():\n"
        "    c = make()\n"
        "    yield c\n"
        "    c.session.close()\n"
        "@pytest.fixture\n"
        "def closes_own():\n"
        "    c = make()\n"
        "    yield c\n"
        "    c.close()\n"
    )
    tree = ast.parse(source)
    found = {node.name: _cleans_up(node) for node in tree.body if isinstance(node, ast.FunctionDef)}

    assert found == {
        "yields_nothing": True,
        "closes_another": True,
        "closes_own_then_more": True,
        "closes_own_attribute": True,
        "closes_own": False,
    }
