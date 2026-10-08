from __future__ import annotations

import subprocess
from pathlib import Path


CHART = Path(__file__).resolve().parents[1]
VALUES = CHART / "examples" / "production-values.yaml"


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


ALKAHEST_GROUP = (
    "--set-string",
    "sellerEvmAddress=0x00000000000000000000000000000000000000aa",
    "--set-json",
    'chains={"anvil":{"rpc_url":"http://anvil:8545",'
    '"alkahest_address_config_path":"/etc/arkhai/alkahest/alkahest_addresses.json"}}',
    "--set-string",
    "walletKeySecret.name=bare-metal-storefront-wallet",
)


def test_a_hosted_only_release_renders_no_alkahest_inputs() -> None:
    rendered = _render()
    assert rendered.returncode == 0, rendered.stderr
    for absent in (
        "BARE_METAL_STOREFRONT_EVM_ADDRESS",
        "BARE_METAL_STOREFRONT_CHAINS",
        "BARE_METAL_STOREFRONT_EVM_PRIVATE_KEY",
        "alkahest-address-book",
    ):
        assert absent not in rendered.stdout


def test_the_alkahest_group_renders_together_with_the_key_by_reference() -> None:
    rendered = _render(
        *ALKAHEST_GROUP,
        "--set-string",
        "alkahestAddressBook.configMapName=alkahest-addresses",
    )
    assert rendered.returncode == 0, rendered.stderr
    manifest = rendered.stdout
    assert "name: BARE_METAL_STOREFRONT_EVM_ADDRESS" in manifest
    assert "name: BARE_METAL_STOREFRONT_CHAINS" in manifest
    assert "name: BARE_METAL_STOREFRONT_EVM_PRIVATE_KEY" in manifest
    assert 'name: "bare-metal-storefront-wallet"' in manifest
    assert "name: alkahest-address-book" in manifest
    assert "readOnly: true" in manifest
    assert "BARE_METAL_STOREFRONT_EVM_PRIVATE_KEY\n              value:" not in manifest


def test_a_partial_alkahest_group_fails_closed() -> None:
    for omitted in range(3):
        partial = [
            item
            for index, pair in enumerate(
                zip(ALKAHEST_GROUP[0::2], ALKAHEST_GROUP[1::2])
            )
            if index != omitted
            for item in pair
        ]
        rendered = _render(*partial)
        assert rendered.returncode != 0, partial


if __name__ == "__main__":
    test_production_values_render_dedicated_secret_bound_role()
    test_missing_site_secret_fails_closed()
    test_a_hosted_only_release_renders_no_alkahest_inputs()
    test_the_alkahest_group_renders_together_with_the_key_by_reference()
    test_a_partial_alkahest_group_fails_closed()
