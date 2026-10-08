#!/usr/bin/env python3
"""Publish every distribution in the manifest to a Python package registry.

Reads `manifests/published-distributions.json` -- the single declaration of
what this repository publishes -- and uploads the matching wheel from the
wheelhouse for each entry.

Replaces three wheels named literally in the Makefile. The literal list and the
workflow's own list disagreed in both directions: the workflow published
twenty-six distributions the registry never received, and the registry received
one the workflow never published. Neither list was wrong on its own terms;
there were simply two of them, and nothing made them agree.

Versions are read from each project's `pyproject.toml` rather than restated
here, for the same reason.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_MANIFEST = _REPO_ROOT / "manifests" / "published-distributions.json"
_VERSION = re.compile(r'^version = "([^"]+)"', re.MULTILINE)


def _distributions() -> list[dict[str, str]]:
    return json.loads(_MANIFEST.read_text(encoding="utf-8"))["distributions"]


def _version_of(project: Path) -> str:
    match = _VERSION.search((project / "pyproject.toml").read_text(encoding="utf-8"))
    if match is None:
        raise SystemExit(f"no version in {project}/pyproject.toml")
    return match.group(1)


def _wheel_for(dist: str, version: str, dist_dir: Path) -> Path:
    # Wheel filenames normalise '-' to '_' in the distribution name.
    name = f"{dist.replace('-', '_')}-{version}-py3-none-any.whl"
    return dist_dir / name


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist-dir", type=Path, required=True)
    parser.add_argument("--registry", required=True)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Resolve and report every wheel without uploading any.",
    )
    args = parser.parse_args()

    planned: list[tuple[str, Path]] = []
    missing: list[str] = []
    for entry in _distributions():
        version = _version_of(_REPO_ROOT / entry["path"])
        wheel = _wheel_for(entry["dist"], version, args.dist_dir)
        if wheel.is_file():
            planned.append((entry["dist"], wheel))
        else:
            missing.append(f"{entry['dist']}=={version} ({wheel.name})")

    # Resolve the whole set before uploading any of it. A partial push leaves
    # the registry holding some distributions of a build and not others, with
    # nothing recording which -- and the missing ones are found by whoever
    # installs next rather than by whoever pushed.
    if missing:
        print("ERROR: wheels absent from the wheelhouse. Run `make dist` first.")
        for name in missing:
            print(f"  {name}")
        return 1

    # Credentials reach the publisher through the environment, never through
    # an argument. A command line is readable by every process on the host, and
    # is reproduced verbatim in a CalledProcessError traceback -- so a failure
    # publishes the token to whatever captured the build log.
    #
    # UV_PUBLISH_TOKEN is cleared explicitly. The publisher refuses a token and
    # a username together, and anyone who has published to a public index from
    # this shell has that variable set, so leaving it inherited turns an
    # unrelated export into a failure on the first distribution.
    if args.dry_run:
        print(f"{len(planned)} distributions resolved")
        return 0

    env = dict(os.environ)
    env.pop("UV_PUBLISH_TOKEN", None)
    env["UV_PUBLISH_USERNAME"] = "oauth2accesstoken"
    env["UV_PUBLISH_PASSWORD"] = subprocess.run(
        ["gcloud", "auth", "print-access-token"],
        check=True, capture_output=True, text=True,
    ).stdout.strip()

    for dist, wheel in planned:
        print(f"  {dist} -> {args.registry}")
        result = subprocess.run(
            ["uv", "publish", "--publish-url", args.registry, str(wheel)],
            env=env,
        )
        if result.returncode != 0:
            # Reported rather than raised: an uncaught CalledProcessError prints
            # the arguments, and this one is invoked with a live credential in
            # its environment.
            print(f"ERROR: publishing {dist} failed with status {result.returncode}")
            return 1

    print(f"{len(planned)} distributions {'resolved' if args.dry_run else 'published'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
