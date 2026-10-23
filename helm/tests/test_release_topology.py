"""The local two-release topology renders as one registry serving two storefronts.

Release 1 is the umbrella as ``make -C helm deploy-local`` installs it; release 2
is the same chart under ``bare-metal-release-values.yaml``: the bare-metal
storefront and its own provisioning service, publishing to release 1's registry.
Each test renders both releases with the names ``helm/Makefile``'s topology
targets install them under, and reads the documents the charts render as JSON
back with ``json``. Standard library only.

Set ``BARE_METAL_STOREFRONT_PYTHON`` to the bare-metal storefront environment's
interpreter to also load release 2's rendered document with the storefront's own
configuration loader and publication checks.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import textwrap
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
    registry = _source(release_one, "charts/registry/templates/deployment.yaml")

    registry_url = _service_url(release_one, f"{RELEASE_ONE}-registry")
    assert storefront["registry"]["urls"] == [registry_url]
    assert storefront["registry"]["authorities"] == {
        registry_url: {
            "authority": _env(registry, "REGISTRY_AUTHORITY_ID"),
            "principals": [
                {
                    "scheme": _env(registry, "REGISTRY_AUTHORITY_SCHEME"),
                    "identifier": _env(registry, "REGISTRY_AUTHORITY_IDENTIFIER"),
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
    assert storefront["Chains"]["anvil"]["alkahest_address_config_path"] == path
    assert storefront["Settlement"]["alkahest"]["address_config_path"] == path


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
    registry = _source(manifest, "charts/registry/templates/deployment.yaml")
    bob = json.loads(_block(_source(manifest, "storefront/templates/configmap.yaml"), "storefront.json"))

    assert profile["registry"]["authority_id"] == _env(registry, "REGISTRY_AUTHORITY_ID")
    assert profile["registry"]["identifier"] == _env(registry, "REGISTRY_AUTHORITY_IDENTIFIER")
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
        url = _env(deployment, "DATABASE_URL")
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
    assert components == {*order, "dev-env"}


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


def _selectors_and_test_pods(manifest: str) -> tuple[dict[str, dict[str, str]], dict[str, dict[str, str]]]:
    """Every rendered Deployment's ``spec.selector.matchLabels`` and every Pod
    annotated ``helm.sh/hook: test``'s labels, each by its name."""
    selectors, test_pods = {}, {}
    for document in _documents(manifest):
        lines = document.splitlines()
        deployment = "kind: Deployment" in lines
        test_pod = "kind: Pod" in lines and _TEST_HOOK.search(document) is not None
        if not (deployment or test_pod):
            continue
        name = next(line.split(": ", 1)[1].strip('"') for line in lines if line.startswith("  name: "))
        if deployment:
            selectors[name] = _mapping_under(lines, "    matchLabels:")
        else:
            test_pods[name] = _mapping_under(lines, "  labels:")
    return selectors, test_pods


def _test_templates(manifest: str) -> set[str]:
    """The name of every Pod rendered from a chart's ``templates/tests/``."""
    names = set()
    for document in _documents(manifest):
        lines = document.splitlines()
        if "kind: Pod" in lines and any(
            line.startswith("# Source: ") and "/templates/tests/" in line for line in lines
        ):
            names.add(next(line.split(": ", 1)[1].strip('"') for line in lines if line.startswith("  name: ")))
    return names


def test_no_test_pod_carries_a_workload_selector() -> None:
    """The deployment-state scenario "Both topology releases are rendered", a
    static stand-in for selecting a workload's pods in a cluster: no Helm test
    pod carries all of any Deployment's selector, since every test pod lacks
    ``app.kubernetes.io/name``, which every selector requires, and each carries
    its release's instance label and ``component: test``."""
    for release_name, release in ((RELEASE_ONE, _release_one()), (RELEASE_TWO, _release_two())):
        selectors, test_pods = _selectors_and_test_pods(release)
        # Every test template's Pod is read as a test pod, so none escapes the
        # checks below by a hook annotation spelled some other way.
        assert set(test_pods) == _test_templates(release), (sorted(test_pods), release_name)
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
