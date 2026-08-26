#!/usr/bin/env python3
"""Verify immutable hosted production release inputs."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

_RELEASE_CONTRACT = "arkhai.hosted-settlement-release.v2"
#: Artifacts whose filename carries no version, so no release names them
#: differently. The versioned three are derived from the contract instead.
_UNVERSIONED_ARTIFACT_FILENAMES = {
    "sbom": "sbom.spdx.json",
    "provenance": "provenance.intoto.json",
}


class ReleaseContract:
    """What one hosted release serves, taken from the trust config that pins it.

    These used to be literals here. A literal cannot admit the next release
    without an edit, and cannot report a mismatch as a mismatch -- it reports
    it as "not the release this verifier was written for". The committed trust
    config already names every one of them and is the pin that decides which
    release is trusted, so it is the one place they belong.
    """

    def __init__(self, trust: dict[str, Any]) -> None:
        self.release_version = _text(trust.get("release_version"), "release_version")
        self.api_version = _text(trust.get("api_version"), "api_version")
        schema_version = trust.get("schema_version")
        if not isinstance(schema_version, int) or schema_version < 1:
            raise ReleaseVerificationError("trust schema_version must be a positive integer")
        self.schema_version = schema_version
        self.capabilities = tuple(
            _text(value, "required_capabilities entry")
            for value in (trust.get("required_capabilities") or ())
        )
        if not self.capabilities:
            raise ReleaseVerificationError("trust required_capabilities must not be empty")
        self.identity_contract = _object(
            trust.get("identity_contract"), "identity_contract"
        )
        _equal(
            self.identity_contract.get("capabilities"),
            list(self.capabilities),
            "identity_contract capabilities",
        )
        self.funding_profiles = tuple(
            _text(value, "identity_contract funding_profiles entry")
            for value in (self.identity_contract.get("funding_profiles") or ())
        )
        if not self.funding_profiles:
            raise ReleaseVerificationError(
                "trust identity_contract must name the profiles the release funds"
            )
        self.artifact_filenames = {
            "openapi": f"openapi-v{self.release_version}.json",
            "conformance": f"conformance-v{self.release_version}.json",
            "migrations": f"migrations-v{self.schema_version}.json",
            **_UNVERSIONED_ARTIFACT_FILENAMES,
        }


_REQUIRED_CLIENT_EXPORTS = frozenset(
    {
        "CreatePayerProfileRequest",
        "FundingAuthorizationRequest",
        "FundingAuthorizationResult",
        "FundingProfile",
        "FundingProfileReadiness",
        "HostedSettlementAsyncClient",
        "HostedSettlementClient",
        "InstrumentListResult",
        "PayerAction",
        "PayerProfileResult",
        "PayerSetupRequest",
        "PayerSetupResult",
        "Signer",
    }
)
_FORBIDDEN_CLIENT_IMPLEMENTATION_PARTS = frozenset(
    {
        "authority",
        "database",
        "migrations",
        "providers",
        "recovery",
        "storage",
        "webhook",
        "webhooks",
    }
)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_ADDRESS = re.compile(r"^0x[0-9a-f]{40}$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_FORBIDDEN_RELEASE_TOKENS = (
    "e2e",
    "fixture",
    "simulator",
    "control",
    "clock",
    "event-worker",
)


class ReleaseVerificationError(RuntimeError):
    """The staged release does not match its trusted immutable identity."""


def _object(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ReleaseVerificationError(f"{field} must be an object")
    return value


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ReleaseVerificationError(f"trusted {field} is not pinned")
    return value


def _sha(value: Any, field: str) -> str:
    text = _text(value, field).removeprefix("sha256:")
    if not _SHA256.fullmatch(text):
        raise ReleaseVerificationError(f"trusted {field} is not a lowercase SHA-256")
    return text


def _digest(value: Any, field: str) -> str:
    text = _text(value, field)
    if not _DIGEST.fullmatch(text):
        raise ReleaseVerificationError(f"trusted {field} is not sha256:<digest>")
    return text


def _equal(actual: Any, expected: Any, field: str) -> None:
    if actual != expected:
        raise ReleaseVerificationError(
            f"release {field} does not match the trusted pin"
        )


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
        raise ReleaseVerificationError(
            "manifest payload is outside the supported JCS value domain"
        )

    validate(value)
    return json.dumps(
        value, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")


def _read_json(path: Path, field: str) -> tuple[bytes, dict[str, Any]]:
    try:
        raw = path.read_bytes()
        return raw, _object(json.loads(raw), field)
    except (OSError, json.JSONDecodeError) as exc:
        raise ReleaseVerificationError(f"cannot read {field}: {exc}") from exc


def _verify_signature(
    envelope: dict[str, Any], *, authority_id: str, authority_address: str, label: str
) -> dict[str, Any]:
    if set(envelope) != {
        "payload",
        "signature_scheme",
        "authority_id",
        "authority_address",
        "signature",
    }:
        raise ReleaseVerificationError(
            f"{label} manifest envelope has unexpected fields"
        )
    _equal(envelope.get("signature_scheme"), "eip191", f"{label} signature_scheme")
    _equal(envelope.get("authority_id"), authority_id, f"{label} authority_id")
    _equal(
        envelope.get("authority_address"),
        authority_address,
        f"{label} authority_address",
    )
    payload = _object(envelope.get("payload"), f"{label}.payload")
    try:
        from eth_account import Account
        from eth_account.messages import encode_defunct
    except ImportError as exc:
        raise ReleaseVerificationError(
            "eth-account is required to verify the release signer"
        ) from exc
    try:
        recovered = Account.recover_message(
            encode_defunct(primitive=_canonical_jcs(payload)),
            signature=_text(envelope.get("signature"), f"{label} signature"),
        ).lower()
    except Exception as exc:
        raise ReleaseVerificationError(
            f"{label} manifest signature is invalid"
        ) from exc
    if recovered != authority_address:
        raise ReleaseVerificationError(f"{label} manifest signer is not trusted")
    return payload


def _wheel_metadata(path: Path, field: str) -> tuple[str, str]:
    try:
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            metadata_names = [
                name for name in names if name.endswith(".dist-info/METADATA")
            ]
            entry_points = [
                name for name in names if name.endswith(".dist-info/entry_points.txt")
            ]
            if len(metadata_names) != 1:
                raise ReleaseVerificationError(
                    f"staged {field} wheel must contain exactly one METADATA file"
                )
            metadata = archive.read(metadata_names[0]).decode("utf-8")
    except (OSError, UnicodeDecodeError, zipfile.BadZipFile) as exc:
        raise ReleaseVerificationError(
            f"staged {field} wheel is not a readable wheel archive: {exc}"
        ) from exc
    if field == "client" and entry_points:
        raise ReleaseVerificationError(
            "staged client wheel must not contain console-script entry-point metadata"
        )
    fields: dict[str, str] = {}
    for line in metadata.splitlines():
        if ":" in line:
            name, value = line.split(":", 1)
            fields.setdefault(name.lower(), value.strip())
    try:
        return fields["name"], fields["version"]
    except KeyError as exc:
        raise ReleaseVerificationError(
            f"staged {field} wheel metadata is incomplete"
        ) from exc


def _verify_client_boundary(path: Path) -> None:
    try:
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            lowered = tuple(name.lower() for name in names)
            if any(
                "hosted_settlement_service" in name
                or name.startswith("stripe/")
                or "/stripe/" in name
                for name in lowered
            ):
                raise ReleaseVerificationError(
                    "staged client wheel contains service/provider implementation"
                )
            client_paths = (
                PurePosixPath(name)
                for name in lowered
                if name.startswith("hosted_settlement_client/")
            )
            if any(
                any(
                    PurePosixPath(part).stem in _FORBIDDEN_CLIENT_IMPLEMENTATION_PARTS
                    for part in client_path.parts[1:]
                )
                for client_path in client_paths
            ):
                raise ReleaseVerificationError(
                    "staged client wheel contains service/provider implementation"
                )
            source_names = [
                name
                for name in names
                if name.startswith("hosted_settlement_client/") and name.endswith(".py")
            ]
            imports: set[str] = set()
            exports: set[str] = set()
            for name in source_names:
                tree = ast.parse(archive.read(name).decode("utf-8"), filename=name)
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        imports.update(
                            alias.name.split(".", 1)[0] for alias in node.names
                        )
                    elif isinstance(node, ast.ImportFrom) and node.module:
                        imports.add(node.module.split(".", 1)[0])
                if name == "hosted_settlement_client/__init__.py":
                    for node in tree.body:
                        if isinstance(node, ast.Assign) and any(
                            isinstance(target, ast.Name) and target.id == "__all__"
                            for target in node.targets
                        ):
                            exports.update(ast.literal_eval(node.value))
            if imports.intersection({"hosted_settlement_service", "stripe"}):
                raise ReleaseVerificationError(
                    "staged client wheel imports hosted service/provider modules"
                )
            missing = sorted(_REQUIRED_CLIENT_EXPORTS - exports)
            if missing:
                raise ReleaseVerificationError(
                    "staged client wheel is missing expanded public exports: "
                    + ", ".join(missing)
                )
    except (
        OSError,
        UnicodeDecodeError,
        SyntaxError,
        ValueError,
        zipfile.BadZipFile,
    ) as exc:
        raise ReleaseVerificationError(
            f"staged client wheel boundary is unreadable: {exc}"
        ) from exc


def _verify_wheel(
    path: Path,
    descriptor: dict[str, Any],
    *,
    field: str,
    expected_distribution: str | None = None,
    expected_version: str | None = None,
) -> str:
    filename = _text(descriptor.get("filename"), f"{field}.filename")
    if path.name != filename:
        raise ReleaseVerificationError(f"staged {field} wheel filename does not match")
    expected_sha = _sha(descriptor.get("sha256"), f"{field}.sha256")
    try:
        actual_sha = hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise ReleaseVerificationError(
            f"cannot read staged {field} wheel: {exc}"
        ) from exc
    if actual_sha != expected_sha:
        raise ReleaseVerificationError(f"staged {field} wheel hash does not match")
    distribution, version = _wheel_metadata(path, field)
    wanted_distribution = expected_distribution or _text(
        descriptor.get("distribution"), f"{field}.distribution"
    )
    wanted_version = expected_version or _text(
        descriptor.get("version"), f"{field}.version"
    )
    if (distribution, version) != (wanted_distribution, wanted_version):
        raise ReleaseVerificationError(f"staged {field} wheel metadata does not match")
    if field == "client":
        _verify_client_boundary(path)
    return expected_sha


def _verify_file(root: Path, descriptor: dict[str, Any], field: str) -> Path:
    filename = _text(descriptor.get("filename"), f"{field}.filename")
    if Path(filename).name != filename:
        raise ReleaseVerificationError(f"{field}.filename must be a basename")
    path = root / filename
    expected = _sha(descriptor.get("sha256"), f"{field}.sha256")
    try:
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise ReleaseVerificationError(
            f"cannot read staged {field} artifact: {exc}"
        ) from exc
    if actual != expected:
        raise ReleaseVerificationError(f"staged {field} artifact hash does not match")
    return path


def _verify_contract_artifacts(
    paths: dict[str, Path], contract: ReleaseContract
) -> None:
    _, openapi = _read_json(paths["openapi"], "staged OpenAPI")
    info = _object(openapi.get("info"), "openapi.info")
    _equal(info.get("version"), contract.api_version, "OpenAPI version")

    _, conformance = _read_json(paths["conformance"], "staged conformance")
    _equal(
        conformance.get("api_version"), contract.api_version, "conformance api_version"
    )
    _equal(
        conformance.get("schema_version"),
        contract.schema_version,
        "conformance schema_version",
    )
    _equal(
        tuple(conformance.get("funding_profiles") or ()),
        contract.funding_profiles,
        "conformance funding_profiles",
    )
    _equal(
        conformance.get("identity_contract"),
        contract.identity_contract,
        "conformance identity_contract",
    )

    _, migrations = _read_json(paths["migrations"], "staged migrations")
    _equal(
        migrations.get("schema_version"),
        contract.schema_version,
        "migration artifact schema_version",
    )
    migration_rows = migrations.get("migrations")
    if not isinstance(migration_rows, list):
        raise ReleaseVerificationError("migration artifact migrations must be a list")
    positions = [row.get("position") for row in migration_rows if isinstance(row, dict)]
    if positions != list(range(1, contract.schema_version + 1)):
        raise ReleaseVerificationError(
            "migration artifact must contain the exact ordered schema history"
        )
    # Which migration the history ends at is fixed by hash, not by name here:
    # the trust config pins the manifest, the manifest pins this artifact's
    # sha256, and the staged bytes were checked against it before this ran.


def _verify_image(image: dict[str, Any], field: str) -> tuple[str, str]:
    reference = _text(image.get("reference"), f"{field}.reference")
    digest = _digest(image.get("digest"), f"{field}.digest")
    final_component = reference.rsplit("/", 1)[-1]
    if "@" in reference or ":" in final_component:
        raise ReleaseVerificationError(
            f"{field}.reference must not contain a floating tag or embedded digest"
        )
    return reference, digest


def verify_release(
    *,
    trust_path: Path,
    manifest_path: Path,
    wheel_path: Path | None,
) -> dict[str, Any]:
    _, trust = _read_json(trust_path, "release trust config")
    _equal(trust.get("contract_version"), _RELEASE_CONTRACT, "trust contract_version")
    contract = ReleaseContract(trust)
    if manifest_path.name != _text(trust.get("manifest_filename"), "manifest_filename"):
        raise ReleaseVerificationError(
            "staged manifest filename does not match the trusted pin"
        )
    trusted_manifest_sha = _sha(trust.get("manifest_sha256"), "manifest_sha256")
    authority_id = _text(trust.get("authority_id"), "authority_id")
    authority_address = _text(trust.get("authority_address"), "authority_address")
    if not _ADDRESS.fullmatch(authority_address):
        raise ReleaseVerificationError(
            "trusted authority_address is not a lowercase address"
        )
    repository = _text(trust.get("repository"), "repository")
    workflow_ref = _text(trust.get("workflow_ref"), "workflow_ref")
    source_commit = _text(trust.get("source_commit"), "source_commit")
    if not _COMMIT.fullmatch(source_commit):
        raise ReleaseVerificationError(
            "trusted source_commit is not a full lowercase commit"
        )

    manifest_bytes, envelope = _read_json(manifest_path, "staged release manifest")
    if hashlib.sha256(manifest_bytes).hexdigest() != trusted_manifest_sha:
        raise ReleaseVerificationError("staged release manifest hash does not match")
    payload = _verify_signature(
        envelope,
        authority_id=authority_id,
        authority_address=authority_address,
        label="production",
    )
    _equal(payload.get("contract_version"), _RELEASE_CONTRACT, "contract_version")
    _equal(
        payload.get("release_version"), contract.release_version, "release_version"
    )
    _equal(
        payload.get("identity_contract"),
        contract.identity_contract,
        "identity_contract",
    )
    migrations = _object(payload.get("migrations"), "payload.migrations")
    _equal(
        migrations.get("schema_version"),
        contract.schema_version,
        "migration schema_version",
    )
    artifact_paths: dict[str, Path] = {}
    artifact_sha256: dict[str, str] = {}
    for artifact_name, filename in contract.artifact_filenames.items():
        descriptor = _object(payload.get(artifact_name), f"payload.{artifact_name}")
        _equal(descriptor.get("filename"), filename, f"{artifact_name}.filename")
        artifact_paths[artifact_name] = _verify_file(
            manifest_path.parent,
            descriptor,
            artifact_name,
        )
        artifact_sha256[artifact_name] = "sha256:" + _sha(
            descriptor.get("sha256"),
            f"{artifact_name}.sha256",
        )
    _verify_contract_artifacts(artifact_paths, contract)

    build = _object(payload.get("build"), "payload.build")
    _equal(build.get("repository"), repository, "build.repository")
    _equal(build.get("workflow_ref"), workflow_ref, "build.workflow_ref")
    _equal(build.get("source_commit"), source_commit, "build.source_commit")

    trusted_client = _object(trust.get("client_wheel"), "client_wheel")
    client = _object(payload.get("client_wheel"), "payload.client_wheel")
    for field in ("filename", "distribution", "version"):
        _equal(client.get(field), trusted_client.get(field), f"client_wheel.{field}")
    _equal(
        client.get("sha256"),
        "sha256:" + _sha(trusted_client.get("sha256"), "client_wheel.sha256"),
        "client_wheel.sha256",
    )
    expected_client_path = manifest_path.parent / str(trusted_client["filename"])

    for field, descriptor in payload.items():
        if not isinstance(descriptor, dict) or "filename" not in descriptor:
            continue
        filename = str(descriptor["filename"]).lower()
        if any(
            token in field.lower() or token in filename
            for token in _FORBIDDEN_RELEASE_TOKENS
        ):
            raise ReleaseVerificationError(
                "production release manifest contains a test-only hosted artifact"
            )
    staged_client = wheel_path or expected_client_path
    if staged_client.resolve() != expected_client_path.resolve():
        raise ReleaseVerificationError(
            "client wheel must be staged beside the release manifest"
        )
    client_sha = _verify_wheel(staged_client, client, field="client")

    service = _object(payload.get("service_wheel"), "payload.service_wheel")
    service_sha = _sha(service.get("sha256"), "service_wheel.sha256")

    image_reference, image_digest = _verify_image(
        _object(payload.get("service_image"), "payload.service_image"),
        "service_image",
    )
    trusted_image = _object(trust.get("service_image"), "service_image")
    _equal(image_reference, trusted_image.get("reference"), "service_image.reference")
    _equal(image_digest, trusted_image.get("digest"), "service_image.digest")
    canonical_digest = "sha256:" + hashlib.sha256(_canonical_jcs(envelope)).hexdigest()
    return {
        "kind": "production",
        "manifest_sha256": trusted_manifest_sha,
        "manifest_digest": canonical_digest,
        "client_wheel_sha256": client_sha,
        "service_wheel_sha256": service_sha,
        "service_image_reference": image_reference,
        "service_image_digest": image_digest,
        "release_version": contract.release_version,
        "api_version": contract.api_version,
        "schema_version": contract.schema_version,
        "funding_profiles": list(contract.funding_profiles),
        "capabilities": list(contract.capabilities),
        "artifact_sha256": artifact_sha256,
        "authority_id": authority_id,
        "authority_scheme": "eip191",
        "authority_address": authority_address,
        "identity_contract": contract.identity_contract,
        "repository": repository,
        "workflow_ref": workflow_ref,
        "source_commit": source_commit,
        # The filenames stay; the caller joins them with the release directory
        # to read the contract from the artifact the manifest hash-pinned,
        # rather than from a restatement of it.
        "artifacts": dict(contract.artifact_filenames),
    }


def verify_ready_response(
    production: dict[str, Any],
    response: dict[str, Any],
) -> None:
    checks = {
        "ready": True,
        "manifest_digest": production["manifest_digest"],
        "api_version": production["api_version"],
        "schema_version": production["schema_version"],
    }
    for field, expected in checks.items():
        if response.get(field) != expected:
            raise ReleaseVerificationError(
                f"ready response {field} does not match release"
            )
    missing = sorted(
        set(production["capabilities"]) - set(response.get("capabilities") or ())
    )
    if missing:
        raise ReleaseVerificationError(
            f"ready response is missing required capabilities: {', '.join(missing)}"
        )


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
    except (ReleaseVerificationError, OSError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, separators=(",", ":"), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
