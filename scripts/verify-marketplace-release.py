#!/usr/bin/env python3
"""Verify one attested marketplace consumer release manifest and its local artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

_CONTRACT = "arkhai.marketplace-release.v1"
_REPOSITORY = "arkhai-io/simple-compute-market"
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_WORKFLOW_REF = re.compile(r"^[A-Za-z0-9.][A-Za-z0-9._/@:-]{7,255}$")
_IMAGE_REFERENCE = re.compile(r"^[a-z0-9][a-z0-9._/-]{2,255}$")
_REQUIRED_ARTIFACTS = {
    "wheelhouse": "marketplace-wheelhouse.tar.gz",
    "settlement_config_schema": "settlement-config-schema.json",
    "provenance": "provenance.intoto.json",
}


class MarketplaceReleaseVerificationError(RuntimeError):
    """The attested marketplace artifact set is incomplete or mismatched."""


def _object(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise MarketplaceReleaseVerificationError(f"{field} must be an object")
    return value


def _exact_keys(value: dict[str, Any], expected: set[str], field: str) -> None:
    if set(value) != expected:
        raise MarketplaceReleaseVerificationError(f"{field} has unexpected or missing fields")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
    except OSError as exc:
        raise MarketplaceReleaseVerificationError(
            f"marketplace release artifact is unavailable: {path.name}"
        ) from exc
    return "sha256:" + digest.hexdigest()


def _artifact_path(release_dir: Path, filename: Any) -> Path:
    if not isinstance(filename, str) or not filename or Path(filename).name != filename:
        raise MarketplaceReleaseVerificationError("marketplace artifact filename is invalid")
    path = release_dir / filename
    if not path.is_file():
        raise MarketplaceReleaseVerificationError(
            f"marketplace release artifact is unavailable: {filename}"
        )
    return path


def verify_marketplace_release(
    *,
    manifest_path: Path,
    expected_manifest_sha256: str,
    expected_commit: str,
    expected_workflow_ref: str,
    expected_workflow_run_id: str,
    expected_image_digest: str,
) -> dict[str, Any]:
    """Verify exact consumer identities after repository attestation verification."""

    for digest in (expected_manifest_sha256, expected_image_digest):
        if not _DIGEST.fullmatch(digest):
            raise MarketplaceReleaseVerificationError(
                "marketplace release digest must be an exact sha256 identity"
            )
    if not _COMMIT.fullmatch(expected_commit):
        raise MarketplaceReleaseVerificationError("marketplace source commit is invalid")
    if not _WORKFLOW_REF.fullmatch(expected_workflow_ref):
        raise MarketplaceReleaseVerificationError("marketplace workflow reference is invalid")
    if not expected_workflow_run_id.isdigit():
        raise MarketplaceReleaseVerificationError("marketplace workflow run ID is invalid")
    if _sha256(manifest_path) != expected_manifest_sha256:
        raise MarketplaceReleaseVerificationError(
            "marketplace release manifest digest does not match the trusted identity"
        )
    try:
        manifest = _object(json.loads(manifest_path.read_text(encoding="utf-8")), "manifest")
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MarketplaceReleaseVerificationError(
            "marketplace release manifest is unreadable"
        ) from exc
    _exact_keys(
        manifest,
        {
            "contract",
            "repository",
            "source_commit",
            "workflow_ref",
            "workflow_run_id",
            "service_image",
            "artifacts",
        },
        "manifest",
    )
    if (
        manifest["contract"] != _CONTRACT
        or manifest["repository"] != _REPOSITORY
        or manifest["source_commit"] != expected_commit
        or manifest["workflow_ref"] != expected_workflow_ref
        or manifest["workflow_run_id"] != expected_workflow_run_id
    ):
        raise MarketplaceReleaseVerificationError(
            "marketplace repository, source, workflow, or run identity mismatched"
        )
    image = _object(manifest["service_image"], "service_image")
    _exact_keys(image, {"reference", "digest"}, "service_image")
    reference = image["reference"]
    digest = image["digest"]
    if (
        not isinstance(reference, str)
        or not _IMAGE_REFERENCE.fullmatch(reference)
        or digest != expected_image_digest
    ):
        raise MarketplaceReleaseVerificationError(
            "marketplace service image does not match the trusted digest"
        )
    artifacts = _object(manifest["artifacts"], "artifacts")
    _exact_keys(artifacts, set(_REQUIRED_ARTIFACTS), "artifacts")
    verified_artifacts: dict[str, dict[str, str]] = {}
    release_dir = manifest_path.resolve().parent
    for name, required_filename in _REQUIRED_ARTIFACTS.items():
        artifact = _object(artifacts[name], f"artifacts.{name}")
        _exact_keys(artifact, {"filename", "sha256"}, f"artifacts.{name}")
        if artifact["filename"] != required_filename or not isinstance(
            artifact["sha256"], str
        ) or not _DIGEST.fullmatch(artifact["sha256"]):
            raise MarketplaceReleaseVerificationError(
                f"marketplace {name} artifact identity is invalid"
            )
        path = _artifact_path(release_dir, artifact["filename"])
        if _sha256(path) != artifact["sha256"]:
            raise MarketplaceReleaseVerificationError(
                f"marketplace {name} artifact digest mismatched"
            )
        verified_artifacts[name] = {
            "filename": artifact["filename"],
            "sha256": artifact["sha256"],
        }
    return {
        "contract": _CONTRACT,
        "repository": _REPOSITORY,
        "source_commit": expected_commit,
        "workflow_ref": expected_workflow_ref,
        "workflow_run_id": expected_workflow_run_id,
        "manifest_sha256": expected_manifest_sha256,
        "service_image_reference": reference,
        "service_image_digest": digest,
        "artifacts": verified_artifacts,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--workflow-ref", required=True)
    parser.add_argument("--workflow-run-id", required=True)
    parser.add_argument("--image-digest", required=True)
    args = parser.parse_args()
    try:
        result = verify_marketplace_release(
            manifest_path=args.manifest,
            expected_manifest_sha256=args.manifest_sha256,
            expected_commit=args.source_commit,
            expected_workflow_ref=args.workflow_ref,
            expected_workflow_run_id=args.workflow_run_id,
            expected_image_digest=args.image_digest,
        )
    except MarketplaceReleaseVerificationError as exc:
        parser.error(str(exc))
    print(json.dumps(result, separators=(",", ":"), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
