"""The mediation lane double runs in the local release alone, under its fixed Service name.

Each test renders the umbrella with the values a release is installed with, or
the chart alone, and asserts on the rendered text. Standard library only: an
overlay is written as JSON, which is YAML.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

CHART = Path(__file__).resolve().parents[1]
UMBRELLA = CHART.parents[1]
VALUES = UMBRELLA / "values.yaml"
LOCAL = UMBRELLA / "local-values.yaml"
TOPOLOGY = UMBRELLA / "bare-metal-release-values.yaml"


def _render(*values: Path, overlay: dict | None = None, chart: Path = UMBRELLA) -> str:
    with tempfile.NamedTemporaryFile("w", suffix=".json") as handle:
        json.dump(overlay or {}, handle)
        handle.flush()
        command = ["helm", "template", "arkhai-node-operator", str(chart)]
        for path in (*values, Path(handle.name)):
            command += ["--values", str(path)]
        rendered = subprocess.run(command, check=False, capture_output=True, text=True)
    assert rendered.returncode == 0, rendered.stderr
    return rendered.stdout


def _documents(manifest: str) -> list[str]:
    """The documents the double's chart renders, through the umbrella or alone."""
    return [
        document
        for document in manifest.split("\n---\n")
        if any(line.startswith("# Source: ") and "mediation-lane-double/templates/" in line for line in document.splitlines())
    ]


def _kind(documents: list[str], kind: str) -> list[str]:
    return [document for document in documents if f"kind: {kind}" in document.splitlines()]


def test_the_double_is_disabled_by_default() -> None:
    assert not _documents(_render(VALUES))


def test_the_local_release_runs_one_double_behind_the_service_mediation_double() -> None:
    documents = _documents(_render(VALUES, LOCAL))
    (deployment,) = _kind(documents, "Deployment")
    (service,) = _kind(documents, "Service")

    # The name the double's lane-CA leaf is issued for and the registry's
    # recommended origin names.
    assert "  name: mediation-double" in service.splitlines()
    assert re.search(r"^\s+port: 8443\n\s+targetPort: https$", service, re.MULTILINE)
    assert "  name: arkhai-node-operator-mediation-lane-double" in deployment.splitlines()
    # The Service selects the Deployment's pods.
    selector = re.search(r"^  selector:\n((?:    \S.*\n)+)", service, re.MULTILINE).group(1)
    labels = re.search(r"^      labels:\n((?:        \S.*\n)+)", deployment, re.MULTILINE).group(1)
    assert {line.strip() for line in selector.splitlines()} <= {line.strip() for line in labels.splitlines()}
    assert "app.kubernetes.io/name: mediation-lane-double" in selector
    assert 'image: "arkhai:mediation-lane-double"' in deployment
    assert "replicas: 1" in deployment and "type: Recreate" in deployment
    # The probes ask over HTTPS, which the kubelet does not verify, so they hold
    # whichever certificate the double serves.
    assert deployment.count("scheme: HTTPS") == 3
    # The image's committed TLS files are served: nothing is mounted over them.
    assert "volumes:" not in deployment and "volumeMounts:" not in deployment


def test_the_bare_metal_release_runs_no_double() -> None:
    """The Service name is not release-scoped, so the namespace's second release
    runs none."""
    assert not _documents(_render(VALUES, LOCAL, TOPOLOGY))


def test_an_existing_tls_secret_is_served_over_the_images_files() -> None:
    overlay = {"mediation-lane-double": {"tls": {"existingSecret": "mediation-double-tls"}}}
    (deployment,) = _kind(_documents(_render(VALUES, LOCAL, overlay=overlay)), "Deployment")

    for path in ("double.pem", "double.key.pem"):
        assert re.search(
            rf"- name: server-tls\n\s+mountPath: /opt/mediation-lane-double/tls/{re.escape(path)}\n"
            rf"\s+subPath: {re.escape(path)}\n\s+readOnly: true",
            deployment,
        ), path
    assert re.search(
        r'secretName: "mediation-double-tls"\n\s+items:\n\s+- key: tls\.crt\n\s+path: double\.pem\n'
        r"\s+- key: tls\.key\n\s+path: double\.key\.pem",
        deployment,
    )


def test_the_chart_alone_names_its_service_mediation_double() -> None:
    (service,) = _kind(_documents(_render(chart=CHART)), "Service")

    assert "  name: mediation-double" in service.splitlines()


def main() -> int:
    failures = 0
    for name, test in sorted(globals().items()):
        if name.startswith("test_") and callable(test):
            try:
                test()
                print(f"ok    {name}")
            except Exception as exc:  # noqa: BLE001 - every error is a failed test
                failures += 1
                print(f"FAIL  {name}: {type(exc).__name__}: {exc}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
