"""The storefront chart passes an agent's config through and adds only what the release knows.

Each test renders the umbrella chart, because the storefront subchart takes its
registry, provisioning, and identity coordinates from the umbrella's globals,
and reads the rendered ``storefront.json`` back with ``json``. Standard library
only: values are written as JSON, which is YAML.

Set ``STOREFRONT_PYTHON`` to the storefront environment's interpreter to also
load one rendered document with the storefront's own configuration loader.
"""

from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

CHART = Path(__file__).resolve().parents[1]
UMBRELLA = CHART.parents[1]
RELEASE = "rt"
REGISTRY_URL = f"http://{RELEASE}-registry:8080"
PROVISIONING_URL = "http://arkhai-node-operator-provisioning:8081"
ACTIVE_REGISTRY = {"scheme": "eip191", "identifier": "0x90f79bf6eb2c4f870365e785982e1f101e93b906"}
ACTIVE_PROVISIONING = {"scheme": "eip191", "identifier": "0xf39fd6e51aad88f6f4ce6ab8827279cfffb92266"}

# A complete agent in the default release's shape; tests copy and edit it.
BASE_AGENT = {
    "name": "bob",
    "port": 8001,
    "component": "seller",
    "identity": {"credentialSecret": {"name": "arkhai-bob-identity", "key": "credential"}},
    "internalRegistryTrust": {"authority": "registry-a", "principals": [ACTIVE_REGISTRY]},
    "secret": {"createSecret": False, "secretName": "arkhai-bob-runtime"},
    "config": {
        "agent_id": "bob",
        "storefront_domains": [
            {
                "contribution": "vms",
                "offering_mode": "vm",
                "domain_identity": "compute.v1",
                "contract_version": "1.0",
            }
        ],
        "Identity": {
            "principal": {"scheme": "eip191", "identifier": "0x3c44cdddb6a900fa2b585dd299e03d12fa4293bc"},
            "service_peers": {
                "provisioning_default": {
                    "role": "service",
                    "site_id": "default",
                    "principals": [ACTIVE_PROVISIONING],
                }
            },
        },
        "provisioning": {"identity": {"principals": [ACTIVE_PROVISIONING]}},
        "Settlement": {"priority": []},
    },
}


def _agent(**changes) -> dict:
    agent = copy.deepcopy(BASE_AGENT)
    agent.update(changes)
    return agent


def _without(key: str) -> dict:
    agent = _agent()
    del agent[key]
    return agent


def _with_config(**changes) -> dict:
    agent = _agent()
    agent["config"].update(changes)
    return agent


def _render(*, agent: dict | None = None, extra: dict | None = None, files=()) -> subprocess.CompletedProcess[str]:
    values: dict = {"storefront": {"agents": [agent if agent is not None else _agent()]}}
    if extra:
        values["storefront"].update(extra)
    with tempfile.NamedTemporaryFile("w", suffix=".json") as handle:
        json.dump(values, handle)
        handle.flush()
        command = ["helm", "template", RELEASE, str(UMBRELLA), "--values", str(UMBRELLA / "values.yaml")]
        for fixture in files:
            command += ["--values", str(UMBRELLA / "fixtures" / fixture)]
        if agent is not None or extra:
            command += ["--values", handle.name]
        return subprocess.run(command, check=False, capture_output=True, text=True)


def _ok(rendered: subprocess.CompletedProcess[str]) -> str:
    assert rendered.returncode == 0, rendered.stderr
    return rendered.stdout


def _source(manifest: str, path: str) -> str:
    """The rendered document whose ``# Source:`` names ``path``."""
    for document in manifest.split("\n---\n"):
        if f"# Source: arkhai-node-operator/charts/storefront/templates/{path}" in document:
            return document
    raise AssertionError(f"{path} not rendered")


def _config(manifest: str) -> dict:
    document = _source(manifest, "configmap.yaml")
    marker = "  storefront.json: |\n"
    assert marker in document, "ConfigMap does not carry storefront.json"
    body = document.split(marker, 1)[1]
    lines = []
    for line in body.splitlines():
        if line and not line.startswith("    "):
            break
        lines.append(line)
    return json.loads(textwrap.dedent("\n".join(lines)))


def _refused(rendered: subprocess.CompletedProcess[str], *names: str) -> None:
    assert rendered.returncode != 0, "render succeeded"
    for name in names:
        assert name in rendered.stderr, f"{name!r} not named in: {rendered.stderr}"


# --- rendering and mounting ------------------------------------------------


def test_default_release_renders_mounts_and_derives_together() -> None:
    manifest = _ok(_render())
    config = _config(manifest)
    deployment = _source(manifest, "deployment.yaml")

    lines = {line.strip() for line in deployment.splitlines()}
    assert {
        "mountPath: /etc/arkhai/storefront.json",
        "subPath: storefront.json",
        "- key: storefront.json",
        "path: storefront.json",
    } <= lines
    assert "storefront.toml" not in manifest
    assert config["port"] == 8001
    assert config["base_url"] == f"http://{RELEASE}-storefront-bob:8001/"
    assert config["db_path"] == "/var/lib/arkhai/agent.db"
    assert config["registry"] == {
        "urls": [REGISTRY_URL],
        "authorities": {REGISTRY_URL: {"authority": "registry-a", "principals": [ACTIVE_REGISTRY]}},
    }
    assert config["provisioning"]["service_url"] == PROVISIONING_URL
    assert config["capacity"] == {"sites": {"default": PROVISIONING_URL}}
    assert config["Settlement"] == {"priority": []}
    assert "wait-for-registry" in deployment
    assert "wait-for-rpc" not in deployment


def test_a_section_the_chart_has_never_heard_of_passes_through_intact() -> None:
    section = {"sinks": {"ops": {"kind": "file", "path": "/var/log/x", "retries": 3, "tags": ["a", "b"]}}, "enabled": True}
    config = _config(_ok(_render(agent=_with_config(Futuristic=section))))

    assert config["Futuristic"] == section


def test_numbers_keep_their_types_and_addresses_stay_strings() -> None:
    address = "0x3c44cdddb6a900fa2b585dd299e03d12fa4293bc"
    config = _config(
        _ok(
            _render(
                agent=_with_config(
                    retention_seconds=2592000,
                    huge=10000000,
                    ratio=2.5,
                    timeout=10.0,
                    amount="123456789012345678901234567890",
                    Wallet={"address": address},
                )
            )
        )
    )

    for key, value in (("retention_seconds", 2592000), ("huge", 10000000), ("timeout", 10)):
        assert config[key] == value and isinstance(config[key], int), key
    assert config["ratio"] == 2.5
    assert config["amount"] == "123456789012345678901234567890"
    assert config["Wallet"]["address"] == address


def test_stated_values_are_rendered_as_stated() -> None:
    external = "http://registry.example:8080"
    agent = _with_config(
        base_url="https://bob.example/",
        db_path="/var/lib/arkhai/custom.db",
        registry={"urls": [external], "authorities": {external: {"authority": "registry-x", "principals": [ACTIVE_REGISTRY]}}},
        provisioning={"service_url": "http://provisioning.example:8081"},
        capacity={"sites": {"west": "http://provisioning.example:8081"}},
    )
    del agent["internalRegistryTrust"]
    manifest = _ok(_render(agent=agent))
    config = _config(manifest)

    assert config["base_url"] == "https://bob.example/"
    assert config["db_path"] == "/var/lib/arkhai/custom.db"
    assert config["registry"] == agent["config"]["registry"]
    assert config["provisioning"] == {"service_url": "http://provisioning.example:8081"}
    assert config["capacity"] == {"sites": {"west": "http://provisioning.example:8081"}}
    assert "wait-for-registry" not in _source(manifest, "deployment.yaml")


def test_a_stated_port_equal_to_the_agents_is_accepted() -> None:
    assert _config(_ok(_render(agent=_with_config(port=8001))))["port"] == 8001


def test_a_differently_spelled_section_is_read_for_release_checks() -> None:
    agent = _agent()
    agent["config"]["identity"] = agent["config"].pop("Identity")
    agent["config"]["settlement"] = {"alkahest": {"enabled": True}}
    del agent["config"]["Settlement"]
    agent["config"]["chains"] = {"anvil": {"chain_id": 31337, "rpc_url": "http://anvil:8545"}}
    manifest = _ok(_render(agent=agent))

    assert "wait-for-rpc" in _source(manifest, "deployment.yaml")
    assert _config(manifest)["identity"]["service_peers"]


def test_a_chain_whose_rpc_url_is_in_the_overlay_is_not_probed() -> None:
    """An RPC URL carrying a credential lives in the Secret overlay; the pod
    spec must not name it, so no readiness probe is rendered for it."""
    agent = _with_config(
        Settlement={"priority": ["alkahest.v1"], "alkahest": {"enabled": True}},
        Chains={"anvil": {"chain_id": 31337}},
    )
    manifest = _ok(_render(agent=agent))

    assert "wait-for-rpc" not in _source(manifest, "deployment.yaml")
    assert "rpc_url" not in _config(manifest)["Chains"]["anvil"]


# --- release checks --------------------------------------------------------


def test_release_disagreements_are_refused_naming_them() -> None:
    cases = {
        "port": (_with_config(port=9000), "differs from the agent's port"),
        "trust missing": (_without("internalRegistryTrust"), "requires internalRegistryTrust"),
        "trust authority": (
            _agent(internalRegistryTrust={"authority": "registry-z", "principals": [ACTIVE_REGISTRY]}),
            "internalRegistryTrust.authority",
        ),
        "trust principal": (
            _agent(internalRegistryTrust={"authority": "registry-a", "principals": [ACTIVE_PROVISIONING]}),
            "internalRegistryTrust.principals",
        ),
        "trust with urls": (
            _with_config(registry={"urls": ["http://registry.example:8080"]}),
            "internalRegistryTrust applies only to the internal registry",
        ),
        "two trust statements": (
            _with_config(registry={"authorities": {REGISTRY_URL: {"authority": "registry-a", "principals": [ACTIVE_REGISTRY]}}}),
            "state one",
        ),
        "provisioning trust": (
            _with_config(provisioning={"identity": {"principals": [ACTIVE_REGISTRY]}}),
            "provisioning.identity.principals",
        ),
    }
    peerless = _agent()
    peerless["config"]["Identity"]["service_peers"] = {}
    cases["service peer"] = (peerless, "Identity.service_peers")
    for label, (agent, message) in cases.items():
        rendered = _render(agent=agent)
        assert rendered.returncode != 0, label
        assert message in rendered.stderr, f"{label}: {rendered.stderr}"


def test_two_spellings_of_one_key_are_refused_at_any_depth() -> None:
    _refused(_render(agent=_with_config(settlement={"priority": []})), '"Settlement"', '"settlement"')
    _refused(
        _render(agent=_with_config(provisioning={"service_url": "http://a", "SERVICE_URL": "http://b"})),
        "config.provisioning",
        '"SERVICE_URL"',
    )
    domains = copy.deepcopy(BASE_AGENT["config"]["storefront_domains"])
    domains[0]["Contribution"] = "vms"
    _refused(_render(agent=_with_config(storefront_domains=domains)), "config.storefront_domains[0]")


def test_release_owned_keys_are_matched_in_any_spelling() -> None:
    """The loader reads keys case-insensitively; so does every chart check."""
    _refused(_render(agent=_with_config(Port=9000)), "config.Port 9000 differs")
    config = _config(_ok(_render(agent=_with_config(Port=8001, Base_URL="https://bob.example/", DB_Path="/data/x.db"))))
    assert config["Port"] == 8001 and "port" not in config
    assert config["Base_URL"] == "https://bob.example/" and "base_url" not in config
    assert config["DB_Path"] == "/data/x.db" and "db_path" not in config

    external = "http://registry.example:8080"
    agent = _with_config(Registry={"URLS": [external], "authorities": {external: {"authority": "registry-x", "principals": [ACTIVE_REGISTRY]}}})
    del agent["internalRegistryTrust"]
    manifest = _ok(_render(agent=agent))
    assert _config(manifest)["Registry"]["URLS"] == [external]
    assert "urls" not in _config(manifest)["Registry"]
    assert "wait-for-registry" not in _source(manifest, "deployment.yaml")

    agent = _with_config(
        Settlement={"priority": ["alkahest.v1"], "alkahest": {"enabled": True}},
        CHAINS={"anvil": {"chain_id": 31337, "RPC_URL": "http://anvil:8545"}},
    )
    assert "wait-for-rpc" in _source(_ok(_render(agent=agent)), "deployment.yaml")


def test_typed_fields_are_accepted_in_any_spelling() -> None:
    """The values schema accepts what the loader reads; the release checks
    still find principals and peers however their fields are spelled."""
    agent = _agent()
    identity = agent["config"]["Identity"]
    identity["Principal"] = identity.pop("principal")
    peer = identity["service_peers"]["provisioning_default"]
    identity["Service_Peers"] = {
        "provisioning_default": {
            "Role": peer["role"],
            "SITE_ID": peer["site_id"],
            "Principals": [
                {"Scheme": p["scheme"], "Identifier": p["identifier"]} for p in peer["principals"]
            ],
        }
    }
    del identity["service_peers"]
    agent["config"]["Settlement"] = {"Priority": [], "Arkhai_Payments": {"Enabled": False}}
    config = _config(_ok(_render(agent=agent)))

    assert config["Identity"]["Principal"] == BASE_AGENT["config"]["Identity"]["principal"]
    assert config["Settlement"] == {"Priority": [], "Arkhai_Payments": {"Enabled": False}}

    wrong = copy.deepcopy(agent)
    wrong["config"]["Identity"]["Service_Peers"]["provisioning_default"]["Principals"] = [
        {"Scheme": "eip191", "Identifier": ACTIVE_REGISTRY["identifier"]}
    ]
    _refused(_render(agent=wrong), "Identity.service_peers")


def test_retired_and_secret_keys_are_refused_in_any_spelling() -> None:
    for key in ("Seller", "RegistryUrl", "STOREFRONTDOMAINS", "Chain"):
        _refused(_render(agent=_with_config(**{key: {}})), key)
    _refused(_render(agent=_with_config(Wallet={"Private_Key": "0xabc"})), "Private_Key")
    _refused(_render(agent=_with_config(registry={"AUTH": {"http://x": "t"}})), "AUTH")


def test_a_stated_port_must_be_a_number_equal_to_the_agents() -> None:
    _refused(_render(agent=_with_config(port="8001")), "must be a number")
    _refused(_render(agent=_with_config(port=8001.5)), "differs from the agent's port")


# --- values schema ---------------------------------------------------------


def test_retired_values_are_refused_naming_the_key() -> None:
    cases = {
        "seller": _with_config(seller={"agentId": "bob"}),
        "storefrontDomains": _with_config(storefrontDomains=[]),
        "registryAuthority": _with_config(registryAuthority={}),
        "registryUrl": _with_config(registryUrl="http://x"),
        "configMapName": _with_config(configMapName="x"),
        "agentId": _agent(agentId="bob"),
        "autoRegister": _agent(autoRegister=True),
        "rootPath": _agent(rootPath="/x"),
        "principal": _agent(identity={"credentialSecret": BASE_AGENT["identity"]["credentialSecret"], "principal": {}}),
    }
    for key, agent in cases.items():
        _refused(_render(agent=agent), key)
    _refused(_render(extra={"image": {"settlementConfigSchemaVersion": 1}}), "settlementConfigSchemaVersion")


def test_generated_schema_refuses_secret_and_unknown_typed_fields() -> None:
    cases = {
        "secret wallet key": (_with_config(Wallet={"private_key": "0xabc"}), "private_key"),
        "any spelling": (_with_config(wallet={"PRIVATE_KEY": "0xabc"}), "PRIVATE_KEY"),
        "registry token": (_with_config(registry={"auth": {"http://x": "t"}}), "auth"),
        "unregistered mechanism": (_with_config(Settlement={"priority": [], "teleport": {}}), "teleport"),
        "typed field type": (_with_config(Settlement={"priority": [], "schema_version": "one"}), "schema_version"),
    }
    for label, (agent, name) in cases.items():
        rendered = _render(agent=agent)
        assert rendered.returncode != 0, label
        assert name in rendered.stderr, f"{label}: {rendered.stderr}"


def test_identity_admits_only_its_public_keys() -> None:
    """Private identity material arrives through the credential Secret; any key
    Identity does not declare is refused at every level, whatever its name."""

    def with_identity(edit) -> dict:
        agent = _agent()
        edit(agent["config"]["Identity"])
        return agent

    cases = {
        "root": (with_identity(lambda i: i.update(private_key="x")), "private_key"),
        "root, other name": (with_identity(lambda i: i.update(request_credential="x")), "request_credential"),
        "principal": (with_identity(lambda i: i["principal"].update(credential="x")), "credential"),
        "administrator": (
            with_identity(lambda i: i.update(administrators={"operator": {"principals": [], "seed": "x"}})),
            "seed",
        ),
        "service peer": (
            with_identity(lambda i: i["service_peers"]["provisioning_default"].update(token="x")),
            "token",
        ),
    }
    for label, (agent, name) in cases.items():
        rendered = _render(agent=agent)
        assert rendered.returncode != 0, label
        assert name in rendered.stderr, f"{label}: {rendered.stderr}"


# --- committed fixtures ----------------------------------------------------


def test_contact_exchange_fixture_passes_contact_and_delivery_through() -> None:
    manifest = _ok(_render(files=("contact-exchange-values.yaml",)))
    config = _config(manifest)

    contact = config["Settlement"]["contact"]
    assert contact["origins"]["default"]["contact_payload"] == {
        "email": "bob-sales@seller.invalid"
    }
    assert config["Delivery"]["seller-mail"]["sink"] == "smtp"
    assert config["Delivery"]["seller-mail"]["port"] == 1025
    assert "# Source: arkhai-node-operator/charts/dev-env/templates/mailpit.yaml" in manifest


def test_mailpit_is_absent_unless_enabled() -> None:
    assert "dev-env/templates/mailpit.yaml" not in _ok(_render())


def test_generated_schema_refuses_secret_delivery_settings() -> None:
    def delivery(**instances) -> dict:
        return _with_config(Delivery={"enabled": list(instances), **instances})

    smtp = {"sink": "smtp", "host": "mail", "sender": "s@x.invalid", "recipients": ["r@x.invalid"]}
    cases = {
        "webhook url": (delivery(hook={"sink": "webhook", "url": "https://x.invalid"}), "url"),
        "smtp password": (delivery(mail={**smtp, "password": "p"}), "password"),
        "apprise urls": (delivery(note={"sink": "apprise", "urls": ["mailto://x"]}), "urls"),
        "misnamed table": (delivery(webhook={"sink": "file", "path": "/x"}), "sink"),
    }
    for label, (agent, name) in cases.items():
        rendered = _render(agent=agent)
        assert rendered.returncode != 0, label
        assert name in rendered.stderr, f"{label}: {rendered.stderr}"
    _ok(_render(agent=delivery(mail=smtp)))


def test_evm_fixture_waits_for_its_chain() -> None:
    manifest = _ok(_render(files=("eip191-evm-values.yaml",)))

    assert _config(manifest)["Chains"]["anvil"]["chain_id"] == 31337
    assert "wait-for-rpc" in _source(manifest, "deployment.yaml")


def test_rendered_document_loads_with_the_storefront_loader() -> None:
    python = os.environ.get("STOREFRONT_PYTHON")
    if not python:
        print("skip: STOREFRONT_PYTHON unset; the storefront loader check did not run")
        return
    config = _config(_ok(_render(files=("eip191-evm-values.yaml",))))
    with tempfile.TemporaryDirectory() as home:
        directory = Path(home) / "arkhai"
        directory.mkdir()
        (directory / "storefront.json").write_text(json.dumps(config))
        probe = (
            "import json, warnings; warnings.simplefilter('ignore')\n"
            "from market_storefront.utils import config as c\n"
            "print(json.dumps([c.settings.port, c.settings.get('identity.principal.identifier'),"
            " c.get_evm_wallet_address(), sorted(c.get_registry_authorities())]))"
        )
        loaded = subprocess.run(
            [python, "-c", probe],
            env={**os.environ, "XDG_CONFIG_HOME": home},
            check=True,
            capture_output=True,
            text=True,
        )
    port, identifier, wallet, registries = json.loads(loaded.stdout.strip().splitlines()[-1])
    assert port == config["port"]
    assert identifier == config["Identity"]["principal"]["identifier"]
    assert wallet == config["Wallet"]["address"]
    assert registries == config["registry"]["urls"]


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
