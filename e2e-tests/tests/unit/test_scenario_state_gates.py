"""Every `require_state` key a scenario gates on is produced by some stage.

A gate nothing satisfies makes each dependent stage skip, and pytest reports a
skip as neither pass nor failure — so an entire scenario tail can stop running
without any summary showing it. `_evaluate_negotiate_passed` gated stages 05b
onward of both full-deal scenarios and was never assigned anywhere, which is how
the negotiation, settlement, provisioning, and teardown stages went unexecuted.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

SCENARIOS = sorted(
    (Path(__file__).resolve().parents[1] / "e2e" / "roles" / "scenarios" / "vms")
    .glob("test_*.py")
)
_REQUIRE = re.compile(r"require_state\(\s*\w+\s*,\s*([^)]*)\)", re.S)
_KEY = re.compile(r'"([A-Za-z_][A-Za-z0-9_]*)"')


def _required_keys(source: str) -> set[str]:
    return {
        key
        for call in _REQUIRE.findall(source)
        for key in _KEY.findall(call)
    }


@pytest.mark.parametrize("path", SCENARIOS, ids=lambda p: p.name)
def test_every_gated_state_is_produced_somewhere(path: Path) -> None:
    source = path.read_text()
    required = _required_keys(source)
    if not required:
        pytest.skip(f"{path.name} gates on no state")

    # A state is produced by assigning the attribute or by writing into it —
    # `state.ids[k] = v` is as much a producer as `state.flag = True`, and a
    # dict-valued gate is normally filled the first way.
    unset = sorted(
        key for key in required
        if not re.search(
            rf"\.{re.escape(key)}\s*(?:=[^=]|\[[^\]]*\]\s*=[^=])", source
        )
    )
    assert not unset, (
        f"{path.name} gates stages on {unset}, which no stage in it assigns. "
        "Every dependent stage skips, and a skip is invisible in a pass/fail "
        "summary — the scenario stops proving its own subject silently."
    )
