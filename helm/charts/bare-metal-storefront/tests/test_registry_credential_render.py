"""The registry publication credential reaches the storefront only by reference.

Values are synthetic: the Secret name refers to nothing real.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import yaml

CHART = Path(__file__).resolve().parents[1]
VALUES = CHART / "examples" / "production-values.yaml"
KEY_ENV = "BARE_METAL_STOREFRONT_REGISTRY_API_KEY"


def _render(*extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["helm", "template", "bare-metal-test", str(CHART), "--values", str(VALUES), *extra],
        check=False,
        capture_output=True,
        text=True,
    )


def _container_env(manifest: str) -> dict[str, dict]:
    for document in yaml.safe_load_all(manifest):
        if document and document.get("kind") == "Deployment":
            container = document["spec"]["template"]["spec"]["containers"][0]
            return {item["name"]: item for item in container.get("env", [])}
    raise AssertionError("chart rendered no Deployment")


def test_open_registry_renders_no_publication_credential() -> None:
    """An empty entry would hand the client a malformed bearer instead of none."""
    rendered = _render()
    assert rendered.returncode == 0, rendered.stderr

    assert KEY_ENV not in _container_env(rendered.stdout)


def test_write_gated_registry_binds_the_credential_by_secret_reference() -> None:
    rendered = _render(
        "--set-string", "registryApiKeySecret.name=example-registry-key",
        "--set-string", "registryApiKeySecret.key=api-key",
    )
    assert rendered.returncode == 0, rendered.stderr

    entry = _container_env(rendered.stdout)[KEY_ENV]
    assert "value" not in entry
    assert entry["valueFrom"] == {
        "secretKeyRef": {"name": "example-registry-key", "key": "api-key"}
    }


def test_credential_reference_without_a_key_fails_the_render() -> None:
    rendered = _render(
        "--set-string", "registryApiKeySecret.name=example-registry-key",
        "--set-string", "registryApiKeySecret.key=",
    )

    assert rendered.returncode != 0


def test_a_literal_credential_cannot_be_supplied_as_a_value() -> None:
    rendered = _render(
        "--set-string", "registryApiKeySecret.name=example-registry-key",
        "--set-string", "registryApiKeySecret.value=synthetic-dev-key",
    )

    assert rendered.returncode != 0
