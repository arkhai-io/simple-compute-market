from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import zipfile

import pytest
from eth_account import Account
from eth_account.messages import encode_defunct


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "package-review-wheelhouse.sh"
_CAPABILITIES = [
    "scheme-tagged-identities.v1",
    "account-owner-admission.v1",
    "account-owner-rotation.v1",
    "account-owner-retirement.v1",
    "signer-injected-client.v1",
    "provider-neutral-seller-onboarding.v1",
    "conditional-escrow.v2",
    "stripe-connect-separate-charges-transfers.v2",
    "portable-attestation.v1",
    "eas-arbiter.v1",
    "payer-profile.v1",
    "funding-authorization.v1",
    "funding-profile.card.v1",
    "funding-profile.us_bank_transfer.v1",
    "funding-profile.us_ach_debit.v1",
    "normalized-funding-reversal.v1",
    "operator-recovery-redaction.v1",
]
_IDENTITY_CONTRACT = {
    "request_signature_protocol": "arkhai.hosted-request-signature.v2",
    "response_signature_protocol": "arkhai.hosted-response-signature.v2",
    "supported_identity_schemes": ["eip191", "ed25519"],
    "capabilities": _CAPABILITIES,
    "account_owner_admission_protocol": "arkhai.account-owner-admission.v1",
    "account_owner_rotation_protocol": "arkhai.account-owner-rotation.v1",
    "client_signer_api": "hosted_settlement_client.Signer",
    "seller_onboarding_api": "hosted_settlement_client.SellerOnboarding",
    "payer_profile_protocol": "arkhai.payer-profile.v1",
    "funding_authorization_protocol": "arkhai.funding-authorization.v1",
    "funding_profiles": ["card.v1", "us_bank_transfer.v1", "us_ach_debit.v1"],
}

def _identity_wheel() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, mode="w") as archive:
        archive.writestr("market_identity/__init__.py", "")
        archive.writestr(
            "arkhai_kit_identity-0.3.0.dist-info/METADATA",
            "Name: arkhai-kit-identity\nVersion: 0.3.0\n",
        )
    return buffer.getvalue()



def _hosted_client_wheel(
    *,
    entry_points: str | None = None,
    extra_member: str | None = None,
) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, mode="w") as archive:
        archive.writestr(
            "hosted_settlement_client/__init__.py",
            "__all__ = ["
            "'CreatePayerProfileRequest','FundingAuthorizationRequest',"
            "'FundingAuthorizationResult','FundingProfile',"
            "'FundingProfileReadiness','HostedSettlementAsyncClient',"
            "'HostedSettlementClient','InstrumentListResult',"
            "'PayerAction','PayerProfileResult','PayerSetupRequest',"
            "'PayerSetupResult','Signer']\n",
        )
        archive.writestr(
            "arkhai_hosted_settlement_client-0.2.0.dist-info/METADATA",
            "Name: arkhai-hosted-settlement-client\nVersion: 0.2.0\n",
        )
        if entry_points is not None:
            archive.writestr(
                "arkhai_hosted_settlement_client-0.2.0.dist-info/entry_points.txt",
                entry_points,
            )
        if extra_member is not None:
            archive.writestr(extra_member, "")
    return buffer.getvalue()


def _fake_uv(bin_dir: Path) -> None:
    executable = bin_dir / "uv"
    executable.write_text(
        """#!/usr/bin/env python3
import os
from pathlib import Path
import sys

args = sys.argv[1:]
if args and args[0] == "run":
    python_index = max(index for index, value in enumerate(args) if value == "python")
    os.execv(sys.executable, [sys.executable, *args[python_index + 1:]])
if args and args[0] == "sync":
    environment = Path(os.environ["UV_PROJECT_ENVIRONMENT"])
    target = environment / "bin" / "python"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(f'#!/bin/sh\\nexec "{sys.executable}" "$@"\\n')
    target.chmod(0o755)
    raise SystemExit(0)
raise SystemExit(f"unsupported fake uv invocation: {args}")
""",
        encoding="utf-8",
    )
    executable.chmod(0o755)


def _stage_root(
    tmp_path: Path,
    *,
    lock_extra: str = "",
    hosted_entry_points: str | None = None,
    hosted_extra_member: str | None = None,
) -> tuple[Path, dict[str, str]]:
    root = tmp_path / "repo"
    (root / "scripts").mkdir(parents=True)
    (root / "manifests").mkdir()
    (root / ".dist").mkdir()
    (root / "project").mkdir()
    shutil.copy2(SCRIPT, root / "scripts" / SCRIPT.name)
    shutil.copy2(
        REPO_ROOT / "scripts" / "verify-hosted-release.py",
        root / "scripts" / "verify-hosted-release.py",
    )

    (root / ".dist" / "arkhai_kit_identity-0.3.0-py3-none-any.whl").write_bytes(
        _identity_wheel()
    )
    hosted_client_wheel = _hosted_client_wheel(
        entry_points=hosted_entry_points,
        extra_member=hosted_extra_member,
    )
    client_filename = "arkhai_hosted_settlement_client-0.2.0-py3-none-any.whl"
    client_path = root / ".dist" / client_filename
    client_path.write_bytes(hosted_client_wheel)
    artifacts = {
        "openapi-v0.2.0.json": json.dumps(
            {"openapi": "3.1.0", "info": {"version": "0.2.0"}}
        ).encode(),
        "conformance-v0.2.0.json": json.dumps(
            {
                "api_version": "0.2.0",
                "schema_version": 5,
                "funding_profiles": [
                    "card.v1",
                    "us_bank_transfer.v1",
                    "us_ach_debit.v1",
                ],
                "identity_contract": _IDENTITY_CONTRACT,
            }
        ).encode(),
        "migrations-v5.json": json.dumps(
            {
                "schema_version": 5,
                "migrations": [
                    {"position": 1, "migration_id": "0001_authority"},
                    {"position": 2, "migration_id": "0002_portable_attestations"},
                    {"position": 3, "migration_id": "0003_durable_lifecycle"},
                    {"position": 4, "migration_id": "0004_scheme_tagged_identities"},
                    {"position": 5, "migration_id": "0005_payer_funding_profiles"},
                ],
            }
        ).encode(),
        "sbom.spdx.json": b'{"spdxVersion":"SPDX-2.3"}\n',
        "provenance.intoto.json": b'{"_type":"https://in-toto.io/Statement/v1"}\n',
    }
    for filename, content in artifacts.items():
        (root / ".dist" / filename).write_bytes(content)

    def artifact(filename: str) -> dict[str, str]:
        return {
            "filename": filename,
            "media_type": "application/json",
            "sha256": "sha256:" + hashlib.sha256(artifacts[filename]).hexdigest(),
        }

    client_sha = hashlib.sha256(hosted_client_wheel).hexdigest()
    source_commit = "12" * 20
    workflow_ref = ".github/workflows/release.yml@refs/tags/v0.2.0"
    payload = {
        "contract_version": "arkhai.hosted-settlement-release.v2",
        "release_version": "0.2.0",
        "api_version": "0.2.0",
        "schema_version": 5,
        "funding_profiles": ["card.v1", "us_bank_transfer.v1", "us_ach_debit.v1"],
        "capabilities": _CAPABILITIES,
        "identity_contract": _IDENTITY_CONTRACT,
        "client_wheel": {
            "filename": client_filename,
            "distribution": "arkhai-hosted-settlement-client",
            "version": "0.2.0",
            "sha256": "sha256:" + client_sha,
        },
        "service_wheel": {
            "filename": "arkhai_hosted_settlement_service-0.2.0-py3-none-any.whl",
            "distribution": "arkhai-hosted-settlement-service",
            "version": "0.2.0",
            "sha256": "sha256:" + "cd" * 32,
        },
        "service_image": {
            "reference": "ghcr.io/arkhai/hosted-settlement-service",
            "digest": "sha256:" + "ab" * 32,
        },
        "openapi": artifact("openapi-v0.2.0.json"),
        "conformance": artifact("conformance-v0.2.0.json"),
        "migrations": {**artifact("migrations-v5.json"), "schema_version": 5},
        "sbom": artifact("sbom.spdx.json"),
        "provenance": artifact("provenance.intoto.json"),
        "build": {
            "repository": "arkhai/hosted-settlement-service",
            "workflow_ref": workflow_ref,
            "source_commit": source_commit,
        },
    }
    canonical = json.dumps(
        payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode()
    authority_key = "0x" + "11" * 32
    authority = Account.from_key(authority_key)
    signature = Account.sign_message(
        encode_defunct(primitive=canonical), private_key=authority_key
    ).signature.hex()
    manifest = {
        "payload": payload,
        "signature_scheme": "eip191",
        "authority_id": "release-authority",
        "authority_address": authority.address.lower(),
        "signature": signature,
    }
    manifest_path = root / ".dist" / "release-manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, separators=(",", ":"), sort_keys=True),
        encoding="utf-8",
    )
    trust = {
        "contract_version": "arkhai.hosted-settlement-release.v2",
        "release_version": "0.2.0",
        "api_version": "0.2.0",
        "schema_version": 5,
        "required_capabilities": _CAPABILITIES,
        "identity_contract": _IDENTITY_CONTRACT,
        "manifest_filename": manifest_path.name,
        "manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        "authority_id": "release-authority",
        "authority_address": authority.address.lower(),
        "repository": "arkhai/hosted-settlement-service",
        "workflow_ref": workflow_ref,
        "source_commit": source_commit,
        "client_wheel": {
            "filename": client_filename,
            "distribution": "arkhai-hosted-settlement-client",
            "version": "0.2.0",
            "sha256": client_sha,
        },
        "service_image": {
            "reference": "ghcr.io/arkhai/hosted-settlement-service",
            "digest": "sha256:" + "ab" * 32,
        },
    }
    (root / "manifests" / "hosted-settlement-v0.2.0-trust.json").write_text(
        json.dumps(trust), encoding="utf-8"
    )
    (root / "project" / "pyproject.toml").write_text(
        """[project]
name = "fixture-project"
version = "1.0.0"
requires-python = ">=3.12"
dependencies = []
""",
        encoding="utf-8",
    )
    (root / "project" / "uv.lock").write_text(
        """version = 1
revision = 3
requires-python = ">=3.12"

[[package]]
name = "fixture-project"
version = "1.0.0"
source = { editable = "." }
"""
        + lock_extra,
        encoding="utf-8",
    )
    bin_dir = root / "bin"
    bin_dir.mkdir()
    _fake_uv(bin_dir)
    env = {
        **os.environ,
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "REVIEW_PROJECTS": "project",
        "REVIEW_PYTHON": "3.13",
        "REVIEW_SOURCE_COMMIT": "34" * 20,
    }
    return root, env


def _run(root: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(root / "scripts" / SCRIPT.name), str(root / "bundle.tar.gz")],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_wheelhouse_requires_exact_identity_release_filename(tmp_path: Path) -> None:
    root, env = _stage_root(tmp_path)
    exact = root / ".dist" / "arkhai_kit_identity-0.3.0-py3-none-any.whl"
    exact.rename(root / ".dist" / "arkhai_kit_identity-0.1.0-py3-none-any.whl")

    result = _run(root, env)

    assert result.returncode == 2
    assert "arkhai_kit_identity-0.3.0-py3-none-any.whl" in result.stderr


def test_wheelhouse_rejects_hosted_fixture_distribution(tmp_path: Path) -> None:
    root, env = _stage_root(tmp_path)
    fixture = root / ".dist" / "arkhai_hosted_settlement_e2e-0.2.0-py3-none-any.whl"
    fixture.write_bytes(b"retired fixture")

    result = _run(root, env)

    assert result.returncode == 2
    assert "cannot contain hosted service/provider distribution" in result.stderr


def test_wheelhouse_rejects_incomplete_hosted_identity_contract(
    tmp_path: Path,
) -> None:
    root, env = _stage_root(tmp_path)
    trust_path = root / "manifests" / "hosted-settlement-v0.2.0-trust.json"
    trust = json.loads(trust_path.read_text(encoding="utf-8"))
    trust["identity_contract"]["capabilities"].remove("account-owner-retirement.v1")
    trust_path.write_text(json.dumps(trust), encoding="utf-8")

    result = _run(root, env)

    assert result.returncode != 0
    assert "exact identity contract" in result.stderr


def test_wheelhouse_rejects_hosted_seller_entry_point(tmp_path: Path) -> None:
    root, env = _stage_root(
        tmp_path,
        hosted_entry_points=(
            "[console_scripts]\n"
            "hosted-settlement-seller = hosted_settlement_client.seller:main\n"
        ),
    )

    result = _run(root, env)

    assert result.returncode != 0
    assert "console-script entry-point metadata" in result.stderr

@pytest.mark.parametrize(
    "member",
    (
        "hosted_settlement_service/api.py",
        "stripe/__init__.py",
        "hosted_settlement_client/database.py",
        "hosted_settlement_client/migrations/0005.py",
        "hosted_settlement_client/providers.py",
        "hosted_settlement_client/storage.py",
        "hosted_settlement_client/webhooks.py",
    ),
)
def test_wheelhouse_rejects_service_or_provider_module_in_client(
    tmp_path: Path,
    member: str,
) -> None:
    root, env = _stage_root(tmp_path, hosted_extra_member=member)

    result = _run(root, env)

    assert result.returncode != 0
    assert "service/provider implementation" in result.stderr


def test_wheelhouse_rejects_portable_lock_source_leakage(tmp_path: Path) -> None:
    root, env = _stage_root(
        tmp_path,
        lock_extra="""

[[package]]
name = "sibling-package"
version = "1.0.0"
source = { directory = "../sibling" }
""",
    )

    result = _run(root, env)

    assert result.returncode != 0
    assert "portable review lock retains repository source paths" in result.stderr


def test_wheelhouse_does_not_treat_project_name_as_dependency_pin(
    tmp_path: Path,
) -> None:
    root, env = _stage_root(tmp_path)
    pyproject = root / "project" / "pyproject.toml"
    pyproject.write_text(
        pyproject.read_text(encoding="utf-8").replace(
            'name = "fixture-project"',
            'name = "arkhai-kit-identity"',
        ),
        encoding="utf-8",
    )
    lockfile = root / "project" / "uv.lock"
    lockfile.write_text(
        lockfile.read_text(encoding="utf-8").replace(
            'name = "fixture-project"',
            'name = "arkhai-kit-identity"',
        ),
        encoding="utf-8",
    )

    result = _run(root, env)

    assert result.returncode == 0, result.stderr


def test_wheelhouse_checks_identity_package_record_not_dependency_reference(
    tmp_path: Path,
) -> None:
    root, env = _stage_root(
        tmp_path,
        lock_extra="""

[[package]]
name = "arkhai-kit-identity"
version = "0.3.0"
source = { registry = "../.dist" }
wheels = [
    { path = "../.dist/arkhai_kit_identity-0.3.0-py3-none-any.whl" },
]
""",
    )
    lockfile = root / "project" / "uv.lock"
    lockfile.write_text(
        lockfile.read_text(encoding="utf-8").replace(
            'source = { editable = "." }',
            'source = { editable = "." }\n'
            'dependencies = [{ name = "arkhai-kit-identity" }]',
        ),
        encoding="utf-8",
    )

    result = _run(root, env)

    assert result.returncode == 0, result.stderr


def test_wheelhouse_packages_external_release_inputs_and_portable_lock(
    tmp_path: Path,
) -> None:
    root, env = _stage_root(tmp_path)

    result = _run(root, env)

    assert result.returncode == 0, result.stderr
    assert (root / "bundle.tar.gz").is_file()
    assert "Created" in result.stdout
    with tarfile.open(root / "bundle.tar.gz", "r:gz") as archive:
        member = archive.extractfile("./release/artifact-pins.json")
        assert member is not None
        pins = json.load(member)
    assert pins["schema_version"] == 2
    assert pins["settlement_config_schema_version"] == 1
    identity_path = root / ".dist" / "arkhai_kit_identity-0.3.0-py3-none-any.whl"
    assert pins["identity_wheel"] == {
        "filename": identity_path.name,
        "sha256": hashlib.sha256(identity_path.read_bytes()).hexdigest(),
    }
    producer = pins["producer_release"]
    assert producer["release_version"] == "0.2.0"
    assert producer["api_version"] == "0.2.0"
    assert producer["schema_version"] == 5
    assert producer["funding_profiles"] == [
        "card.v1",
        "us_bank_transfer.v1",
        "us_ach_debit.v1",
    ]
    assert producer["client_wheel"] == {
        "filename": "arkhai_hosted_settlement_client-0.2.0-py3-none-any.whl",
        "sha256": hashlib.sha256(
            (
                root
                / ".dist"
                / "arkhai_hosted_settlement_client-0.2.0-py3-none-any.whl"
            ).read_bytes()
        ).hexdigest(),
        "entry_point_metadata": False,
    }
    assert pins["consumer_release"] == {
        "repository": "arkhai/simple-market-service",
        "source_commit": "34" * 20,
        "wheels": {
            "arkhai_kit_identity-0.3.0-py3-none-any.whl": hashlib.sha256(
                identity_path.read_bytes()
            ).hexdigest()
        },
    }
