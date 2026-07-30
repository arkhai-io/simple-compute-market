#!/usr/bin/env python3
"""Resolve Python review projects from an explicit scope, manifest, or Git diff."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Project:
    path: str
    package: str
    tests: tuple[str, ...]
    dist_targets: tuple[str, ...]
    verify_packages: tuple[str, ...] = ()


PROJECTS: dict[str, Project] = {
    "kit/site": Project("kit/site", "arkhai-kit-site", ("kit/site/tests",), ("dist-kits",)),
    "kit/resource-pools": Project(
        "kit/resource-pools",
        "arkhai-kit-resource-pools",
        ("kit/resource-pools/tests",),
        ("dist-kits",),
    ),
    "kit/fulfillment": Project(
        "kit/fulfillment",
        "arkhai-kit-fulfillment",
        ("kit/fulfillment/tests",),
        ("dist-kits",),
    ),
    "provisioning/compute/service": Project(
        "provisioning/compute/service",
        "arkhai-compute-provisioning-service",
        ("provisioning/compute/service/tests",),
        (
            "dist-compute-provisioning-service",
            "dist-storefront-client",
            "dist-core",
        ),
        (
            "arkhai-compute-provisioning-service",
            "arkhai-vms-provisioning-adapter",
            "arkhai-bare-metal-provisioning-adapter",
        ),
    ),
}

IMPACT_EXPANSION: dict[str, tuple[str, ...]] = {
    "kit/fulfillment": (
        "kit/site",
        "kit/resource-pools",
        "provisioning/compute/service",
    ),
}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--projects", nargs="*")
    parser.add_argument("--scope-file", type=Path)
    parser.add_argument("--base-ref", default="HEAD^")
    parser.add_argument("--format", choices=("json", "lines"), default="json")
    return parser.parse_args()


def _changed_files(root: Path, base_ref: str) -> list[str]:
    command = ["git", "diff", "--name-only", f"{base_ref}...HEAD"]
    result = subprocess.run(
        command,
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    return [line for line in result.stdout.splitlines() if line]


def _projects_for_files(files: list[str]) -> set[str]:
    selected: set[str] = set()
    roots = sorted(PROJECTS, key=len, reverse=True)
    for changed in files:
        for root in roots:
            if changed == root or changed.startswith(f"{root}/"):
                selected.add(root)
                break
    return selected


def _load_manifest(path: Path) -> set[str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    values = payload.get("validation_projects")
    if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
        raise ValueError("scope file must contain a string list named validation_projects")
    return set(values)


def _validate(projects: set[str]) -> None:
    unknown = sorted(projects - PROJECTS.keys())
    if unknown:
        raise ValueError(f"unsupported review projects: {', '.join(unknown)}")
    if not projects:
        raise ValueError("review scope resolved to no supported Python projects")


def main() -> int:
    args = _parse_args()
    root = args.root.resolve()
    changed_files: list[str] = []

    if args.projects:
        direct = set(args.projects)
        source = "explicit"
    elif args.scope_file:
        direct = _load_manifest(args.scope_file)
        source = "manifest"
    else:
        changed_files = _changed_files(root, args.base_ref)
        direct = _projects_for_files(changed_files)
        source = "git-diff"

    _validate(direct)
    expanded = set(direct)
    reasons: dict[str, str] = {}
    for project in sorted(direct):
        for impacted in IMPACT_EXPANSION.get(project, ()):
            if impacted not in expanded:
                reasons[impacted] = f"impact expansion from {project}"
            expanded.add(impacted)
    _validate(expanded)

    projects = [PROJECTS[name] for name in sorted(expanded)]
    payload = {
        "schema_version": 1,
        "source": source,
        "base_ref": args.base_ref if source == "git-diff" else None,
        "changed_files": changed_files,
        "direct_projects": sorted(direct),
        "validation_projects": [project.path for project in projects],
        "project_packages": {project.path: project.package for project in projects},
        "project_verify_packages": {
            project.path: list(project.verify_packages or (project.package,))
            for project in projects
        },
        "project_test_paths": {
            project.path: list(project.tests) for project in projects
        },
        "test_paths": sorted({path for project in projects for path in project.tests}),
        "dist_targets": sorted(
            {target for project in projects for target in project.dist_targets}
        ),
        "reasons": reasons,
    }
    if args.format == "lines":
        print("\n".join(payload["validation_projects"]))
    else:
        json.dump(payload, sys.stdout, indent=2)
        print()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, subprocess.CalledProcessError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
