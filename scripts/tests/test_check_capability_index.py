"""The capability index lists every capability with a specification and links
nothing that does not exist."""

from __future__ import annotations

from pathlib import Path

import pytest

import check_capability_index as checker

HEADER = "# Index\n\n## Capabilities\n\n| Capability | Spec | Architecture |\n|---|---|---|\n"


def _specs(tmp_path: Path, rows: str, capabilities: tuple[str, ...] = ("fulfillment",)) -> Path:
    specs = tmp_path / "openspec/specs"
    for name in capabilities:
        (specs / name).mkdir(parents=True)
        (specs / name / "spec.md").write_text(f"# {name}\n")
    (specs / "README.md").write_text(HEADER + rows + "\n## Reading order\n\n"
                                     "| x | [elsewhere](missing/spec.md) |\n")
    return tmp_path


def test_an_index_listing_every_capability_passes(tmp_path: Path) -> None:
    root = _specs(tmp_path, "| Fulfillment | [Spec](fulfillment/spec.md) | — |\n")

    assert checker.problems(root) == []


def test_a_capability_with_no_row_is_named(tmp_path: Path) -> None:
    root = _specs(tmp_path, "| Fulfillment | [Spec](fulfillment/spec.md) | — |\n",
                  ("fulfillment", "contact-exchange-settlement"))

    assert checker.problems(root) == [
        "openspec/specs/README.md: no row links "
        "openspec/specs/contact-exchange-settlement/spec.md"]


def test_a_row_linking_nothing_is_named(tmp_path: Path) -> None:
    root = _specs(tmp_path, "| Fulfillment | [Spec](fulfillment/spec.md) | "
                            "[Architecture](fulfillment/architecture.md) |\n")

    [problem] = checker.problems(root)

    assert "links fulfillment/architecture.md, which does not exist" in problem


@pytest.mark.parametrize("row", [
    "| Fulfillment | — | — |\n",
    "| Fulfillment | [Notes](fulfillment/notes.md) | — |\n",
])
def test_a_row_linking_no_capabilitys_spec_is_named(tmp_path: Path, row: str) -> None:
    root = _specs(tmp_path, "| Fulfillment | [Spec](fulfillment/spec.md) | — |\n" + row)
    (root / "openspec/specs/fulfillment/notes.md").write_text("notes\n")

    assert checker.problems(root) == [
        f"openspec/specs/README.md: the row `{row.strip()}` links no capability's spec.md"]


def test_the_repository_index_passes() -> None:
    assert checker.main() == 0
