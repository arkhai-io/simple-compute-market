"""The development storefronts bind independent provisioning authorities."""

import json
import os
import subprocess
import tomllib
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]


def _site_profile(service: dict) -> dict:
    """The site profile a provisioning service loads: the second of its
    ACTIVE_PROFILES, bound into its CONFIG_DIRECTORY."""
    environment = service["environment"]
    site = environment["ACTIVE_PROFILES"].split(",")[1]
    target = f"{environment['CONFIG_DIRECTORY']}/config-{site}.yml"
    (source,) = [v["source"] for v in service["volumes"] if v["target"] == target]
    return yaml.safe_load(Path(source).read_text(encoding="utf-8"))


def test_storefront_authorities_are_isolated():
    env = {key: value for key, value in os.environ.items() if key != "PROVISIONING_MODE"}
    result = subprocess.run(
        ["docker", "compose",
         "-f", "docker-compose.yml", "-f", "compose.vms-local.yml",
         "-f", "compose.apicredits-local.yml",
         "config", "--format", "json"],
        cwd=REPO_ROOT, capture_output=True, text=True, check=True, env=env,
    )
    services = json.loads(result.stdout)["services"]
    authority_ids = set()
    for seller, authority, port in (
        ("bob", "provisioning", 8001),
        ("alice", "alice-provisioning", 8002),
    ):
        profile = tomllib.loads(
            (REPO_ROOT / f"domains/vms/storefront/storefront.{seller}.toml").read_text()
        )
        service = services[authority]
        env = service["environment"]
        site = _site_profile(service)
        principal = profile["Identity"]["principal"]
        assert site["storefront_identity"] == principal
        assert env["PROVISIONING_STOREFRONT_URL"] == f"http://{seller}-storefront:{port}"
        expected = site["identity"]
        authority_ids.add(tuple(expected.values()))
        # The site's responses verify against its service peer alone.
        assert "identity" not in profile["provisioning"]
        peer = profile["Identity"]["service_peers"]["provisioning_default"]
        assert peer["principals"] == [expected]
        assert peer["site_id"] == site["storefront_site_id"]
        assert profile["capacity"]["sites"]["default"] == f"http://{authority}:8081"
        assert profile["provisioning"]["service_url"] == f"http://{authority}:8081"
        assert "use_site_projection_for_listings" not in profile["capacity"]
        assert authority in services[f"{seller}-storefront"]["depends_on"]
        # Database paths are container-local; a shared mount would defeat that.
        assert all(v["target"] != "/app/data" for v in service.get("volumes", []))
    assert len(authority_ids) == 2
    assert services["alice-provisioning"]["environment"]["PROVISIONING_DATABASE_URL"] == (
        "sqlite:////app/data/provisioning.db"
    )
