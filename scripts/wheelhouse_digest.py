#!/usr/bin/env python3
"""Print the wheelhouse digest: the content digest of the declared wheels in `.dist`.

An image whose build installs wheels from the wheelhouse takes this digest as
its `WHEELHOUSE_DIGEST` build argument and records it as the label
`org.arkhai.wheelhouse-digest`. Loading a release candidate uploads nothing
unless every such image carries the digest of the wheelhouse it is storing, so
the stored wheels are the ones the validated images installed. The argument is
also each build's cache key: Podman can otherwise reuse cross-stage layers built
from an earlier wheelhouse.

The digest is `release_bom.files_digest` over the wheels
`manifests/release-components.json` declares, the dirhash the chart's content
digest uses. A declared wheel missing from the wheelhouse is refused, naming
`make dist`, rather than digesting a partial set.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from release_bom import files_digest
from release_components import DECLARATION_PATH, REPO_ROOT, DeclarationError, declared_wheels, load

LABEL = "org.arkhai.wheelhouse-digest"


class MissingWheels(ValueError):
    """A declared wheel is not in the wheelhouse."""


def wheelhouse_digest(root: Path = REPO_ROOT, dist_dir: Path | None = None) -> str:
    """The digest of the declared wheels in `dist_dir`, `.dist` by default."""
    dist_dir = dist_dir or root / ".dist"
    wheels = declared_wheels(load(root / DECLARATION_PATH), root, dist_dir)
    missing = [wheel.name for wheel in wheels if not wheel.is_file()]
    if missing:
        raise MissingWheels(f"{dist_dir} holds no wheel for {len(missing)} declared "
                            "distribution(s); build the wheelhouse with `make dist`: "
                            + ", ".join(missing))
    return files_digest(wheels)


def main(argv: list[str] | None = None, root: Path = REPO_ROOT) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dist-dir", type=Path, help="the wheelhouse (default: .dist)")
    arguments = parser.parse_args(argv)
    try:
        print(wheelhouse_digest(root, arguments.dist_dir))
    except (MissingWheels, DeclarationError) as error:
        print(f"wheelhouse_digest: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
