"""The local two-release topology renders as one registry serving two storefronts.

Release 1 is the umbrella as ``make -C helm deploy-local`` installs it; release 2
is the same chart under ``bare-metal-release-values.yaml``: the bare-metal
storefront and its own provisioning service, publishing to release 1's registry.
Release 1 also runs the payments lane double, which both storefronts are
configured to reach through the values a deployment supplies. Each test renders
both releases with the names ``helm/Makefile``'s topology
targets install them under, and reads the documents the charts render as JSON
back with ``json``. Standard library only.

Set ``BARE_METAL_STOREFRONT_PYTHON`` to the bare-metal storefront environment's
interpreter to also load release 2's rendered document with the storefront's own
configuration loader and publication checks, and ``REGISTRY_PYTHON`` to the
registry environment's to load release 1's rendered registry profile with the
registry's own loader.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import textwrap
import tomllib
from pathlib import Path, PurePosixPath

UMBRELLA = Path(__file__).resolve().parents[1]
MAKEFILE = UMBRELLA / "Makefile"


def _make_variable(name: str) -> str:
    """A simple ``NAME := value`` assignment in helm/Makefile."""
    match = re.search(rf"^{name}\s*:?=\s*(\S+)\s*$", MAKEFILE.read_text(), re.MULTILINE)
    assert match, f"{name} not assigned in {MAKEFILE}"
    return match.group(1)


def _make_words(name: str) -> list[str]:
    """The words of a ``NAME := a b \\`` assignment in helm/Makefile, continuation
    lines included."""
    text = MAKEFILE.read_text().replace("\\\n", " ")
    match = re.search(rf"^{name}\s*:?=(.*)$", text, re.MULTILINE)
    assert match, f"{name} not assigned in {MAKEFILE}"
    return match.group(1).split()


RELEASE_ONE = _make_variable("RELEASE")
RELEASE_TWO = _make_variable("TOPOLOGY_RELEASE")
OVERLAY = UMBRELLA / _make_variable("TOPOLOGY_VALUES")
RELEASE_ONE_VALUES = (UMBRELLA / "values.yaml", UMBRELLA / "local-values.yaml")
RELEASE_TWO_VALUES = (*RELEASE_ONE_VALUES, OVERLAY)

# The payments lane double, whose committed fixtures the releases' payments
# values restate, and the script a Compose lane reads them with.
DOUBLE = UMBRELLA.parent / "tools" / "payments-lane-double"
# The lane CA, which the controls project generates for both lane doubles.
LANE_CA = UMBRELLA.parent / "tools" / "lane-double-controls" / "tls" / "lane-ca.pem"
# The mediation lane double's committed fixture, whose identity the release's
# registry recommends.
MEDIATION_AUTHORITY = UMBRELLA.parent / "tools" / "mediation-lane-double" / "fixtures" / "authority.toml"
# Bob's Compose secret overlay, whose dispute credential topology-secrets copies
# into his runtime overlay.
BOB_COMPOSE_SECRETS = UMBRELLA.parent / "dev-env" / "identities" / "bob.storefront.secrets.toml"
_LANE_ENV_SPEC = importlib.util.spec_from_file_location("lane_env", DOUBLE / "scripts" / "lane_env.py")
assert _LANE_ENV_SPEC is not None and _LANE_ENV_SPEC.loader is not None
lane_env = importlib.util.module_from_spec(_LANE_ENV_SPEC)
_LANE_ENV_SPEC.loader.exec_module(lane_env)


def _render(release: str, values: tuple[Path, ...], overlay: dict | None = None) -> subprocess.CompletedProcess[str]:
    with tempfile.NamedTemporaryFile("w", suffix=".json") as handle:
        json.dump(overlay or {}, handle)
        handle.flush()
        command = ["helm", "template", release, str(UMBRELLA)]
        for path in (*values, Path(handle.name)):
            command += ["--values", str(path)]
        return subprocess.run(command, check=False, capture_output=True, text=True)


def _ok(rendered: subprocess.CompletedProcess[str]) -> str:
    assert rendered.returncode == 0, rendered.stderr
    return rendered.stdout


def _release_one(overlay: dict | None = None) -> str:
    return _ok(_render(RELEASE_ONE, RELEASE_ONE_VALUES, overlay))


def _release_two(overlay: dict | None = None) -> str:
    return _ok(_render(RELEASE_TWO, RELEASE_TWO_VALUES, overlay))


def _documents(manifest: str) -> list[str]:
    return manifest.split("\n---\n")


def _source(manifest: str, path: str) -> str:
    """The rendered document whose ``# Source:`` ends with ``path``."""
    for document in _documents(manifest):
        if any(line.startswith("# Source: ") and line.endswith(path) for line in document.splitlines()):
            return document
    raise AssertionError(f"{path} not rendered")


def _sources(manifest: str) -> set[str]:
    return {line.removeprefix("# Source: ") for line in manifest.splitlines() if line.startswith("# Source: ")}


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


def _storefront_document(manifest: str) -> dict:
    return json.loads(_block(_source(manifest, "bare-metal-storefront/templates/configmap.yaml"), "storefront.json"))


def _provisioning_document(manifest: str) -> dict:
    return json.loads(_block(_source(manifest, "provisioning/templates/configmap.yaml"), "config-production.yml"))


def _smoke_profile(manifest: str) -> dict:
    return json.loads(_block(_source(manifest, "templates/tests/test-config.yaml"), "config-helm.yml"))


def _named(manifest: str, kind: str, name: str) -> str:
    """The rendered ``kind`` named ``name``."""
    for document in _documents(manifest):
        lines = document.splitlines()
        if f"kind: {kind}" in lines and f"  name: {name}" in lines:
            return document
    raise AssertionError(f"no {kind} {name} rendered")


def _service_url(manifest: str, name: str) -> str:
    """``http://<name>:<port>`` for the Service ``name`` renders."""
    service = _named(manifest, "Service", name)
    port = re.search(r"^\s+port: (\d+)$", service, re.MULTILINE)
    assert port, f"Service {name} renders no port"
    return f"http://{name}:{port.group(1)}"


def _labelled(manifest: str, kind: str) -> list[tuple[str, str]]:
    """``(name, app.kubernetes.io/name)`` of every rendered ``kind``."""
    found = []
    for document in _documents(manifest):
        lines = document.splitlines()
        if f"kind: {kind}" not in lines:
            continue
        name = next(line.split(": ", 1)[1] for line in lines if line.startswith("  name: "))
        component = next(line.split(": ", 1)[1] for line in lines if line.startswith("    app.kubernetes.io/name: "))
        found.append((name, component))
    return found


def _env(document: str, name: str) -> str:
    match = re.search(rf"- name: {name}\n\s+value: \"?([^\"\n]+)\"?", document)
    assert match, f"{name} not set"
    return match.group(1)


_PROFILE_LINE = re.compile(r"([A-Z_]+)='((?:\\'|[^'])*)'(?:\n|$)")


def _registry_profile(manifest: str, chart: str = "registry") -> dict[str, str]:
    """The settings a registry chart renders into ``config-production.env``,
    each ``NAME='value'`` line decoded as the registry's dotenv reader decodes a
    single-quoted value, ``\\\\`` and ``\\'`` only. That is its reading of every
    value the chart renders, since the chart refuses the two it would read
    otherwise; the registry's own loader reads one rendered profile in
    ``test_the_rendered_registry_profile_loads_with_the_registry_loader``."""
    text = _block(_source(manifest, f"charts/{chart}/templates/configmap.yaml"), "config-production.env")
    lines = list(_PROFILE_LINE.finditer(text))
    assert "".join(line.group(0) for line in lines) == text, f"{chart} renders a line that is not NAME='value'"
    return {line[1]: re.sub(r"\\([\\'])", r"\1", line[2]) for line in lines}


# --- release 2 ------------------------------------------------------------


def test_release_two_provisioning_admits_and_calls_back_the_bare_metal_storefront() -> None:
    """Release 2's provisioning service trusts the bare-metal storefront's
    signer for its requests and callbacks and calls back its Service, and the
    storefront's `default` site is that provisioning service, trusted under its
    own signer."""
    manifest = _release_two()
    storefront = _storefront_document(manifest)
    provisioning = _provisioning_document(manifest)

    storefront_service = _service_url(manifest, f"{RELEASE_TWO}-bare-metal-storefront")
    provisioning_service = _service_url(manifest, f"{RELEASE_TWO}-provisioning")
    assert provisioning["storefront_identity"] == storefront["Identity"]["principal"]
    assert provisioning["storefront_url"] == storefront_service == storefront["base_url"]
    assert storefront["capacity"]["sites"] == {"default": provisioning_service}
    (peer,) = storefront["Identity"]["service_peers"].values()
    assert peer["role"] == "service" and peer["site_id"] == "default"
    assert peer["principals"] == [provisioning["identity"]]
    # Release 2's provisioning signs as its own principal, not release 1's.
    assert provisioning["identity"] != _provisioning_document(_release_one())["identity"]


def test_release_two_publishes_to_release_ones_registry_under_its_pinned_trust() -> None:
    """The bare-metal storefront's one registry is release 1's Service, its
    trust the principal release 1's registry signs as; its chain and Alkahest
    address book are release 1's dev-env."""
    release_one = _release_one()
    storefront = _storefront_document(_release_two())
    registry = _registry_profile(release_one)

    registry_url = _service_url(release_one, f"{RELEASE_ONE}-registry")
    assert storefront["registry"]["urls"] == [registry_url]
    assert storefront["registry"]["authorities"] == {
        registry_url: {
            "authority": registry["REGISTRY_AUTHORITY_ID"],
            "principals": [
                {
                    "scheme": registry["REGISTRY_AUTHORITY_SCHEME"],
                    "identifier": registry["REGISTRY_AUTHORITY_IDENTIFIER"],
                }
            ],
        }
    }
    chain = _service_url(release_one, f"{RELEASE_ONE}-dev-env")
    assert storefront["Chains"]["anvil"]["rpc_url"] == chain.replace("http://", "ws://", 1)
    address_book = _named(release_one, "ConfigMap", f"{RELEASE_ONE}-dev-env-alkahest-addresses")
    assert "  alkahest_anvil_addresses.json: |" in address_book.splitlines()
    deployment = _source(_release_two(), "bare-metal-storefront/templates/deployment.yaml")
    assert f'name: "{RELEASE_ONE}-dev-env-alkahest-addresses"' in {line.strip() for line in deployment.splitlines()}
    path = "/etc/arkhai/alkahest/alkahest_anvil_addresses.json"
    assert storefront["Settlement"]["alkahest"]["address_books"] == {"anvil": path}
    assert "alkahest_address_config_path" not in storefront["Chains"]["anvil"]
    assert "address_config_path" not in storefront["Settlement"]["alkahest"]


def test_release_two_runs_only_its_storefront_and_provisioning_service() -> None:
    manifest = _release_two()
    charts = {source.split("/")[2] for source in _sources(manifest) if source.split("/")[1] == "charts"}

    assert charts == {"bare-metal-storefront", "provisioning"}
    # Its smoke-test profile names its own provisioning service and no VM agent
    # or registry, which release 2 does not run.
    profile = _smoke_profile(manifest)
    assert sorted(profile) == ["provisioning", "rpc", "settlement"]
    assert profile["provisioning"]["api_url"] == _service_url(manifest, f"{RELEASE_TWO}-provisioning")


def test_release_two_refuses_a_provisioning_service_that_does_not_trust_its_storefront() -> None:
    """With the VM storefront disabled, the smoke-test profile checks the
    bare-metal storefront's signer against provisioning's trust instead."""
    # Bob's principal, Anvil account 2: a well-known development address, never
    # for a public network.
    distrusted = {
        "provisioning": {
            "storefrontIdentity": {
                "principals": [{"scheme": "eip191", "identifier": "0x3c44cdddb6a900fa2b585dd299e03d12fa4293bc"}]
            }
        }
    }
    refused = _render(RELEASE_TWO, RELEASE_TWO_VALUES, distrusted)

    assert refused.returncode != 0, "render succeeded"
    assert "must include the bare-metal storefront's config.Identity.principal" in refused.stderr


# --- release 1 ------------------------------------------------------------


def test_release_one_runs_bob_on_its_own_provisioning_service() -> None:
    """Release 1 runs the registry, Bob, provisioning, and dev-env, and no
    bare-metal storefront; its provisioning service trusts and calls back Bob,
    and its smoke tests target Bob and the release's registry. These are the
    properties the release keeps; they are not compared with an earlier
    render."""
    manifest = _release_one()
    charts = {source.split("/")[2] for source in _sources(manifest) if source.split("/")[1] == "charts"}
    provisioning = _provisioning_document(manifest)
    bob = json.loads(_block(_source(manifest, "storefront/templates/configmap.yaml"), "storefront.json"))

    assert {"registry", "storefront", "provisioning", "dev-env"} <= charts
    assert "bare-metal-storefront" not in charts
    assert provisioning["storefront_identity"] == bob["Identity"]["principal"]
    assert provisioning["storefront_url"] == _service_url(manifest, f"{RELEASE_ONE}-storefront-bob")
    profile = _smoke_profile(manifest)
    assert profile["seller"]["api_url"] == _service_url(manifest, f"{RELEASE_ONE}-storefront-bob")
    assert profile["registry"]["api_url"] == _service_url(manifest, f"{RELEASE_ONE}-registry")


def test_release_ones_smoke_profile_carries_the_pins_and_wallets_the_release_states() -> None:
    """The registry smoke test's pins are the registry the release's clients
    trust, which is the identity release 1's registry signs as; contract
    validation's wallets are the e2e-tests chart's buyer and Bob's
    `[Wallet].address`; the registry smoke test's buyer credential comes from
    the e2e-tests chart's Secret, layered as its `e2e-secret` profile."""
    manifest = _release_one()
    profile = _smoke_profile(manifest)
    registry = _registry_profile(manifest)
    bob = json.loads(_block(_source(manifest, "storefront/templates/configmap.yaml"), "storefront.json"))

    assert profile["registry"]["authority_id"] == registry["REGISTRY_AUTHORITY_ID"]
    assert profile["registry"]["identifier"] == registry["REGISTRY_AUTHORITY_IDENTIFIER"]
    # The e2e-tests chart's buyer, Anvil account 1: a well-known development
    # address, never for a public network.
    assert profile["buyer"]["wallet_address"] == "0x70997970c51812dc3a010c7d01b50e0d17dc79c8"
    assert profile["seller"]["wallet_address"] == bob["Wallet"]["address"]
    assert "marketplace_credential" not in profile["buyer"]

    smoke = _source(manifest, "charts/registry/templates/tests/registry-environment-test.yaml")
    deal = _source(manifest, "charts/e2e-tests/templates/tests/e2e-deal-test.yaml")
    secret = re.search(r"secretName: \"([^\"]+)\"", smoke)
    assert secret and secret.group(1) == "arkhai-e2e-credentials" in _make_words("TEST_SECRETS")
    assert f"secretName: {secret.group(1)}" in {line.strip() for line in deal.splitlines()}
    assert _env(smoke, "ACTIVE_PROFILES") == "helm,e2e-secret"
    assert "mountPath: /app/config/config-e2e-secret.yml" in {line.strip() for line in smoke.splitlines()}


def test_the_smoke_profile_pins_each_releases_provisioning_signer() -> None:
    """The provisioning smoke test verifies the service's responses against
    `provisioning.authority_scheme` and `authority_identifier`: each release's
    profile carries the signer its provisioning service renders, its own
    global.provisioningIdentity, whatever its scheme, and never the
    administrator credential, which is signing material."""
    ed25519 = _ok(_render(RELEASE_ONE, (UMBRELLA / "values.yaml", UMBRELLA / "fixtures/payments-ed25519-values.yaml")))
    for manifest in (_release_one(), _release_two(), ed25519):
        signer = _provisioning_document(manifest)["identity"]
        profile = _smoke_profile(manifest)["provisioning"]
        assert {"scheme": profile["authority_scheme"], "identifier": profile["authority_identifier"]} == signer
        assert "admin_credential" not in profile
    assert _smoke_profile(_release_two())["provisioning"]["authority_identifier"] != (
        _smoke_profile(_release_one())["provisioning"]["authority_identifier"]
    )


def test_each_registry_keeps_its_database_on_its_volume() -> None:
    """Release 1's registry, and the API-credits registry where it is enabled,
    keep their SQLite database under the mount of the PersistentVolumeClaim
    their chart renders, so a replaced registry pod -- `topology-up` restarts
    the registry on every run -- keeps its listings."""
    manifest = _release_one({"api-credits-registry": {"enabled": True}})
    for chart in ("registry", "api-credits-registry"):
        deployment = _source(manifest, f"charts/{chart}/templates/deployment.yaml")
        url = _registry_profile(manifest, chart)["DATABASE_URL"]
        assert url.startswith("sqlite:///"), url
        database = PurePosixPath(url.removeprefix("sqlite:///"))
        mount = re.search(r'- name: arkhai-data\n\s+mountPath: "?([^"\n]+)"?', deployment)
        claim = re.search(r'- name: arkhai-data\n\s+persistentVolumeClaim:\n\s+claimName: "?([^"\n]+)"?', deployment)
        assert mount and claim, f"{chart} mounts no claim as arkhai-data"
        assert database.is_absolute() and PurePosixPath(mount.group(1)) in database.parents, (chart, url, mount.group(1))
        _named(manifest, "PersistentVolumeClaim", claim.group(1))


def test_the_registry_smoke_test_appends_its_credential_profile_once() -> None:
    """The credential profile follows the test's profiles whether the chart
    states them or global.smokeTests derives them, and is not listed twice."""
    def profiles(active: str) -> str:
        overlay = {"registry": {"tests": {"activeProfiles": active}}}
        smoke = _source(_release_one(overlay), "charts/registry/templates/tests/registry-environment-test.yaml")
        return _env(smoke, "ACTIVE_PROFILES")

    assert profiles("helm,extra") == "helm,extra,e2e-secret"
    assert profiles("e2e-secret,helm") == "e2e-secret,helm"


def test_the_smoke_profile_carries_only_what_the_release_states() -> None:
    """A wallet is carried only where the release states it, and registry pins
    only for the release's own EIP-191 registry; the chart defaults mount no
    credential profile."""
    defaults = _ok(_render(RELEASE_ONE, (UMBRELLA / "values.yaml",)))
    profile = _smoke_profile(defaults)
    assert "wallet_address" not in profile["seller"]
    assert profile["registry"]["authority_id"] == "registry-a"
    smoke = _source(defaults, "charts/registry/templates/tests/registry-environment-test.yaml")
    assert "credential-profile" not in smoke and _env(smoke, "ACTIVE_PROFILES") == "helm"

    # The smoke test verifies only EIP-191 signatures, so an ed25519 registry
    # identity is not pinned.
    ed25519 = _ok(_render(RELEASE_ONE, (UMBRELLA / "values.yaml", UMBRELLA / "fixtures/payments-ed25519-values.yaml")))
    registry = _smoke_profile(ed25519)["registry"]
    assert registry["authorities"] and "authority_id" not in registry and "identifier" not in registry

    # A buyer of another development account flows through; without the
    # e2e-tests chart there is no development buyer. Anvil account 3: a
    # well-known development address, never for a public network.
    other = "0x90f79bf6eb2c4f870365e785982e1f101e93b906"
    buyer = {"e2e-tests": {"buyer": {"identity": {"identifier": other}}}}
    assert _smoke_profile(_release_one(buyer))["buyer"]["wallet_address"] == other
    without = _smoke_profile(_release_one({"e2e-tests": {"enabled": False}}))
    assert "wallet_address" not in without["buyer"]

    # A registry Bob names in registry.urls is not the release's, so the
    # profile carries its trust but no pins of the release's registry.
    external = "https://registry.example.com"  # placeholder on a reserved domain
    trust = {"authority": "registry-a", "principals": [{"scheme": "eip191", "identifier": other}]}
    elsewhere = {
        "storefront": {
            "agents": {
                "bob": {
                    "internalRegistryTrust": None,
                    "config": {"registry": {"urls": [external], "authorities": {external: trust}}},
                }
            }
        }
    }
    registry = _smoke_profile(_release_one(elsewhere))["registry"]
    assert registry["api_url"] == external and registry["authorities"] == {external: trust}
    assert "authority_id" not in registry and "identifier" not in registry


def test_a_registry_signing_as_another_identity_than_its_clients_trust_is_refused() -> None:
    """The pins are what the release's clients trust; the registry the release
    runs must sign as that identity."""
    # Anvil account 4: a well-known development address, never for a public network.
    other = {"registry": {"identity": {"principal": {"identifier": "0x15d34aaf54267db7d7c367839aaf71a00a2c6a65"}}}}
    refused = _render(RELEASE_ONE, RELEASE_ONE_VALUES, other)

    assert refused.returncode != 0, "render succeeded"
    assert "global.registryIdentity, the registry the release's clients trust, must equal registry.identity" in refused.stderr
    # Release 2 runs no registry, so it is not checked there.
    _release_two(other)


def test_topology_up_restarts_every_deployment_but_the_chain() -> None:
    """`topology-up`'s restart order is the component of every Deployment either
    release renders, in dependency order, except dev-env's: Anvil reloads its
    state file, so the contracts survive, but a restart loses every transaction
    since start-up that the other releases' volumes still refer to."""
    order = _make_words("TOPOLOGY_ROLLOUT_ORDER")
    deployments = _labelled(_release_one(), "Deployment") + _labelled(_release_two(), "Deployment")
    components = {component for _, component in deployments}

    assert order == ["registry", "provisioning", "storefront", "bare-metal-storefront"]
    # The lane doubles are left out for the same reason as the chain: they keep
    # every payment and case in memory, which a restart loses.
    assert components == {*order, "dev-env", "payments-lane-double", "mediation-lane-double"}


def _mapping_under(lines: list[str], header: str) -> dict[str, str]:
    """The ``key: value`` lines nested under the first line equal to ``header``,
    at the next indentation, with any quotes around a value removed."""
    start = lines.index(header)
    indent = " " * (len(header) - len(header.lstrip()) + 2)
    mapping = {}
    for line in lines[start + 1 :]:
        if not line.startswith(indent) or line.startswith(indent + " "):
            break
        key, value = line.strip().split(": ", 1)
        mapping[key.strip('"')] = value.strip('"')
    return mapping


_TEST_HOOK = re.compile(r'^\s+"?helm\.sh/hook"?: "?test"?$', re.MULTILINE)


def _selectors_and_test_pods(
    manifest: str,
) -> tuple[dict[str, dict[str, str]], dict[str, dict[str, str]]]:
    """Every rendered Deployment's ``spec.selector.matchLabels`` and Service's
    ``spec.selector``, each by its kind and name, and every Pod annotated
    ``helm.sh/hook: test``'s labels, by its name."""
    selectors, test_pods = {}, {}
    for document in _documents(manifest):
        lines = document.splitlines()
        deployment = "kind: Deployment" in lines
        service = "kind: Service" in lines and "  selector:" in lines
        test_pod = "kind: Pod" in lines and _TEST_HOOK.search(document) is not None
        if not (deployment or service or test_pod):
            continue
        name = next(line.split(": ", 1)[1].strip('"') for line in lines if line.startswith("  name: "))
        if deployment:
            selectors[f"Deployment/{name}"] = _mapping_under(lines, "    matchLabels:")
        elif service:
            selectors[f"Service/{name}"] = _mapping_under(lines, "  selector:")
        else:
            test_pods[name] = _mapping_under(lines, "  labels:")
    return selectors, test_pods


def _test_templates(manifest: str) -> dict[str, str]:
    """Every Pod rendered from a chart's ``templates/tests/``: its name, and
    the template it was rendered from, from ``templates/tests/`` on."""
    templates = {}
    for document in _documents(manifest):
        lines = document.splitlines()
        source = next(
            (line for line in lines if line.startswith("# Source: ") and "/templates/tests/" in line),
            None,
        )
        if "kind: Pod" in lines and source is not None:
            name = next(line.split(": ", 1)[1].strip('"') for line in lines if line.startswith("  name: "))
            templates[name] = source[source.index("templates/tests/") :]
    return templates


#: The test templates each topology release renders a Pod from, so a test pod
#: that stops rendering fails here rather than leaving nothing to check.
_EXPECTED_TEST_TEMPLATES = {
    RELEASE_ONE: {
        "templates/tests/registry-environment-test.yaml",
        "templates/tests/storefront-environment-test.yaml",
        "templates/tests/provisioning-smoke-test.yaml",
        "templates/tests/e2e-deal-test.yaml",
        "templates/tests/chain-environment-test.yaml",
        "templates/tests/payments-check-test.yaml",
        "templates/tests/mediation-check-test.yaml",
    },
    RELEASE_TWO: {
        "templates/tests/provisioning-smoke-test.yaml",
        "templates/tests/health-test.yaml",
        "templates/tests/payments-check-test.yaml",
    },
}


def test_no_test_pod_carries_a_workload_selector() -> None:
    """The deployment-state scenario "Both topology releases are rendered", a
    static stand-in for selecting a workload's pods in a cluster: no Helm test
    pod carries all of any Deployment's or Service's selector, since every test
    pod lacks ``app.kubernetes.io/name``, which every selector requires, and
    each carries its release's instance label and ``component: test``."""
    for release_name, release in ((RELEASE_ONE, _release_one()), (RELEASE_TWO, _release_two())):
        selectors, test_pods = _selectors_and_test_pods(release)
        templates = _test_templates(release)
        # Every test template's Pod is read as a test pod, so none escapes the
        # checks below by a hook annotation spelled some other way.
        assert set(test_pods) == set(templates), (sorted(test_pods), release_name)
        assert set(templates.values()) == _EXPECTED_TEST_TEMPLATES[release_name], (
            sorted(templates.values()),
            release_name,
        )
        assert any(key.startswith("Service/") for key in selectors), (sorted(selectors), release_name)
        assert selectors and test_pods, (sorted(selectors), sorted(test_pods))
        assert all("app.kubernetes.io/name" in selector for selector in selectors.values()), selectors
        for pod, labels in test_pods.items():
            assert labels.get("app.kubernetes.io/component") == "test", (pod, labels)
            assert labels.get("app.kubernetes.io/instance") == release_name, (pod, labels)
            assert "app.kubernetes.io/name" not in labels, (pod, labels)
            for deployment, selector in selectors.items():
                assert not selector.items() <= labels.items(), (pod, deployment)


def _secret_references(manifest: str) -> set[str]:
    named = re.findall(r'secretName: "?([^"\s]+)"?', manifest)
    keyed = re.findall(r'secretKeyRef:\n\s+name: "?([^"\s]+)"?', manifest)
    return {*named, *keyed}


def test_topology_secrets_creates_every_secret_both_releases_read() -> None:
    """`topology-secrets` creates exactly the Secrets the two releases'
    workloads and Helm tests reference, which are the ones the topology
    targets check for."""
    script = (UMBRELLA / "scripts" / "topology-secrets.sh").read_text()
    created = set(re.findall(r"^(?:credential|apply) (\S+)", script, re.MULTILINE))
    referenced = _secret_references(_release_one()) | _secret_references(_release_two())
    checked = {*_make_words("LOCAL_SECRETS"), *_make_words("TOPOLOGY_SECRETS"), *_make_words("TEST_SECRETS")}

    assert created == referenced == checked, (created, referenced, checked)


def _container_env_names(document: str) -> list[str]:
    """The variable names of the first container ``env`` block in ``document``:
    the list items nested under its ``env:`` line."""
    lines = document.splitlines()
    start = next(index for index, line in enumerate(lines) if line.strip() == "env:")
    indent = len(lines[start]) - len(lines[start].lstrip())
    names = []
    for line in lines[start + 1 :]:
        if line.strip() and len(line) - len(line.lstrip()) <= indent:
            break
        match = re.fullmatch(r"\s*- name: \"?([^\"]+)\"?", line)
        if match:
            names.append(match.group(1))
    return names


def _configmap_references(manifest: str) -> set[str]:
    return set(re.findall(r'configMap:\n\s+name: "?([^"\s]+)"?', manifest))


def _rendered_names(manifest: str, kind: str) -> set[str]:
    names = set()
    for document in _documents(manifest):
        lines = document.splitlines()
        if f"kind: {kind}" in lines:
            names.add(next(line.split(": ", 1)[1].strip('"') for line in lines if line.startswith("  name: ")))
    return names


def test_topology_secrets_creates_every_configmap_the_releases_read_and_no_chart_renders() -> None:
    """The one such ConfigMap is the storefronts' CA bundle, created from the
    lane doubles' committed lane CA under the key both storefronts
    mount; `check-local-secrets` checks for it. Neither storefront reads a
    payments key from a Secret key: the key is in the runtime Secret's overlay
    each mounts (scripts/tests/test_change_build_and_helm_targets.py runs the
    script and reads the overlays it writes)."""
    release_one, release_two = _release_one(), _release_two()
    referenced = _configmap_references(release_one) | _configmap_references(release_two)
    rendered = _rendered_names(release_one, "ConfigMap") | _rendered_names(release_two, "ConfigMap")
    script = (UMBRELLA / "scripts" / "topology-secrets.sh").read_text()
    created = set(re.findall(r"kubectl create configmap (\S+)", script))

    assert referenced - rendered == created == set(_make_words("LOCAL_CONFIGMAPS")) == {"payments-ca-bundle"}
    assert '"--from-file=ca-bundle.pem=$PAYMENTS_LANE_CA_FILE"' in script
    assert (UMBRELLA / _make_variable("PAYMENTS_LANE_CA_FILE")).resolve() == LANE_CA
    assert (UMBRELLA / _make_variable("PAYMENTS_LANE_ENV")).resolve() == DOUBLE / "scripts" / "lane_env.py"
    for manifest, chart, runtime in (
        (release_one, "storefront", "arkhai-bob-runtime"),
        (release_two, "bare-metal-storefront", "arkhai-bare-metal-storefront-runtime"),
    ):
        for path in ("templates/deployment.yaml", "templates/tests/payments-check-test.yaml"):
            document = _source(manifest, f"charts/{chart}/{path}")
            assert re.search(r'configMap:\n\s+name: "payments-ca-bundle"\n\s+items:\n\s+- key: "ca-bundle.pem"', document)
            assert re.search(rf'secret:\n\s+secretName: "{runtime}"\n\s+items:\n\s+- key: "?storefront\.secrets\.toml"?', document)
            # The configuration directory and the signing credential, and no
            # payments variable.
            assert _container_env_names(document) == ["XDG_CONFIG_HOME", "ARKHAI_IDENTITY_CREDENTIAL"], (chart, path)


# --- the payments rehearsal -------------------------------------------------


def _fixture(name: str) -> dict:
    with (DOUBLE / "fixtures" / name).open("rb") as handle:
        return tomllib.load(handle)


def _recommended_mediation_double() -> dict:
    """The mediation double's identity, params and advertisement, as a registry
    recommends it, from its committed fixture."""
    with MEDIATION_AUTHORITY.open("rb") as handle:
        authority = tomllib.load(handle)
    return {key: authority[key] for key in
            ("interface", "origin", "account", "record_key", "params", "advertisement")}


def _lane_runner_payments() -> dict:
    """The lanes' shared runner profile's `payments` mapping. Each top-level
    section is one flat mapping of JSON scalars, quoted strings, numbers and
    booleans, read here line by line because this suite has no YAML parser."""
    path = UMBRELLA.parent / "e2e-tests" / "config" / "config-payments-lane.yml"
    values = {}
    section = None
    for line in path.read_text(encoding="utf-8").splitlines():
        heading = re.fullmatch(r"([a-z_]+):", line)
        if heading:
            section = heading[1]
            continue
        match = re.fullmatch(r"  ([a-z_]+): (.+)", line)
        if match and section == "payments":
            values[match[1]] = json.loads(match[2])
    return values


def _bob_document(manifest: str) -> dict:
    return json.loads(_block(_source(manifest, "storefront/templates/configmap.yaml"), "storefront.json"))


def test_the_two_releases_run_one_payments_double_and_both_storefronts_reach_it() -> None:
    """Release 1 runs the double; release 2 runs none and its storefront reaches
    release 1's by the Service name, `payments-double`, that is the same in every
    release and is the name the double's certificate covers."""
    release_one, release_two = _release_one(), _release_two()

    deployments = [name for name, component in _labelled(release_one, "Deployment") if component == "payments-lane-double"]
    assert deployments == [f"{RELEASE_ONE}-payments-lane-double"]
    assert not any("/charts/payments-lane-double/" in source for source in _sources(release_two))
    service = _named(release_one, "Service", "payments-double")
    port = re.search(r"^\s+port: (\d+)$", service, re.MULTILINE)
    assert port, "Service payments-double renders no port"
    url = f"https://payments-double:{port.group(1)}"
    assert url == lane_env.SERVICE_URL
    for document in (_bob_document(release_one), _storefront_document(release_two)):
        assert document["Settlement"]["arkhai_payments"]["service_url"] == url


def _recommended_dispute_authorities(manifest: str) -> list:
    profile = _registry_profile(manifest)
    assert "REGISTRY_DESCRIPTOR_RECOMMENDED_DISPUTE_AUTHORITIES" in profile, "the registry recommends no dispute authority"
    return json.loads(profile["REGISTRY_DESCRIPTOR_RECOMMENDED_DISPUTE_AUTHORITIES"])


def test_the_local_payments_values_are_the_payments_doubles_committed_fixtures() -> None:
    """Each payments value the two releases state restates the double's
    fixtures: the receipt identity and fee both storefronts pin, the seller
    account both payments checks read, and the e2e-tests chart's PAYMENTS
    settings, which are the ones a Compose lane's runner receives. The registry
    recommends the mediation double, restating its fixture. No storefront uses
    development authentication."""
    accounts = _fixture("accounts.toml")
    release_one, release_two = _release_one(), _release_two()
    seller = accounts["accounts"]["seller"]["account"]

    for manifest, document, check in (
        (release_one, _bob_document(release_one), "storefront/templates/tests/payments-check-test.yaml"),
        (release_two, _storefront_document(release_two), "bare-metal-storefront/templates/tests/payments-check-test.yaml"),
    ):
        payments = document["Settlement"]["arkhai_payments"]
        assert payments["enabled"] is True
        assert payments["service_identity"] == accounts["receipt_identity"]
        assert payments["fee_bps"] == accounts["fee_bps"]
        assert payments["livemode"] is False
        # Trust through the chart's derived path to the mounted lane CA; the key
        # is in the runtime overlay, never named or stated in the public document.
        assert payments["ca_bundle_path"] == "/etc/arkhai/ca/ca-bundle.pem"
        assert not {"api_key", "api_key_env", "development_auth"} & set(payments)
        assert "arkhai.payments.v1" in document["Settlement"]["priority"]
        assert f'- "{seller}"' in {line.strip() for line in _source(manifest, check).splitlines()}
        assert "development_auth" not in manifest

    assert _recommended_dispute_authorities(release_one) == [_recommended_mediation_double()]

    # The release's runner profile states the lanes' public payments settings, as
    # the lanes' committed runner profile does, which test_lane_env.py holds to
    # the same fixtures.
    profile = _smoke_profile(release_one)["payments"]
    assert profile == {
        "service_url": lane_env.SERVICE_URL,
        "service_identity": accounts["receipt_identity"]["identifier"],
        "fee_bps": accounts["fee_bps"],
        "livemode": False,
        "lane_owned": True,
        "api_key_env": _lane_runner_payments()["api_key_env"],
        "buyer_account": accounts["accounts"]["buyer"]["account"],
        "seller_account": seller,
    }
    lane = _lane_runner_payments()
    assert {key: lane[key] for key in profile} == profile
    assert "payments" not in _smoke_profile(release_two)


def test_bobs_mediation_check_reads_the_mediation_double_his_credential_names() -> None:
    """Release 1 runs the mediation double behind `mediation-double`, the name
    its leaf covers, and release 2 runs none. Bob's mediation check names the
    origin that Service answers, which is the double's fixture origin and the
    origin of the dispute credential his runtime overlay copies from his Compose
    overlay, so the check selects that credential."""
    release_one, release_two = _release_one(), _release_two()

    deployments = [name for name, component in _labelled(release_one, "Deployment")
                   if component == "mediation-lane-double"]
    assert deployments == [f"{RELEASE_ONE}-mediation-lane-double"]
    assert not any("/charts/mediation-lane-double/" in source for source in _sources(release_two))
    service = _named(release_one, "Service", "mediation-double")
    port = re.search(r"^\s+port: (\d+)$", service, re.MULTILINE)
    assert port, "Service mediation-double renders no port"
    origin = f"https://mediation-double:{port.group(1)}"

    check = _source(release_one, "storefront/templates/tests/mediation-check-test.yaml")
    assert f'- "{origin}"' in {line.strip() for line in check.splitlines()}
    assert _recommended_mediation_double()["origin"] == origin
    with BOB_COMPOSE_SECRETS.open("rb") as handle:
        (credential,) = tomllib.load(handle)["DisputeCredential"]
    assert credential["origin"] == origin


def test_the_e2e_tests_chart_refuses_a_payments_credential() -> None:
    """The PAYMENTS settings render into a ConfigMap, so the parties'
    marketplace credentials and development authentication are refused."""
    for key, value in (
        ("buyer_marketplace_credential", "x"),
        ("seller_marketplace_credential", "x"),
        ("development_auth", True),
    ):
        refused = _render(RELEASE_ONE, RELEASE_ONE_VALUES, {"e2e-tests": {"payments": {key: value}}})
        assert refused.returncode != 0, key
        assert key in refused.stderr, refused.stderr


def test_topology_secrets_creates_the_volume_the_deal_test_mounts() -> None:
    """The claim `topology-secrets` creates, and `topology-check` checks for, is
    the one release 1's deal test mounts; release 2 runs no deal test."""
    deal = _source(_release_one(), "charts/e2e-tests/templates/tests/e2e-deal-test.yaml")
    mounted = set(re.findall(r'claimName: "?([^"\s]+)"?', deal))
    script = (UMBRELLA / "scripts" / "topology-secrets.sh").read_text()

    assert mounted == set(_make_words("TEST_VOLUMES")) == {"arkhai-buyer-profiles"}
    assert "for claim in $TEST_VOLUMES; do" in script
    assert not any("/charts/e2e-tests/" in source for source in _sources(_release_two()))


def test_release_one_still_refuses_a_provisioning_service_that_does_not_trust_bob() -> None:
    # The bare-metal storefront's principal, Anvil account 8: a well-known
    # development address, never for a public network.
    distrusted = {
        "provisioning": {
            "storefrontIdentity": {
                "principals": [{"scheme": "eip191", "identifier": "0x23618e81e3f5cdf7f54c3d65f7fbc0abf5b21e8f"}]
            }
        }
    }
    refused = _render(RELEASE_ONE, RELEASE_ONE_VALUES, distrusted)

    assert refused.returncode != 0, "render succeeded"
    assert "must include the active storefront signer principal" in refused.stderr


def test_one_release_running_both_storefronts_on_its_provisioning_service_is_refused() -> None:
    """The release's provisioning service trusts and calls back one storefront,
    so a bare-metal storefront bound to it beside Bob is refused, naming the
    second release that runs it; bound to a site of its own it is not."""
    both = {"bare-metal-storefront": {"enabled": True}}
    refused = _render(RELEASE_ONE, RELEASE_ONE_VALUES, both)

    assert refused.returncode != 0, "render succeeded"
    assert "run the bare-metal storefront as a second release" in refused.stderr
    assert OVERLAY.name in refused.stderr and "make helm-topology-up" in refused.stderr
    own_site = {
        "bare-metal-storefront": {
            "enabled": True,
            "internalRegistryTrust": None,
            "config": {
                # Placeholder URLs on a reserved domain.
                "registry": {"urls": ["https://registry.example.com"]},
                "capacity": {"sites": {"site-a": "https://site-a.example.com"}},
            },
        }
    }
    _ok(_render(RELEASE_ONE, RELEASE_ONE_VALUES, own_site))

    # A later values file removing those sites leaves the derived `default` site on
    # the release's provisioning service, which the release refuses again: the
    # check reads the bare-metal config with its nulls removed.
    with tempfile.NamedTemporaryFile("w", suffix=".json") as stated:
        json.dump(own_site, stated)
        stated.flush()
        removed = _render(
            RELEASE_ONE,
            (*RELEASE_ONE_VALUES, Path(stated.name)),
            {"bare-metal-storefront": {"config": {"capacity": {"sites": None}}}},
        )
    assert removed.returncode != 0, "render succeeded"
    assert "run the bare-metal storefront as a second release" in removed.stderr, removed.stderr


# --- the registry's profile -------------------------------------------------


def _resolver_environment(deployment: str) -> dict[str, str]:
    """The registry container's whole ``env`` block, as name and value.

    The application container's, after the migration init container's, which
    the registry chart's own render test holds equal to it."""
    application = deployment.split("\n      containers:\n", 1)[1]
    block = application.split("          env:\n", 1)[1].split("          volumeMounts:\n", 1)[0]
    pairs = re.findall(r'- name: (\S+)\n\s+value: "?([^"\n]*)"?', block)
    assert len(pairs) == block.count("- name: "), f"an env entry is not a plain value: {block}"
    return dict(pairs)


_REGISTRY_SETTINGS = {
    "REGISTRY_AUTHORITY_ID",
    "REGISTRY_AUTHORITY_SCHEME",
    "REGISTRY_AUTHORITY_IDENTIFIER",
    "REGISTRY_AUTHORITY_CREDENTIAL_FILE",
    "REGISTRY_FILTER_SPEC_PATH",
    "REGISTRY_DESCRIPTOR_BASE_URL",
    "REGISTRY_DESCRIPTOR_DISPLAY_NAME",
    "REGISTRY_DESCRIPTOR_OPERATOR_IDENTITY",
    "DATABASE_URL",
    "PORT",
    "HOST",
    "LOG_LEVEL",
    "ROOT_PATH",
    "REGISTRY_REQUIRE_READ_API_KEY",
    "REGISTRY_REQUIRE_WRITE_API_KEY",
}


def test_each_registry_renders_its_settings_as_a_profile_and_sets_only_the_resolver_variables() -> None:
    """The deployment-state scenario "The registry chart renders a release",
    without a secret profile: each registry, the default and the API-credit
    alias, renders its identity, descriptor, settings, port and filter
    specification into its own `config-production.env`, mounted under the
    configuration directory, and its pod environment holds only the two
    resolver variables. The settings nothing reads are not rendered."""
    manifest = _release_one({"api-credits-registry": {"enabled": True}})
    expected = {
        "registry": {
            "REGISTRY_AUTHORITY_ID": "registry-a",
            "REGISTRY_FILTER_SPEC_PATH": "/app/filter-spec.yaml",
            "REGISTRY_DESCRIPTOR_DISPLAY_NAME": "Local VM Compute Registry",
        },
        "api-credits-registry": {
            "REGISTRY_AUTHORITY_ID": "registry-api-credits",
            "REGISTRY_FILTER_SPEC_PATH": "/app/filter-spec-apicredits.yaml",
            "REGISTRY_DESCRIPTOR_DISPLAY_NAME": "Local API Credits Registry",
        },
    }
    for chart, own in expected.items():
        profile = _registry_profile(manifest, chart)
        deployment = _source(manifest, f"charts/{chart}/templates/deployment.yaml")
        name = f"{RELEASE_ONE}-{chart}"

        # Release 1's registry alone recommends the mediation double.
        recommends = {"REGISTRY_DESCRIPTOR_RECOMMENDED_DISPUTE_AUTHORITIES"} if chart == "registry" else set()
        assert set(profile) == _REGISTRY_SETTINGS | recommends, sorted(profile)
        assert {key: profile[key] for key in own} == own
        assert profile["PORT"] == _service_url(manifest, name).rsplit(":", 1)[1]
        assert profile["REGISTRY_REQUIRE_READ_API_KEY"] == profile["REGISTRY_REQUIRE_WRITE_API_KEY"] == "false"
        assert profile["ROOT_PATH"] == "" and profile["HOST"] == "0.0.0.0" and profile["LOG_LEVEL"] == "info"
        # The credential file the profile names is the Secret key the pod mounts.
        mount = re.search(r'- name: registry-identity\n\s+mountPath: "?([^"\n]+)"?', deployment)
        item = re.search(r"- name: registry-identity\n\s+secret:\n.*?\n\s+path: \"?([^\"\n]+)\"?", deployment, re.DOTALL)
        assert mount and item, f"{chart} mounts no signer credential"
        assert profile["REGISTRY_AUTHORITY_CREDENTIAL_FILE"] == f"{mount.group(1)}/{item.group(1)}"

        assert _resolver_environment(deployment) == {"CONFIG_DIRECTORY": "/app/config", "ACTIVE_PROFILES": "production"}
        lines = {line.strip() for line in deployment.splitlines()}
        assert {"mountPath: /app/config/config-production.env", "subPath: config-production.env"} <= lines
        assert f'name: "{name}-config"' in lines
        assert "secret-profile" not in deployment
        _named(manifest, "ConfigMap", f"{name}-config")


def test_a_values_file_stating_settings_nothing_reads_renders() -> None:
    """A values file stating the settings the registry does not read renders,
    and they reach neither its profile nor its environment; so does one
    stating the key Secrets with no name."""
    stated = {
        "registry": {
            "config": {"enableHealthChecks": True, "healthCheckInterval": 60, "endpointCheckTimeout": 10, "heartbeatTtlSecs": 60},
            "auth": {"bootstrapKeySecret": {"name": "", "key": ""}, "adminKeySecret": {"name": "", "key": ""}},
        }
    }
    manifest = _release_one(stated)
    assert set(_registry_profile(manifest)) == _REGISTRY_SETTINGS | {"REGISTRY_DESCRIPTOR_RECOMMENDED_DISPUTE_AUTHORITIES"}
    assert not re.search(r"ENABLE_HEALTH_CHECKS|HEALTH_CHECK_INTERVAL|ENDPOINT_CHECK_TIMEOUT|HEARTBEAT_TTL_SECS", manifest)


def test_a_registry_secret_profile_is_mounted_beside_the_rendered_one_and_layered_after_it() -> None:
    """The deployment-state scenario "The registry chart renders a release": a
    `secretProfile` mounts the named Secret's `config-<profile>.env` under the
    configuration directory and appends the profile to ACTIVE_PROFILES, and
    the pod environment still holds only the two resolver variables."""
    overlay = {"registry": {"secretProfile": {"secretName": "registry-keys", "profile": "keys"}}}
    deployment = _source(_release_one(overlay), "charts/registry/templates/deployment.yaml")

    assert _resolver_environment(deployment) == {"CONFIG_DIRECTORY": "/app/config", "ACTIVE_PROFILES": "production,keys"}
    assert re.search(
        r'- name: secret-profile\n\s+mountPath: "/app/config/config-keys\.env"\n\s+subPath: "config-keys\.env"\n\s+readOnly: true',
        deployment,
    )
    assert re.search(
        r'- name: secret-profile\n\s+secret:\n\s+secretName: "registry-keys"\n\s+items:\n'
        r'\s+- key: "config-keys\.env"\n\s+path: "config-keys\.env"',
        deployment,
    )
    assert "subPath: config-production.env" in deployment

    for secret_profile, refusal in (
        ({"secretName": "registry-keys", "profile": ""}, "registry secretProfile.profile is required with its secretName"),
        ({"secretName": "registry-keys", "profile": "production"}, "registry secretProfile.profile must not be production"),
        # A comma would split ACTIVE_PROFILES; the values schema refuses it.
        ({"secretName": "registry-keys", "profile": "keys,more"}, "secretProfile"),
        ({"secretName": "registry-keys", "profile": "keys", "key": "x"}, "secretProfile"),
    ):
        refused = _render(RELEASE_ONE, RELEASE_ONE_VALUES, {"registry": {"secretProfile": secret_profile}})
        assert refused.returncode != 0, secret_profile
        assert refusal in refused.stderr, refused.stderr


def test_a_retired_registry_key_secret_is_refused_naming_secret_profile() -> None:
    """The deployment-state scenario "A values file uses a retired key Secret"."""
    for key in ("bootstrapKeySecret", "adminKeySecret"):
        refused = _render(RELEASE_ONE, RELEASE_ONE_VALUES, {"registry": {"auth": {key: {"name": "registry-keys", "key": "api-key"}}}})
        assert refused.returncode != 0, key
        assert f"registry auth.{key} is retired" in refused.stderr and "secretProfile" in refused.stderr, refused.stderr


def test_a_registry_setting_its_profile_cannot_carry_is_refused() -> None:
    """A value ending in a backslash, which the dotenv reader would take as an
    escaped closing quote, and one holding `${`, which it would expand as a
    variable, are refused naming the setting."""
    for descriptor, refusal in (
        ({"displayName": "Local registry \\"}, "registry setting REGISTRY_DESCRIPTOR_DISPLAY_NAME must not end in a backslash"),
        ({"operatorIdentity": "Operator ${HOME}"}, "registry setting REGISTRY_DESCRIPTOR_OPERATOR_IDENTITY must not contain ${"),
    ):
        refused = _render(RELEASE_ONE, RELEASE_ONE_VALUES, {"registry": {"descriptor": descriptor}})
        assert refused.returncode != 0, descriptor
        assert refusal in refused.stderr, refused.stderr


def test_the_registry_posture_checks_refuse_a_mismatched_descriptor() -> None:
    """A key-gated registry needs an access acquisition pointer and a public one
    must not state one."""
    for overlay, refusal in (
        ({"config": {"requireReadApiKey": True}}, "key-gated registry descriptor requires an access acquisition pointer"),
        (
            {"descriptor": {"accessAcquisitionPointer": "https://registry.example/access"}},
            "public registry descriptor must not configure an access acquisition pointer",
        ),
    ):
        refused = _render(RELEASE_ONE, RELEASE_ONE_VALUES, {"registry": overlay})
        assert refused.returncode != 0, overlay
        assert refusal in refused.stderr, refused.stderr
    gated = {
        "registry": {
            "config": {"requireReadApiKey": True},
            "descriptor": {"accessAcquisitionPointer": "https://registry.example/access"},
        }
    }
    profile = _registry_profile(_release_one(gated))
    assert profile["REGISTRY_REQUIRE_READ_API_KEY"] == "true"
    assert profile["REGISTRY_DESCRIPTOR_ACCESS_ACQUISITION_POINTER"] == "https://registry.example/access"


_REGISTRY_PROBE = """
import json, sys
from core_registry.config import load_settings
from core_registry.settings_source import load_database_settings
resolver = {"CONFIG_DIRECTORY": sys.argv[1], "ACTIVE_PROFILES": sys.argv[2]}
settings = load_settings(resolver).model_dump(mode="json")
settings["migration"] = load_database_settings(resolver).model_dump(mode="json")
print(json.dumps(settings))
"""


def test_the_rendered_registry_profile_loads_with_the_registry_loader() -> None:
    """Release 1's rendered profile, and a secret profile after it, read by the
    registry's own loader. Every rendered setting differs from the registry's
    default, so a line it dropped would show; the display name holds a newline
    and the sequences a single-quoted dotenv value decodes, a backslash pair and
    a backslashed quote. Each value arrives as given, the dispute authorities as
    the list, and the secret profile both adds a key and overrides one the
    rendered profile states. The migration's loader reads the same database URL
    and log level from them."""
    python = os.environ.get("REGISTRY_PYTHON")
    if not python:
        print("skip: REGISTRY_PYTHON unset; the registry loader check did not run")
        return
    awkward = "Bob's \\\\ registry\n\\' here"
    overlay = {
        "registry": {
            "descriptor": {"displayName": awkward, "accessAcquisitionPointer": "https://registry.example/access"},
            "service": {"port": 8081},
            "config": {"rootPath": "/registry", "logLevel": "debug", "requireReadApiKey": True, "requireWriteApiKey": True},
        }
    }
    manifest = _release_one(overlay)
    text = _block(_source(manifest, "charts/registry/templates/configmap.yaml"), "config-production.env")
    with tempfile.TemporaryDirectory() as directory:
        Path(directory, "config-production.env").write_text(text + "\n", encoding="utf-8")
        # A placeholder key, never a real one.
        Path(directory, "config-keys.env").write_text(
            "REGISTRY_ADMIN_API_KEY='placeholder-admin-key'\nLOG_LEVEL='warning'\n", encoding="utf-8"
        )
        loaded = subprocess.run(
            [python, "-c", _REGISTRY_PROBE, directory, "production,keys"],
            # An empty working directory and environment, so no default dotenv
            # file or process variable reaches the loader.
            cwd=directory,
            env={"PATH": os.environ.get("PATH", "")},
            check=True,
            capture_output=True,
            text=True,
        )
    settings = json.loads(loaded.stdout.strip().splitlines()[-1])
    profile = _registry_profile(manifest)

    assert settings["registry_descriptor_display_name"] == awkward
    assert settings["registry_descriptor_recommended_dispute_authorities"] == [_recommended_mediation_double()]
    for setting, line in (
        ("registry_authority_id", "REGISTRY_AUTHORITY_ID"),
        ("registry_authority_scheme", "REGISTRY_AUTHORITY_SCHEME"),
        ("registry_authority_identifier", "REGISTRY_AUTHORITY_IDENTIFIER"),
        ("registry_authority_credential_file", "REGISTRY_AUTHORITY_CREDENTIAL_FILE"),
        ("registry_filter_spec_path", "REGISTRY_FILTER_SPEC_PATH"),
        ("registry_descriptor_base_url", "REGISTRY_DESCRIPTOR_BASE_URL"),
        ("registry_descriptor_operator_identity", "REGISTRY_DESCRIPTOR_OPERATOR_IDENTITY"),
        ("database_url", "DATABASE_URL"),
        ("host", "HOST"),
    ):
        assert settings[setting] == profile[line], setting
    assert settings["registry_descriptor_access_acquisition_pointer"] == "https://registry.example/access"
    assert settings["port"] == 8081 and settings["root_path"] == "/registry"
    assert settings["require_read_api_key"] is True and settings["require_write_api_key"] is True
    # The secret profile, layered after the rendered one, adds the key and wins
    # on the setting both state.
    assert profile["LOG_LEVEL"] == "debug" and settings["log_level"] == "warning"
    assert settings["admin_api_key"] == "placeholder-admin-key"
    # The migration init container reads the same profiles through its own
    # loader, and finds the database the application serves.
    assert settings["migration"] == {"database_url": profile["DATABASE_URL"], "log_level": "warning"}


# --- the storefront's own loader -----------------------------------------


_PROBE = """
import json, warnings; warnings.simplefilter('ignore')
from arkhai_bare_metal_storefront.config import load_storefront_settings
from arkhai_bare_metal_storefront.pool_overrides import compile_publication_clauses
from arkhai_bare_metal_storefront.site_clients import parse_site_bindings
from arkhai_bare_metal_storefront.startup_refusal import publication_startup_problems
settings = load_storefront_settings()
problems = publication_startup_problems(settings)
report = {"problems": problems, "registries": sorted(settings.registry_authorities())}
if not problems:
    report["clauses"] = len(compile_publication_clauses(settings.pricing.settlements))
    report["sites"] = [
        [binding.site_id, binding.service_peer]
        for binding in parse_site_bindings(settings.capacity.sites, settings.service_peer_configs())
    ]
print(json.dumps(report))
"""


def test_release_twos_document_loads_with_the_storefront_loader() -> None:
    """Release 2's rendered document is one the storefront could publish under
    (publishable, not startable: composing the runtime also needs the
    credential, the overlay's wallet key, a writable database, and the chain)."""
    python = os.environ.get("BARE_METAL_STOREFRONT_PYTHON")
    if not python:
        print("skip: BARE_METAL_STOREFRONT_PYTHON unset; the storefront loader check did not run")
        return
    config = _storefront_document(_release_two())
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
    report = json.loads(loaded.stdout.strip().splitlines()[-1])

    assert report["problems"] == [], report["problems"]
    assert report["registries"] == config["registry"]["urls"]
    assert report["clauses"] == 1
    assert report["sites"] == [["default", "provisioning_default"]]


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
