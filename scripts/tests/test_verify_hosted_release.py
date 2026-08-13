from __future__ import annotations

import copy
import hashlib
import importlib.util
import io
import json
import sys
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

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


def _client_wheel_bytes(*, entry_points: str | None = None) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, mode="w") as archive:
        archive.writestr("hosted_settlement_client/__init__.py", "")
        archive.writestr(
            "arkhai_hosted_settlement_client-0.1.0.dist-info/METADATA",
            "Name: arkhai-hosted-settlement-client\nVersion: 0.1.0\n",
        )
        archive.writestr(
            "arkhai_hosted_settlement_client-0.1.0.dist-info/WHEEL",
            "Wheel-Version: 1.0\nTag: py3-none-any\n",
        )
        if entry_points is not None:
            archive.writestr(
                "arkhai_hosted_settlement_client-0.1.0.dist-info/entry_points.txt",
                entry_points,
            )
    return buffer.getvalue()


def _stage_release(
    root: Path,
    *,
    mutate_payload: Callable[[dict[str, Any]], None] | None = None,
    mutate_envelope: Callable[[dict[str, Any]], None] | None = None,
    mutate_trust: Callable[[dict[str, Any]], None] | None = None,
    client_entry_points: str | None = None,
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
    client_bytes = _client_wheel_bytes(entry_points=client_entry_points)
    client_path = root / client_filename
    client_path.write_bytes(client_bytes)
    client_sha = _sha(client_bytes)
    image_digest = "sha256:" + "ab" * 32

    def artifact(filename: str) -> dict[str, str]:
        return {
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


def test_production_manifest_with_test_fixture_artifact_is_rejected(
    tmp_path: Path,
) -> None:
    def add_fixture(payload: dict[str, Any]) -> None:
        payload["fixture_wheel"] = {
            "filename": "arkhai_hosted_settlement_e2e-0.1.0-py3-none-any.whl",
            "sha256": "sha256:" + "ef" * 32,
        }

    with pytest.raises(
        verifier.ReleaseVerificationError,
        match="test-only hosted artifact",
    ):
        _verify(tmp_path, mutate_payload=add_fixture)


def test_client_wheel_with_seller_entry_point_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(
        verifier.ReleaseVerificationError,
        match="must not contain console-script entry-point metadata",
    ):
        _verify(
            tmp_path,
            client_entry_points=(
                "[console_scripts]\n"
                "hosted-settlement-seller = hosted_settlement_client.seller:main\n"
            ),
        )


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


def test_unsigned_local_manifest_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(verifier.ReleaseVerificationError, match="signature"):
        _verify(
            tmp_path,
            mutate_envelope=lambda envelope: envelope.__setitem__(
                "signature", "00" * 65
            ),
            mutate_trust=lambda trust: trust.__setitem__("workflow_ref", "local"),
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


def test_compose_env_uses_exact_verified_release_identities(tmp_path: Path) -> None:
    trust_path, manifest_path, client_path = _stage_release(tmp_path)
    output_path = tmp_path / "hosted-compose.env"
    release = verifier.verify_release(
        trust_path=trust_path,
        manifest_path=manifest_path,
        wheel_path=client_path,
    )

    image = preparer.prepare_compose_env(
        trust_path=trust_path,
        manifest_path=manifest_path,
        wheel_path=client_path,
        output_path=output_path,
    )
    values = dict(
        line.split("=", 1)
        for line in output_path.read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#")
    )

    assert image == f"ghcr.io/arkhai/hosted-settlement-service@sha256:{'ab' * 32}"
    assert values == {
        "HOSTED_SETTLEMENT_VERIFIED_AUTHORITY_ADDRESS": release["authority_address"],
        "HOSTED_SETTLEMENT_VERIFIED_AUTHORITY_ID": release["authority_id"],
        "HOSTED_SETTLEMENT_VERIFIED_AUTHORITY_SCHEME": release["authority_scheme"],
        "HOSTED_SETTLEMENT_VERIFIED_CLIENT_WHEEL_SHA256": (
            "sha256:" + release["client_wheel_sha256"]
        ),
        "HOSTED_SETTLEMENT_VERIFIED_IMAGE": image,
        "HOSTED_SETTLEMENT_VERIFIED_MANIFEST_DIGEST": release["manifest_digest"],
        "HOSTED_SETTLEMENT_VERIFIED_MANIFEST_SHA256": (
            "sha256:" + release["manifest_sha256"]
        ),
        "HOSTED_SETTLEMENT_VERIFIED_RELEASE_DIR": str(manifest_path.resolve().parent),
        "HOSTED_SETTLEMENT_VERIFIED_SOURCE_COMMIT": release["source_commit"],
        "HOSTED_SETTLEMENT_VERIFIED_REPOSITORY": release["repository"],
        "HOSTED_SETTLEMENT_VERIFIED_WORKFLOW_REF": release["workflow_ref"],
    }


def test_compose_env_rejects_arbitrary_image_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    trust_path, manifest_path, client_path = _stage_release(tmp_path)
    monkeypatch.setenv(
        "HOSTED_SETTLEMENT_VERIFIED_IMAGE", "attacker.invalid/image:latest"
    )

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


def test_compose_env_rejects_arbitrary_release_directory_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    trust_path, manifest_path, client_path = _stage_release(tmp_path)
    monkeypatch.setenv(
        "HOSTED_SETTLEMENT_VERIFIED_RELEASE_DIR",
        str(tmp_path / "unverified-release"),
    )

    with pytest.raises(
        preparer.ComposePreparationError,
        match="HOSTED_SETTLEMENT_VERIFIED_RELEASE_DIR does not match",
    ):
        preparer.prepare_compose_env(
            trust_path=trust_path,
            manifest_path=manifest_path,
            wheel_path=client_path,
            output_path=tmp_path / "hosted-compose.env",
        )


def test_floating_production_image_tag_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(
        verifier.ReleaseVerificationError, match="must not contain a floating tag"
    ):
        _verify(
            tmp_path,
            mutate_payload=lambda payload: payload["service_image"].__setitem__(
                "reference", "ghcr.io/arkhai/hosted-settlement-service:latest"
            ),
            mutate_trust=lambda trust: trust["service_image"].__setitem__(
                "reference", "ghcr.io/arkhai/hosted-settlement-service:latest"
            ),
        )


def test_generated_environment_contains_only_allowlisted_nonsecret_keys(
    tmp_path: Path,
) -> None:
    trust_path, manifest_path, client_path = _stage_release(tmp_path)
    output = tmp_path / "hosted-compose.env"
    preparer.prepare_compose_env(
        trust_path=trust_path,
        manifest_path=manifest_path,
        wheel_path=client_path,
        output_path=output,
    )
    keys = {
        line.split("=", 1)[0]
        for line in output.read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#")
    }
    assert keys == {
        "HOSTED_SETTLEMENT_VERIFIED_AUTHORITY_ADDRESS",
        "HOSTED_SETTLEMENT_VERIFIED_AUTHORITY_ID",
        "HOSTED_SETTLEMENT_VERIFIED_AUTHORITY_SCHEME",
        "HOSTED_SETTLEMENT_VERIFIED_CLIENT_WHEEL_SHA256",
        "HOSTED_SETTLEMENT_VERIFIED_IMAGE",
        "HOSTED_SETTLEMENT_VERIFIED_MANIFEST_DIGEST",
        "HOSTED_SETTLEMENT_VERIFIED_MANIFEST_SHA256",
        "HOSTED_SETTLEMENT_VERIFIED_RELEASE_DIR",
        "HOSTED_SETTLEMENT_VERIFIED_SOURCE_COMMIT",
        "HOSTED_SETTLEMENT_VERIFIED_REPOSITORY",
        "HOSTED_SETTLEMENT_VERIFIED_WORKFLOW_REF",
    }


def test_compose_preparer_rejects_release_mode_selector(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "prepare-hosted-compose.py",
            "--trust",
            "trust.json",
            "--manifest",
            "release-manifest.json",
            "--wheel",
            "client.whl",
            "--output",
            "compose.env",
            "--mode",
            "hermetic",
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        preparer.main()

    assert exc_info.value.code == 2
    assert "unrecognized arguments: --mode hermetic" in capsys.readouterr().err
