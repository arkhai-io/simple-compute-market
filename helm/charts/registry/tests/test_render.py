"""The registry chart's migration init container.

The registry refuses a database `registry-migrate` has not brought to its
script head, so the command runs as the pod's one init container: from the
application's image, with the application's resolver variables and profile
files, which name the database, over the same data volume at the same path,
before the application container, which runs the application alone. Both
instances of the chart render it — the `registry` instance and its
`api-credits-registry` alias — and a disabled instance renders nothing.
Standard library only: values are written as JSON, which is YAML.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

CHART = Path(__file__).resolve().parents[1]
UMBRELLA = CHART.parents[1]


def _helm_template(release: str, chart: Path, values: dict, *files: Path) -> str:
    with tempfile.NamedTemporaryFile("w", suffix=".json") as handle:
        json.dump(values, handle)
        handle.flush()
        command = ["helm", "template", release, str(chart)]
        for path in (*files, Path(handle.name)):
            command += ["--values", str(path)]
        rendered = subprocess.run(command, check=False, capture_output=True, text=True)
    assert rendered.returncode == 0, rendered.stderr
    return rendered.stdout


def _source(document: str) -> list[str]:
    """The path parts of a rendered document's ``# Source:`` line."""
    for line in document.splitlines():
        if line.startswith("# Source: "):
            return line.removeprefix("# Source: ").split("/")
    return []


def _deployment(manifest: str, chart: str) -> str:
    deployments = [
        document
        for document in manifest.split("\n---")
        if _source(document)[-3:] == [chart, "templates", "deployment.yaml"]
    ]
    assert len(deployments) == 1, f"{len(deployments)} {chart} Deployments rendered"
    return deployments[0]


def _containers(deployment: str, key: str) -> list[str]:
    """Each container under the pod spec's ``key``, as its rendered text."""
    following = deployment.split(f"\n      {key}:\n", 1)
    assert len(following) == 2, f"the Deployment renders no {key}"
    lines = []
    for line in following[1].splitlines():
        if line.strip() and not line.startswith("        "):
            break
        lines.append(line)
    return ("\n" + "\n".join(lines)).split("\n        - name: ")[1:]


def _field(container: str, name: str) -> str:
    (line,) = [
        line for line in container.splitlines() if line.startswith(f"          {name}:")
    ]
    return line.split(":", 1)[1].strip()


def _block(container: str, name: str) -> str:
    """The text of the container's ``name:`` list, without its key line."""
    following = container.split(f"\n          {name}:\n", 1)
    assert len(following) == 2, f"the container renders no {name}"
    lines = []
    for line in following[1].splitlines():
        if not line.startswith("            "):
            break
        lines.append(line)
    return "\n".join(lines)


def _mounts(container: str) -> list[str]:
    return [
        "- " + entry.strip()
        for entry in _block(container, "volumeMounts").split("- ")[1:]
    ]


def _data_mount(mount_path: str) -> str:
    return f'- name: arkhai-data\n              mountPath: "{mount_path}"'


def _assert_migration_first(deployment: str, mount_path: str) -> None:
    assert deployment.index("\n      initContainers:\n") < deployment.index(
        "\n      containers:\n"
    )
    (migration,) = _containers(deployment, "initContainers")
    (application,) = _containers(deployment, "containers")
    assert migration.startswith("migrate\n"), migration
    assert _field(migration, "command") == '["registry-migrate"]'
    assert _field(migration, "image") == _field(application, "image")
    assert _field(migration, "imagePullPolicy") == _field(application, "imagePullPolicy")
    assert _block(migration, "env") == _block(application, "env")
    # The data volume at the application's path, and every profile file the
    # application reads; the signer credential the migration does not read.
    data = _data_mount(mount_path)
    assert data in migration and data in application
    migration_mounts = _mounts(migration)
    application_mounts = _mounts(application)
    assert set(migration_mounts) < set(application_mounts)
    assert {m for m in application_mounts if "registry-identity" not in m} == set(
        migration_mounts
    )
    assert any("config-production.env" in m for m in migration_mounts)
    # The application container runs the application alone.
    command = _block(application, "command")
    assert "core_registry.main:app" in command and "registry-migrate" not in command


def test_the_migration_runs_first_from_the_application_image_over_its_database() -> None:
    for values in (
        {},
        {"persistence": {"enabled": False}},
        {"persistence": {"mountPath": "/data/registry"}},
    ):
        deployment = _deployment(
            _helm_template("registry-test", CHART, values), "registry"
        )
        mount = values.get("persistence", {}).get("mountPath", "/var/lib/arkhai-registry")
        _assert_migration_first(deployment, mount)


def test_the_migration_reads_the_secret_profile_the_application_reads() -> None:
    """A secret profile may state the database URL, so the migration mounts it
    and lists it in its profiles exactly as the application does."""
    values = {"secretProfile": {"secretName": "registry-keys", "profile": "keys"}}
    deployment = _deployment(_helm_template("registry-test", CHART, values), "registry")
    _assert_migration_first(deployment, "/var/lib/arkhai-registry")
    (migration,) = _containers(deployment, "initContainers")
    assert '"/app/config/config-keys.env"' in migration
    assert '"production,keys"' in _block(migration, "env")


def test_each_instance_renders_its_migration_and_a_disabled_one_renders_nothing() -> None:
    values = UMBRELLA / "values.yaml"
    enabled = _helm_template(
        "umbrella", UMBRELLA, {"api-credits-registry": {"enabled": True}}, values
    )
    for chart in ("registry", "api-credits-registry"):
        _assert_migration_first(
            _deployment(enabled, chart), "/var/lib/arkhai-registry"
        )
    disabled = _helm_template(
        "umbrella", UMBRELLA, {"api-credits-registry": {"enabled": False}}, values
    )
    assert not [
        document
        for document in disabled.split("\n---")
        if "api-credits-registry" in _source(document)
    ]
    _assert_migration_first(_deployment(disabled, "registry"), "/var/lib/arkhai-registry")


if __name__ == "__main__":
    test_the_migration_runs_first_from_the_application_image_over_its_database()
    test_the_migration_reads_the_secret_profile_the_application_reads()
    test_each_instance_renders_its_migration_and_a_disabled_one_renders_nothing()
    print("registry chart render checks passed")
