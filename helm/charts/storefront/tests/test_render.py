"""The storefront chart passes an agent's config through and adds only what the release knows.

Each test renders the umbrella chart, because the storefront subchart takes its
registry, provisioning, and identity coordinates from the umbrella's globals,
and reads the rendered ``storefront.json`` back with ``json``. Standard library
only: values are written as JSON, which is YAML.

Agents are keyed by name, and a test states only what it changes in Bob's
default agent from ``values.yaml``, as an operator's overlay does: Helm merges
the overlay into the agent key by key, replaces lists, and removes a key the
overlay sets to ``None``.

Set ``STOREFRONT_PYTHON`` to the storefront environment's interpreter to also
load rendered documents with the storefront's own configuration loader.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

CHART = Path(__file__).resolve().parents[1]
UMBRELLA = CHART.parents[1]
REPO = UMBRELLA.parent
RELEASE = "rt"
REGISTRY_URL = f"http://{RELEASE}-registry:8080"
PROVISIONING_URL = "http://arkhai-node-operator-provisioning:8081"
ACTIVE_REGISTRY = {"scheme": "eip191", "identifier": "0x90f79bf6eb2c4f870365e785982e1f101e93b906"}
ACTIVE_PROVISIONING = {"scheme": "eip191", "identifier": "0xf39fd6e51aad88f6f4ce6ab8827279cfffb92266"}
BOB_PRINCIPAL = {"scheme": "eip191", "identifier": "0x3c44cdddb6a900fa2b585dd299e03d12fa4293bc"}
# The release `make -C helm deploy-local` installs, by its Makefile's name.
LOCAL_RELEASE = "arkhai-node-operator"
ANVIL_ADDRESS_BOOK = REPO / "kit" / "alkahest" / "src" / "market_alkahest" / "data" / "alkahest_anvil_addresses.json"


def _agent(**changes) -> dict:
    """An overlay of Bob's agent changing its top-level ``changes``."""
    return dict(changes)


def _without(key: str) -> dict:
    """An overlay removing ``key`` from Bob's agent."""
    return {key: None}


def _with_config(**changes) -> dict:
    """An overlay of Bob's agent changing ``changes`` in its ``config``."""
    return {"config": dict(changes)}


def _render(
    *,
    agent: dict | None = None,
    agents: dict | None = None,
    extra: dict | None = None,
    values: dict | None = None,
    files=(),
    release: str = RELEASE,
) -> subprocess.CompletedProcess[str]:
    """Render values.yaml, then each fixture, then the overlay: ``agent``
    overlays Bob's agent, ``agents`` the agents map, ``extra`` the storefront's
    other values, and ``values`` the release's other charts."""
    storefront: dict = {}
    if agent is not None:
        storefront["agents"] = {"bob": agent}
    if agents is not None:
        storefront["agents"] = agents
    if extra:
        storefront.update(extra)
    overlay = {**(values or {}), "storefront": storefront}
    with tempfile.NamedTemporaryFile("w", suffix=".json") as handle:
        json.dump(overlay, handle)
        handle.flush()
        command = ["helm", "template", release, str(UMBRELLA), "--values", str(UMBRELLA / "values.yaml")]
        for fixture in files:
            command += ["--values", str(UMBRELLA / "fixtures" / fixture)]
        if storefront or values:
            command += ["--values", handle.name]
        return subprocess.run(command, check=False, capture_output=True, text=True)


def _render_local(*, overlay: bool = True) -> subprocess.CompletedProcess[str]:
    """The release `make -C helm deploy-local` installs: values.yaml with
    local-values.yaml, or without it for the same release's defaults."""
    command = ["helm", "template", LOCAL_RELEASE, str(UMBRELLA), "--values", str(UMBRELLA / "values.yaml")]
    if overlay:
        command += ["--values", str(UMBRELLA / "local-values.yaml")]
    return subprocess.run(command, check=False, capture_output=True, text=True)


def _ok(rendered: subprocess.CompletedProcess[str]) -> str:
    assert rendered.returncode == 0, rendered.stderr
    return rendered.stdout


def _documents(manifest: str, path: str, chart: str = "storefront") -> list[str]:
    """Every rendered document whose ``# Source:`` names ``path`` in ``chart``."""
    marker = f"# Source: arkhai-node-operator/charts/{chart}/templates/{path}"
    return [document for document in manifest.split("\n---\n") if marker in document]


def _source(manifest: str, path: str, chart: str = "storefront") -> str:
    """The rendered document whose ``# Source:`` names ``path``."""
    documents = _documents(manifest, path, chart)
    if not documents:
        raise AssertionError(f"{path} not rendered")
    return documents[0]


def _block(document: str, key: str) -> str:
    """The text of the block scalar ``key: |`` that ``document``'s data holds."""
    marker = f"  {key}: |\n"
    assert marker in document, f"{key} not rendered"
    lines = []
    for line in document.split(marker, 1)[1].splitlines():
        if line and not line.startswith("    "):
            break
        lines.append(line)
    return textwrap.dedent("\n".join(lines))


def _config(manifest: str) -> dict:
    return json.loads(_block(_source(manifest, "configmap.yaml"), "storefront.json"))


def _configs(manifest: str) -> dict[str, dict]:
    """Each agent's storefront.json, by the name its ConfigMap carries."""
    rendered = {}
    for document in _documents(manifest, "configmap.yaml"):
        name = re.search(r"^  name: (\S+)$", document, re.MULTILINE).group(1)
        rendered[name] = json.loads(_block(document, "storefront.json"))
    return rendered


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
    # The release's widened source-confirmation window passes through, and
    # the chart adds the capacity site beside it.
    assert config["capacity"] == {
        "source_confirmation_seconds": 3600,
        "sites": {"default": PROVISIONING_URL},
    }
    assert config["Settlement"] == {"priority": []}
    assert "provisioning" not in config or "identity" not in config["provisioning"]
    assert "wait-for-registry" in deployment
    assert "wait-for-rpc" not in deployment
    assert "alkahest-address-book" not in deployment


def test_the_pod_environment_carries_no_service_links() -> None:
    """Service-link variables named for a Service beginning `storefront` would
    land in the storefront's STOREFRONT_ override layer."""
    deployment = _source(_ok(_render()), "deployment.yaml")

    assert "enableServiceLinks: false" in {line.strip() for line in deployment.splitlines()}


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
    agent["internalRegistryTrust"] = None
    manifest = _ok(_render(agent=agent))
    config = _config(manifest)

    assert config["base_url"] == "https://bob.example/"
    assert config["db_path"] == "/var/lib/arkhai/custom.db"
    assert config["registry"] == agent["config"]["registry"]
    assert config["provisioning"] == {"mode": "mock", "service_url": "http://provisioning.example:8081"}
    assert config["capacity"] == {
        "source_confirmation_seconds": 3600,
        "sites": {"west": "http://provisioning.example:8081"},
    }
    assert "wait-for-registry" not in _source(manifest, "deployment.yaml")


def test_a_stated_port_equal_to_the_agents_is_accepted() -> None:
    assert _config(_ok(_render(agent=_with_config(port=8001))))["port"] == 8001


def test_a_differently_spelled_section_is_read_for_release_checks() -> None:
    agent = _with_config(
        Identity=None,
        identity={
            "principal": BOB_PRINCIPAL,
            "service_peers": {
                "provisioning_default": {
                    "role": "service",
                    "site_id": "default",
                    "principals": [ACTIVE_PROVISIONING],
                }
            },
        },
        Settlement=None,
        settlement={"alkahest": {"enabled": True}},
        chains={"anvil": {"chain_id": 31337, "rpc_url": "http://anvil:8545"}},
    )
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
        "service peer": (
            _with_config(Identity={"service_peers": {"provisioning_default": None}}),
            "Identity.service_peers",
        ),
        "service peer principal": (
            _with_config(
                Identity={"service_peers": {"provisioning_default": {"principals": [ACTIVE_REGISTRY]}}}
            ),
            "includes the release's provisioning principal",
        ),
    }
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
    domains = [
        {
            "contribution": "vms",
            "Contribution": "vms",
            "offering_mode": "vm",
            "domain_identity": "compute.v1",
            "contract_version": "1.0",
        }
    ]
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
    agent["internalRegistryTrust"] = None
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
    peer = {
        "Role": "service",
        "SITE_ID": "default",
        "Principals": [{"Scheme": p["scheme"], "Identifier": p["identifier"]} for p in [ACTIVE_PROVISIONING]],
    }
    agent = _with_config(
        Identity={
            "principal": None,
            "Principal": BOB_PRINCIPAL,
            "service_peers": None,
            "Service_Peers": {"provisioning_default": peer},
        },
        Settlement={"priority": None, "Priority": [], "Arkhai_Payments": {"Enabled": False}},
    )
    config = _config(_ok(_render(agent=agent)))

    assert config["Identity"]["Principal"] == BOB_PRINCIPAL
    assert "principal" not in config["Identity"] and "service_peers" not in config["Identity"]
    assert config["Settlement"] == {"Priority": [], "Arkhai_Payments": {"Enabled": False}}

    wrong = {**peer, "Principals": [{"Scheme": "eip191", "Identifier": ACTIVE_REGISTRY["identifier"]}]}
    agent["config"]["Identity"]["Service_Peers"] = {"provisioning_default": wrong}
    _refused(_render(agent=agent), "Identity.service_peers")


def test_retired_and_secret_keys_are_refused_in_any_spelling() -> None:
    for key in ("Seller", "RegistryUrl", "STOREFRONTDOMAINS", "Chain"):
        _refused(_render(agent=_with_config(**{key: {}})), key)
    _refused(_render(agent=_with_config(Wallet={"Private_Key": "0xabc"})), "Private_Key")
    _refused(_render(agent=_with_config(registry={"AUTH": {"http://x": "t"}})), "AUTH")


def test_retired_inventory_settings_are_refused_in_any_spelling() -> None:
    """Inventory is declared at provisioning; the storefront's CSV seeding,
    escrow templates, and local-table listing switch no longer exist."""
    for key in ("Resources_CSV_Path", "RESOURCES_CSV_INLINE", "Escrow_Templates"):
        _refused(_render(agent=_with_config(**{key: {}})), key)
    flag = "Use_Site_Projection_For_Listings"
    _refused(_render(agent=_with_config(Capacity={flag: False})), flag)
    _ok(_render(agent=_with_config(capacity={"sites": {}})))


def test_the_renamed_servicing_interval_is_refused_in_any_spelling() -> None:
    """The storefront refuses to start on its old servicing-interval key; the
    schema refuses it first, and its replacement passes through."""
    for key in ("claims_sweep_interval", "Claims_Sweep_Interval"):
        _refused(_render(agent=_with_config(**{key: 30})), key)
    config = _config(_ok(_render(agent=_with_config(settlement_servicing_interval_seconds=30))))
    assert config["settlement_servicing_interval_seconds"] == 30


def test_the_removed_registry_switch_is_refused_in_any_spelling() -> None:
    """The storefront refuses to start on the switch it no longer honours,
    whatever its value; the schema refuses it first."""
    for key, value in (("enable_registry_discovery", False), ("ENABLE_REGISTRY_DISCOVERY", True)):
        _refused(_render(agent=_with_config(**{key: value})), key)


def test_the_removed_provisioning_trust_set_is_refused_in_any_spelling() -> None:
    """Each site's responses verify against its own service peer, which the
    chart checks; the storefront refuses to start on the trust set it no longer
    reads, and the schema refuses it first."""
    principals = {"principals": [ACTIVE_PROVISIONING]}
    for provisioning in ({"identity": principals}, {"IDENTITY": principals}):
        _refused(_render(agent=_with_config(provisioning=provisioning)), next(iter(provisioning)))


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
        "principal": _agent(identity={"principal": {}}),
        "resourcesCsvInline": _agent(secret={"resourcesCsvInline": "resource_id\n"}),
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

    def with_identity(identity: dict) -> dict:
        return _with_config(Identity=identity)

    cases = {
        "root": (with_identity({"private_key": "x"}), "private_key"),
        "root, other name": (with_identity({"request_credential": "x"}), "request_credential"),
        "principal": (with_identity({"principal": {"credential": "x"}}), "credential"),
        "administrator": (
            with_identity({"administrators": {"operator": {"principals": [], "seed": "x"}}}),
            "seed",
        ),
        "service peer": (
            with_identity({"service_peers": {"provisioning_default": {"token": "x"}}}),
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
    # The fixture names the dev-env chart's Services and ConfigMap by the
    # release name the Makefile installs.
    manifest = _ok(_render(files=("eip191-evm-values.yaml",), release=LOCAL_RELEASE))

    assert _config(manifest)["Chains"]["anvil"]["chain_id"] == 31337
    assert "wait-for-rpc" in _source(manifest, "deployment.yaml")
    _mounted_address_book(manifest)


# --- agents keyed by name --------------------------------------------------

CAROL = {
    "port": 8002,
    "identity": {"credentialSecret": {"name": "arkhai-carol-identity", "key": "credential"}},
    "internalRegistryTrust": {"authority": "registry-a", "principals": [ACTIVE_REGISTRY]},
    "config": {
        "agent_id": "carol",
        "Identity": {
            "principal": BOB_PRINCIPAL,
            "service_peers": {
                "provisioning_default": {
                    "role": "service",
                    "site_id": "default",
                    "principals": [ACTIVE_PROVISIONING],
                }
            },
        },
        "Settlement": {"priority": []},
    },
}


def test_an_overlay_changes_one_agent_by_name_and_adds_another() -> None:
    manifest = _ok(_render(agents={"bob": {"config": {"log_file_path": "./logs/x.log"}}, "carol": CAROL}))
    configs = _configs(manifest)

    assert set(configs) == {f"{RELEASE}-storefront-bob-config", f"{RELEASE}-storefront-carol-config"}
    bob = configs[f"{RELEASE}-storefront-bob-config"]
    assert bob["log_file_path"] == "./logs/x.log"
    # Every key the overlay leaves alone keeps values.yaml's value.
    assert bob["agent_id"] == "bob"
    assert bob["capacity"]["source_confirmation_seconds"] == 3600
    assert bob["Identity"]["administrators"]
    carol = configs[f"{RELEASE}-storefront-carol-config"]
    assert carol["port"] == 8002
    assert carol["base_url"] == f"http://{RELEASE}-storefront-carol:8002/"
    assert f"name: {RELEASE}-storefront-carol" in manifest


def test_a_null_removes_an_agent() -> None:
    manifest = _ok(
        _render(
            agents={"bob": None, "carol": CAROL},
            values={"provisioning": {"storefront": {"agentName": "carol", "port": 8002}}},
        )
    )

    assert set(_configs(manifest)) == {f"{RELEASE}-storefront-carol-config"}
    assert "storefront-bob" not in manifest


def test_a_list_of_agents_is_refused_naming_the_map() -> None:
    _refused(
        _render(agents=[{"name": "bob", **CAROL}]),
        "agents is a map keyed by agent name",
    )


def test_an_agent_is_named_by_its_key_alone() -> None:
    _refused(_render(agent=_agent(name="carol")), "agents.bob.name")


# --- Alkahest address books ------------------------------------------------


def _address_paths(config: dict) -> list[str]:
    """Every Alkahest address-book path ``config`` names."""
    paths = [
        chain["alkahest_address_config_path"]
        for chain in (config.get("Chains") or {}).values()
        if chain.get("alkahest_address_config_path")
    ]
    alkahest = (config.get("Settlement") or {}).get("alkahest") or {}
    if alkahest.get("address_config_path"):
        paths.append(alkahest["address_config_path"])
    return paths


def _mounted_address_book(manifest: str) -> tuple[str, dict]:
    """The one address-book file the storefront mounts, and its content.

    Every address path the agent's configuration names must be that file: the
    Deployment mounts a ConfigMap's key at ``<mountPath>/<key>``, and the
    release renders that ConfigMap.
    """
    deployment = _source(manifest, "deployment.yaml")
    mount = re.search(
        r'- name: alkahest-address-book\n\s+mountPath: "?([^"\n]+)"?\n\s+readOnly: true', deployment
    )
    volume = re.search(
        r'- name: alkahest-address-book\n\s+configMap:\n\s+name: "?([^"\n]+)"?\n'
        r'\s+items:\n\s+- key: "?([^"\n]+)"?\n\s+path: "?([^"\n]+)"?',
        deployment,
    )
    assert mount and volume, "no address book is mounted"
    configmap, key, item_path = volume.groups()
    assert item_path == key
    mounted = f"{mount.group(1).rstrip('/')}/{key}"
    paths = _address_paths(_config(manifest))
    assert paths, "the configuration names no address book"
    assert set(paths) == {mounted}, f"{paths} not all {mounted}"
    (document,) = [
        document
        for document in manifest.split("\n---\n")
        if "\nkind: ConfigMap\n" in f"\n{document}" and re.search(rf"^  name: {re.escape(configmap)}$", document, re.MULTILINE)
    ]
    return mounted, json.loads(_block(document, key))


def test_an_agent_mounts_its_named_address_book_read_only() -> None:
    deployment = _source(
        _ok(_render(agent=_agent(alkahestAddressBook={"configMapName": "books"}))), "deployment.yaml"
    )

    assert re.search(
        r'- name: alkahest-address-book\n\s+mountPath: "/etc/arkhai/alkahest"\n\s+readOnly: true', deployment
    )
    assert re.search(
        r'configMap:\n\s+name: "books"\n\s+items:\n\s+- key: "alkahest_addresses.json"\n'
        r'\s+path: "alkahest_addresses.json"',
        deployment,
    )


def test_the_local_release_names_only_the_dev_chains_mounted_address_book() -> None:
    """Both address paths name the file the agent mounts from the dev-env
    chart's ConfigMap, and that file is kit/alkahest's Anvil address book."""
    _path, book = _mounted_address_book(_ok(_render_local()))

    assert book == json.loads(ANVIL_ADDRESS_BOOK.read_text())


def test_the_local_release_enables_alkahest_and_contact_exchange_and_the_defaults_nothing() -> None:
    defaults = _config(_ok(_render_local(overlay=False)))
    local = _config(_ok(_render_local()))

    assert defaults["Settlement"] == {"priority": []}
    assert local["Settlement"]["priority"] == ["alkahest.v1", "contact-exchange.v1"]
    assert local["Settlement"]["alkahest"]["enabled"] is True
    assert local["Settlement"]["contact"]["enabled"] is True
    assert local["Settlement"]["contact"]["origins"]["default"]["contact_payload"] == {
        "email": "bob-sales@seller.invalid"
    }
    assert local["Chains"]["anvil"]["rpc_url"] == "http://arkhai-node-operator-dev-env:8545"
    assert local["Wallet"]["address"] == local["Identity"]["principal"]["identifier"]
    assert local["capacity"]["sites"] == {"default": PROVISIONING_URL}
    # The overlay changes only what it states; the rest is Bob's default agent.
    differing = {key for key in set(defaults) | set(local) if defaults.get(key) != local.get(key)}
    assert differing == {"Wallet", "Chains", "pricing", "Settlement"}, differing


_PROBE = """
import json, warnings; warnings.simplefilter('ignore')
from market_storefront.startup_refusal import StorefrontStartupError, require_publishable_storefront
try:
    require_publishable_storefront()
except StorefrontStartupError as exc:
    print(json.dumps({"refusal": str(exc)}))
    raise SystemExit(0)
from market_storefront.services.publication_terms import demands_for_publication_clauses
from market_storefront.utils.config import get_evm_wallet_address, settlement_publication_defaults
demands = demands_for_publication_clauses(
    settlement_publication_defaults(), wallet_address=get_evm_wallet_address()
)
print(json.dumps({"refusal": None, "demands": demands}))
"""


def _storefront_starts(config: dict, python: str, *, files: dict[str, str] | None = None) -> dict:
    """What the storefront's own startup refusal reports for one rendered
    document and, when it starts, the release conditions it derives for its
    configured clauses.

    ``files`` maps each absolute path the document names to the content the
    release mounts there; the paths are re-rooted under a temporary directory,
    since the probe runs outside the pod.
    """
    with tempfile.TemporaryDirectory() as home:
        document = json.dumps(config)
        for index, (mounted, content) in enumerate((files or {}).items()):
            local = Path(home) / f"mounted-{index}.json"
            local.write_text(content)
            document = document.replace(json.dumps(mounted), json.dumps(str(local)))
        directory = Path(home) / "arkhai"
        directory.mkdir()
        (directory / "storefront.json").write_text(document)
        loaded = subprocess.run(
            [python, "-c", _PROBE],
            env={**os.environ, "XDG_CONFIG_HOME": home},
            check=True,
            capture_output=True,
            text=True,
        )
    return json.loads(loaded.stdout.strip().splitlines()[-1])


def test_the_local_release_starts_and_derives_its_alkahest_release_conditions() -> None:
    python = os.environ.get("STOREFRONT_PYTHON")
    if not python:
        print("skip: STOREFRONT_PYTHON unset; the storefront startup check did not run")
        return
    manifest = _ok(_render_local())
    mounted, book = _mounted_address_book(manifest)
    config = _config(manifest)
    started = _storefront_starts(config, python, files={mounted: json.dumps(book)})

    assert started["refusal"] is None, started["refusal"]
    # The configured Alkahest clause advertises the recipient arbiter of the
    # mounted address book, paying Bob's wallet on the release's chain.
    assert started["demands"] == [
        {
            "chain_name": "anvil",
            "arbiter": book["arbiters_addresses"]["recipient_arbiter"].lower(),
            "demand_data": {"recipient": config["Wallet"]["address"].lower()},
        }
    ]
    # The chart defaults enable no mechanism, so the same check refuses them.
    refused = _storefront_starts(_config(_ok(_render())), python)
    assert "no settlement mechanism is enabled under [Settlement]" in refused["refusal"], refused


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
