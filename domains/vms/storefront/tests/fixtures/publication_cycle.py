"""Contract fixtures for the publication cycle report.

The storefront's publication loop produces this report from
``/api/v1/admin/lifecycle/publication/run-cycle`` and ``.../dry-run``; the
``market-storefront publish`` command consumes it.

- ``tests/integration/test_publication_loop.py`` calls ``validate_cycle_report``
  on reports real cycles produce.
- ``tests/unit/cli/test_publish_command.py`` uses ``build_cycle_report`` so the
  command is tested against exactly the shape the loop emits.
"""

from __future__ import annotations

from typing import Any

ACTIONS = frozenset(
    {
        "publish",
        "refresh",
        "close",
        "reopen",
        "hold",
        "refuse",
        "skip",
        "converge",
        "fail",
    }
)


def build_cycle_report(
    *,
    dry_run: bool = False,
    actions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    actions = (
        actions
        if actions is not None
        else [
            {"action": "publish", "source": {"derivation_key": "k1", "capacity_backing": "unbacked"}},
            {"action": "close", "listing_id": "listing-1", "reason": "source_gone"},
        ]
    )
    counts: dict[str, int] = {}
    for item in actions:
        counts[item["action"]] = counts.get(item["action"], 0) + 1
    return {
        "loop": "publication",
        "dry_run": dry_run,
        "actions": actions,
        "counts": dict(sorted(counts.items())),
    }


def validate_cycle_report(report: dict[str, Any]) -> None:
    assert report["loop"] == "publication"
    assert isinstance(report["dry_run"], bool)
    assert isinstance(report["actions"], list)
    counts: dict[str, int] = {}
    for item in report["actions"]:
        assert item["action"] in ACTIONS, item
        counts[item["action"]] = counts.get(item["action"], 0) + 1
    assert report["counts"] == dict(sorted(counts.items()))
