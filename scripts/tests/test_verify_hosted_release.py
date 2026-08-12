from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any, Callable
import sys

import pytest
from eth_account import Account
from eth_account.messages import encode_defunct


REPO_ROOT = Path(__file__).resolve().parents[2]
VERIFIER_PATH = REPO_ROOT / "scripts" / "verify-hosted-release.py"
_SPEC = importlib.util.spec_from_file_location("verify_hosted_release", VERIFIER_PATH)
assert _SPEC is not None and _SPEC.loader is not None
verifier = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(verifier)
PREPARER_PATH = REPO_ROOT / "scripts" / "prepare-hosted-compose.py"
_PREPARER_SPEC = importlib.util.spec_from_file_location(
    "prepare_hosted_compose", PREPARER_PATH
)
assert _PREPARER_SPEC is not None and _PREPARER_SPEC.loader is not None
preparer = importlib.util.module_from_spec(_PREPARER_SPEC)
sys.modules[_PREPARER_SPEC.name] = preparer
_PREPARER_SPEC.loader.exec_module(preparer)

_AUTHORITY_KEY = "0x" + "11" * 32
_IDENTITY_CAPABILITIES = [
    "scheme-tagged-identities.v1",
    "account-owner-admission.v1",
    "account-owner-rotation.v1",
    "account-owner-retirement.v1",
    "signer-injected-client.v1",
    "provider-neutral-seller-onboarding.v1",
]
_IDENTITY_CONTRACT = {
    "request_signature_protocol": "arkhai.hosted-request-signature.v2",
    "response_signature_protocol": "arkhai.hosted-response-signature.v2",
    "supported_identity_schemes": ["eip191", "ed25519"],
    "capabilities": _IDENTITY_CAPABILITIES,
    "account_owner_admission_protocol": "arkhai.account-owner-admission.v1",
    "account_owner_rotation_protocol": "arkhai.account-owner-rotation.v1",
    "client_signer_api": "hosted_settlement_client.Signer",
    "seller_onboarding_api": "hosted_settlement_client.SellerOnboarding",
}
_REQUIRED_CAPABILITIES = [
    "conditional-escrow.v1",
    "stripe-connect-separate-charges-transfers.v1",
    "portable-attestation.v1",
    "eas-arbiter.v1",
    *_IDENTITY_CAPABILITIES,
]


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _stage_release(
    root: Path,
    *,
    mutate_payload: Callable[[dict[str, Any]], None] | None = None,
    mutate_envelope: Callable[[dict[str, Any]], None] | None = None,
    mutate_trust: Callable[[dict[str, Any]], None] | None = None,
) -> tuple[Path, Path, Path]:
    artifact_contents = {
        "openapi-v0.1.0.json": b'{"openapi":"3.1.0"}\n',
        "conformance-v0.1.0.json": b'{"schema_version":4}\n',
        "migrations-v4.json": b'{"schema_version":4}\n',
        "sbom.spdx.json": b'{"spdxVersion":"SPDX-2.3"}\n',
        "provenance.intoto.json": b'{"_type":"https://in-toto.io/Statement/v1"}\n',
    }
    for filename, contents in artifact_contents.items():
        (root / filename).write_bytes(contents)

    client_filename = "arkhai_hosted_settlement_client-0.1.0-py3-none-any.whl"
    client_bytes = b"exact hosted client wheel fixture"
    client_path = root / client_filename
    client_path.write_bytes(client_bytes)
    client_sha = _sha(client_bytes)
    image_digest = "sha256:" + "ab" * 32
    artifact = lambda filename: {
        "filename": filename,
        "media_type": "application/json",
        "sha256": "sha256:" + _sha(artifact_contents[filename]),
    }
    payload: dict[str, Any] = {
        "contract_version": "arkhai.hosted-settlement-release.v2",
        "release_version": "0.1.0",
        "identity_contract": copy.deepcopy(_IDENTITY_CONTRACT),
        "client_wheel": {
            "filename": client_filename,
            "distribution": "arkhai-hosted-settlement-client",
            "version": "0.1.0",
            "sha256": "sha256:" + client_sha,
        },
        "service_wheel": {
            "filename": "arkhai_hosted_settlement_service-0.1.0-py3-none-any.whl",
            "distribution": "arkhai-hosted-settlement-service",
            "version": "0.1.0",
            "sha256": "sha256:" + "cd" * 32,
        },
        "service_image": {
            "reference": "ghcr.io/arkhai/hosted-settlement-service",
            "digest": image_digest,
        },
        "openapi": artifact("openapi-v0.1.0.json"),
        "conformance": artifact("conformance-v0.1.0.json"),
        "migrations": {
            **artifact("migrations-v4.json"),
            "schema_version": 4,
        },
        "sbom": artifact("sbom.spdx.json"),
        "provenance": artifact("provenance.intoto.json"),
        "build": {
            "repository": "arkhai/hosted-settlement-service",
            "workflow_ref": ".github/workflows/release.yml@refs/tags/v0.1.0",
            "source_commit": "12" * 20,
        },
    }
    if mutate_payload is not None:
        mutate_payload(payload)

    account = Account.from_key(_AUTHORITY_KEY)
    signature = Account.sign_message(
        encode_defunct(primitive=verifier._canonical_jcs(payload)),
        private_key=_AUTHORITY_KEY,
    ).signature.hex()
    envelope: dict[str, Any] = {
        "payload": payload,
        "signature_scheme": "eip191",
        "authority_id": "release-authority",
        "authority_address": account.address.lower(),
        "signature": signature,
    }
    if mutate_envelope is not None:
        mutate_envelope(envelope)
    manifest_path = root / "release-manifest.json"
    manifest_path.write_bytes(
        json.dumps(envelope, separators=(",", ":"), sort_keys=True).encode()
    )

    trust: dict[str, Any] = {
        "contract_version": "arkhai.hosted-settlement-release.v2",
        "release_version": "0.1.0",
        "api_version": "0.1.0",
        "schema_version": 4,
        "required_capabilities": list(_REQUIRED_CAPABILITIES),
        "identity_contract": copy.deepcopy(_IDENTITY_CONTRACT),
        "manifest_filename": manifest_path.name,
        "manifest_sha256": _sha(manifest_path.read_bytes()),
        "authority_id": "release-authority",
        "authority_address": account.address.lower(),
        "repository": "arkhai/hosted-settlement-service",
        "workflow_ref": ".github/workflows/release.yml@refs/tags/v0.1.0",
        "source_commit": "12" * 20,
        "client_wheel": {
            "filename": client_filename,
            "distribution": "arkhai-hosted-settlement-client",
            "version": "0.1.0",
            "sha256": client_sha,
        },
        "service_image": {
            "reference": "ghcr.io/arkhai/hosted-settlement-service",
            "digest": image_digest,
        },
    }
    if mutate_trust is not None:
        mutate_trust(trust)
    trust_path = root / "marketplace-trust.json"
    trust_path.write_text(json.dumps(trust), encoding="utf-8")
    return trust_path, manifest_path, client_path


def _verify(root: Path, **kwargs: Any) -> dict[str, Any]:
    trust_path, manifest_path, client_path = _stage_release(root, **kwargs)
    return verifier.verify_release(
        trust_path=trust_path,
        manifest_path=manifest_path,
        wheel_path=client_path,
    )


def test_schema_four_identity_release_is_accepted(tmp_path: Path) -> None:
    result = _verify(tmp_path)

    assert result["schema_version"] == 4
    assert result["identity_contract"] == _IDENTITY_CONTRACT
    assert result["capabilities"] == _REQUIRED_CAPABILITIES


@pytest.mark.parametrize("schema_version", [1, 3, 5])
def test_non_current_trusted_schema_is_rejected(
    tmp_path: Path, schema_version: int
) -> None:
    with pytest.raises(verifier.ReleaseVerificationError, match="trust schema_version"):
        _verify(
            tmp_path,
            mutate_trust=lambda trust: trust.__setitem__(
                "schema_version", schema_version
            ),
        )


def test_missing_identity_capability_is_rejected(tmp_path: Path) -> None:
    def remove_retirement(payload: dict[str, Any]) -> None:
        payload["identity_contract"]["capabilities"].remove(
            "account-owner-retirement.v1"
        )

    with pytest.raises(verifier.ReleaseVerificationError, match="identity_contract"):
        _verify(tmp_path, mutate_payload=remove_retirement)


def test_old_signature_envelope_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(verifier.ReleaseVerificationError, match="signature_scheme"):
        _verify(
            tmp_path,
            mutate_envelope=lambda envelope: envelope.__setitem__(
                "signature_scheme", "ed25519"
            ),
        )


def test_tampered_provenance_is_rejected(tmp_path: Path) -> None:
    trust_path, manifest_path, client_path = _stage_release(tmp_path)
    (tmp_path / "provenance.intoto.json").write_bytes(b"{}\n")

    with pytest.raises(
        verifier.ReleaseVerificationError,
        match="staged provenance artifact hash does not match",
    ):
        verifier.verify_release(
            trust_path=trust_path,
            manifest_path=manifest_path,
            wheel_path=client_path,
        )


def test_compose_env_uses_exact_verified_image(tmp_path: Path) -> None:
    trust_path, manifest_path, client_path = _stage_release(tmp_path)
    output_path = tmp_path / "hosted-compose.env"

    image = preparer.prepare_compose_env(
        trust_path=trust_path,
        manifest_path=manifest_path,
        wheel_path=client_path,
        output_path=output_path,
    )

    assert image == f"ghcr.io/arkhai/hosted-settlement-service@sha256:{'ab' * 32}"
    assert output_path.read_text(encoding="utf-8").splitlines()[1] == (
        f"HOSTED_SETTLEMENT_VERIFIED_IMAGE={image}"
    )


def test_compose_env_rejects_arbitrary_image_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    trust_path, manifest_path, client_path = _stage_release(tmp_path)
    monkeypatch.setenv("HOSTED_SETTLEMENT_VERIFIED_IMAGE", "attacker.invalid/image:latest")

    with pytest.raises(
        preparer.ComposePreparationError,
        match="HOSTED_SETTLEMENT_VERIFIED_IMAGE does not match",
    ):
        preparer.prepare_compose_env(
            trust_path=trust_path,
            manifest_path=manifest_path,
            wheel_path=client_path,
            output_path=tmp_path / "hosted-compose.env",
        )


def test_compose_env_rejects_tampered_digest_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    trust_path, manifest_path, client_path = _stage_release(tmp_path)
    monkeypatch.setenv("HOSTED_SETTLEMENT_IMAGE_DIGEST", f"sha256:{'00' * 32}")

    with pytest.raises(
        preparer.ComposePreparationError,
        match="HOSTED_SETTLEMENT_IMAGE_DIGEST does not match",
    ):
        preparer.prepare_compose_env(
            trust_path=trust_path,
            manifest_path=manifest_path,
            wheel_path=client_path,
            output_path=tmp_path / "hosted-compose.env",
        )