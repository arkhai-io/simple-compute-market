#!/usr/bin/env python3
"""Publish every declared distribution to a Python package registry.

Reads the distributions from `manifests/release-components.json` through
`release_components`, and uploads each one's wheel from the wheelhouse, in
declaration order, which is dependency order. Each version is read from the
distribution's own `pyproject.toml` rather than restated here.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

from release_components import REPO_ROOT, load, project_version, wheel_file_name


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
    for entry in load().distributions:
        version = project_version(REPO_ROOT, entry)
        wheel = args.dist_dir / wheel_file_name(entry, version)
        if wheel.is_file():
            planned.append((entry.dist, wheel))
        else:
            missing.append(f"{entry.dist}=={version} ({wheel.name})")

    # Resolve the whole set before uploading any of it. A partial push leaves
    # the registry holding some distributions of a build and not others, with
    # nothing recording which -- and the missing ones are found by whoever
    # installs next rather than by whoever pushed.
    if missing:
        print("ERROR: wheels absent from the wheelhouse. Run `make dist` first.")
        for name in missing:
            print(f"  {name}")
        return 1

    if args.dry_run:
        print(f"{len(planned)} distributions resolved")
        return 0

    # Credentials reach the publisher through the environment, never through
    # an argument. A command line is readable by every process on the host, and
    # is reproduced verbatim in a CalledProcessError traceback -- so a failure
    # publishes the token to whatever captured the build log.
    #
    # UV_PUBLISH_TOKEN is cleared explicitly. The publisher refuses a token and
    # a username together, and anyone who has published to a public index from
    # this shell has that variable set, so leaving it inherited turns an
    # unrelated export into a failure on the first distribution.
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

    print(f"{len(planned)} distributions published")
    return 0


if __name__ == "__main__":
    sys.exit(main())
