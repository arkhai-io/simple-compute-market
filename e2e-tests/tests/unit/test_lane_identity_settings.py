"""Profiles keep marketplace principals separate from selected EVM effects."""
from __future__ import annotations

import base64
import importlib
import shutil
from contextlib import ExitStack, contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from eth_account import Account
from market_identity import IdentityScheme, create_signer

from e2e_harness import settings as settings_module

vm = importlib.import_module("tests.e2e.roles.scenarios.vms.conftest")
bm = importlib.import_module("tests.e2e.roles.scenarios.bare_metal.conftest")
real_bm = importlib.import_module("tests.e2e.roles.scenarios.bare_metal.test_real_provisioning_deal")
multi = importlib.import_module("tests.e2e.roles.scenarios.vms.test_multi_registry")
CONFIG = Path(__file__).resolve().parents[2] / "config"
# Deterministic offline fixture seeds only; never use on a public network.
BUYER_SEED, SELLER_SEED, AUTHORITY_SEED = (
    base64.urlsafe_b64encode(bytes([value]) * 32).decode().rstrip("=")
    for value in (17, 34, 51)
)


def _settings(directory, profiles):
    for filename in ("config.yml", "config-local.yml", "config-docker.yml"):
        shutil.copy(CONFIG / filename, directory / filename)
    return settings_module._load_bootstrap({
        "CONFIG_DIRECTORY": str(directory), "ACTIVE_PROFILES": profiles,
    }).settings


@pytest.fixture
def configured(tmp_path, monkeypatch):
    local = _settings(tmp_path, "local")
    authority = create_signer("ed25519", AUTHORITY_SEED).identity
    profile = {
        "buyer": {"marketplace_scheme": "ed25519", "marketplace_credential": BUYER_SEED},
        "seller": {"marketplace_scheme": "ed25519", "marketplace_credential": SELLER_SEED,
                   "admin_scheme": "eip191", "admin_credential": local.SELLER.PRIVATE_KEY},
        "registry": {"authority_scheme": "ed25519", "identifier": authority.identifier},
        "provisioning": {"api_url": "http://provisioning.example.invalid",
                         "authority_scheme": "ed25519", "authority_identifier": authority.identifier,
                         "service_scheme": "eip191", "service_credential": local.BUYER.PRIVATE_KEY},
        "bare_metal_lane": {
            "buyer_scheme": "ed25519", "buyer_credential": BUYER_SEED,
            "buyer_wallet_private_key": local.BUYER.PRIVATE_KEY,
            "buyer_wallet_address": local.BUYER.WALLET_ADDRESS, "buyer_rpc_url": local.BUYER.CHAIN_RPC_URL,
            "storefront_url": "http://storefront.example.invalid", "storefront_scheme": "ed25519",
            "storefront_identifier": create_signer("ed25519", SELLER_SEED).identity.identifier,
            "registry_url": "http://registry.example.invalid", "registry_scheme": "ed25519",
            "registry_identifier": authority.identifier, "registry_authority_id": "offline-registry",
        },
    }
    (tmp_path / "config-offline-identities.yml").write_text(
        "# Deterministic offline fixtures; never use on a public network.\n" + yaml.safe_dump(profile)
    )
    selected = _settings(tmp_path, "local,offline-identities")
    for module in (vm, bm, multi):
        monkeypatch.setattr(module, "settings", selected)
    return selected


@contextmanager
def _client(fixture):
    generator = fixture.__wrapped__()
    try:
        yield next(generator)
    finally:
        generator.close()


def test_vm_typed_clients_share_profile_signers_and_exact_publisher_pins(configured):
    buyer = create_signer("ed25519", BUYER_SEED).identity
    seller = create_signer("ed25519", SELLER_SEED).identity
    assert vm.buyer_principal.__wrapped__() == buyer
    with ExitStack() as stack:
        for fixture, principal in (
            (vm.storefront_client, buyer), (vm.storefront_seller_client, seller),
            (vm.storefront_admin_client, create_signer("eip191", configured.SELLER.ADMIN_CREDENTIAL).identity),
            (vm.storefront_service_client, create_signer("eip191", configured.PROVISIONING.SERVICE_CREDENTIAL).identity),
        ):
            client = stack.enter_context(_client(fixture))
            assert client._signer.identity == principal
            assert client._expected_publishers.identities == (seller,)
        for fixture, principal in ((vm.registry_client, buyer), (vm.registry_seller_client, seller)):
            client = stack.enter_context(_client(fixture))
            assert client._signer.identity == principal
            assert client._expected_registries.identities == (create_signer("ed25519", AUTHORITY_SEED).identity,)
    assert vm.site_capacity_admin_client.__wrapped__()._signer.identity == seller
    assert vm.signed_listing_read_headers("offline-listing")


def test_vm_wallet_stays_evm_while_marketplace_identity_is_ed25519(configured):
    wallet = vm.buyer_config.__wrapped__()
    assert wallet["private_key"] == configured.BUYER.PRIVATE_KEY != BUYER_SEED
    assert Account.from_key(wallet["private_key"]).address.lower() == wallet["wallet_address"].lower()
    assert wallet["rpc_url"] == configured.BUYER.CHAIN_RPC_URL
    assert vm._buyer_signer().identity.scheme is IdentityScheme.ED25519


def test_multi_registry_typed_client_and_authority_preserve_scheme(configured):
    url = configured.REGISTRY.API_URL
    client = multi._registry_client(url)
    try:
        assert client._signer.identity == vm._buyer_signer().identity
        assert client._expected_registries.identities == vm._registry_trust().identities
        assert multi._registry_authority(url).principals == vm._registry_trust()
    finally:
        client.close()


def test_bare_metal_mock_and_real_wallets_do_not_reuse_ed25519_seed(configured):
    buyer = bm._signer("buyer").identity
    assert buyer == create_signer("ed25519", BUYER_SEED).identity
    shared = bm.buyer_config.__wrapped__()
    actual = real_bm.buyer_config.__wrapped__(SimpleNamespace(public_line="offline-public-key"))
    assert actual == {**shared, "ssh_public_key": "offline-public-key"}
    assert actual["private_key"] == configured.BUYER.PRIVATE_KEY != BUYER_SEED
    assert Account.from_key(actual["private_key"]).address.lower() == actual["wallet_address"].lower()
    assert actual["rpc_url"] == configured.BUYER.CHAIN_RPC_URL
    with _client(bm.storefront_client) as client:
        assert client._signer.identity == buyer
        assert client._expected_publishers.identities == (create_signer("ed25519", SELLER_SEED).identity,)
    with _client(bm.bare_metal_registry) as client:
        assert client._signer.identity == buyer
        assert client._expected_registries.identities == (create_signer("ed25519", AUTHORITY_SEED).identity,)


@pytest.mark.parametrize("profile", ["local", "docker"])
def test_existing_profiles_keep_eip191_and_existing_wallet_defaults(tmp_path, monkeypatch, profile):
    settings = _settings(tmp_path, profile)
    monkeypatch.setattr(vm, "settings", settings)
    assert vm._buyer_signer().identity == create_signer("eip191", settings.BUYER.MARKETPLACE_CREDENTIAL).identity
    assert vm._seller_signer().identity == create_signer("eip191", settings.SELLER.PRIVATE_KEY).identity
    assert vm._registry_trust().identities[0].scheme is IdentityScheme.EIP191
    assert vm.buyer_config.__wrapped__()["private_key"] == settings.BUYER.PRIVATE_KEY
    if profile == "docker":
        monkeypatch.setattr(bm, "settings", settings)
        wallet = bm.buyer_config.__wrapped__()
        assert wallet["private_key"] == settings.BARE_METAL_LANE.BUYER_CREDENTIAL
        assert bm._signer("buyer").identity == create_signer("eip191", wallet["private_key"]).identity
