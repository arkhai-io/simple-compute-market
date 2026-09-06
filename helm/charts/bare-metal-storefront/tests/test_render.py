from __future__ import annotations

import json
import subprocess
from pathlib import Path

import yaml


CHART = Path(__file__).resolve().parents[1]
VALUES = CHART / "examples" / "production-values.yaml"

# Deterministic development-only fixture. `chain:8545` is an in-cluster
# development chain name, not a real endpoint.
#
# Braces and commas are Helm --set list/map syntax; passing the JSON through a
# file-free --set-string still needs them escaped.
_CHAINS_JSON = (
    '{\\"anvil\\": {\\"rpc_url\\": \\"http://chain:8545\\"}}'
    .replace("{", "\\{")
    .replace("}", "\\}")
    .replace(",", "\\,")
)


def _render(*extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "helm",
            "template",
            "bare-metal-test",
            str(CHART),
            "--values",
            str(VALUES),
            *extra,
        ],
        check=False,
        capture_output=True,
        text=True,
    )


def test_production_values_render_dedicated_secret_bound_role() -> None:
    rendered = _render()
    assert rendered.returncode == 0, rendered.stderr
    manifest = rendered.stdout
    assert "kind: Deployment" in manifest
    assert "kind: Service" in manifest
    assert "kind: PersistentVolumeClaim" in manifest
    assert "image: \"registry.example.com/arkhai/arkhai@sha256:" in manifest
    assert "name: ARKHAI_IDENTITY_CREDENTIAL" in manifest
    assert "name: BARE_METAL_STOREFRONT_SITES" in manifest
    assert "name: \"bare-metal-storefront-identity\"" in manifest
    assert "name: \"bare-metal-storefront-sites\"" in manifest
    assert "path: /health" in manifest
    assert "wait-for-" not in manifest
    for forbidden in (
        "authority_url",
        "private_key",
        "provider_metadata",
        "ARKHAI_IDENTITY_CREDENTIAL\n              value:",
    ):
        assert forbidden not in manifest


def test_missing_site_secret_fails_closed() -> None:
    rendered = _render("--set-string", "siteBindingsSecret.name=")
    assert rendered.returncode != 0


def test_hosted_only_role_mounts_no_chain_configuration() -> None:
    """A role with no Alkahest must construct no wallet, RPC, or chain client."""
    rendered = _render()
    assert rendered.returncode == 0, rendered.stderr

    assert "BARE_METAL_STOREFRONT_CHAINS" not in rendered.stdout
    assert "BARE_METAL_STOREFRONT_EVM_PRIVATE_KEY" not in rendered.stdout
    assert "BARE_METAL_STOREFRONT_EVM_ADDRESS" not in rendered.stdout


def test_alkahest_role_receives_its_chain_configuration() -> None:
    """Alkahest needs an RPC endpoint and a signing key to reach a chain.

    Without them the runtime resolves no chain client and reports a missing
    wallet, so a chart that advertises Alkahest while rendering neither
    produces a deployment that cannot settle.
    """
    rendered = _render(
        "--set",
        "alkahestEnabled=true",
        "--set-string",
        "sellerEvmAddress=0x0000000000000000000000000000000000000001",
        "--set-string",
        "chainsJson=" + _CHAINS_JSON,
        "--set-string",
        "walletSecret.name=bare-metal-storefront-wallet",
        "--set-string",
        "walletSecret.key=private-key",
    )
    assert rendered.returncode == 0, rendered.stderr
    manifest = rendered.stdout

    assert "name: BARE_METAL_STOREFRONT_CHAINS" in manifest
    assert "name: BARE_METAL_STOREFRONT_EVM_ADDRESS" in manifest
    assert "name: BARE_METAL_STOREFRONT_EVM_PRIVATE_KEY" in manifest
    # The signing key is a credential: it may only arrive by Secret reference.
    assert 'name: "bare-metal-storefront-wallet"' in manifest
    assert (
        "BARE_METAL_STOREFRONT_EVM_PRIVATE_KEY\n              value:" not in manifest
    )


def test_alkahest_without_chain_configuration_fails_closed() -> None:
    rendered = _render(
        "--set",
        "alkahestEnabled=true",
        "--set-string",
        "sellerEvmAddress=0x0000000000000000000000000000000000000001",
        "--set-string",
        "walletSecret.name=bare-metal-storefront-wallet",
    )
    assert rendered.returncode != 0


def test_alkahest_without_a_wallet_secret_fails_closed() -> None:
    rendered = _render(
        "--set",
        "alkahestEnabled=true",
        "--set-string",
        "sellerEvmAddress=0x0000000000000000000000000000000000000001",
        "--set-string",
        "chainsJson=" + _CHAINS_JSON,
        "--set-string",
        "walletSecret.name=",
    )
    assert rendered.returncode != 0


_ADDRESS_PATH = "/etc/arkhai/chain/alkahest-addresses.json"
_LOCAL_CHAINS_JSON = (
    '{\\"anvil\\": {\\"rpc_url\\": \\"http://chain:8545\\", '
    f'\\"alkahest_address_config_path\\": \\"{_ADDRESS_PATH}\\"}}}}'
).replace("{", "\\{").replace("}", "\\}").replace(",", "\\,")


# Deterministic development-only fixture values. The zero address and the
# example chain endpoint are not real deployment inputs and must never be used
# on a public network.
def _alkahest_render(*extra: str) -> subprocess.CompletedProcess[str]:
    return _render(
        "--set",
        "alkahestEnabled=true",
        "--set-string",
        "sellerEvmAddress=0x0000000000000000000000000000000000000001",
        "--set-string",
        "walletSecret.name=bare-metal-storefront-wallet",
        "--set-string",
        "walletSecret.key=private-key",
        *extra,
    )


def test_local_chain_addresses_are_mountable() -> None:
    """A chain with no published address set needs its addresses on disk.

    The runtime refuses to resolve address configuration for such a chain
    without a file, and the client factory then builds no settlement client, so
    rendering the chain JSON alone does not make the role able to settle.
    """
    rendered = _alkahest_render(
        "--set-string",
        "chainsJson=" + _LOCAL_CHAINS_JSON,
        "--set",
        "chainAddressConfig.enabled=true",
        "--set-string",
        "chainAddressConfig.secretName=bare-metal-storefront-chain-addresses",
    )
    assert rendered.returncode == 0, rendered.stderr

    deployment = _deployment(rendered.stdout)
    spec = deployment["spec"]["template"]["spec"]
    volume = next(v for v in spec["volumes"] if v["name"] == "chain-address-config")
    mount = next(
        m
        for m in spec["containers"][0]["volumeMounts"]
        if m["name"] == "chain-address-config"
    )

    assert volume["secret"]["secretName"] == "bare-metal-storefront-chain-addresses"
    assert mount["mountPath"] == "/etc/arkhai/chain"
    assert mount["readOnly"] is True
    # The mounted file and the path the runtime is told to read must agree.
    assert f"{mount['mountPath']}/{volume['secret']['items'][0]['path']}" == _ADDRESS_PATH


def test_enabled_address_mount_without_a_secret_fails_closed() -> None:
    rendered = _alkahest_render(
        "--set-string",
        "chainsJson=" + _LOCAL_CHAINS_JSON,
        "--set",
        "chainAddressConfig.enabled=true",
        "--set-string",
        "chainAddressConfig.secretName=",
    )
    assert rendered.returncode != 0


def test_rendered_chain_json_is_what_the_runtime_parses() -> None:
    """Render strings are not runtime validation; parse them as the runtime does.

    The runtime requires each chain to carry `rpc_url` and treats
    `alkahest_address_config_path` as the location it will read. Asserting the
    environment variable exists would not catch a value the runtime rejects.
    """
    rendered = _alkahest_render(
        "--set-string", "chainsJson=" + _LOCAL_CHAINS_JSON
    )
    assert rendered.returncode == 0, rendered.stderr

    value = _env_value(rendered.stdout, "BARE_METAL_STOREFRONT_CHAINS")
    chains = json.loads(value)

    assert isinstance(chains, dict) and chains
    for name, chain in chains.items():
        assert isinstance(chain, dict), name
        assert chain["rpc_url"]
        # Mounted path and declared path must agree, or the runtime reads a
        # file the chart never placed.
        assert chain["alkahest_address_config_path"] == _ADDRESS_PATH


def test_empty_chain_object_is_not_usable_configuration() -> None:
    """An empty JSON object renders, so the schema alone does not protect this."""
    rendered = _alkahest_render("--set-string", "chainsJson=\\{\\}")
    assert rendered.returncode == 0, rendered.stderr

    chains = json.loads(
        _env_value(rendered.stdout, "BARE_METAL_STOREFRONT_CHAINS")
    )

    assert chains == {}, (
        "documented as a render-level limitation: the chart cannot tell an "
        "operator's real chain map from an empty one, so deployment "
        "verification has to check the running role"
    )


def _deployment(manifest: str) -> dict:
    return next(
        document
        for document in yaml.safe_load_all(manifest)
        if document and document.get("kind") == "Deployment"
    )


def _env_value(manifest: str, name: str) -> str:
    """Read one env value from the rendered Deployment.

    `helm template` emits a multi-document stream, so the Deployment has to be
    selected rather than assumed to be the only document.
    """
    container = _deployment(manifest)["spec"]["template"]["spec"]["containers"][0]
    for entry in container["env"]:
        if entry["name"] == name:
            return entry["value"]
    raise AssertionError(f"{name} was not rendered")
