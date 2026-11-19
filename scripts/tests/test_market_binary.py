"""The release's `market` binary is derived from the declaration."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import market_binary
from release_components import REPO_ROOT, DeclarationError, load

TARGET = "build-market-binary"
BINARY = {"name": "market", "target": TARGET, "path": ".dist/bin/market"}


def _project(root: Path, path: str, name: str, version: str, extra: str = "") -> None:
    directory = root / path
    directory.mkdir(parents=True)
    (directory / "pyproject.toml").write_text(
        f'[project]\nname = "{name}"\nversion = "{version}"\n{extra}', encoding="utf-8")


CLI = '[project.scripts]\nmarket = "shop_cli.cli:main"\n'


def _domain(entry: str) -> str:
    return f'[project.entry-points."market.buyer_domains"]\n{entry}\n'


def _declare(root: Path, distributions: list[tuple[str, str]],
             binaries: list[dict[str, str]] | None = None) -> None:
    document = {
        "distributions": [{"key": path.rsplit("/", 1)[-1], "path": path, "dist": dist}
                          for path, dist in distributions],
        "images": [{"name": "registry", "local": "registry"}],
        "chart": {"path": "helm"},
        "binaries": [BINARY] if binaries is None else binaries,
        "development_images": [{"name": "dev-env", "local": "dev-env"}],
    }
    manifests = root / "manifests"
    manifests.mkdir(exist_ok=True)
    (manifests / "release-components.json").write_text(json.dumps(document), encoding="utf-8")


def _components(root: Path):
    return load(root / "manifests" / "release-components.json")


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    _project(tmp_path, "kit/base", "shop-base", "1.0.0")
    _project(tmp_path, "core/cli", "shop-cli", "0.6.2", CLI)
    _project(tmp_path, "domains/boats", "shop-boats-buyer", "0.3.0",
             _domain('boats = "shop_boats.plugin:domain"'))
    _project(tmp_path, "domains/cars", "shop-cars-buyer", "2.1.0",
             _domain('cars = "shop_cars.cli:domain"\nvans = "shop_cars.vans:domain"'))
    _declare(tmp_path, [("kit/base", "shop-base"), ("core/cli", "shop-cli"),
                        ("domains/boats", "shop-boats-buyer"),
                        ("domains/cars", "shop-cars-buyer")])
    return tmp_path


def _run(root: Path, *argv: str, capsys: pytest.CaptureFixture[str],
         target: str = TARGET) -> tuple[int, list[str], str]:
    status = market_binary.main(["--target", target, *argv], root=root)
    captured = capsys.readouterr()
    return status, captured.out.splitlines(), captured.err


def test_the_name_and_output_directory_are_the_binary_entrys(
        tree: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert _run(tree, "name", capsys=capsys) == (0, ["market"], "")
    assert _run(tree, "output-dir", capsys=capsys) == (0, [".dist/bin"], "")


def test_the_binary_is_the_entry_whose_target_the_caller_names(
        tree: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _declare(tree, [("core/cli", "shop-cli"), ("domains/boats", "shop-boats-buyer")],
             [{"name": "other", "target": "build-other", "path": "out/other"}, BINARY])

    assert _run(tree, "output-dir", capsys=capsys) == (0, [".dist/bin"], "")
    assert _run(tree, "name", capsys=capsys, target="build-other") == (0, ["other"], "")


@pytest.mark.parametrize(("binaries", "message"), [
    ([], "found 0"),
    ([BINARY, {**BINARY, "name": "shop", "path": ".dist/bin/shop"}], "found 2"),
    ([{**BINARY, "path": ".dist/bin/market-linux"}], "does not end in its name"),
])
def test_a_missing_doubled_or_misnamed_binary_entry_is_refused(
        tree: Path, capsys: pytest.CaptureFixture[str], binaries: list[dict[str, str]],
        message: str) -> None:
    _declare(tree, [("core/cli", "shop-cli")], binaries)

    status, lines, error = _run(tree, "name", capsys=capsys)

    assert (status, lines) == (1, [])
    assert message in error


def test_the_entry_point_is_the_console_script_named_for_the_binary(
        tree: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert _run(tree, "entry-point", capsys=capsys) == (0, ["shop_cli.cli:main"], "")


def test_pyinstaller_options_copy_each_bundled_distributions_metadata_and_import_each_domain(
        tree: Path, capsys: pytest.CaptureFixture[str]) -> None:
    status, lines, _ = _run(tree, "pyinstaller-options", capsys=capsys)

    assert status == 0
    assert lines == [
        "--copy-metadata shop-cli --copy-metadata shop-boats-buyer --copy-metadata shop-cars-buyer"
        " --hidden-import shop_boats.plugin --hidden-import shop_cars.cli"
        " --hidden-import shop_cars.vans"
    ]


def test_the_cli_and_the_domains_are_found_in_declaration_order(tree: Path) -> None:
    found = market_binary.inputs(_components(tree), tree, "market")

    assert found.cli.distribution.dist == "shop-cli"
    assert [domain.distribution.dist for domain in found.domains] == [
        "shop-boats-buyer", "shop-cars-buyer"]
    assert found.domains[1].modules == ("shop_cars.cli", "shop_cars.vans")


def test_a_declared_project_with_no_pyproject_is_reported(
        tree: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tree / "kit" / "base" / "pyproject.toml").unlink()

    status, lines, error = _run(tree, "entry-point", capsys=capsys)

    assert (status, lines) == (1, [])
    assert "kit/base/pyproject.toml does not exist" in error


def test_a_second_distribution_defining_the_console_script_is_refused(tmp_path: Path) -> None:
    _project(tmp_path, "a", "shop-a", "1.0.0", CLI)
    _project(tmp_path, "b", "shop-b", "1.0.0", CLI + _domain('b = "shop_b:domain"'))
    _declare(tmp_path, [("a", "shop-a"), ("b", "shop-b")])

    with pytest.raises(DeclarationError, match="found shop-a, shop-b"):
        market_binary.inputs(_components(tmp_path), tmp_path, "market")


def test_no_declared_cli_is_refused(tmp_path: Path) -> None:
    _project(tmp_path, "b", "shop-b", "1.0.0", _domain('b = "shop_b:domain"'))
    _declare(tmp_path, [("b", "shop-b")])

    with pytest.raises(DeclarationError, match="found none"):
        market_binary.inputs(_components(tmp_path), tmp_path, "market")


def test_no_declared_buyer_domain_is_refused(tmp_path: Path) -> None:
    _project(tmp_path, "a", "shop-a", "1.0.0", CLI)
    _declare(tmp_path, [("a", "shop-a")])

    with pytest.raises(DeclarationError, match="market.buyer_domains"):
        market_binary.inputs(_components(tmp_path), tmp_path, "market")


def test_this_repository_bundles_its_three_buyer_domains_into_the_core_buyer_cli() -> None:
    components = load()
    entry = market_binary.binary(components, market_binary.TARGET)
    found = market_binary.inputs(components, REPO_ROOT, entry.name)

    assert (entry.name, entry.path) == ("market", ".dist/bin/market")
    assert found.cli.distribution.dist == "arkhai-core-buyer"
    assert found.entry_point == "core_buyer.cli:main"
    assert sorted(domain.distribution.dist for domain in found.domains) == [
        "arkhai-apicredits-buyer", "arkhai-bare-metal-buyer", "arkhai-vms-buyer",
    ]


def test_a_declaration_the_reader_refuses_is_reported_and_prints_nothing(
        tree: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tree / "manifests" / "release-components.json").write_text('{"distributions": []}',
                                                                encoding="utf-8")

    status, lines, error = _run(tree, "entry-point", capsys=capsys)

    assert (status, lines) == (1, [])
    assert "required key 'images' is missing" in error
