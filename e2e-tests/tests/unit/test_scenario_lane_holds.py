"""Every scenario module a compute pipeline lane selects holds its lane's timers.

A lane is its marker expression in ``e2e-tests/Makefile``, the one place lane
membership is written, collected as the lane collects it: over pytest's own
test paths, not its lane's directory, so a module in any directory that joins a
lane comes under the rule. Each module it selects holds, for the whole module,
its lane's storefront loops, fulfillment convergence, and lease watchdog, and a
VM-lane module also Alice's storefront loops: a timer left running is a
participant no stage scripted. Two kinds of module are outside the rule: one no
lane selects, such as one an operator runs against a real host, and one under
``scenarios/core/``, which reaches only the dev chain and messages no storefront
or provisioning service, so it meets none of the timers its lane holds.
Which fixtures a module sets up is pytest's resolution, not its source's, so it
is read from ``pytest --setup-plan`` over the real lane conftests and modules.
See ``openspec/specs/test-compatibility/spec.md``, "Scenarios hold shared
services for the whole module".
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

from tests.unit.test_scenario_cleanup_order import module_plans

TESTS = Path(__file__).resolve().parents[1]
PROJECT = TESTS.parent
MAKEFILE = PROJECT / "Makefile"
SCENARIOS = TESTS / "e2e" / "roles" / "scenarios"
#: The chain-only scenario modules, which no lane's holds cover.
CHAIN_ONLY = SCENARIOS / "core"

VM_HOLDS = (
    "storefront_loops_held",
    "alice_loops_held",
    "fulfillment_convergence_held",
    "lease_watchdog_held",
)
BARE_METAL_HOLDS = (
    "storefront_loops_held",
    "fulfillment_convergence_held",
    "lease_watchdog_held",
)
#: Each compute pipeline lane's marker-expression variable, and the holds every
#: module it selects takes.
LANES = {
    "E2E_MODULE": VM_HOLDS,
    "E2E_BARE_METAL_MODULE": BARE_METAL_HOLDS,
}


def makefile_variable(text: str, name: str) -> str:
    """The value a Makefile assigns ``name``, its continuation lines joined
    and its whitespace collapsed; fails naming the variable when no
    assignment gives it a value."""
    joined = re.sub(r"\\\n", " ", text)
    assignment = re.compile(rf"^{re.escape(name)}\s*[?:+]?=(.*)$")
    for line in joined.splitlines():
        if match := assignment.match(line):
            value = " ".join(match.group(1).split())
            if value:
                return value
    raise AssertionError(
        f"e2e-tests/Makefile assigns no value to {name}, so the lane it names "
        "cannot be read and no module of it can be checked"
    )


def lane_plans(expression: str, *, cwd: Path = PROJECT) -> dict[str, dict]:
    """The setup plan of every module ``expression`` selects, by the module
    path pytest reports relative to its rootdir, which is ``cwd`` wherever this
    check runs; empty when it selects none.

    No path is given, so pytest collects its configured test paths, as the
    lane's own run does. Skip marks are not evaluated (``-p no:skipping``): a
    module skipped in this environment may still run in its lane, and one
    skipped there needs its holds no less once it is not.
    """
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--setup-plan", "-q", "-p", "no:cacheprovider",
         "-p", "no:skipping", "-m", expression],
        cwd=cwd, capture_output=True, text=True, check=False,
    )
    # pytest exits 5 when the expression selects no test.
    assert result.returncode in (0, 5), result.stdout[-4000:] + result.stderr[-4000:]
    return module_plans(result.stdout)


def held_plans(
    plans: dict[str, dict], *, cwd: Path = PROJECT, chain_only: Path = CHAIN_ONLY,
) -> dict[str, dict]:
    """The plans of the modules the hold rule covers: every one but those
    under ``chain_only``."""
    return {
        module: plan
        for module, plan in plans.items()
        if not (cwd / module).resolve().is_relative_to(chain_only.resolve())
    }


def missing_holds(plans: dict[str, dict], holds: tuple[str, ...]) -> list[str]:
    """``module: hold`` for each hold a module's setup plan lacks."""
    return [
        f"{module}: {hold}"
        for module, plan in sorted(plans.items())
        for hold in holds
        if hold not in {name for name, _ in plan["setup"]}
    ]


def check_lane(variable: str, plans: dict[str, dict], holds: tuple[str, ...]) -> None:
    assert plans, (
        f"{variable} selects no scenario module the hold rule covers, so no "
        "hold of it can be checked"
    )
    missing = missing_holds(plans, holds)
    assert not missing, (
        f"modules {variable} selects lack their lane's holds; list them first in "
        "the module's `usefixtures`, after moving a module outside its lane's "
        f"directory into it, where the hold fixtures are defined: {missing}"
    )


@pytest.mark.parametrize("variable", sorted(LANES))
def test_every_module_a_lane_selects_holds_its_lanes_timers(variable: str):
    expression = makefile_variable(MAKEFILE.read_text(), variable)
    check_lane(variable, held_plans(lane_plans(expression)), LANES[variable])


def test_a_continued_variable_is_read_whole():
    text = (
        "# A lane's scenarios.\n"
        "E2E_MODULE ?= e2e_deal or e2e_buy \\\n"
        "              or e2e_listing_shapes\n"
        "OTHER ?= x\n"
    )

    assert makefile_variable(text, "E2E_MODULE") == "e2e_deal or e2e_buy or e2e_listing_shapes"


def test_a_variable_with_no_value_fails_by_name():
    with pytest.raises(AssertionError, match="E2E_BARE_METAL_MODULE"):
        makefile_variable("E2E_MODULE ?= e2e_deal\nE2E_BARE_METAL_MODULE ?=\n", "E2E_BARE_METAL_MODULE")


def test_a_lane_selecting_nothing_fails_by_name():
    with pytest.raises(AssertionError, match="E2E_MODULE selects no scenario module"):
        check_lane("E2E_MODULE", {}, VM_HOLDS)


def test_a_planted_plan_missing_a_hold_names_the_module_and_the_hold():
    plan = (
        "    SETUP    M storefront_loops_held (fixtures used: storefront_admin_client)\n"
        "    SETUP    M fulfillment_convergence_held\n"
        "        tests/e2e/roles/scenarios/bare_metal/test_m.py::test_a\n"
        "    TEARDOWN M fulfillment_convergence_held\n"
        "    TEARDOWN M storefront_loops_held\n"
    )

    assert missing_holds(module_plans(plan), BARE_METAL_HOLDS) == [
        "tests/e2e/roles/scenarios/bare_metal/test_m.py: lease_watchdog_held",
    ]


def test_the_selection_is_the_expression_not_the_directory(tmp_path: Path):
    """Over a planted tree, through the real setup plan: every module the
    lane's expression selects is held to the holds — in the lane's directory,
    skipped where the check runs, or in another directory — except one under
    the chain-only directory; one the expression leaves out is not required,
    and an expression selecting nothing yields no plan."""
    (tmp_path / "conftest.py").write_text(
        "import pytest\n"
        "def pytest_configure(config):\n"
        "    config.addinivalue_line('markers', 'planted_lane: the planted lane')\n"
        + "".join(
            f"@pytest.fixture(scope='module')\ndef {hold}():\n    yield\n"
            for hold in BARE_METAL_HOLDS
        )
    )
    for directory in ("lane", "elsewhere", "core"):
        (tmp_path / directory).mkdir()
    (tmp_path / "lane" / "test_selected.py").write_text(
        "import pytest\n"
        "pytestmark = [\n"
        "    pytest.mark.usefixtures('storefront_loops_held', 'fulfillment_convergence_held'),\n"
        "    pytest.mark.planted_lane,\n"
        "]\n"
        "def test_a():\n    pass\n"
    )
    (tmp_path / "lane" / "test_skipped_here.py").write_text(
        "import pytest\n"
        "pytestmark = [pytest.mark.skipif(True, reason='not here'), pytest.mark.planted_lane]\n"
        "def test_c():\n    pass\n"
    )
    (tmp_path / "elsewhere" / "test_joined.py").write_text(
        "import pytest\npytestmark = pytest.mark.planted_lane\ndef test_d():\n    pass\n"
    )
    (tmp_path / "core" / "test_chain_only.py").write_text(
        "import pytest\npytestmark = pytest.mark.planted_lane\ndef test_e():\n    pass\n"
    )
    (tmp_path / "lane" / "test_by_hand.py").write_text("def test_b():\n    pass\n")

    plans = lane_plans("planted_lane", cwd=tmp_path)
    held = held_plans(plans, cwd=tmp_path, chain_only=tmp_path / "core")

    assert sorted(plans) == [
        "core/test_chain_only.py", "elsewhere/test_joined.py",
        "lane/test_selected.py", "lane/test_skipped_here.py",
    ]
    assert missing_holds(held, BARE_METAL_HOLDS) == [
        *(f"elsewhere/test_joined.py: {hold}" for hold in BARE_METAL_HOLDS),
        "lane/test_selected.py: lease_watchdog_held",
        *(f"lane/test_skipped_here.py: {hold}" for hold in BARE_METAL_HOLDS),
    ]
    assert lane_plans("no_such_lane", cwd=tmp_path) == {}
