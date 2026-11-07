"""A change's image overlay names every image the umbrella chart renders.

A change's Helm validation builds its images under tags ending in `-<change>` and
deploys them through the overlay `scripts/change_namespace.py` writes from the
image tags `helm/values.yaml` sets. An image the overlay missed would deploy under
its bare tag, which any build may have rewritten, so each test renders a release
validation can deploy, with the overlay, and asserts that every image built here
(named `arkhai`, with no repository) carries the change's tag. Third-party images
are not built here and keep their own tags. Standard library only.
"""

from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
import tempfile
from pathlib import Path

UMBRELLA = Path(__file__).resolve().parents[1]
SCRIPT = UMBRELLA.parent / "scripts" / "change_namespace.py"
_SPEC = importlib.util.spec_from_file_location("change_namespace", SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
change_namespace = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(change_namespace)

CHANGE = "image-overlay-probe"
SUFFIX = change_namespace.image_suffix(CHANGE)
BUILT_HERE = "arkhai"
LOCAL = (UMBRELLA / "values.yaml", UMBRELLA / "local-values.yaml")
BARE_METAL = (*LOCAL, UMBRELLA / "bare-metal-release-values.yaml")
_IMAGE = re.compile(r'^\s*image:\s*"?([^"\s]+)"?\s*$', re.MULTILINE)


def _render(values: tuple[Path, ...], *, overlay: bool, extra: tuple[str, ...] = ()) -> str:
    with tempfile.TemporaryDirectory() as work:
        command = ["helm", "template", "arkhai-node-operator", str(UMBRELLA)]
        for path in values:
            command += ["--values", str(path)]
        if overlay:
            written = change_namespace.write_image_overlay(CHANGE, Path(work) / "images.json")
            command += ["--values", str(written)]
        rendered = subprocess.run([*command, *extra], check=False, capture_output=True,
                                  text=True)
    assert rendered.returncode == 0, rendered.stderr
    return rendered.stdout


def _images(manifest: str, *, built_here: bool) -> list[tuple[str, str]]:
    images = []
    for reference in _IMAGE.findall(manifest):
        name, _, tag = reference.partition(":")
        if (name == BUILT_HERE) == built_here:
            images.append((reference, tag))
    return images


def _assert_overlaid(values: tuple[Path, ...], extra: tuple[str, ...] = ()) -> None:
    plain = _render(values, overlay=False, extra=extra)
    overlaid = _render(values, overlay=True, extra=extra)
    bare = sorted({tag for _, tag in _images(plain, built_here=True)})
    suffixed = _images(overlaid, built_here=True)

    assert bare, "the release renders no image built here"
    unsuffixed = sorted({reference for reference, tag in suffixed if not tag.endswith(SUFFIX)})
    assert not unsuffixed, f"images the overlay does not name: {unsuffixed}"
    assert sorted({tag for _, tag in suffixed}) == [tag + SUFFIX for tag in bare]
    assert _images(overlaid, built_here=False) == _images(plain, built_here=False)


def test_the_local_release_deploys_only_the_changes_images() -> None:
    _assert_overlaid(LOCAL)


def test_the_local_release_with_its_optional_registry_deploys_only_the_changes_images() -> None:
    _assert_overlaid(LOCAL, ("--set", "api-credits-registry.enabled=true"))


def test_the_bare_metal_release_deploys_only_the_changes_images() -> None:
    _assert_overlaid(BARE_METAL)


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
