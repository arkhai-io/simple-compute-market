"""What the release's `market` binary bundles is derived from the declaration."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import buyer_domain_wheels
from release_components import REPO_ROOT, DeclarationError, load


def _project(root: Path, path: str, name: str, version: str, extra: str = "") -> None:
    directory = root / path
    directory.mkdir(parents=True)
    (directory / "pyproject.toml").write_text(
        f'[project]\nname = "{name}"\nversion = "{version}"\n{extra}', encoding="utf-8")


CLI = '[project.scripts]\nmarket = "shop_cli.cli:main"\n'


def _domain(entry: str) -> str:
    return f'[project.entry-points."market.buyer_domains"]\n{entry}\n'


def _declare(root: Path, distributions: list[tuple[str, str]]) -> None:
    document = {
        "distributions": [{"key": path.rsplit("/", 1)[-1], "path": path, "dist": dist}
                          for path, dist in distributions],
        "images": [{"name": "registry", "local": "registry"}],
        "chart": {"path": "helm"},
        "binaries": [{"name": "market", "target": "build-market-binary",
                      "path": ".dist/bin/market"}],
        "development_images": [{"name": "dev-env", "local": "dev-env"}],
    }
    (root / "manifests").mkdir()
    (root / "manifests" / "release-components.json").write_text(json.dumps(document),
                                                                encoding="utf-8")


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
    dist = tmp_path / ".dist"
    dist.mkdir()
    for wheel in ("shop_cli-0.6.2-py3-none-any.whl", "shop_boats_buyer-0.3.0-py3-none-any.whl",
                  "shop_cars_buyer-2.1.0-py3-none-any.whl"):
        (dist / wheel).write_bytes(b"")
    return tmp_path


def _run(root: Path, *argv: str, capsys: pytest.CaptureFixture[str]) -> tuple[int, list[str], str]:
    status = buyer_domain_wheels.main(list(argv), root=root)
    captured = capsys.readouterr()
    return status, captured.out.splitlines(), captured.err


def test_domains_are_the_declared_distributions_registering_a_buyer_domain(
        tree: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert _run(tree, capsys=capsys) == (
        0, ["shop_boats_buyer-0.3.0-py3-none-any.whl", "shop_cars_buyer-2.1.0-py3-none-any.whl"], "")


def test_the_cli_is_the_declared_distribution_defining_the_binary_as_a_console_script(
        tree: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert _run(tree, "cli", capsys=capsys) == (0, ["shop_cli-0.6.2-py3-none-any.whl"], "")
    assert _run(tree, "entry-point", capsys=capsys) == (0, ["shop_cli.cli:main"], "")


def test_constraints_pin_every_declared_distribution_at_its_declared_version(
        tree: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert _run(tree, "constraints", capsys=capsys) == (0, [
        "shop-base==1.0.0", "shop-cli==0.6.2", "shop-boats-buyer==0.3.0", "shop-cars-buyer==2.1.0",
    ], "")


def test_pyinstaller_options_copy_each_bundled_distributions_metadata_and_import_each_domain(
        tree: Path, capsys: pytest.CaptureFixture[str]) -> None:
    status, lines, _ = _run(tree, "pyinstaller-options", capsys=capsys)

    assert status == 0
    assert lines == [
        "--copy-metadata shop-cli --copy-metadata shop-boats-buyer --copy-metadata shop-cars-buyer"
        " --hidden-import shop_boats.plugin --hidden-import shop_cars.cli"
        " --hidden-import shop_cars.vans"
    ]


def test_a_wheel_the_wheelhouse_lacks_is_refused_naming_make_dist(
        tree: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tree / ".dist" / "shop_cars_buyer-2.1.0-py3-none-any.whl").unlink()

    status, lines, error = _run(tree, capsys=capsys)

    assert (status, lines) == (1, [])
    assert "shop_cars_buyer-2.1.0-py3-none-any.whl" in error and "make dist" in error


def test_a_cli_wheel_the_wheelhouse_lacks_is_refused_naming_make_dist(
        tree: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tree / ".dist" / "shop_cli-0.6.2-py3-none-any.whl").unlink()

    status, lines, error = _run(tree, "cli", capsys=capsys)

    assert (status, lines) == (1, [])
    assert "shop_cli-0.6.2-py3-none-any.whl" in error and "make dist" in error


def test_a_declared_project_with_no_pyproject_is_reported(
        tree: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tree / "kit" / "base" / "pyproject.toml").unlink()

    status, lines, error = _run(tree, "constraints", capsys=capsys)

    assert (status, lines) == (1, [])
    assert "kit/base/pyproject.toml does not exist" in error


def test_a_second_distribution_defining_the_console_script_is_refused(tmp_path: Path) -> None:
    _project(tmp_path, "a", "shop-a", "1.0.0", CLI)
    _project(tmp_path, "b", "shop-b", "1.0.0", CLI + _domain('b = "shop_b:domain"'))
    _declare(tmp_path, [("a", "shop-a"), ("b", "shop-b")])

    with pytest.raises(DeclarationError, match="found shop-a, shop-b"):
        buyer_domain_wheels.inputs(load(tmp_path / "manifests" / "release-components.json"),
                                   tmp_path)


def test_no_declared_cli_is_refused(tmp_path: Path) -> None:
    _project(tmp_path, "b", "shop-b", "1.0.0", _domain('b = "shop_b:domain"'))
    _declare(tmp_path, [("b", "shop-b")])

    with pytest.raises(DeclarationError, match="found none"):
        buyer_domain_wheels.inputs(load(tmp_path / "manifests" / "release-components.json"),
                                   tmp_path)


def test_no_declared_buyer_domain_is_refused(tmp_path: Path) -> None:
    _project(tmp_path, "a", "shop-a", "1.0.0", CLI)
    _declare(tmp_path, [("a", "shop-a")])

    with pytest.raises(DeclarationError, match="market.buyer_domains"):
        buyer_domain_wheels.inputs(load(tmp_path / "manifests" / "release-components.json"),
                                   tmp_path)


def test_this_repository_bundles_its_three_buyer_domains_into_the_core_buyer_cli() -> None:
    found = buyer_domain_wheels.inputs(load(), REPO_ROOT)

    assert found.cli.distribution.dist == "arkhai-core-buyer"
    assert found.entry_point == "core_buyer.cli:main"
    assert sorted(domain.distribution.dist for domain in found.domains) == [
        "arkhai-apicredits-buyer", "arkhai-bare-metal-buyer", "arkhai-vms-buyer",
    ]


def test_a_declaration_the_reader_refuses_is_reported_and_prints_nothing(
        tree: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tree / "manifests" / "release-components.json").write_text('{"distributions": []}',
                                                                encoding="utf-8")

    status, lines, error = _run(tree, "constraints", capsys=capsys)

    assert (status, lines) == (1, [])
    assert "required key 'images' is missing" in error
