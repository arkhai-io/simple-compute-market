#!/usr/bin/env python3
"""Canonical package manifest for installer and release artifacts."""

from __future__ import annotations

import json
from typing import Any


MANIFEST_VERSION = "2026-03-23"

INSTALLED_LAYOUT = {
    "repo_root": "~/.market",
    "market_binary": "~/.local/bin/market",
    "runtime_venv": "core/.venv",
}

SUPPORTED_INSTALLED_ENTRYPOINTS = ["~/.local/bin/market"]

INCLUDED_TOP_LEVEL_PATHS = [
    "README.md",
    "cli",
    "core",
    "service",
    "async-provisioning-service",
    "erc-8004-contracts",
    "erc-8004-registry-py",
    "domain",
    "docs",
    "scripts",
    "install.sh",
]

TAR_EXCLUDE_PATTERNS = [
    ".git",
    ".github",
    "mcp",
    "tmp",
    "__pycache__",
    "*.pyc",
    "*.pyo",
    ".venv",
    "node_modules",
    ".env",
    ".env.tmp",
    "*.egg-info",
    ".claude",
    "docker-compose*.yml",
    "market-installer.sh",
    ".DS_Store",
    "*.pt",
    "experiments",
]


def manifest_snapshot() -> dict[str, Any]:
    """Return the canonical package manifest as a machine-readable mapping."""

    return {
        "version": MANIFEST_VERSION,
        "installed_layout": INSTALLED_LAYOUT,
        "supported_installed_entrypoints": SUPPORTED_INSTALLED_ENTRYPOINTS,
        "included_top_level_paths": INCLUDED_TOP_LEVEL_PATHS,
        "tar_exclude_patterns": TAR_EXCLUDE_PATTERNS,
    }


def main() -> int:
    print(json.dumps(manifest_snapshot(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
