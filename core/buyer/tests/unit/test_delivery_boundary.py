"""The buyer role package delivers without importing any settlement mechanism."""

from __future__ import annotations

import ast
from collections.abc import Iterable
from pathlib import Path

from market_delivery import SINK_ENTRY_POINT_GROUP

import core_buyer.delivery as delivery

MECHANISM_PACKAGES = (
    "market_contact_exchange",
    "market_alkahest",
    "market_hosted_settlement",
)


def _source_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "src" / "core_buyer"
        if candidate.is_dir():
            return candidate
    raise AssertionError("core_buyer source root not found above test file")


def _absolute_imports(path: Path) -> Iterable[tuple[int, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield node.lineno, alias.name
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            yield node.lineno, node.module


def test_core_buyer_imports_no_settlement_mechanism() -> None:
    root = _source_root()

    violations = [
        f"{path.name}:{lineno}: imports {module}"
        for path in sorted(root.rglob("*.py"))
        for lineno, module in _absolute_imports(path)
        if any(
            module == prefix or module.startswith(prefix + ".")
            for prefix in MECHANISM_PACKAGES
        )
    ]

    assert not violations, (
        "delivering a revealed introduction must not make a mechanism kit a "
        "core dependency:\n" + "\n".join(violations)
    )


def test_sinks_are_reached_only_through_the_plugin_contract(monkeypatch) -> None:
    """No sink is importable only by naming it; the group is the whole path."""

    seen = {}

    class Recorded:
        name = "recorded"

        def load(self):
            return lambda settings: (lambda event: None)

    def fake_entry_points(*, group):
        seen["group"] = group
        return [Recorded()]

    monkeypatch.setattr("market_delivery.discovery.entry_points", fake_entry_points)
    monkeypatch.setattr(
        delivery,
        "buyer_delivery_section",
        lambda config_path=None: {"enabled": ["recorded"]},
    )

    sinks = delivery.load_buyer_delivery_sinks()

    assert seen["group"] == SINK_ENTRY_POINT_GROUP
    assert [sink.name for sink in sinks.sinks] == ["recorded"]


def test_a_broken_sink_distribution_leaves_the_buyer_working(monkeypatch) -> None:
    class Broken:
        name = "broken"

        def load(self):
            raise ImportError("half-installed distribution")

    class Working:
        name = "working"

        def load(self):
            return lambda settings: (lambda event: None)

    monkeypatch.setattr(
        "market_delivery.discovery.entry_points",
        lambda *, group: [Broken(), Working()],
    )
    monkeypatch.setattr(
        delivery,
        "buyer_delivery_section",
        lambda config_path=None: {"enabled": ["working"]},
    )

    sinks = delivery.load_buyer_delivery_sinks()

    assert [sink.name for sink in sinks.sinks] == ["working"]
    assert any("broken" in warning for warning in sinks.warnings)
