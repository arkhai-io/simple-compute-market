from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "verify-marketplace-release.py"
SPEC = importlib.util.spec_from_file_location("verify_marketplace_release", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

COMMIT = "a" * 40
WORKFLOW_REF = ".github/workflows/release.yml@refs/tags/marketplace-v0.2.0"
RUN_ID = "123456"
IMAGE_DIGEST = "sha256:" + "b" * 64


def _sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _release(tmp_path: Path) -> tuple[Path, str]:
    artifacts: dict[str, dict[str, str]] = {}
    for name, filename in {
        "wheelhouse": "marketplace-wheelhouse.tar.gz",
        "settlement_config_schema": "settlement-config-schema.json",
        "provenance": "provenance.intoto.json",
    }.items():
        path = tmp_path / filename
        path.write_bytes(f"{name}-release-artifact".encode())
        artifacts[name] = {"filename": filename, "sha256": _sha256(path)}
    manifest = tmp_path / "marketplace-release-manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "contract": "arkhai.marketplace-release.v1",
                "repository": "arkhai/simple-market-service",
                "source_commit": COMMIT,
                "workflow_ref": WORKFLOW_REF,
                "workflow_run_id": RUN_ID,
                "service_image": {
                    "reference": "ghcr.io/arkhai/simple-market-service",
                    "digest": IMAGE_DIGEST,
                },
                "artifacts": artifacts,
            },
            separators=(",", ":"),
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return manifest, _sha256(manifest)


def _verify(manifest: Path, digest: str):
    return MODULE.verify_marketplace_release(
        manifest_path=manifest,
        expected_manifest_sha256=digest,
        expected_commit=COMMIT,
        expected_workflow_ref=WORKFLOW_REF,
        expected_workflow_run_id=RUN_ID,
        expected_image_digest=IMAGE_DIGEST,
    )


def test_exact_attested_marketplace_release_set_is_accepted(tmp_path: Path) -> None:
    manifest, digest = _release(tmp_path)

    result = _verify(manifest, digest)

    assert result["service_image_reference"] == "ghcr.io/arkhai/simple-market-service"
    assert result["service_image_digest"] == IMAGE_DIGEST
    assert set(result["artifacts"]) == {
        "wheelhouse",
        "settlement_config_schema",
        "provenance",
    }


@pytest.mark.parametrize(
    "mutation",
    ["stale_manifest", "partial_artifacts", "wrong_image", "changed_wheelhouse"],
)
def test_stale_partial_or_mismatched_marketplace_release_fails_closed(
    tmp_path: Path,
    mutation: str,
) -> None:
    manifest, digest = _release(tmp_path)
    if mutation == "stale_manifest":
        digest = "sha256:" + "c" * 64
    elif mutation == "changed_wheelhouse":
        (tmp_path / "marketplace-wheelhouse.tar.gz").write_bytes(b"changed")
    else:
        value = json.loads(manifest.read_text(encoding="utf-8"))
        if mutation == "partial_artifacts":
            value["artifacts"].pop("provenance")
        else:
            value["service_image"]["digest"] = "sha256:" + "d" * 64
        manifest.write_text(
            json.dumps(value, separators=(",", ":"), sort_keys=True),
            encoding="utf-8",
        )
        digest = _sha256(manifest)

    with pytest.raises(MODULE.MarketplaceReleaseVerificationError):
        _verify(manifest, digest)
