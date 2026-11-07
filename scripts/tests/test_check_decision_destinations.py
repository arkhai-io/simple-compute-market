"""Each `### D<n>` decision of a change's design names its permanent destination in
its proposal's "Knowledge to promote"."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

import check_decision_destinations as checker

CHANGE = "shape-bounds"
DESIGN = """# Design

## Context

### D9 — a heading outside the decisions is not one

### Decisions

### D6 — under a third-level heading of that name, not a decision either

## Decisions

### D1 — Bounds are published

```markdown
### D8 — an example inside a fence is not a decision
```python
### D4 — a line opening another fence does not close this one
```

````markdown
```
### D5 — nor inside a longer fence holding a shorter one
```
````

### Grouping heading

### D2 — Nothing is promoted

## Open Questions

### D7 — not a decision either
"""


def _change(tmp_path: Path, design: str, proposal: str) -> Path:
    """A change in a Git repository, where the workflow's command finds it."""
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    directory = tmp_path / "openspec/changes" / CHANGE
    directory.mkdir(parents=True)
    (directory / checker.DESIGN_FILE).write_text(design)
    (directory / checker.PROPOSAL_FILE).write_text(proposal)
    return tmp_path


def _proposal(*bullets: str) -> str:
    return ("## Why\n\n- D2 is mentioned here, outside the section\n\n"
            "### Knowledge to promote\n\n" + "".join(f"- {b}\n" for b in bullets)
            + "\n## Impact\n\n- D2 again outside\n")


def test_decisions_are_read_only_from_the_decisions_section_outside_fences() -> None:
    assert checker.decisions(DESIGN) == ["D1", "D2"]


def test_every_decision_named_passes(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = _change(tmp_path, DESIGN, _proposal(
        "D1, published bounds: `openspec/specs/storefront-publication/spec.md`",
        "D2: no permanent destination — a decision not to add a rule"))

    assert checker.main([CHANGE], root=root) == 0
    assert "2 decisions" in capsys.readouterr().out


def test_a_missing_bullet_is_named(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = _change(tmp_path, DESIGN, _proposal("D1: `docs/development/ARCHITECTURE.md`"))

    assert checker.main([CHANGE], root=root) == 1
    out = capsys.readouterr().out
    assert "D2 has no bullet starting `D2`" in out
    assert "D1 has" not in out


def test_a_bullet_must_start_with_the_decision(tmp_path: Path) -> None:
    root = _change(tmp_path, DESIGN, _proposal(
        "D1: here", "Published bounds, per D2: here", "D20: a longer number is not D2"))

    assert checker.main([CHANGE], root=root) == 1


def test_a_design_without_decision_headings_is_not_checked(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = _change(tmp_path, "# Design\n\n## Decisions\n\n- **Bounds are published.**\n",
                   "## Why\n")

    assert checker.main([CHANGE], root=root) == 0
    assert "not checked" in capsys.readouterr().out
