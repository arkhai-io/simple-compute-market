"""Entry-point discovery: broken plugins are skipped, not fatal."""

from __future__ import annotations

import core_buyer.plugins as plugins_mod
from core_buyer.plugins import BuyerSchemaPlugin, discover_plugins


class _FakeEntryPoint:
    def __init__(self, name, loader):
        self.name = name
        self._loader = loader

    def load(self):
        return self._loader()


def _noop_register(app):  # pragma: no cover - never invoked here
    pass


def test_discover_skips_broken_and_mistyped_plugins(monkeypatch, capsys):
    good = BuyerSchemaPlugin(schema_id="good", register=_noop_register)

    def _boom():
        raise ImportError("missing native dep")

    eps = [
        _FakeEntryPoint("broken", _boom),
        _FakeEntryPoint("mistyped", lambda: object()),
        _FakeEntryPoint("good", lambda: good),
    ]
    monkeypatch.setattr(plugins_mod, "_iter_entry_points", lambda: eps)

    loaded = discover_plugins()

    assert loaded == [good]
    err = capsys.readouterr().err
    assert "broken" in err and "failed to load" in err
    assert "mistyped" in err and "BuyerSchemaPlugin" in err


def test_discover_empty_when_nothing_installed(monkeypatch):
    monkeypatch.setattr(plugins_mod, "_iter_entry_points", lambda: [])
    assert discover_plugins() == []
