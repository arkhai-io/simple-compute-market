"""The release-component declaration's reader accepts only the shape it knows."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from release_components import (
    DECLARATION,
    DeclarationError,
    Distribution,
    declared_wheels,
    load,
    parse,
    wheel_file_name,
)

VALID = {
    "distributions": [
        {"key": "kit-a", "path": "kit/a", "dist": "arkhai-kit-a"},
        {"key": "kit-b", "path": "kit/b", "dist": "arkhai-kit-b"},
    ],
    "images": [
        {"name": "registry", "local": "registry"},
        {"name": "provisioning", "local": "compute-provisioning"},
    ],
    "chart": {"path": "helm"},
    "binaries": [{"name": "market", "target": "build-market", "path": "out/market"}],
    "development_images": [{"name": "dev-env", "local": "dev-env"}],
}


def _document(**changes: object) -> dict:
    document = copy.deepcopy(VALID)
    for key, value in changes.items():
        if value is None:
            del document[key]
        else:
            document[key] = value
    return document


def _refusal(document: object) -> str:
    with pytest.raises(DeclarationError) as raised:
        parse(document, "declaration.json")
    return str(raised.value)


def test_a_valid_declaration_is_read_in_order() -> None:
    components = parse(_document())

    assert [entry.dist for entry in components.distributions] == ["arkhai-kit-a", "arkhai-kit-b"]
    assert [(image.name, image.local) for image in components.images] == [
        ("registry", "registry"), ("provisioning", "compute-provisioning")]
    assert components.chart.path == "helm"
    assert components.binaries[0].target == "build-market"
    assert components.development_images[0].name == "dev-env"
    assert components.npm is None


def test_a_declared_npm_package_is_read() -> None:
    components = parse(_document(npm=[{"path": "middleware/typescript"}]))

    assert components.npm is not None
    assert [package.path for package in components.npm] == ["middleware/typescript"]


@pytest.mark.parametrize("key", ["distributions", "images", "chart", "binaries",
                                 "development_images"])
def test_a_missing_required_key_is_refused(key: str) -> None:
    assert f"required key {key!r} is missing" in _refusal(_document(**{key: None}))


def test_an_unknown_key_is_refused() -> None:
    assert "unknown key 'public'" in _refusal(_document(public=True))


def test_an_unknown_key_in_an_entry_is_refused() -> None:
    document = _document()
    document["distributions"][0]["wheel_only"] = True

    assert "distributions[0] has unknown key 'wheel_only'" in _refusal(document)


def test_an_empty_npm_list_is_refused() -> None:
    assert "npm is present and empty" in _refusal(_document(npm=[]))


def test_a_duplicated_image_name_is_refused_across_release_and_development_images() -> None:
    document = _document(development_images=[{"name": "registry", "local": "dev-registry"}])

    assert "image name 'registry' is declared twice" in _refusal(document)


def test_a_duplicated_distribution_is_refused_however_it_is_spelled() -> None:
    document = _document()
    document["distributions"].append({"key": "kit-a2", "path": "kit/a2", "dist": "arkhai_kit_A"})

    assert "distribution dist 'arkhai_kit_A' is declared twice" in _refusal(document)


@pytest.mark.parametrize(("document", "message"), [
    (_document(images={"name": "registry"}), "images is dict, not a list"),
    (_document(chart=["helm"]), "chart is list, not an object"),
    (_document(binaries=[{"name": "market", "target": "build-market", "path": 7}]),
     "binaries[0].path is not a non-empty string"),
    (["not", "an", "object"], "the declaration is not a JSON object"),
])
def test_a_value_of_the_wrong_kind_is_refused(document: object, message: str) -> None:
    assert message in _refusal(document)


def test_every_problem_is_named_at_once() -> None:
    refusal = _refusal(_document(images=None, npm=[], extra=1))

    assert "required key 'images' is missing" in refusal
    assert "npm is present and empty" in refusal
    assert "unknown key 'extra'" in refusal


def test_a_file_that_is_not_json_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "release-components.json"
    path.write_text("{", encoding="utf-8")

    with pytest.raises(DeclarationError, match="not JSON"):
        load(path)


def test_the_repository_declaration_is_read() -> None:
    components = load(DECLARATION)

    assert components.distributions
    assert components.npm is None


def test_a_wheel_file_name_spells_the_distribution_with_underscores() -> None:
    entry = Distribution(key="kit-a", path="kit/a", dist="arkhai-kit-a")

    assert wheel_file_name(entry, "1.2.3") == "arkhai_kit_a-1.2.3-py3-none-any.whl"


def test_declared_wheels_read_each_version_from_its_project(tmp_path: Path) -> None:
    for name, version in (("a", "1.0.0"), ("b", "0.2.0")):
        project = tmp_path / "kit" / name
        project.mkdir(parents=True)
        (project / "pyproject.toml").write_text(
            f'[project]\nname = "arkhai-kit-{name}"\nversion = "{version}"\n', encoding="utf-8")
    declaration = tmp_path / "release-components.json"
    declaration.write_text(json.dumps(VALID), encoding="utf-8")

    wheels = declared_wheels(load(declaration), tmp_path, tmp_path / ".dist")

    assert [wheel.name for wheel in wheels] == [
        "arkhai_kit_a-1.0.0-py3-none-any.whl", "arkhai_kit_b-0.2.0-py3-none-any.whl"]
