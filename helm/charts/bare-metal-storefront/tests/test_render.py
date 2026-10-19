"""The bare-metal chart passes its config through and adds only what its release knows.

Each test renders the chart with ``examples/production-values.yaml`` and an
overlay, and reads the rendered ``storefront.json`` back with ``json``.
Standard library only: overlays are written as JSON, which is YAML, and Helm
merges an overlay into the values key by key, replacing lists and removing a
key the overlay sets to ``None``.

Set ``BARE_METAL_STOREFRONT_PYTHON`` to the bare-metal storefront environment's
interpreter to also load a rendered document with the storefront's own
configuration loader and the checks that it could publish under it.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import textwrap
import tomllib
from pathlib import Path

CHART = Path(__file__).resolve().parents[1]
UMBRELLA = CHART.parents[1]
REPO = CHART.parents[2]
VALUES = CHART / "examples" / "production-values.yaml"
RELEASE = "rt"
FULLNAME = f"{RELEASE}-bare-metal-storefront"
# The development configuration the bare-metal end-to-end lane runs on.
DEV_CONFIGURATION = REPO / "domains" / "bare_metal" / "storefront" / "storefront.dev.toml"


def _render(overlay: dict | None = None, *, values: Path | None = VALUES) -> subprocess.CompletedProcess[str]:
    """Render the chart over ``values`` (its defaults alone when ``None``), then ``overlay``."""
    with tempfile.NamedTemporaryFile("w", suffix=".json") as handle:
        json.dump(overlay or {}, handle)
        handle.flush()
        command = ["helm", "template", RELEASE, str(CHART)]
        if values is not None:
            command += ["--values", str(values)]
        command += ["--values", handle.name]
        return subprocess.run(command, check=False, capture_output=True, text=True)


#: The bare-metal storefront's principal in the umbrella renders: Anvil account
#: 8, a well-known development address, never for a public network.
UMBRELLA_STOREFRONT_PRINCIPAL = {"scheme": "eip191", "identifier": "0x23618e81e3f5cdf7f54c3d65f7fbc0abf5b21e8f"}


def _render_umbrella(overlay: dict | None = None) -> subprocess.CompletedProcess[str]:
    """Render the umbrella as a release of the bare-metal storefront and its
    own provisioning service, over its values.yaml, then ``overlay`` of the
    storefront's values.

    The VM storefront is disabled: the release's provisioning service trusts
    and calls back one storefront, so a release running both is refused. The
    provisioning service trusts the storefront's principal, as the smoke-test
    profile requires.
    """
    release = {
        "storefront": {"enabled": False},
        "provisioning": {"storefrontIdentity": {"principals": [UMBRELLA_STOREFRONT_PRINCIPAL]}},
        "bare-metal-storefront": {"enabled": True, "config": {"Identity": {"principal": UMBRELLA_STOREFRONT_PRINCIPAL}}},
    }
    with tempfile.NamedTemporaryFile("w", suffix=".json") as base, tempfile.NamedTemporaryFile("w", suffix=".json") as handle:
        json.dump(release, base)
        base.flush()
        json.dump({"bare-metal-storefront": overlay or {}}, handle)
        handle.flush()
        command = [
            "helm", "template", RELEASE, str(UMBRELLA),
            "--values", str(UMBRELLA / "values.yaml"), "--values", base.name, "--values", handle.name,
        ]
        return subprocess.run(command, check=False, capture_output=True, text=True)


def _with_config(**changes) -> dict:
    """An overlay changing ``changes`` in the example's ``config``."""
    return {"config": dict(changes)}


def _ok(rendered: subprocess.CompletedProcess[str]) -> str:
    assert rendered.returncode == 0, rendered.stderr
    return rendered.stdout


def _refused(rendered: subprocess.CompletedProcess[str], *names: str) -> None:
    assert rendered.returncode != 0, "render succeeded"
    for name in names:
        assert name in rendered.stderr, f"{name!r} not named in: {rendered.stderr}"


def _source(manifest: str, path: str) -> str:
    """The rendered document whose ``# Source:`` names ``path``."""
    # Installed alone or as the umbrella's subchart, whose sources it prefixes.
    marker = f"bare-metal-storefront/templates/{path}\n"
    documents = [
        document
        for document in manifest.split("\n---\n")
        if any(line.startswith("# Source: ") and line.endswith(marker.strip()) for line in document.splitlines())
    ]
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


def _lines(document: str) -> set[str]:
    return {line.strip() for line in document.splitlines()}


def _environment(deployment: str) -> list[str]:
    """The names of the storefront container's environment variables."""
    section = deployment.split("          env:\n", 1)[1].split("          ports:\n", 1)[0]
    return [line.strip().removeprefix("- name: ") for line in section.splitlines() if line.strip().startswith("- name: ")]


def _assert_configuration_files(manifest: str, *, overlay: str | None) -> dict:
    """The public document, the overlay, and their mounts, asserted together.

    ``storefront.json`` renders into the chart's ConfigMap and mounts from it at
    /etc/arkhai/; the overlay mounts from ``overlay``, the existing Secret
    ``secret`` names, at the same directory, or with no Secret named neither its
    volume nor its mount renders. Returns the rendered document.
    """
    config = _config(manifest)
    deployment = _source(manifest, "deployment.yaml")
    lines = _lines(deployment)
    assert {
        "- name: config",
        "mountPath: /etc/arkhai/storefront.json",
        "subPath: storefront.json",
        f'name: "{FULLNAME}-config"',
        "- key: storefront.json",
        "path: storefront.json",
    } <= lines
    assert f"name: {FULLNAME}-config" in _lines(_source(manifest, "configmap.yaml"))
    overlay_lines = {
        "- name: secrets",
        "mountPath: /etc/arkhai/storefront.secrets.toml",
        "subPath: storefront.secrets.toml",
        "path: storefront.secrets.toml",
    }
    if overlay is None:
        assert not overlay_lines & lines
        assert "secretName:" not in deployment
    else:
        assert overlay_lines <= lines
        assert f'secretName: "{overlay}"' in lines
    assert "XDG_CONFIG_HOME" in _environment(deployment)
    assert "value: /etc" in lines
    return config


# --- rendering and mounting ------------------------------------------------


def test_production_values_render_mount_and_derive_together() -> None:
    manifest = _ok(_render())
    config = _assert_configuration_files(manifest, overlay="bare-metal-storefront-runtime")

    # The release knows the port, and the database path under its mount; the
    # example states its own public URL, which renders as stated.
    assert config["port"] == 8000
    assert config["db_path"] == "/var/lib/arkhai/bare-metal-storefront.db"
    assert config["base_url"] == "https://bare-metal.example.com"
    # Everything else is the example's config, unchanged: keys as spelled,
    # numbers as numbers, and an EVM address and a rate as strings.
    assert sorted(config) == [
        "Chains", "Identity", "Settlement", "Wallet", "base_url", "capacity", "db_path",
        "port", "pricing", "registry",
    ]
    assert config["Settlement"] == {"schema_version": 1, "priority": ["alkahest.v1"], "alkahest": {"enabled": True}}
    assert config["capacity"]["sites"] == {"site-a": "https://site-a.example.com"}
    assert config["Wallet"] == {"address": "0x00000000000000000000000000000000000000aa"}
    assert config["pricing"]["default_max_duration_seconds"] == 86400
    assert config["pricing"]["settlements"][0]["rate"] == "10"
    assert "image: \"registry.example.com/arkhai/arkhai@sha256:" in manifest
    for kind in ("Deployment", "Service", "PersistentVolumeClaim", "ConfigMap"):
        assert f"kind: {kind}" in manifest
    assert "kind: Secret" not in manifest
    assert "path: /health" in manifest
    assert "wait-for-" not in manifest


def test_a_release_naming_no_overlay_mounts_none() -> None:
    _assert_configuration_files(_ok(_render({"secret": {"secretName": ""}})), overlay=None)


def test_the_chart_defaults_derive_the_service_url_port_and_database_path() -> None:
    config = _config(_ok(_render(values=None)))

    assert config == {
        "port": 8000,
        "base_url": f"http://{FULLNAME}:8000",
        "db_path": "/var/lib/arkhai/bare-metal-storefront.db",
    }


def test_the_port_the_container_probes_and_service_share_is_rendered() -> None:
    manifest = _ok(_render({"port": 9100}, values=None))
    config = _config(manifest)

    assert config["port"] == 9100
    assert config["base_url"] == f"http://{FULLNAME}:9100"
    assert "containerPort: 9100" in _lines(_source(manifest, "deployment.yaml"))
    assert "port: 9100" in _lines(_source(manifest, "service.yaml"))
    assert f"http://{FULLNAME}:9100/health" in _source(manifest, "tests/health-test.yaml")


def test_stated_values_are_rendered_as_stated() -> None:
    config = _config(_ok(_render(_with_config(db_path="/var/lib/arkhai/seller.db", port=8000))))

    assert config["db_path"] == "/var/lib/arkhai/seller.db"
    assert config["port"] == 8000


def test_the_pod_environment_carries_only_the_configuration_directory_and_the_credential() -> None:
    deployment = _source(_ok(_render()), "deployment.yaml")
    lines = _lines(deployment)

    assert _environment(deployment) == ["XDG_CONFIG_HOME", "ARKHAI_IDENTITY_CREDENTIAL"]
    assert {"secretKeyRef:", 'name: "bare-metal-storefront-identity"', 'key: "credential"'} <= lines
    assert "ARKHAI_IDENTITY_CREDENTIAL\n              value:" not in deployment
    # Kubernetes injects no Service variables, which the loader's override
    # layer would read for a Service named storefront-anything.
    assert "enableServiceLinks: false" in lines
    # The port reaches the storefront through its configuration, not its command.
    command = deployment.split("          command:\n", 1)[1].split("          env:\n", 1)[0]
    assert [line.strip() for line in command.splitlines()] == ["- bare-metal-storefront", "- serve"]
    assert "BARE_METAL_STOREFRONT" not in deployment


def test_a_missing_credential_secret_fails_closed() -> None:
    _refused(_render({"identity": {"credentialSecret": {"name": ""}}}), "credentialSecret")


def test_an_alkahest_address_book_mounts_read_only_when_named() -> None:
    assert "alkahest-address-book" not in _ok(_render())
    manifest = _ok(_render({"alkahestAddressBook": {"configMapName": "alkahest-addresses"}}))
    deployment = _source(manifest, "deployment.yaml")
    mount = deployment.split("- name: alkahest-address-book\n", 1)[1]

    assert "mountPath: \"/etc/arkhai/alkahest\"" in mount.splitlines()[0]
    assert "readOnly: true" in mount.splitlines()[1]
    assert {'name: "alkahest-addresses"', 'path: "alkahest_addresses.json"'} <= _lines(deployment)


# --- the umbrella release ---------------------------------------------------

UMBRELLA_REGISTRY = f"http://{RELEASE}-registry:8080"
UMBRELLA_PROVISIONING = "http://arkhai-node-operator-provisioning:8081"
# The umbrella's development principals (helm/values.yaml): its registry's and its
# provisioning service's, never for a public network.
UMBRELLA_REGISTRY_PRINCIPAL = {"scheme": "eip191", "identifier": "0x90f79bf6eb2c4f870365e785982e1f101e93b906"}
UMBRELLA_PROVISIONING_PRINCIPAL = {"scheme": "eip191", "identifier": "0xf39fd6e51aad88f6f4ce6ab8827279cfffb92266"}


def test_an_umbrella_release_derives_its_registry_and_provisioning_site() -> None:
    manifest = _ok(_render_umbrella())
    config = _assert_configuration_files(manifest, overlay=None)

    assert config["registry"] == {
        "urls": [UMBRELLA_REGISTRY],
        "authorities": {
            UMBRELLA_REGISTRY: {"authority": "registry-a", "principals": [UMBRELLA_REGISTRY_PRINCIPAL]}
        },
    }
    assert config["capacity"] == {"sites": {"default": UMBRELLA_PROVISIONING}}
    peer = config["Identity"]["service_peers"]["provisioning_default"]
    assert peer == {"role": "service", "site_id": "default", "principals": [UMBRELLA_PROVISIONING_PRINCIPAL]}
    assert config["base_url"] == f"http://{FULLNAME}:8000"
    assert config["db_path"] == "/var/lib/arkhai/bare-metal-storefront.db"


def test_an_umbrella_release_keeps_a_registry_and_sites_the_config_states() -> None:
    config = _config(_ok(_render_umbrella({
        "internalRegistryTrust": None,
        "config": {
            "registry": {"urls": ["https://registry.example.com"]},
            "capacity": {"sites": {"site-a": "https://site-a.example.com"}},
        },
    })))

    assert config["registry"] == {"urls": ["https://registry.example.com"]}
    assert config["capacity"] == {"sites": {"site-a": "https://site-a.example.com"}}


def test_an_umbrella_releases_parts_that_disagree_are_refused() -> None:
    other = {"scheme": "eip191", "identifier": "0x" + "ab" * 20}
    cases = {
        "requires internalRegistryTrust": {"internalRegistryTrust": None},
        "differs from the release's registry authority": {
            "internalRegistryTrust": {"authority": "registry-b"}
        },
        "must include the release's registry principal": {
            "internalRegistryTrust": {"principals": [other]}
        },
        "applies only to the release's internal registry": {
            "config": {"registry": {"urls": ["https://registry.example.com"]}}
        },
        "includes the release's provisioning principal": {
            "config": {"Identity": {"service_peers": {"provisioning_default": {"principals": [other]}}}}
        },
    }
    for message, overlay in cases.items():
        _refused(_render_umbrella(overlay), message)


def test_a_chart_installed_alone_has_no_internal_registry_to_trust() -> None:
    trust = {"authority": "registry-a", "principals": [UMBRELLA_REGISTRY_PRINCIPAL]}
    _refused(
        _render({"internalRegistryTrust": trust}, values=None),
        "the release has no internal registry",
    )


# --- release checks --------------------------------------------------------


def test_a_stated_port_must_be_a_number_equal_to_the_charts() -> None:
    _refused(_render(_with_config(port=9000)), "differs from the chart's port")
    _refused(_render(_with_config(Port=9000)), "config.Port", "differs from the chart's port")
    # The values schema types the port, so a string is refused before render.
    _refused(_render(_with_config(port="8000")), "config.port")


def test_two_spellings_of_one_key_are_refused_at_any_depth() -> None:
    _refused(_render(_with_config(settlement={"priority": []})), "config", "Settlement", "settlement")
    _refused(
        _render(_with_config(capacity={"POLL_INTERVAL": 2, "poll_interval": 2})),
        "config.capacity", "POLL_INTERVAL", "poll_interval",
    )


# --- values schema ---------------------------------------------------------


def test_a_key_the_storefront_does_not_read_is_refused_naming_it() -> None:
    cases = {
        "root": _with_config(negotiation_timeout=60),
        "typed section": _with_config(capacity={"poll_intervall": 2}),
        "service peer": _with_config(Identity={"service_peers": {"site_a_authority": {"token": "x"}}}),
        "chain": _with_config(Chains={"base_sepolia": {"rpc_url": "https://x.invalid", "private_key": "x"}}),
        "registry write token": _with_config(registry={"auth": {"https://registry.example.com": "t"}}),
        "unregistered mechanism": _with_config(Settlement={"teleport": {}}),
    }
    names = {
        "root": "negotiation_timeout",
        "typed section": "poll_intervall",
        "service peer": "token",
        "chain": "private_key",
        "registry write token": "auth",
        "unregistered mechanism": "teleport",
    }
    for label, overlay in cases.items():
        rendered = _render(overlay)
        assert rendered.returncode != 0, label
        assert names[label] in rendered.stderr, f"{label}: {rendered.stderr}"


def test_a_secret_setting_is_refused_in_any_spelling() -> None:
    _refused(_render(_with_config(Wallet={"private_key": "0xabc"})), "private_key")
    _refused(_render(_with_config(Wallet={"PRIVATE_KEY": "0xabc"})), "PRIVATE_KEY")
    hook = {"enabled": ["hook"], "hook": {"sink": "webhook", "url": "https://hook.invalid"}}
    _refused(_render(_with_config(Delivery=hook)), "url")


def test_a_typed_setting_is_accepted_in_any_spelling() -> None:
    stated = {"Poll_Interval": 2, "SITES": {"site-a": "https://site-a.example.com"}}
    config = _config(_ok(_render(_with_config(CAPACITY=stated), values=None)))

    assert config["CAPACITY"] == stated


def test_a_duration_outside_the_shared_bounds_is_refused() -> None:
    _refused(_render(_with_config(capacity={"poll_interval": 0})), "poll_interval")
    _refused(_render(_with_config(negotiation_watchdog_interval=-1)), "negotiation_watchdog_interval")


def test_the_retired_values_shape_is_refused_naming_each_key() -> None:
    cases = {
        "siteBindingsSecret": {"siteBindingsSecret": {"name": "sites", "key": "sites.json"}},
        "settlementConfigSecret": {"settlementConfigSecret": {"name": "s", "key": "settlement.json"}},
        "sellerEvmAddress": {"sellerEvmAddress": ""},
        "chains": {"chains": {}},
        "walletKeySecret": {"walletKeySecret": {"name": "", "key": "private-key"}},
        "adminPrincipals": {"adminPrincipals": []},
        "publicUrl": {"publicUrl": "https://x.invalid"},
        "databasePath": {"databasePath": "/var/lib/arkhai/x.db"},
        "sitePlacement": {"sitePlacement": "fill_first"},
        "principal": {"identity": {"principal": {"scheme": "ed25519"}}},
        "service.port": {"service": {"port": 8000}},
    }
    for name, overlay in cases.items():
        _refused(_render(overlay), f"Additional property {name.rsplit('.', 1)[-1]} is not allowed")


def test_the_development_configuration_passes_the_schema() -> None:
    """The configuration the end-to-end lane's storefront runs on is one the
    chart accepts as written."""
    with DEV_CONFIGURATION.open("rb") as handle:
        development = tomllib.load(handle)
    config = _config(_ok(_render({"config": development}, values=None)))

    assert {key: value for key, value in config.items() if key != "db_path"} == development


# --- the storefront's own loader -----------------------------------------


_PROBE = """
import json, warnings; warnings.simplefilter('ignore')
from arkhai_bare_metal_storefront.config import load_storefront_settings
from arkhai_bare_metal_storefront.pool_overrides import compile_publication_clauses
from arkhai_bare_metal_storefront.site_clients import parse_site_bindings
from arkhai_bare_metal_storefront.startup_refusal import publication_startup_problems
settings = load_storefront_settings()
problems = publication_startup_problems(settings)
report = {
    "port": settings.port,
    "base_url": settings.base_url,
    "db_path": settings.db_path,
    "principal": settings.identity.principal.model_dump(mode="json") if settings.identity.principal else None,
    "registries": sorted(settings.registry_authorities()) if settings.registry.urls else [],
    "problems": problems,
}
if not problems:
    report["clauses"] = len(compile_publication_clauses(settings.pricing.settlements))
    report["sites"] = [
        [binding.site_id, binding.service_peer]
        for binding in parse_site_bindings(settings.capacity.sites, settings.service_peer_configs())
    ]
print(json.dumps(report))
"""


def _loaded(config: dict, python: str) -> dict:
    """What the storefront's own loader and startup checks make of one rendered
    document, read where the pod reads it."""
    # The probe reads only the rendered document: the loader's override layer
    # would also read any STOREFRONT_ variable this process carries.
    environment = {key: value for key, value in os.environ.items() if not key.startswith("STOREFRONT_")}
    with tempfile.TemporaryDirectory() as home:
        directory = Path(home) / "arkhai"
        directory.mkdir()
        (directory / "storefront.json").write_text(json.dumps(config))
        loaded = subprocess.run(
            [python, "-c", _PROBE],
            env={**environment, "XDG_CONFIG_HOME": home},
            check=True,
            capture_output=True,
            text=True,
        )
    return json.loads(loaded.stdout.strip().splitlines()[-1])


def test_the_rendered_document_loads_with_the_storefront_loader() -> None:
    """The rendered example is one the storefront could publish under. It shows
    publishable, not startable: composing the runtime also needs the credential
    owning the configured principal, the overlay's wallet key, a writable
    database, and chain clients."""
    python = os.environ.get("BARE_METAL_STOREFRONT_PYTHON")
    if not python:
        print("skip: BARE_METAL_STOREFRONT_PYTHON unset; the storefront loader check did not run")
        return
    config = _config(_ok(_render()))
    loaded = _loaded(config, python)

    assert loaded["problems"] == [], loaded["problems"]
    assert loaded["port"] == config["port"]
    assert loaded["base_url"] == config["base_url"]
    assert loaded["db_path"] == config["db_path"]
    assert loaded["principal"] == config["Identity"]["principal"]
    assert loaded["registries"] == config["registry"]["urls"]
    assert loaded["clauses"] == 1
    assert loaded["sites"] == [["site-a", "site_a_authority"]]
    # The chart defaults state none of what publication needs, so the same
    # checks refuse them, naming each.
    refused = _loaded(_config(_ok(_render(values=None))), python)
    assert [problem.split(":")[0] for problem in refused["problems"]] == [
        "no registry to publish to",
        "no settlement mechanism is enabled under [Settlement]",
        "no site to publish from",
    ], refused["problems"]


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
