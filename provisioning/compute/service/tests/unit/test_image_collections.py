"""The image installs exactly the Ansible collections the domains declare."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[5]
DOCKERFILE = REPO_ROOT / "provisioning/compute/service/Dockerfile"
DOMAIN_REQUIREMENTS = sorted(
    REPO_ROOT.glob("domains/*/provisioning/iac/ansible/requirements.yml")
)


def _declared() -> set[str]:
    declared = set()
    for path in DOMAIN_REQUIREMENTS:
        for collection in yaml.safe_load(path.read_text())["collections"]:
            name = collection["name"].replace(".", "-")
            declared.add(f"{name}-{collection['version']}")
    return declared


def test_every_domain_that_runs_playbooks_declares_its_collections() -> None:
    domains = {path.relative_to(REPO_ROOT).parts[1] for path in DOMAIN_REQUIREMENTS}
    assert {"vms", "bare_metal"} <= domains


def test_the_image_fetches_and_installs_the_union_of_the_domains_collections() -> None:
    text = DOCKERFILE.read_text()
    fetched = set(re.findall(r'^\s+"([a-z]+-[a-z]+-[0-9.]+)" \\$', text, re.MULTILINE))
    installed = set(re.findall(r"/tmp/galaxy-tarballs/([a-z]+-[a-z]+-[0-9.]+)\.tar\.gz", text))

    assert fetched == _declared()
    assert installed == _declared()
