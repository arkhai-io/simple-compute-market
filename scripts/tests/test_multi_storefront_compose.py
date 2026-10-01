"""The development storefronts bind independent provisioning authorities."""

import json
import subprocess
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_storefront_authorities_are_isolated(tmp_path):
    env_file = tmp_path / "identities.env"
    with env_file.open("w") as output:
        subprocess.run(
            ["make", "-s", "--no-print-directory", "e2e-dev-identities-env"],
            cwd=REPO_ROOT, stdout=output, check=True,
        )
    result = subprocess.run(
        ["docker", "compose", "--env-file", str(env_file),
         "-f", "docker-compose.yml", "-f", "compose.local-identities.yml",
         "config", "--format", "json"],
        cwd=REPO_ROOT, capture_output=True, text=True, check=True,
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
        principal = profile["Identity"]["principal"]
        assert env["PROVISIONING_STOREFRONT_IDENTITY__IDENTIFIER"] == (
            "@str " + principal["identifier"]
        )
        assert env["PROVISIONING_STOREFRONT_URL"] == f"http://{seller}-storefront:{port}"
        expected = {
            "scheme": env["PROVISIONING_IDENTITY__SCHEME"],
            "identifier": env["PROVISIONING_IDENTITY__IDENTIFIER"].removeprefix("@str "),
        }
        authority_ids.add(tuple(expected.values()))
        assert profile["provisioning"]["identity"]["principals"] == [expected]
        peer = profile["Identity"]["service_peers"]["provisioning_default"]
        assert peer["principals"] == [expected]
        assert peer["site_id"] == env["PROVISIONING_STOREFRONT_SITE_ID"]
        assert profile["capacity"]["sites"]["default"] == f"http://{authority}:8081"
        assert profile["provisioning"]["service_url"] == f"http://{authority}:8081"
        assert profile["capacity"].get("use_site_projection_for_listings", True)
        assert authority in services[f"{seller}-storefront"]["depends_on"]
        # Database paths are container-local; a shared mount would defeat that.
        assert all(v["target"] != "/app/data" for v in service.get("volumes", []))
    assert len(authority_ids) == 2
    assert services["alice-provisioning"]["environment"]["PROVISIONING_DATABASE_URL"] == (
        "sqlite:////app/data/provisioning.db"
    )
