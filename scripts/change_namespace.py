#!/usr/bin/env python3
"""The names that keep one change's Helm validation apart from another's.

Each change's Helm validation runs in a namespace of its own, `validate-<change>`,
and deploys images built under tags of its own, the bare tag with `-<change>`
appended. A namespace is a DNS label of at most 63 characters, so a longer name is
cut and ends in a short hash of the whole, which keeps two long change names that
share a prefix apart.

The images reach the release through a values overlay that names the tag of every
image built here that `helm/values.yaml` sets, each with the suffix appended; a
third-party image keeps its tag, since no build writes it. `helm/tests/` holds the
overlay to every image the chart renders, so an image added later cannot deploy
under its bare tag, which another change's build may have written.

`change_namespace.py <change>` prints the namespace, as `helm/Makefile` derives it
from `CHANGE=`; `--image-overlay <path>` also writes the change's overlay there.
`--images` prints instead every image a change's validation build tags, which
`make -C helm teardown` removes.

Contract: openspec/specs/change-workflow/spec.md, "Each Helm validation is isolated
in its change's namespace".
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Sequence

ROOT = Path(__file__).resolve().parents[1]
HELM_VALUES = ROOT / "helm" / "values.yaml"
PREFIX = "validate-"
# A Kubernetes namespace is an RFC 1123 label.
LABEL_LIMIT = 63
HASH_LENGTH = 8
# The image name every image the build targets write carries.
BUILT_HERE = "arkhai"
# The bare tag of every image `make build-dev`, the build a change's validation
# runs, writes with the change's suffix. Teardown removes exactly these rather than
# every tag ending in the suffix, which would also take the images of a change
# whose name ends in this one's: `arkhai:storefront-bar-foo` is `bar-foo`'s
# storefront, not `foo`'s. A test holds the list to what the build writes.
BUILT_IMAGES = ("apicredits-sample-app", "apicredits-service", "apicredits-storefront",
                "bare-metal-storefront", "compute-provisioning", "dev-env", "e2e-tests",
                "registry", "storefront")
_CHANGE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
_KEY = re.compile(r"^(?P<indent> *)(?P<key>[A-Za-z0-9_.-]+):(?P<value>.*)$")


def _checked(change: str) -> str:
    if not _CHANGE.match(change):
        raise ValueError(f"{change!r} is not a change name: lowercase letters, digits, "
                         "and single hyphens between them")
    return change


def namespace(change: str) -> str:
    """The namespace a change's Helm validation deploys into."""
    name = PREFIX + _checked(change)
    if len(name) <= LABEL_LIMIT:
        return name
    digest = hashlib.sha256(name.encode("utf-8")).hexdigest()[:HASH_LENGTH]
    return name[:LABEL_LIMIT - HASH_LENGTH - 1].rstrip("-") + "-" + digest


def image_suffix(change: str) -> str:
    """What every image tag a change's build writes ends with."""
    return "-" + _checked(change)


def change_images(change: str) -> list[str]:
    """Every image a change's validation build tags, `arkhai:<tag>-<change>`."""
    suffix = image_suffix(change)
    return [f"{BUILT_HERE}:{tag}{suffix}" for tag in BUILT_IMAGES]


def image_tags(values: str) -> dict[tuple[str, ...], str]:
    """The tag of every image built here that a values file sets, by its path of keys.

    An image built here is a mapping with `name: arkhai` and a `tag`, as each chart
    names one; a third-party image keeps its own tag. The values file is read as
    the block mappings it is written in, which is all `helm/values.yaml` uses where
    it sets an image; block scalars are skipped, and a tag inside a list cannot be
    named by a path of keys, so one is refused rather than skipped.
    """
    mappings: dict[tuple[str, ...], dict[str, str]] = {}
    path: list[tuple[int, str]] = []
    scalar_indent: int | None = None
    for number, line in enumerate(values.splitlines(), 1):
        indent = len(line) - len(line.lstrip())
        if scalar_indent is not None:
            if not line.strip() or indent > scalar_indent:
                continue
            scalar_indent = None
        content = line.split(" #", 1)[0].rstrip()
        if not content.strip() or content.lstrip().startswith("#"):
            continue
        while path and path[-1][0] >= indent:
            path.pop()
        stripped = content.lstrip()
        if stripped.startswith("- "):
            # A list item: nothing under it is an image this overlay can name.
            path.append((indent, "[]"))
            item = _KEY.match(" " * (indent + 2) + stripped[2:])
            if item and item["key"] == "tag":
                raise ValueError(f"line {number}: an image tag inside a list")
            continue
        match = _KEY.match(content)
        if not match:
            continue
        key, value = match["key"], match["value"].strip()
        keys = tuple(name for _, name in path)
        if value.startswith(("|", ">")):
            scalar_indent = indent
        elif value:
            if key == "tag" and "[]" in keys:
                raise ValueError(f"line {number}: an image tag inside a list")
            mappings.setdefault(keys, {})[key] = value.strip("\"'")
        else:
            path.append((indent, key))
    return {keys + ("tag",): fields["tag"] for keys, fields in mappings.items()
            if "tag" in fields and fields.get("name") == BUILT_HERE}


def image_overlay(change: str, values: str) -> dict:
    """A values overlay naming every image tag `values` sets, with the change's suffix."""
    suffix = image_suffix(change)
    overlay: dict = {}
    for keys, tag in image_tags(values).items():
        node = overlay
        for key in keys[:-1]:
            node = node.setdefault(key, {})
        node[keys[-1]] = tag + suffix
    return overlay


def write_image_overlay(change: str, path: Path, values: Path = HELM_VALUES) -> Path:
    """Write the change's image overlay to `path`, as JSON, which Helm reads as YAML."""
    overlay = image_overlay(change, values.read_text("utf-8"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(overlay, indent=2, sort_keys=True) + "\n", "utf-8")
    return path


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("change")
    parser.add_argument("--image-overlay", type=Path, metavar="PATH",
                        help="also write the change's image overlay to PATH")
    parser.add_argument("--images", action="store_true",
                        help="print every image the change's validation build tags instead")
    args = parser.parse_args(argv)
    try:
        if args.images:
            print("\n".join(change_images(args.change)))
            return 0
        name = namespace(args.change)
        if args.image_overlay:
            write_image_overlay(args.change, args.image_overlay)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
