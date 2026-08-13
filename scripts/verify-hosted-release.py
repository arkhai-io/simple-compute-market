#!/usr/bin/env python3
"""Verify immutable hosted production and private E2E release inputs."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import zipfile
from pathlib import Path
from typing import Any

_RELEASE_CONTRACT = "arkhai.hosted-settlement-release.v2"
_E2E_RELEASE_CONTRACT = "arkhai.hosted-settlement-private-e2e.v1"
_RELEASE_VERSION = "0.1.0"
_API_VERSION = "0.1.0"
_SCHEMA_VERSION = 4
_CONTROL_PROTOCOL = "arkhai.hosted-settlement-e2e-control.v1"
_CLOCK_PROTOCOL = "arkhai.hosted-settlement-e2e-clock.v1"
_PROVIDER_PROTOCOL = "arkhai.hosted-settlement-e2e-provider.v1"
_CONTROL_SCHEMA_CONTRACT = "arkhai.hosted-settlement-e2e-control-schema.v1"
_SIMULATOR_MIGRATIONS_CONTRACT = "arkhai.hosted-settlement-e2e-simulator-migrations.v1"
_SIMULATOR_SCHEMA_VERSION = 1
_CAPABILITIES = (
    "conditional-escrow.v1",
    "stripe-connect-separate-charges-transfers.v1",
    "portable-attestation.v1",
    "eas-arbiter.v1",
    "scheme-tagged-identities.v1",
    "account-owner-admission.v1",
    "account-owner-rotation.v1",
    "account-owner-retirement.v1",
    "signer-injected-client.v1",
    "provider-neutral-seller-onboarding.v1",
)
_E2E_CAPABILITIES = (
    "deterministic-provider.v1",
    "controlled-clock.v1",
    "controlled-events.v1",
    "authenticated-control.v1",
    "sanitized-effects.v1",
    "process-restart.v1",
)
_IDENTITY_CONTRACT = {
    "request_signature_protocol": "arkhai.hosted-request-signature.v2",
    "response_signature_protocol": "arkhai.hosted-response-signature.v2",
    "supported_identity_schemes": ["eip191", "ed25519"],
    "capabilities": [
        "scheme-tagged-identities.v1",
        "account-owner-admission.v1",
        "account-owner-rotation.v1",
        "account-owner-retirement.v1",
        "signer-injected-client.v1",
        "provider-neutral-seller-onboarding.v1",
    ],
    "account_owner_admission_protocol": "arkhai.account-owner-admission.v1",
    "account_owner_rotation_protocol": "arkhai.account-owner-rotation.v1",
    "client_signer_api": "hosted_settlement_client.Signer",
    "seller_onboarding_api": "hosted_settlement_client.SellerOnboarding",
}
_ARTIFACT_FILENAMES = {
    "openapi": "openapi-v0.1.0.json",
    "conformance": "conformance-v0.1.0.json",
    "migrations": "migrations-v4.json",
    "sbom": "sbom.spdx.json",
    "provenance": "provenance.intoto.json",
}
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_ADDRESS = re.compile(r"^0x[0-9a-f]{40}$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")


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
    service_wheel_path: Path | None = None,
) -> dict[str, Any]:
    _, trust = _read_json(trust_path, "release trust config")
    _equal(trust.get("contract_version"), _RELEASE_CONTRACT, "trust contract_version")
    _equal(trust.get("release_version"), _RELEASE_VERSION, "trust release_version")
    _equal(trust.get("api_version"), _API_VERSION, "trust api_version")
    _equal(trust.get("schema_version"), _SCHEMA_VERSION, "trust schema_version")
    _equal(
        tuple(trust.get("required_capabilities") or ()),
        _CAPABILITIES,
        "trust capabilities",
    )
    _equal(
        trust.get("identity_contract"), _IDENTITY_CONTRACT, "trust identity_contract"
    )
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
    _equal(payload.get("release_version"), _RELEASE_VERSION, "release_version")
    _equal(payload.get("identity_contract"), _IDENTITY_CONTRACT, "identity_contract")
    migrations = _object(payload.get("migrations"), "payload.migrations")
    _equal(
        migrations.get("schema_version"), _SCHEMA_VERSION, "migration schema_version"
    )
    for artifact_name, filename in _ARTIFACT_FILENAMES.items():
        descriptor = _object(payload.get(artifact_name), f"payload.{artifact_name}")
        _equal(descriptor.get("filename"), filename, f"{artifact_name}.filename")
        _verify_file(manifest_path.parent, descriptor, artifact_name)

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
    staged_client = wheel_path or expected_client_path
    if staged_client.resolve() != expected_client_path.resolve():
        raise ReleaseVerificationError(
            "client wheel must be staged beside the release manifest"
        )
    client_sha = _verify_wheel(staged_client, client, field="client")

    service = _object(payload.get("service_wheel"), "payload.service_wheel")
    service_sha = _sha(service.get("sha256"), "service_wheel.sha256")
    if service_wheel_path is not None:
        expected_service_path = manifest_path.parent / str(service.get("filename"))
        if service_wheel_path.resolve() != expected_service_path.resolve():
            raise ReleaseVerificationError(
                "service wheel must be staged beside the release manifest"
            )
        service_sha = _verify_wheel(service_wheel_path, service, field="service")

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
        "release_version": _RELEASE_VERSION,
        "api_version": _API_VERSION,
        "schema_version": _SCHEMA_VERSION,
        "capabilities": list(_CAPABILITIES),
        "identity_contract": _IDENTITY_CONTRACT,
        "repository": repository,
        "workflow_ref": workflow_ref,
        "source_commit": source_commit,
        "artifacts": dict(_ARTIFACT_FILENAMES),
    }


def verify_hermetic_release(
    *,
    production: dict[str, Any],
    manifest_path: Path,
    manifest_sha256: str,
    fixture_wheel_path: Path,
    service_wheel_path: Path,
    authority_id: str,
    authority_address: str,
    repository: str,
    workflow_ref: str,
    source_commit: str,
) -> dict[str, Any]:
    expected_raw_sha = _sha(manifest_sha256, "E2E manifest_sha256")
    if not _ADDRESS.fullmatch(authority_address):
        raise ReleaseVerificationError("trusted E2E authority_address is invalid")
    if not _COMMIT.fullmatch(source_commit):
        raise ReleaseVerificationError("trusted E2E source_commit is invalid")
    raw, envelope = _read_json(manifest_path, "staged E2E release manifest")
    if hashlib.sha256(raw).hexdigest() != expected_raw_sha:
        raise ReleaseVerificationError(
            "staged E2E release manifest hash does not match"
        )
    payload = _verify_signature(
        envelope,
        authority_id=authority_id,
        authority_address=authority_address,
        label="E2E",
    )
    _equal(
        payload.get("contract_version"), _E2E_RELEASE_CONTRACT, "E2E contract_version"
    )
    _equal(payload.get("designation"), "e2e-only", "E2E designation")
    _equal(
        payload.get("release_version"),
        production["release_version"],
        "E2E release_version",
    )
    _equal(payload.get("control_protocol"), _CONTROL_PROTOCOL, "E2E control_protocol")
    _equal(payload.get("clock_protocol"), _CLOCK_PROTOCOL, "E2E clock_protocol")
    _equal(
        payload.get("provider_protocol"), _PROVIDER_PROTOCOL, "E2E provider_protocol"
    )
    _equal(
        tuple(payload.get("capabilities") or ()), _E2E_CAPABILITIES, "E2E capabilities"
    )
    build = _object(payload.get("build"), "E2E payload.build")
    _equal(build.get("repository"), repository, "E2E build.repository")
    _equal(build.get("workflow_ref"), workflow_ref, "E2E build.workflow_ref")
    _equal(build.get("source_commit"), source_commit, "E2E build.source_commit")

    compatibility = _object(payload.get("production"), "E2E payload.production")
    _equal(
        compatibility.get("manifest_digest"),
        production["manifest_digest"],
        "E2E production manifest_digest",
    )
    _equal(
        compatibility.get("release_version"),
        production["release_version"],
        "E2E production release_version",
    )
    _equal(
        compatibility.get("client_wheel_sha256"),
        "sha256:" + production["client_wheel_sha256"],
        "E2E production client wheel",
    )
    _equal(
        compatibility.get("service_wheel_sha256"),
        "sha256:" + production["service_wheel_sha256"],
        "E2E production service wheel",
    )
    _equal(
        compatibility.get("service_image_digest"),
        production["service_image_digest"],
        "E2E production service image",
    )
    _equal(
        compatibility.get("migration_schema_version"),
        production["schema_version"],
        "E2E production migration schema",
    )
    production_manifest = _object(
        payload.get("production_manifest"), "E2E payload.production_manifest"
    )
    _equal(
        production_manifest.get("sha256"),
        "sha256:" + production["manifest_sha256"],
        "E2E production manifest file hash",
    )
    _equal(
        production_manifest.get("filename"),
        manifest_path.parent.joinpath(str(production_manifest.get("filename"))).name,
        "E2E production manifest filename",
    )
    _verify_file(manifest_path.parent, production_manifest, "E2E production manifest")

    fixture = _object(payload.get("fixture_wheel"), "E2E payload.fixture_wheel")
    fixture_sha = _verify_wheel(
        fixture_wheel_path,
        fixture,
        field="E2E fixture",
        expected_distribution="arkhai-hosted-settlement-e2e",
        expected_version=str(payload.get("release_version")),
    )
    service_descriptor = _object(
        _object(
            json.loads(
                (
                    manifest_path.parent / str(production_manifest["filename"])
                ).read_bytes()
            ),
            "production manifest",
        ).get("payload"),
        "production manifest payload",
    ).get("service_wheel")
    service_sha = _verify_wheel(
        service_wheel_path,
        _object(service_descriptor, "production service_wheel"),
        field="service",
    )
    _equal(
        "sha256:" + service_sha,
        compatibility.get("service_wheel_sha256"),
        "E2E staged service wheel",
    )

    control_schema_descriptor = _object(
        payload.get("control_schema"), "E2E payload.control_schema"
    )
    control_schema_path = _verify_file(
        manifest_path.parent, control_schema_descriptor, "E2E control schema"
    )
    _, control_schema = _read_json(control_schema_path, "E2E control schema")
    _equal(
        control_schema.get("contract"),
        _CONTROL_SCHEMA_CONTRACT,
        "control schema contract",
    )
    _equal(
        control_schema.get("control_protocol"),
        _CONTROL_PROTOCOL,
        "control schema protocol",
    )
    _equal(
        control_schema.get("clock_protocol"), _CLOCK_PROTOCOL, "control clock protocol"
    )
    _equal(
        control_schema.get("provider_protocol"),
        _PROVIDER_PROTOCOL,
        "control provider protocol",
    )

    authority_migrations = _object(
        payload.get("authority_migrations"), "E2E payload.authority_migrations"
    )
    _equal(
        authority_migrations.get("schema_version"),
        production["schema_version"],
        "E2E authority migration schema",
    )
    _verify_file(manifest_path.parent, authority_migrations, "E2E authority migrations")
    simulator_migrations = _object(
        payload.get("simulator_migrations"), "E2E payload.simulator_migrations"
    )
    _equal(
        simulator_migrations.get("schema_version"),
        _SIMULATOR_SCHEMA_VERSION,
        "E2E simulator migration schema",
    )
    simulator_path = _verify_file(
        manifest_path.parent, simulator_migrations, "E2E simulator migrations"
    )
    _, simulator_document = _read_json(simulator_path, "E2E simulator migrations")
    _equal(
        simulator_document.get("contract"),
        _SIMULATOR_MIGRATIONS_CONTRACT,
        "E2E simulator migrations contract",
    )
    _equal(
        simulator_document.get("schema_version"),
        _SIMULATOR_SCHEMA_VERSION,
        "E2E simulator migrations schema",
    )
    for field in ("sbom", "provenance"):
        _verify_file(
            manifest_path.parent,
            _object(payload.get(field), f"E2E payload.{field}"),
            f"E2E {field}",
        )

    authority_reference, authority_digest = _verify_image(
        _object(payload.get("authority_image"), "E2E payload.authority_image"),
        "E2E authority_image",
    )
    simulator_reference, simulator_digest = _verify_image(
        _object(payload.get("simulator_image"), "E2E payload.simulator_image"),
        "E2E simulator_image",
    )
    canonical_digest = "sha256:" + hashlib.sha256(_canonical_jcs(envelope)).hexdigest()
    return {
        "kind": "e2e-only",
        "manifest_sha256": expected_raw_sha,
        "manifest_digest": canonical_digest,
        "authority_image_reference": authority_reference,
        "authority_image_digest": authority_digest,
        "simulator_image_reference": simulator_reference,
        "simulator_image_digest": simulator_digest,
        "fixture_wheel_sha256": fixture_sha,
        "fixture_version": str(fixture.get("version")),
        "control_protocol": _CONTROL_PROTOCOL,
        "clock_protocol": _CLOCK_PROTOCOL,
        "provider_protocol": _PROVIDER_PROTOCOL,
        "simulator_schema_version": _SIMULATOR_SCHEMA_VERSION,
        "capabilities": list(_E2E_CAPABILITIES),
        "repository": repository,
        "workflow_ref": workflow_ref,
        "source_commit": source_commit,
        "production": production,
    }


def verify_ready_response(
    production: dict[str, Any],
    response: dict[str, Any],
    *,
    e2e: dict[str, Any] | None = None,
    e2e_response: dict[str, Any] | None = None,
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
    if e2e is None:
        if e2e_response is not None:
            raise ReleaseVerificationError("E2E ready response has no verified release")
        return
    if e2e_response is None:
        raise ReleaseVerificationError("E2E ready response is required")
    e2e_checks = {
        "ready": True,
        "manifest_digest": production["manifest_digest"],
        "e2e_manifest_digest": e2e["manifest_digest"],
        "control_protocol": e2e["control_protocol"],
    }
    for field, expected in e2e_checks.items():
        if e2e_response.get(field) != expected:
            raise ReleaseVerificationError(
                f"E2E ready response {field} does not match release"
            )
    missing = sorted(
        set(e2e["capabilities"]) - set(e2e_response.get("capabilities") or ())
    )
    if missing:
        raise ReleaseVerificationError(
            f"E2E ready response is missing required capabilities: {', '.join(missing)}"
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trust", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--wheel", type=Path)
    parser.add_argument("--service-wheel", type=Path)
    parser.add_argument("--e2e-manifest", type=Path)
    parser.add_argument("--e2e-manifest-sha256")
    parser.add_argument("--e2e-fixture-wheel", type=Path)
    parser.add_argument("--e2e-authority-id")
    parser.add_argument("--e2e-authority-address")
    parser.add_argument("--e2e-repository")
    parser.add_argument("--e2e-workflow-ref")
    parser.add_argument("--e2e-source-commit")
    args = parser.parse_args()
    try:
        production = verify_release(
            trust_path=args.trust,
            manifest_path=args.manifest,
            wheel_path=args.wheel,
            service_wheel_path=args.service_wheel,
        )
        result: dict[str, Any] = production
        if args.e2e_manifest is not None:
            required = {
                "--service-wheel": args.service_wheel,
                "--e2e-manifest-sha256": args.e2e_manifest_sha256,
                "--e2e-fixture-wheel": args.e2e_fixture_wheel,
                "--e2e-authority-id": args.e2e_authority_id,
                "--e2e-authority-address": args.e2e_authority_address,
                "--e2e-repository": args.e2e_repository,
                "--e2e-workflow-ref": args.e2e_workflow_ref,
                "--e2e-source-commit": args.e2e_source_commit,
            }
            missing = next(
                (name for name, value in required.items() if not value), None
            )
            if missing:
                raise ReleaseVerificationError(
                    f"missing required hermetic input {missing}"
                )
            result = verify_hermetic_release(
                production=production,
                manifest_path=args.e2e_manifest,
                manifest_sha256=str(args.e2e_manifest_sha256),
                fixture_wheel_path=args.e2e_fixture_wheel,
                service_wheel_path=args.service_wheel,
                authority_id=str(args.e2e_authority_id),
                authority_address=str(args.e2e_authority_address),
                repository=str(args.e2e_repository),
                workflow_ref=str(args.e2e_workflow_ref),
                source_commit=str(args.e2e_source_commit),
            )
    except (ReleaseVerificationError, OSError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, separators=(",", ":"), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
