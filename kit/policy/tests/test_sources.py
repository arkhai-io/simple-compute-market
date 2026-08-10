"""Behaviour of the general catalogue source implementations.

The directory source carries a mechanism that previously ran unconditionally:
every storefront scanned an operator config directory whether or not any setting
asked for it. It is now constructed only by a role that authorizes it, and it
takes the symbol it looks for, because the repository uses two different file
contracts under one documented name.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from market_policy import (
    CatalogueBuilder,
    CatalogueItemTypeError,
    CatalogueSourceError,
    DirectorySource,
    EntryPointSource,
    InlineSource,
    default_policy_root,
    negotiation_catalogue_builder,
)

_POLICY_MODULE = """
def middleware(history, context):
    return "from-file"
"""


def _write_policy(root: Path, name: str, body: str = _POLICY_MODULE) -> None:
    folder = root / name
    folder.mkdir(parents=True)
    (folder / "policy.py").write_text(body, encoding="utf-8")


def _negotiation_directory(*roots: Path) -> DirectorySource:
    return DirectorySource.from_paths(roots, symbol="middleware")


# --- directory source ------------------------------------------------------


def test_directory_source_loads_a_policy_folder(tmp_path: Path) -> None:
    _write_policy(tmp_path, "operator_guard")

    loaded = _negotiation_directory(tmp_path).load()

    assert set(loaded) == {"operator_guard"}
    assert loaded["operator_guard"](None, None) == "from-file"


def test_directory_source_skips_absent_roots(tmp_path: Path) -> None:
    """An unset operator path is configuration, not a broken provider."""
    assert _negotiation_directory(tmp_path / "never-created").load() == {}


def test_directory_source_skips_private_and_dotted_folders(tmp_path: Path) -> None:
    _write_policy(tmp_path, "visible")
    _write_policy(tmp_path, "_private")
    _write_policy(tmp_path, ".hidden")

    assert set(_negotiation_directory(tmp_path).load()) == {"visible"}


def test_directory_source_ignores_folders_without_a_policy_module(
    tmp_path: Path,
) -> None:
    (tmp_path / "empty").mkdir()

    assert _negotiation_directory(tmp_path).load() == {}


def test_the_symbol_is_parameterised(tmp_path: Path) -> None:
    """Negotiation policies expose `middleware`; aggregation exposes `factory`."""
    _write_policy(tmp_path, "agg", body="def factory(cfg):\n    return cfg\n")

    assert _negotiation_directory(tmp_path).load.__self__.symbol == "middleware"
    with pytest.raises(AttributeError):
        _negotiation_directory(tmp_path).load()

    loaded = DirectorySource.from_paths([tmp_path], symbol="factory").load()
    assert set(loaded) == {"agg"}


def test_a_module_missing_the_symbol_fails_composition(tmp_path: Path) -> None:
    _write_policy(tmp_path, "misnamed", body="def not_middleware(h, c): return 1\n")

    builder = negotiation_catalogue_builder().add_loader(
        _negotiation_directory(tmp_path)
    )

    with pytest.raises(CatalogueSourceError) as caught:
        builder.build()

    assert "middleware" in str(caught.value)


def test_an_unimportable_policy_module_fails_composition(tmp_path: Path) -> None:
    _write_policy(tmp_path, "broken", body="import a_module_that_does_not_exist\n")

    builder = negotiation_catalogue_builder().add_loader(
        _negotiation_directory(tmp_path)
    )

    with pytest.raises(CatalogueSourceError):
        builder.build()


def test_directory_source_describes_its_roots_and_symbol(tmp_path: Path) -> None:
    described = _negotiation_directory(tmp_path).describe()

    assert str(tmp_path) in described
    assert "middleware" in described


def test_the_conventional_root_is_reported_not_consulted(
    tmp_path: Path, monkeypatch
) -> None:
    """The default config directory is opt-in, not implicit.

    It was previously scanned on every chain load regardless of configuration.
    """
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    root = default_policy_root("policies")
    _write_policy(root.parent, root.name)
    _write_policy(root, "should_not_load")

    assert _negotiation_directory(tmp_path / "elsewhere").load() == {}


def test_directory_and_inline_sources_conflict_like_any_other(
    tmp_path: Path,
) -> None:
    _write_policy(tmp_path, "contested")

    builder = (
        negotiation_catalogue_builder()
        .add_loader(InlineSource({"contested": lambda h, c: None}, label="inline"))
        .add_loader(_negotiation_directory(tmp_path))
    )

    with pytest.raises(Exception) as caught:
        builder.build()

    assert "contested" in str(caught.value)


# --- entry-point source ----------------------------------------------------


class _FakeEntryPoint:
    def __init__(self, name, loader):
        self.name = name
        self._loader = loader

    def load(self):
        return self._loader()


def _patch_entry_points(monkeypatch, entries):
    from market_policy import sources

    monkeypatch.setattr(sources, "entry_points", lambda group: entries)


def test_entry_point_source_loads_published_items(monkeypatch) -> None:
    _patch_entry_points(
        monkeypatch, [_FakeEntryPoint("published", lambda: lambda h, c: "pub")]
    )

    loaded = EntryPointSource(group="any.group").load()

    assert set(loaded) == {"published"}
    assert loaded["published"](None, None) == "pub"


def test_an_entry_point_that_cannot_load_fails_composition(monkeypatch) -> None:
    def _boom():
        raise ModuleNotFoundError("No module named 'widgets.missing'")

    _patch_entry_points(monkeypatch, [_FakeEntryPoint("broken", _boom)])

    builder = negotiation_catalogue_builder().add_loader(
        EntryPointSource(group="any.group")
    )

    with pytest.raises(CatalogueSourceError) as caught:
        builder.build()

    assert "widgets.missing" in str(caught.value)


def test_an_entry_point_offering_a_non_callable_is_rejected(monkeypatch) -> None:
    _patch_entry_points(
        monkeypatch, [_FakeEntryPoint("wrong_type", lambda: "not callable")]
    )

    builder = negotiation_catalogue_builder().add_loader(
        EntryPointSource(group="any.group")
    )

    with pytest.raises(CatalogueItemTypeError) as caught:
        builder.build()

    assert "wrong_type" in str(caught.value)


def test_entry_points_conflicting_with_kit_policies_fail(monkeypatch) -> None:
    _patch_entry_points(
        monkeypatch, [_FakeEntryPoint("bisection", lambda: lambda h, c: None)]
    )

    builder = (
        negotiation_catalogue_builder()
        .add_loader(EntryPointSource(group="any.group"))
        .add_loader(InlineSource({"bisection": lambda h, c: None}, label="kit"))
    )

    with pytest.raises(Exception) as caught:
        builder.build()

    assert "bisection" in str(caught.value)


def test_entry_point_source_describes_its_group() -> None:
    assert "some.group" in EntryPointSource(group="some.group").describe()


def test_entry_point_source_is_reusable_for_any_catalogue(monkeypatch) -> None:
    """The loader is item-neutral; only the catalogue's validator differs."""
    _patch_entry_points(monkeypatch, [_FakeEntryPoint("count", lambda: 7)])

    catalogue = (
        CatalogueBuilder(kind="widget")
        .add_loader(EntryPointSource(group="any.group"))
        .build()
    )

    assert catalogue["count"] == 7
