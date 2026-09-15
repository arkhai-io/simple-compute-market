"""Pinned SSH host trust in the provisioning chart.

The values here are synthetic: ``example-known-hosts`` names no real Secret and
``/pins`` is not a path any deployment uses.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import yaml

CHART = Path(__file__).resolve().parents[1]
PIN_PATH_ENV = "PROVISIONING_BARE_METAL_SSH_KNOWN_HOSTS_PATH"
ENABLED = (
    "--set", "hostKeyPins.enabled=true",
    "--set", "hostKeyPins.secretName=example-known-hosts",
    "--set", "hostKeyPins.mountPath=/pins",
    "--set", "hostKeyPins.key=pinned_hosts",
)


def _render(*extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["helm", "template", "host-trust-test", str(CHART), *extra],
        check=False,
        capture_output=True,
        text=True,
    )


def _pod_spec(manifest: str) -> dict:
    for document in yaml.safe_load_all(manifest):
        if document and document.get("kind") == "Deployment":
            return document["spec"]["template"]["spec"]
    raise AssertionError("chart rendered no Deployment")


def _env(container: dict) -> dict[str, str | None]:
    return {item["name"]: item.get("value") for item in container.get("env", [])}


def test_host_trust_is_absent_by_default() -> None:
    rendered = _render()
    assert rendered.returncode == 0, rendered.stderr
    pod = _pod_spec(rendered.stdout)

    assert PIN_PATH_ENV not in _env(pod["containers"][0])
    assert all(volume["name"] != "host-key-pins" for volume in pod["volumes"])


def test_enabled_pins_mount_read_only_and_name_the_file_to_the_service() -> None:
    rendered = _render(*ENABLED)
    assert rendered.returncode == 0, rendered.stderr
    pod = _pod_spec(rendered.stdout)
    container = pod["containers"][0]

    assert _env(container)[PIN_PATH_ENV] == "/pins/pinned_hosts"
    mounts = {mount["mountPath"]: mount for mount in container["volumeMounts"]}
    assert mounts["/pins/pinned_hosts"] == {
        "name": "host-key-pins",
        "mountPath": "/pins/pinned_hosts",
        "subPath": "pinned_hosts",
        "readOnly": True,
    }
    volumes = {volume["name"]: volume for volume in pod["volumes"]}
    assert volumes["host-key-pins"]["secret"]["secretName"] == "example-known-hosts"


def test_trust_is_applied_per_spawn_not_to_the_whole_container() -> None:
    """VM playbooks keep their existing behaviour; only bare-metal spawns pin."""
    rendered = _render(*ENABLED)
    assert rendered.returncode == 0, rendered.stderr
    env = _env(_pod_spec(rendered.stdout)["containers"][0])

    assert "ANSIBLE_HOST_KEY_CHECKING" not in env
    assert "ANSIBLE_SSH_COMMON_ARGS" not in env


def test_enabled_pins_without_a_secret_fail_the_render() -> None:
    rendered = _render("--set", "hostKeyPins.enabled=true")

    assert rendered.returncode != 0
    assert "hostKeyPins.secretName" in rendered.stderr


def test_pin_contents_cannot_be_supplied_as_values() -> None:
    """Pins arrive only by Secret reference, never inline in chart values."""
    rendered = _render(*ENABLED, "--set-string", "hostKeyPins.knownHosts=example")

    assert rendered.returncode != 0


def test_migration_container_carries_no_ssh_trust() -> None:
    rendered = _render(*ENABLED)
    assert rendered.returncode == 0, rendered.stderr
    init = _pod_spec(rendered.stdout)["initContainers"][0]

    assert PIN_PATH_ENV not in _env(init)
    assert all(mount["name"] != "host-key-pins" for mount in init.get("volumeMounts", []))
