#!/usr/bin/env python3
"""Push declared artifacts to an explicitly selected Artifact Registry.

What is pushed comes from `manifests/release-components.json`, read through
`release_components`: a publish target names no image, chart or binary itself
(`scripts/check_release_components.py` refuses one that does).

- **Images.** Each declared image, or each development image, is pushed from the
  revision tag its build writes, `arkhai:<local>-<revision>`, as
  `arkhai:<name>-<revision>` and as its bare `arkhai:<name>`, which shared
  development releases follow.
- **Chart.** The package `make dist-helm` writes for the declared chart,
  `<name>-<version>.tgz` as its `Chart.yaml` gives them.
- **Binaries.** Each declared binary, as the generic package of its name, version
  `<revision>`, in `<prefix>-cli`.

The registries the Makefile derives from its `AR_*` settings are passed in
whole; the generic repositories are named here from the prefix, since each
upload names its repository apart from the project and location.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

from release_components import (
    DECLARATION_PATH,
    REPO_ROOT,
    Binary,
    DeclarationError,
    Image,
    ReleaseComponents,
    chart_field,
    load,
)

Run = Callable[..., subprocess.CompletedProcess]


@dataclass(frozen=True)
class Destination:
    """An Artifact Registry project, location and repository prefix."""

    project: str
    location: str
    prefix: str

    def repository(self, kind: str) -> str:
        """A repository by its kind, such as `cli` for `<prefix>-cli`."""
        return f"{self.prefix}-{kind}"

    def flags(self, repository: str) -> list[str]:
        return [f"--project={self.project}", f"--location={self.location}",
                f"--repository={repository}"]


def push_image(registry: str, image: Image, suffix: str, run: Run = subprocess.run) -> None:
    """Tag `image`'s revision tag with both its pushed names, then push both."""
    source = f"arkhai:{image.local}-{suffix}"
    tags = [f"{registry}/arkhai:{image.name}-{suffix}", f"{registry}/arkhai:{image.name}"]
    for tag in tags:
        run(["docker", "tag", source, tag], check=True)
    for tag in tags:
        run(["docker", "push", tag], check=True)


def push_images(registry: str, images: Iterable[Image], suffix: str,
                run: Run = subprocess.run) -> None:
    for image in images:
        push_image(registry, image, suffix, run)


def chart_package(components: ReleaseComponents, dist_dir: Path,
                  root: Path = REPO_ROOT) -> Path:
    """Where `helm package` writes the declared chart in `dist_dir`."""
    chart_yaml = root / components.chart.path / "Chart.yaml"
    text = chart_yaml.read_text(encoding="utf-8")
    name, version = chart_field(text, "name"), chart_field(text, "version")
    if not name or not version:
        raise DeclarationError(f"{chart_yaml} declares no name or no version")
    return dist_dir / f"{name}-{version}.tgz"


def push_chart(registry: str, package: Path, run: Run = subprocess.run) -> None:
    run(["helm", "push", str(package), registry], check=True)


def upload_generic(destination: Destination, repository: str, package: str, version: str,
                   source: Path, run: Run = subprocess.run) -> None:
    """Add one file to a generic package version. The upload refuses a file the
    version already holds, so it never replaces one."""
    run(["gcloud", "artifacts", "generic", "upload", *destination.flags(repository),
         f"--package={package}", f"--version={version}", f"--source={source}"], check=True)


def upload_binaries(destination: Destination, binaries: Iterable[Binary], suffix: str,
                    root: Path = REPO_ROOT, run: Run = subprocess.run) -> None:
    for binary in binaries:
        upload_generic(destination, destination.repository("cli"), binary.name, suffix,
                       root / binary.path, run)


def main(argv: list[str] | None = None, run: Run = subprocess.run,
         root: Path = REPO_ROOT) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    for name in ("project", "location", "prefix"):
        parser.add_argument(f"--{name}", required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("check", help="refuse an empty destination, and do nothing else")
    images = commands.add_parser("images", help="push the declared images")
    images.add_argument("--registry", required=True)
    images.add_argument("--suffix", required=True)
    images.add_argument("--development", action="store_true",
                        help="push the declared development images instead")
    chart = commands.add_parser("chart", help="push the declared chart's package")
    chart.add_argument("--registry", required=True)
    chart.add_argument("--dist-dir", required=True, type=Path)
    binaries = commands.add_parser("binaries", help="upload the declared binaries")
    binaries.add_argument("--suffix", required=True)
    args = parser.parse_args(argv)
    for name in ("project", "location", "prefix"):
        if not getattr(args, name).strip():
            parser.error(f"AR_{name.upper()} is required")
    if args.command == "check":
        return 0
    try:
        components = load(root / DECLARATION_PATH)
        if args.command == "images":
            push_images(args.registry, components.development_images if args.development
                        else components.images, args.suffix, run)
        elif args.command == "chart":
            push_chart(args.registry, chart_package(components, args.dist_dir, root), run)
        elif args.command == "binaries":
            upload_binaries(Destination(args.project, args.location, args.prefix),
                            components.binaries, args.suffix, root, run)
    except DeclarationError as error:
        print(f"publish_artifacts: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
