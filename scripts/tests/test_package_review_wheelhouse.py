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


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "package-review-wheelhouse.sh"
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


def _hosted_client_wheel(*, entry_points: str | None = None) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, mode="w") as archive:
        archive.writestr("hosted_settlement_client/__init__.py", "")
        archive.writestr(
            "arkhai_hosted_settlement_client-0.1.0.dist-info/METADATA",
            "Name: arkhai-hosted-settlement-client\nVersion: 0.1.0\n",
        )
        if entry_points is not None:
            archive.writestr(
                "arkhai_hosted_settlement_client-0.1.0.dist-info/entry_points.txt",
                entry_points,
            )
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
) -> tuple[Path, dict[str, str]]:
    root = tmp_path / "repo"
    (root / "scripts").mkdir(parents=True)
    (root / "manifests").mkdir()
    (root / ".dist").mkdir()
    (root / "project").mkdir()
    shutil.copy2(SCRIPT, root / "scripts" / SCRIPT.name)

    (root / ".dist" / "arkhai_kit_identity-0.2.0-py3-none-any.whl").write_bytes(
        b"identity-0.2.0"
    )
    hosted_client_wheel = _hosted_client_wheel(entry_points=hosted_entry_points)
    (root / ".dist" / "arkhai_hosted_settlement_client-0.1.0-py3-none-any.whl").write_bytes(
        hosted_client_wheel
    )
    manifest = {"payload": {"identity_contract": _IDENTITY_CONTRACT}}
    (root / ".dist" / "release-manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    trust = {
        "contract_version": "arkhai.hosted-settlement-release.v2",
        "schema_version": 4,
        "identity_contract": _IDENTITY_CONTRACT,
    }
    (root / "manifests" / "hosted-settlement-v0.1.0-trust.json").write_text(
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
    exact = root / ".dist" / "arkhai_kit_identity-0.2.0-py3-none-any.whl"
    exact.rename(root / ".dist" / "arkhai_kit_identity-0.1.0-py3-none-any.whl")

    result = _run(root, env)

    assert result.returncode == 2
    assert "arkhai_kit_identity-0.2.0-py3-none-any.whl" in result.stderr


def test_wheelhouse_rejects_incomplete_hosted_identity_contract(
    tmp_path: Path,
) -> None:
    root, env = _stage_root(tmp_path)
    trust_path = root / "manifests" / "hosted-settlement-v0.1.0-trust.json"
    trust = json.loads(trust_path.read_text(encoding="utf-8"))
    trust["identity_contract"]["capabilities"].remove(
        "account-owner-retirement.v1"
    )
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
    assert "must not contain seller entry-point metadata" in result.stderr


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
version = "0.2.0"
source = { registry = "../.dist" }
wheels = [
    { path = "../.dist/arkhai_kit_identity-0.2.0-py3-none-any.whl" },
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
    assert pins["schema_version"] == 1
    assert pins["settlement_config_schema_version"] == 1
    assert pins["identity_wheel"] == {
        "filename": "arkhai_kit_identity-0.2.0-py3-none-any.whl",
        "sha256": hashlib.sha256(b"identity-0.2.0").hexdigest(),
    }
    assert pins["hosted_client_wheel"] == {
        "filename": "arkhai_hosted_settlement_client-0.1.0-py3-none-any.whl",
        "sha256": hashlib.sha256(_hosted_client_wheel()).hexdigest(),
        "entry_point_metadata": False,
    }
