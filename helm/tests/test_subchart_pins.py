"""Each of the umbrella chart's dependency entries names its subchart's own version.

The umbrella pins every subchart by exact version over `file://charts/<dir>`, and
`make dist-helm` runs a bare `helm package`, which is not shown to refuse a pin
that disagrees with the subchart beside it. A subchart whose version moved
without its entry, or an entry moved without its subchart, would package a chart
whose dependencies say one thing and whose files hold another, so each entry is
held to its subchart's `Chart.yaml` here. Standard library only.
"""

from __future__ import annotations

import re
import sys
import tempfile
from pathlib import Path

UMBRELLA = Path(__file__).resolve().parents[1]
_FILE_REPOSITORY = "file://"


def _scalar(text: str, field: str) -> str | None:
    match = re.search(rf"^{re.escape(field)}:\s*['\"]?([^'\"\s#]+)", text, re.MULTILINE)
    return match.group(1) if match else None


def dependencies(chart_yaml: str) -> list[dict[str, str]]:
    """Each entry of a `Chart.yaml`'s top-level `dependencies:` list, as its
    scalar fields."""
    entries: list[dict[str, str]] = []
    inside = False
    for line in chart_yaml.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if not line.startswith(" ") and not line.startswith("-"):
            inside = line.startswith("dependencies:")
            continue
        if not inside:
            continue
        item = re.match(r"^\s*-\s+(.*)$", line)
        if item:
            entries.append({})
            line = item.group(1)
        field = re.match(r"^\s*([A-Za-z][A-Za-z0-9_-]*):\s*['\"]?([^'\"#]*?)['\"]?\s*$", line)
        if field and entries:
            entries[-1][field.group(1)] = field.group(2)
    return entries


def pin_mismatches(umbrella: Path = UMBRELLA) -> list[str]:
    """Each dependency entry whose `version` is not its subchart's own."""
    problems: list[str] = []
    for entry in dependencies((umbrella / "Chart.yaml").read_text(encoding="utf-8")):
        label = entry.get("alias") or entry.get("name", "?")
        repository = entry.get("repository", "")
        if not repository.startswith(_FILE_REPOSITORY):
            problems.append(f"dependency {label} is not a local subchart: {repository!r}")
            continue
        chart_yaml = umbrella / repository.removeprefix(_FILE_REPOSITORY) / "Chart.yaml"
        if not chart_yaml.is_file():
            problems.append(f"dependency {label} names {repository}, which holds no Chart.yaml")
            continue
        own = _scalar(chart_yaml.read_text(encoding="utf-8"), "version")
        if entry.get("version") != own:
            problems.append(f"dependency {label} pins subchart {entry.get('name')} at "
                            f"{entry.get('version')}; {chart_yaml.relative_to(umbrella)} "
                            f"is version {own}")
    return problems


def test_every_dependency_entry_names_its_subcharts_own_version() -> None:
    entries = dependencies((UMBRELLA / "Chart.yaml").read_text(encoding="utf-8"))
    assert len(entries) == len({entry.get("alias") or entry["name"] for entry in entries}), (
        "two dependency entries share a name and no alias")
    assert entries, "the umbrella chart declares no dependencies"
    mismatches = pin_mismatches()
    assert not mismatches, "\n".join(mismatches)


def test_a_mismatched_pin_is_named() -> None:
    chart = """\
name: umbrella
version: 1.0.0
dependencies:
  - name: registry
    alias: api-credits-registry
    version: "0.1.0"
    repository: "file://charts/registry"
  - name: storefront
    version: "0.4.0"
    repository: "file://charts/storefront"
"""
    with tempfile.TemporaryDirectory() as work:
        root = Path(work)
        (root / "Chart.yaml").write_text(chart, encoding="utf-8")
        for name, version in (("registry", "0.1.0"), ("storefront", "0.4.1")):
            (root / "charts" / name).mkdir(parents=True)
            (root / "charts" / name / "Chart.yaml").write_text(
                f"name: {name}\nversion: {version}\n", encoding="utf-8")
        assert pin_mismatches(root) == [
            "dependency storefront pins subchart storefront at 0.4.0; "
            "charts/storefront/Chart.yaml is version 0.4.1"]


def main() -> int:
    failures = 0
    for name, test in sorted(globals().items()):
        if name.startswith("test_") and callable(test):
            try:
                test()
                print(f"ok    {name}")
            except Exception as exc:  # noqa: BLE001 - every error is a failed test
                failures += 1
                print(f"FAIL  {name}: {type(exc).__name__}: {exc}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
