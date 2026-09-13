"""Ansible host-trust rendering for the provisioning chart.

The values used here are synthetic: `example-known-hosts` names no real Secret
and `/pins` is not a path any deployment uses.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import yaml


CHART = Path(__file__).resolve().parents[1]


def _render(*extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["helm", "template", "host-trust-test", str(CHART), *extra],
        check=False,
        capture_output=True,
        text=True,
    )


def _deployment(manifest: str) -> dict:
    for doc in yaml.safe_load_all(manifest):
        if doc and doc.get("kind") == "Deployment":
            return doc
    raise AssertionError("chart rendered no Deployment")


def _serving_container(manifest: str) -> dict:
    containers = _deployment(manifest)["spec"]["template"]["spec"]["containers"]
    return containers[0]


def _env(container: dict) -> dict[str, str]:
    return {
        item["name"]: item.get("value")
        for item in container.get("env", [])
    }


def test_host_trust_is_absent_by_default() -> None:
    rendered = _render()
    assert rendered.returncode == 0, rendered.stderr
    env = _env(_serving_container(rendered.stdout))
    assert "ANSIBLE_HOST_KEY_CHECKING" not in env
    assert "ANSIBLE_SSH_COMMON_ARGS" not in env
    volumes = _deployment(rendered.stdout)["spec"]["template"]["spec"]["volumes"]
    assert all(volume["name"] != "host-key-pins" for volume in volumes)


def test_enabling_pins_binds_checking_and_the_mounted_file_together() -> None:
    rendered = _render(
        "--set", "hostKeyPins.enabled=true",
        "--set", "hostKeyPins.secretName=example-known-hosts",
        "--set", "hostKeyPins.mountPath=/pins",
        "--set", "hostKeyPins.key=pinned_hosts",
    )
    assert rendered.returncode == 0, rendered.stderr
    container = _serving_container(rendered.stdout)
    env = _env(container)

    assert env["ANSIBLE_HOST_KEY_CHECKING"] == "True"
    # The pinned file is the only one consulted: the global file is redirected
    # to /dev/null, so a key trusted image-wide cannot satisfy a connection.
    assert env["ANSIBLE_SSH_COMMON_ARGS"] == (
        "-o StrictHostKeyChecking=yes "
        "-o UserKnownHostsFile=/pins/pinned_hosts "
        "-o GlobalKnownHostsFile=/dev/null"
    )

    mounts = {mount["mountPath"]: mount for mount in container["volumeMounts"]}
    assert mounts["/pins/pinned_hosts"]["name"] == "host-key-pins"
    assert mounts["/pins/pinned_hosts"]["subPath"] == "pinned_hosts"
    assert mounts["/pins/pinned_hosts"]["readOnly"] is True

    volumes = {
        volume["name"]: volume
        for volume in _deployment(rendered.stdout)["spec"]["template"]["spec"]["volumes"]
    }
    assert volumes["host-key-pins"]["secret"]["secretName"] == "example-known-hosts"


def test_enabling_pins_without_a_secret_fails_the_render() -> None:
    rendered = _render("--set", "hostKeyPins.enabled=true")
    assert rendered.returncode != 0
    assert "hostKeyPins.secretName" in rendered.stderr


def test_migration_init_container_carries_no_ssh_trust_environment() -> None:
    rendered = _render(
        "--set", "hostKeyPins.enabled=true",
        "--set", "hostKeyPins.secretName=example-known-hosts",
    )
    assert rendered.returncode == 0, rendered.stderr
    init = _deployment(rendered.stdout)["spec"]["template"]["spec"]["initContainers"][0]
    assert "ANSIBLE_SSH_COMMON_ARGS" not in _env(init)
