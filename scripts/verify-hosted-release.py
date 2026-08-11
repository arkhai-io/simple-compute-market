#!/usr/bin/env python3
"""Verify a staged hosted-settlement release without loading sibling source."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

_RELEASE_CONTRACT = "arkhai.hosted-settlement-release.v1"
_RELEASE_VERSION = "0.1.0"
_API_VERSION = "0.1.0"
_SCHEMA_VERSION = 3
_CAPABILITIES = (
    "conditional-escrow.v1",
    "stripe-connect-separate-charges-transfers.v1",
    "portable-attestation.v1",
    "eas-arbiter.v1",
)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_ADDRESS = re.compile(r"^0x[0-9a-f]{40}$")
_IMAGE_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")


class ReleaseVerificationError(RuntimeError):
    """The staged release does not match the checked-in trust contract."""


def _object(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ReleaseVerificationError(f"{field} must be an object")
    return value


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ReleaseVerificationError(f"trusted {field} is not pinned")
    return value


def _sha(value: Any, field: str) -> str:
    text = _text(value, field)
    if not _SHA256.fullmatch(text):
        raise ReleaseVerificationError(f"trusted {field} is not a lowercase SHA-256")
    return text


def _canonical_jcs(value: Any) -> bytes:
    def validate(item: Any) -> None:
        if item is None or isinstance(item, (str, bool, int)):
            return
        if isinstance(item, list):
            for child in item:
                validate(child)
            return
        if isinstance(item, dict) and all(isinstance(key, str) for key in item):
            for child in item.values():
                validate(child)
            return
        raise ReleaseVerificationError("manifest payload is outside the supported JCS value domain")

    validate(value)
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _equal(actual: Any, expected: Any, field: str) -> None:
    if actual != expected:
        raise ReleaseVerificationError(f"release {field} does not match the trusted pin")


def verify_release(
    *,
    trust_path: Path,
    manifest_path: Path,
    wheel_path: Path | None,
) -> dict[str, Any]:
    try:
        trust = _object(json.loads(trust_path.read_text()), "trust")
    except (OSError, json.JSONDecodeError) as exc:
        raise ReleaseVerificationError(f"cannot read release trust config: {exc}") from exc

    _equal(trust.get("contract_version"), _RELEASE_CONTRACT, "trust contract_version")
    _equal(trust.get("release_version"), _RELEASE_VERSION, "trust release_version")
    _equal(trust.get("api_version"), _API_VERSION, "trust api_version")
    _equal(trust.get("schema_version"), _SCHEMA_VERSION, "trust schema_version")
    _equal(tuple(trust.get("required_capabilities") or ()), _CAPABILITIES, "trust capabilities")
    manifest_filename = _text(trust.get("manifest_filename"), "manifest_filename")
    if manifest_path.name != manifest_filename:
        raise ReleaseVerificationError("staged manifest filename does not match the trusted pin")
    trusted_manifest_sha = _sha(trust.get("manifest_sha256"), "manifest_sha256")
    authority_id = _text(trust.get("authority_id"), "authority_id")
    authority_address = _text(trust.get("authority_address"), "authority_address")
    if not _ADDRESS.fullmatch(authority_address):
        raise ReleaseVerificationError("trusted authority_address is not a lowercase address")
    repository = _text(trust.get("repository"), "repository")
    workflow_ref = _text(trust.get("workflow_ref"), "workflow_ref")
    trusted_client = _object(trust.get("client_wheel"), "client_wheel")
    trusted_client_sha = _sha(trusted_client.get("sha256"), "client_wheel.sha256")
    trusted_image = _object(trust.get("service_image"), "service_image")
    image_reference = _text(trusted_image.get("reference"), "service_image.reference")
    image_digest = _text(trusted_image.get("digest"), "service_image.digest")
    if not _IMAGE_DIGEST.fullmatch(image_digest):
        raise ReleaseVerificationError("trusted service_image.digest is not sha256:<digest>")

    try:
        manifest_bytes = manifest_path.read_bytes()
        envelope = _object(json.loads(manifest_bytes), "manifest")
    except (OSError, json.JSONDecodeError) as exc:
        raise ReleaseVerificationError(f"cannot read staged release manifest: {exc}") from exc
    if hashlib.sha256(manifest_bytes).hexdigest() != trusted_manifest_sha:
        raise ReleaseVerificationError("staged release manifest hash does not match")
    if set(envelope) != {"payload", "authority_id", "authority_address", "signature"}:
        raise ReleaseVerificationError("release manifest envelope has unexpected fields")
    payload = _object(envelope.get("payload"), "manifest.payload")
    _equal(envelope.get("authority_id"), authority_id, "authority_id")
    _equal(envelope.get("authority_address"), authority_address, "authority_address")

    try:
        from eth_account import Account
        from eth_account.messages import encode_defunct
    except ImportError as exc:
        raise ReleaseVerificationError("eth-account is required to verify the release signer") from exc
    signature = _text(envelope.get("signature"), "manifest signature")
    try:
        recovered = Account.recover_message(
            encode_defunct(primitive=_canonical_jcs(payload)),
            signature=signature,
        ).lower()
    except Exception as exc:
        raise ReleaseVerificationError("release manifest signature is invalid") from exc
    if recovered != authority_address:
        raise ReleaseVerificationError("release manifest signer is not trusted")

    _equal(payload.get("contract_version"), _RELEASE_CONTRACT, "contract_version")
    _equal(payload.get("release_version"), _RELEASE_VERSION, "release_version")
    migrations = _object(payload.get("migrations"), "payload.migrations")
    _equal(migrations.get("schema_version"), _SCHEMA_VERSION, "migration schema_version")
    build = _object(payload.get("build"), "payload.build")
    _equal(build.get("repository"), repository, "build.repository")
    _equal(build.get("workflow_ref"), workflow_ref, "build.workflow_ref")
    source_commit = trust.get("source_commit")
    if source_commit:
        _equal(build.get("source_commit"), source_commit, "build.source_commit")

    client = _object(payload.get("client_wheel"), "payload.client_wheel")
    for field in ("filename", "distribution", "version"):
        _equal(client.get(field), trusted_client.get(field), f"client_wheel.{field}")
    _equal(client.get("sha256"), f"sha256:{trusted_client_sha}", "client_wheel.sha256")
    image = _object(payload.get("service_image"), "payload.service_image")
    _equal(image.get("reference"), image_reference, "service_image.reference")
    _equal(image.get("digest"), image_digest, "service_image.digest")

    expected_wheel = manifest_path.parent / str(trusted_client["filename"])
    staged_wheel = wheel_path or expected_wheel
    if staged_wheel.resolve() != expected_wheel.resolve():
        raise ReleaseVerificationError("client wheel must be staged beside the release manifest")
    try:
        wheel_sha = hashlib.sha256(staged_wheel.read_bytes()).hexdigest()
    except OSError as exc:
        raise ReleaseVerificationError(f"cannot read staged client wheel: {exc}") from exc
    if wheel_sha != trusted_client_sha:
        raise ReleaseVerificationError("staged client wheel hash does not match")
    return {
        "manifest_sha256": trusted_manifest_sha,
        "client_wheel_sha256": trusted_client_sha,
        "service_image_digest": image_digest,
        "api_version": _API_VERSION,
        "schema_version": _SCHEMA_VERSION,
        "capabilities": list(_CAPABILITIES),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trust", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--wheel", type=Path)
    args = parser.parse_args()
    try:
        result = verify_release(
            trust_path=args.trust,
            manifest_path=args.manifest,
            wheel_path=args.wheel,
        )
    except ReleaseVerificationError as exc:
        parser.error(str(exc))
    print(json.dumps(result, separators=(",", ":"), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
