"""The chart's default values name no release.

A chart's packaged files include its default values. Defaults naming a release's
images would make the chart packaged at a release's cut differ from the chart
validated, and would force a new chart version for every release, so a
deployment names its images in its own values and the defaults keep the bare
development tags with no digest. The tests refuse an image reference carrying a
semver-shaped tag, a revision-suffixed tag or a digest: in the umbrella chart
rendered with its default values, and in every chart's own `values.yaml`; a third
renders such references through `--set` to show each is found. Standard library
only.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

UMBRELLA = Path(__file__).resolve().parents[1]
_IMAGE = re.compile(r'^\s*image:\s*"?([^"\s]+)"?\s*$', re.MULTILINE)
_SEMVER = re.compile(r"(?:^|[-_.])v?\d+\.\d+\.\d+")
# A revision as `git rev-parse --short` abbreviates it, at any length, ending a tag.
_REVISION = re.compile(r"-[0-9a-f]{7,40}$")


def _render(chart: Path, *extra: str) -> str:
    rendered = subprocess.run(["helm", "template", "default-values-probe", str(chart), *extra],
                              check=False, capture_output=True, text=True)
    assert rendered.returncode == 0, rendered.stderr
    return rendered.stdout


def release_names(manifest: str) -> list[str]:
    """Each image reference in `manifest` that names a release: a digest, a
    semver-shaped tag, or a revision-suffixed tag."""
    found = []
    for reference in _IMAGE.findall(manifest):
        name, _, digest = reference.partition("@")
        tag = name.rpartition(":")[2] if ":" in name.rpartition("/")[2] else ""
        if digest or _SEMVER.search(tag) or _REVISION.search(tag):
            found.append(reference)
    return sorted(set(found))


def test_the_chart_renders_no_release_from_its_default_values() -> None:
    manifest = _render(UMBRELLA)

    assert _IMAGE.findall(manifest), "the chart renders no image from its defaults"
    assert not release_names(manifest), f"the defaults name a release: {release_names(manifest)}"


_VALUE = re.compile(r"^\s*(tag|digest|image):\s*['\"]?([^'\"\s#]*)", re.MULTILINE)


def test_no_default_values_file_names_a_release() -> None:
    """A subchart the defaults leave disabled renders nothing above, and a subchart
    renders only inside the umbrella, so every chart's own default values are read
    for the image tags and digests they set."""
    named = []
    files = [UMBRELLA / "values.yaml", *sorted((UMBRELLA / "charts").glob("*/values.yaml"))]
    for values in files:
        for key, value in _VALUE.findall(values.read_text(encoding="utf-8")):
            tag = value.rpartition(":")[2] if key == "image" and ":" in value else value
            if (key == "digest" and value) or "@sha256:" in value or (
                    key != "digest" and (_SEMVER.search(tag) or _REVISION.search(tag))):
                named.append(f"{values.relative_to(UMBRELLA)}: {key}: {value}")
    assert len(files) > 1
    assert not named, "default values naming a release: " + ", ".join(named)


def test_a_release_named_by_a_value_is_found() -> None:
    for value, reference in (("registry-0123456ab", "arkhai:registry-0123456ab"),
                             ("registry-0.3.0", "arkhai:registry-0.3.0")):
        manifest = _render(UMBRELLA, "--set", f"registry.image.tag={value}")
        assert reference in release_names(manifest), value
    manifest = _render(UMBRELLA, "--set", "registry.image.digest=sha256:" + "0" * 64)
    assert any("@sha256:" in reference for reference in release_names(manifest))


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
