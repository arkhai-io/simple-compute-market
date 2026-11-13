"""Read the one declaration of what a marketplace release comprises.

`manifests/release-components.json` declares a release's components: its
distributions in dependency order, its service images, its chart and its
`market` binary. Apart from them, it lists the development images that a release
candidate's validation runs, which are not release components. Every publish
target, check and test that needs one of these lists reads it here, because two
lists kept in agreement by hand drift apart silently.

The reader accepts only the shape it knows. It refuses a declaration with any of
these, naming each one:

- a required key missing, or a key it does not know;
- an `npm` list that is present but empty (the npm package is declared by adding
  the key, so "no npm package" has one spelling: no key);
- an entry declared twice;
- a value of the wrong kind.

A consumer that guessed at an unexpected shape could publish a set nobody
declared.
"""

from __future__ import annotations

import json
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
DECLARATION = REPO_ROOT / "manifests" / "release-components.json"


class DeclarationError(ValueError):
    """The declaration is not in the shape every consumer relies on."""


@dataclass(frozen=True)
class Distribution:
    key: str
    path: str
    dist: str


@dataclass(frozen=True)
class Image:
    """An image by its published name, the stem of its `arkhai:<name>-<rev9>` tag,
    and the local name its build writes, which may differ."""

    name: str
    local: str


@dataclass(frozen=True)
class Chart:
    path: str


@dataclass(frozen=True)
class Binary:
    name: str
    target: str
    path: str


@dataclass(frozen=True)
class Npm:
    path: str


@dataclass(frozen=True)
class ReleaseComponents:
    distributions: tuple[Distribution, ...]
    images: tuple[Image, ...]
    chart: Chart
    binaries: tuple[Binary, ...]
    development_images: tuple[Image, ...]
    npm: tuple[Npm, ...] | None


# Each key's entry type and whether it holds a list of entries or one entry.
_KEYS: dict[str, tuple[type, bool]] = {
    "distributions": (Distribution, True),
    "images": (Image, True),
    "chart": (Chart, False),
    "binaries": (Binary, True),
    "development_images": (Image, True),
    "npm": (Npm, True),
}
_OPTIONAL = {"npm"}


def _fields(kind: type) -> tuple[str, ...]:
    return tuple(kind.__dataclass_fields__)


def _entry(kind: type, value: Any, where: str, problems: list[str]) -> Any:
    if not isinstance(value, dict):
        problems.append(f"{where} is {type(value).__name__}, not an object")
        return None
    fields = _fields(kind)
    for unknown in sorted(set(value) - set(fields)):
        problems.append(f"{where} has unknown key {unknown!r}")
    found = {}
    for field in fields:
        if field not in value:
            problems.append(f"{where} has no {field!r}")
        elif not isinstance(value[field], str) or not value[field].strip():
            problems.append(f"{where}.{field} is not a non-empty string")
        else:
            found[field] = value[field]
    return kind(**found) if len(found) == len(fields) else None


def _duplicates(entries: list[Any], field: str, label: str, problems: list[str],
                normalise=lambda value: value) -> None:
    seen: set[str] = set()
    for entry in entries:
        value = normalise(getattr(entry, field))
        if value in seen:
            problems.append(f"{label} {field} {getattr(entry, field)!r} is declared twice")
        seen.add(value)


def normalise_distribution(name: str) -> str:
    """A distribution name as packaging compares names (PEP 503)."""
    return re.sub(r"[-_.]+", "-", name).lower()


def parse(document: Any, source: str = str(DECLARATION)) -> ReleaseComponents:
    """The declaration's components, or `DeclarationError` naming every problem."""
    if not isinstance(document, dict):
        raise DeclarationError(f"{source}: the declaration is not a JSON object")
    problems: list[str] = []
    for unknown in sorted(set(document) - set(_KEYS)):
        problems.append(f"unknown key {unknown!r}")
    values: dict[str, Any] = {}
    for key, (kind, is_list) in _KEYS.items():
        if key not in document:
            if key not in _OPTIONAL:
                problems.append(f"required key {key!r} is missing")
            continue
        value = document[key]
        if not is_list:
            values[key] = _entry(kind, value, key, problems)
            continue
        if not isinstance(value, list):
            problems.append(f"{key} is {type(value).__name__}, not a list")
            continue
        if key == "npm" and not value:
            problems.append("npm is present and empty; omit the key until a package is declared")
        values[key] = [_entry(kind, item, f"{key}[{index}]", problems)
                       for index, item in enumerate(value)]

    def entries(key: str) -> list[Any]:
        return [entry for entry in values.get(key) or [] if entry is not None]

    _duplicates(entries("distributions"), "key", "distribution", problems)
    _duplicates(entries("distributions"), "path", "distribution", problems)
    _duplicates(entries("distributions"), "dist", "distribution", problems,
                normalise_distribution)
    # Release and development images are tagged and pushed side by side, so a
    # name or local name may appear once across both lists.
    every_image = entries("images") + entries("development_images")
    _duplicates(every_image, "name", "image", problems)
    _duplicates(every_image, "local", "image", problems)
    _duplicates(entries("binaries"), "name", "binary", problems)
    _duplicates(entries("binaries"), "path", "binary", problems)
    _duplicates(entries("npm"), "path", "npm package", problems)

    if problems:
        raise DeclarationError(f"{source}:\n" + "\n".join(f"  {line}" for line in problems))
    return ReleaseComponents(
        distributions=tuple(entries("distributions")),
        images=tuple(entries("images")),
        chart=values["chart"],
        binaries=tuple(entries("binaries")),
        development_images=tuple(entries("development_images")),
        npm=tuple(entries("npm")) if "npm" in document else None,
    )


def load(path: Path = DECLARATION) -> ReleaseComponents:
    """The declaration at `path`, refused as `parse` refuses it."""
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise DeclarationError(f"{path}: not JSON: {error}") from error
    return parse(document, str(path))


def project_version(root: Path, distribution: Distribution) -> str:
    """The version a distribution's project declares."""
    pyproject = root / distribution.path / "pyproject.toml"
    project = tomllib.loads(pyproject.read_text(encoding="utf-8")).get("project", {})
    version = project.get("version")
    if not isinstance(version, str):
        raise DeclarationError(f"{pyproject} declares no static version")
    return version


def wheel_file_name(distribution: Distribution, version: str) -> str:
    """The pure-Python wheel file name a build of `distribution` at `version` writes.

    Wheel file names spell the distribution with underscores (PEP 427).
    """
    name = re.sub(r"[-_.]+", "_", distribution.dist).lower()
    return f"{name}-{version}-py3-none-any.whl"


def declared_wheels(components: ReleaseComponents, root: Path,
                    dist_dir: Path) -> list[Path]:
    """Where each declared distribution's wheel is expected in `dist_dir`, in order."""
    return [dist_dir / wheel_file_name(entry, project_version(root, entry))
            for entry in components.distributions]
