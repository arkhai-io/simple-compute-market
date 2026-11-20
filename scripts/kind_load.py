#!/usr/bin/env python3
"""Load the images a Helm validation built into a kind cluster's node.

Docker Desktop's cluster runs on the daemon that builds the images, so a release
finds them by tag; a kind node keeps its own containerd image store, which sees an
image only once it is loaded. Each image is saved under its fully qualified name,
`docker.io/library/arkhai:<tag>`, and loaded as an archive: the name a pod's
`arkhai:<tag>` resolves to in containerd. `kind load docker-image` is not
used because Podman stores an unqualified local build as `localhost/arkhai:<tag>`,
which kind would import under that name, so the release would pull instead and fail.

`kind_load.py <cluster> [--change <change>]` loads every image the change's
validation build tags, or the bare tags without a change. `kind` and `docker`
(or Podman's `docker` shim, with `KIND_EXPERIMENTAL_PROVIDER=podman`) come from
the owner's machine.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path

import change_namespace

QUALIFIED_PREFIX = "docker.io/library/"


def images(change: str | None) -> list[str]:
    """Every image the build tags: the change's suffixed tags, or the bare ones."""
    if change:
        return change_namespace.change_images(change)
    return [f"{change_namespace.BUILT_HERE}:{tag}" for tag in change_namespace.BUILT_IMAGES]


def load_commands(cluster: str, image: str, archive: Path) -> list[list[str]]:
    """The commands that load `image` into `cluster` through `archive`."""
    qualified = QUALIFIED_PREFIX + image
    return [["docker", "tag", image, qualified],
            ["docker", "save", "--output", str(archive), qualified],
            ["kind", "load", "image-archive", str(archive), "--name", cluster]]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("cluster", help="the kind cluster's name: its context without 'kind-'")
    parser.add_argument("--change", help="the change whose suffixed images to load")
    args = parser.parse_args(argv)
    with tempfile.TemporaryDirectory(prefix="kind-load-") as directory:
        archive = Path(directory) / "image.tar"
        for image in images(args.change):
            print(f"loading {image}", flush=True)
            for command in load_commands(args.cluster, image, archive):
                if subprocess.run(command, check=False).returncode != 0:
                    print(f"failed: {' '.join(command)}", file=sys.stderr)
                    return 1
            archive.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
