#!/usr/bin/env python3
"""Build the canonical installer/release tarball from the package manifest."""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

from package_manifest import INCLUDED_TOP_LEVEL_PATHS, TAR_EXCLUDE_PATTERNS


ROOT = Path(__file__).resolve().parents[1]
ARCHIVE_PREFIX = "market-cli"


def build_tarball(output: Path, prefix: str = ARCHIVE_PREFIX) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)

    cmd = ["tar", "czf", str(output)]
    cmd.extend(f"--exclude={pattern}" for pattern in TAR_EXCLUDE_PATTERNS)
    cmd.extend(["-C", str(ROOT), "--transform", f"s,^,{prefix}/,"])
    cmd.extend(INCLUDED_TOP_LEVEL_PATHS)

    subprocess.run(cmd, check=True, cwd=ROOT)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, help="Path to the output tarball")
    parser.add_argument(
        "--prefix",
        default=ARCHIVE_PREFIX,
        help="Top-level directory prefix inside the tarball",
    )
    args = parser.parse_args()

    build_tarball(Path(args.output).resolve(), prefix=args.prefix)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
