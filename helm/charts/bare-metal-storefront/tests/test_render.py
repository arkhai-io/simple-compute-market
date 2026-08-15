from __future__ import annotations

import subprocess
from pathlib import Path


CHART = Path(__file__).resolve().parents[1]
VALUES = CHART / "examples" / "production-values.yaml"


def _render(*extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "helm",
            "template",
            "bare-metal-test",
            str(CHART),
            "--values",
            str(VALUES),
            *extra,
        ],
        check=False,
        capture_output=True,
        text=True,
    )


def test_production_values_render_dedicated_secret_bound_role() -> None:
    rendered = _render()
    assert rendered.returncode == 0, rendered.stderr
    manifest = rendered.stdout
    assert "kind: Deployment" in manifest
    assert "kind: Service" in manifest
    assert "kind: PersistentVolumeClaim" in manifest
    assert "image: \"registry.example.com/arkhai/arkhai@sha256:" in manifest
    assert "name: ARKHAI_IDENTITY_CREDENTIAL" in manifest
    assert "name: BARE_METAL_STOREFRONT_SITES" in manifest
    assert "name: \"bare-metal-storefront-identity\"" in manifest
    assert "name: \"bare-metal-storefront-sites\"" in manifest
    assert "path: /health" in manifest
    assert "wait-for-" not in manifest
    for forbidden in (
        "authority_url",
        "private_key",
        "provider_metadata",
        "ARKHAI_IDENTITY_CREDENTIAL\n              value:",
    ):
        assert forbidden not in manifest


def test_missing_site_secret_fails_closed() -> None:
    rendered = _render("--set-string", "siteBindingsSecret.name=")
    assert rendered.returncode != 0


if __name__ == "__main__":
    test_production_values_render_dedicated_secret_bound_role()
    test_missing_site_secret_fails_closed()
