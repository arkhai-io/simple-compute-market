#!/usr/bin/env python3
"""Decide where CI gets the hosted client, from what the tree already states.

Two facts are already committed and already authoritative: the version this
repository pins, and the version the trust configuration names as signed. Their
relationship is the whole decision, so no third place states it -- a workflow
input or a repository variable would be the first thing to disagree with the
other two, and nothing would notice.

Equal means the pinned version is the released one: download its assets and
verify them. Different means the pin has moved ahead of the last signature, and
there is no release to verify -- so the wheel comes from the producer's
access-controlled index, carrying access control and nothing else.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_PIN = re.compile(r'arkhai-hosted-settlement-client==([0-9]+\.[0-9]+\.[0-9]+)')
#: The package this repository compiles the hosted consumer against; its
#: pyproject is where the version a run must obtain is stated.
_PINNING_PACKAGE = Path("kit/hosted-settlement/pyproject.toml")
_TRUST_CONFIGS = Path("manifests")


class ChannelUndecidable(RuntimeError):
    """The tree does not say which producer version to obtain."""


def pinned_version(root: Path = _REPO_ROOT) -> str:
    text = (root / _PINNING_PACKAGE).read_text(encoding="utf-8")
    found = sorted(set(_PIN.findall(text)))
    if len(found) != 1:
        raise ChannelUndecidable(
            f"{_PINNING_PACKAGE} states {len(found)} hosted client versions; "
            "exactly one is the version to obtain"
        )
    return found[0]


def trust_config(version: str, root: Path = _REPO_ROOT) -> Path | None:
    """The trust configuration for one version, when that version has one."""

    path = root / _TRUST_CONFIGS / f"hosted-settlement-v{version}-trust.json"
    return path if path.is_file() else None


def channel(root: Path = _REPO_ROOT, *, index_host: str = "") -> dict[str, str]:
    version = pinned_version(root)
    trust = trust_config(version, root)
    if trust is None:
        # Nothing signed this version, so there is nothing to verify and no
        # manifest to read the artifact names out of.
        return {
            "channel": "internal",
            "version": version,
            "wheel": f"arkhai_hosted_settlement_client-{version}-py3-none-any.whl",
            "index_host": index_host or _default_index_host(),
        }
    document = json.loads(trust.read_text(encoding="utf-8"))
    for field in ("repository", "release_version", "manifest_filename", "schema_version"):
        if not document.get(field):
            raise ChannelUndecidable(f"{trust.name} states no {field}")
    if str(document["release_version"]) != version:
        raise ChannelUndecidable(
            f"{trust.name} names release {document['release_version']} "
            f"while the consumer pins {version}"
        )
    return {
        "channel": "release",
        "version": version,
        "repository": str(document["repository"]),
        "manifest": str(document["manifest_filename"]),
        "wheel": str(document["client_wheel"]["filename"]),
        "schema_version": str(document["schema_version"]),
        "trust": str(trust.relative_to(root)),
    }


def _default_index_host() -> str:
    project = os.environ.get("AR_PROJECT", "compute-market-1-dev")
    location = os.environ.get("AR_LOCATION", "us-central1")
    prefix = os.environ.get("AR_PREFIX", project)
    return f"{location}-python.pkg.dev/{project}/{prefix}-python"


def main() -> int:
    try:
        selected = channel()
    except (ChannelUndecidable, OSError, ValueError) as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return 1
    for key, value in selected.items():
        print(f"{key}={value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
