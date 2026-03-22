from __future__ import annotations

import base64
import importlib.util
import stat
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = ROOT / "scripts/materialize_host_envs.py"


def _load_script_module():
    spec = importlib.util.spec_from_file_location("materialize_host_envs", SCRIPT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_env(path: Path, values: dict[str, str]) -> None:
    path.write_text(
        "".join(f"{key}={value}\n" for key, value in values.items()),
        encoding="utf-8",
    )


def test_materialize_host_envs_renders_consistent_host_local_bundle(
    tmp_path: Path,
) -> None:
    module = _load_script_module()
    shared_secrets_dir = tmp_path / "shared-secrets"
    local_secrets_dir = tmp_path / "local-secrets"
    output_dir = tmp_path / "rendered"
    shared_secrets_dir.mkdir()
    local_secrets_dir.mkdir()

    _write_env(
        local_secrets_dir / "shared.env",
        {
            "CHAIN_NAME": "base_sepolia",
            "CHAIN_ID": "84532",
            "ZEROTIER_NETWORK": "zt-network",
            "FRP_SERVER_ADDR": "frp.example.internal",
            "FRP_DOMAIN": "example.internal",
            "FRP_DASHBOARD_PASSWORD": "frp-password",
            "DEFAULT_VM_HOST": "btc1",
            "REGISTRY_URL": "http://10.0.0.11:8080",
            "PROVISIONING_SERVICE_URL": "http://10.0.0.12:8081",
        },
    )
    _write_env(
        local_secrets_dir / "alchemy.env",
        {
            "ALCHEMY_BASE_SEPOLIA_HTTP_URL": "https://alchemy.example/base-sepolia-http",
            "ALCHEMY_BASE_SEPOLIA_WSS_URL": "wss://alchemy.example/base-sepolia-wss",
            "ALCHEMY_BASE_MAINNET_HTTP_URL": "https://alchemy.example/base-mainnet-http",
            "ALCHEMY_BASE_MAINNET_WSS_URL": "wss://alchemy.example/base-mainnet-wss",
        },
    )
    _write_env(
        local_secrets_dir / "contracts.env",
        {
            "IDENTITY_REGISTRY_ADDRESS": "0x1111111111111111111111111111111111111111",
            "REPUTATION_REGISTRY_ADDRESS": "0x2222222222222222222222222222222222222222",
            "VALIDATION_REGISTRY_ADDRESS": "0x3333333333333333333333333333333333333333",
        },
    )
    _write_env(
        local_secrets_dir / "wallets.env",
        {
            "SELLER_PRIVATE_KEY": "0xseller-private-key",
            "SELLER_WALLET_ADDRESS": "0x4444444444444444444444444444444444444444",
            "BUYER_PRIVATE_KEY": "0xbuyer-private-key",
            "BUYER_WALLET_ADDRESS": "0x5555555555555555555555555555555555555555",
            "SSH_PUBLIC_KEY": "ssh-ed25519 AAAAB3NzaC1yc2EAAAADAQABAAABAQCbuyer canary@example",
            "PROVISIONER_SSH_PRIVATE_KEY_PATH": str(local_secrets_dir / "provisioner_ed25519"),
            "CANARY_TENANT_SSH_PRIVATE_KEY_PATH": str(local_secrets_dir / "tenant_ed25519"),
        },
    )
    _write_env(
        local_secrets_dir / "registry.env",
        {
            "DATABASE_URL": "postgresql://registry:registry@db.internal:5432/registry",
            "HOST": "0.0.0.0",
            "PORT": "8080",
            "LOG_LEVEL": "info",
        },
    )
    _write_env(
        local_secrets_dir / "provisioning.env",
        {
            "DATABASE_URL": "postgresql+psycopg2://prov:prov@db.internal:5432/provisioning",
            "REDIS_URL": "redis://redis.internal:6379/0",
            "REDIS_QUEUE_NAME": "provisioning_jobs",
            "ANSIBLE_BECOME_PASS": "sudo-password",
            "MANAGEMENT_VARS_PATH": str(local_secrets_dir / "management-vars.yaml"),
        },
    )
    _write_env(
        local_secrets_dir / "seller-agent.env",
        {
            "AGENT_ID": "seller-prod",
            "GEMINI_API_KEY": "seller-gemini-key",
            "LOG_FILE_PATH": "/var/log/market/seller.log",
        },
    )
    _write_env(
        local_secrets_dir / "buyer-agent.env",
        {
            "AGENT_ID": "buyer-prod",
            "GEMINI_API_KEY": "buyer-gemini-key",
            "LOG_FILE_PATH": "/var/log/market/buyer.log",
        },
    )
    _write_env(
        local_secrets_dir / "prod-canary.env",
        {
            "SELLER_AGENT_URL": "http://10.0.0.21:8000",
            "BUYER_AGENT_URL": "http://10.0.0.22:8000",
            "SELLER_AGENT_ID": "eip155:84532:0x1111111111111111111111111111111111111111:101",
            "BUYER_AGENT_ID": "eip155:84532:0x1111111111111111111111111111111111111111:202",
            "CANARY_VM_HOSTS": "btc1,btc2",
            "CANARY_GPU_MODEL": "H200",
            "CANARY_REGION": "us-west4",
            "CANARY_TOKEN_SYMBOL": "WETH",
            "CANARY_TOKEN_AMOUNT": "0.0",
            "CANARY_GPU_QUANTITY": "1",
            "CANARY_DURATION_HOURS": "1",
            "CANARY_MATCH_SALT": "12345",
        },
    )

    (local_secrets_dir / "management-vars.yaml").write_text(
        "root_ssh_filename: canary-root\n"
        "golden_image_name: sms-golden-image\n"
        "gcs_bucket_url: gs://sms-bucket\n"
        "gcs_image_path: golden/base-sepolia\n",
        encoding="utf-8",
    )
    (local_secrets_dir / "provisioner_ed25519").write_text(
        "-----BEGIN OPENSSH PRIVATE KEY-----\nprovisioner\n-----END OPENSSH PRIVATE KEY-----\n",
        encoding="utf-8",
    )
    (local_secrets_dir / "tenant_ed25519").write_text(
        "-----BEGIN OPENSSH PRIVATE KEY-----\ntenant\n-----END OPENSSH PRIVATE KEY-----\n",
        encoding="utf-8",
    )

    written = module.materialize_host_envs(
        shared_secrets_dir=shared_secrets_dir,
        local_secrets_dir=local_secrets_dir,
        output_dir=output_dir,
    )

    assert set(written) == {
        output_dir / "contracts.env",
        output_dir / "registry.env",
        output_dir / "provisioning.env",
        output_dir / "seller-agent.env",
        output_dir / "buyer-agent.env",
        output_dir / "prod-canary.env",
        output_dir / "management-vars.yaml",
    }

    contracts_text = (output_dir / "contracts.env").read_text(encoding="utf-8")
    assert "CHAIN_ID=84532" in contracts_text
    assert "CHAIN_NAME=base_sepolia" in contracts_text
    assert "RPC_URL=https://alchemy.example/base-sepolia-http" in contracts_text

    registry_text = (output_dir / "registry.env").read_text(encoding="utf-8")
    assert "RPC_URL=https://alchemy.example/base-sepolia-http" in registry_text
    assert "CHAIN_ID=84532" in registry_text
    assert "IDENTITY_REGISTRY_ADDRESS=0x1111111111111111111111111111111111111111" in registry_text

    seller_text = (output_dir / "seller-agent.env").read_text(encoding="utf-8")
    assert "CHAIN_RPC_URL=wss://alchemy.example/base-sepolia-wss" in seller_text
    assert "AGENT_PRIV_KEY=0xseller-private-key" in seller_text
    assert "AGENT_WALLET_ADDRESS=0x4444444444444444444444444444444444444444" in seller_text
    assert "PROVISIONING_SERVICE_URL=http://10.0.0.12:8081" in seller_text
    assert "DEFAULT_VM_HOST=btc1" in seller_text

    buyer_text = (output_dir / "buyer-agent.env").read_text(encoding="utf-8")
    assert "CHAIN_RPC_URL=wss://alchemy.example/base-sepolia-wss" in buyer_text
    assert "AGENT_PRIV_KEY=0xbuyer-private-key" in buyer_text
    assert "AGENT_WALLET_ADDRESS=0x5555555555555555555555555555555555555555" in buyer_text

    provisioning_text = (output_dir / "provisioning.env").read_text(encoding="utf-8")
    assert "REGISTRY_URL=http://10.0.0.11:8080" in provisioning_text
    assert "DEFAULT_VM_HOST=btc1" in provisioning_text
    assert "FRP_SERVER_ADDR=frp.example.internal" in provisioning_text
    assert "FRP_DOMAIN=example.internal" in provisioning_text
    assert "FRP_DASHBOARD_PASSWORD=frp-password" in provisioning_text
    assert (
        "SSH_PRIVATE_KEY="
        + base64.b64encode((local_secrets_dir / "provisioner_ed25519").read_bytes()).decode("ascii")
    ) in provisioning_text
    assert (
        "MANAGEMENT_VARS_YAML="
        + base64.b64encode((local_secrets_dir / "management-vars.yaml").read_bytes()).decode("ascii")
    ) in provisioning_text

    canary_text = (output_dir / "prod-canary.env").read_text(encoding="utf-8")
    assert "CHAIN_RPC_URL=https://alchemy.example/base-sepolia-http" in canary_text
    assert "SSH_PRIVATE_KEY_PATH=" + str(local_secrets_dir / "tenant_ed25519") in canary_text
    assert "SELLER_PRIVATE_KEY=0xseller-private-key" in canary_text
    assert "BUYER_PRIVATE_KEY=0xbuyer-private-key" in canary_text
    assert "FRP_DASHBOARD_URL=http://frp.example.internal:7500" in canary_text

    for path in written:
        mode = stat.S_IMODE(path.stat().st_mode)
        assert mode == 0o600, f"{path.name} must be written with 0600 permissions"


def test_materialize_host_envs_requires_expected_local_secret_bundle(tmp_path: Path) -> None:
    module = _load_script_module()
    shared_secrets_dir = tmp_path / "shared-secrets"
    local_secrets_dir = tmp_path / "local-secrets"
    output_dir = tmp_path / "rendered"
    shared_secrets_dir.mkdir()
    local_secrets_dir.mkdir()

    _write_env(local_secrets_dir / "shared.env", {"CHAIN_NAME": "base_sepolia"})

    with pytest.raises(
        SystemExit,
        match=(
            "Missing required local secret files: buyer-agent.env, "
            "prod-canary.env, provisioning.env, registry.env, seller-agent.env; "
            "Missing required shared or local secret files: alchemy.env, wallets.env"
        ),
    ):
        module.materialize_host_envs(
            shared_secrets_dir=shared_secrets_dir,
            local_secrets_dir=local_secrets_dir,
            output_dir=output_dir,
        )


def test_materialize_host_envs_merges_shared_credentials_with_local_overrides(
    tmp_path: Path,
) -> None:
    module = _load_script_module()
    shared_secrets_dir = tmp_path / "shared-secrets"
    local_secrets_dir = tmp_path / "local-secrets"
    output_dir = tmp_path / "rendered"
    shared_secrets_dir.mkdir()
    local_secrets_dir.mkdir()

    _write_env(
        shared_secrets_dir / "alchemy.env",
        {
            "ALCHEMY_BASE_SEPOLIA_HTTP_URL": "https://alchemy.example/shared-http",
            "ALCHEMY_BASE_SEPOLIA_WSS_URL": "wss://alchemy.example/shared-wss",
        },
    )
    _write_env(
        shared_secrets_dir / "wallets.env",
        {
            "SELLER_PRIVATE_KEY": "0xshared-seller-private-key",
            "SELLER_WALLET_ADDRESS": "0x1111111111111111111111111111111111111111",
            "BUYER_PRIVATE_KEY": "0xshared-buyer-private-key",
            "BUYER_WALLET_ADDRESS": "0x2222222222222222222222222222222222222222",
            "SSH_PUBLIC_KEY": "ssh-ed25519 AAAAB3NzaC1yc2EAAAADAQABAAABAQDshared shared@example",
            "PROVISIONER_SSH_PRIVATE_KEY_PATH": str(local_secrets_dir / "provisioner_ed25519"),
            "CANARY_TENANT_SSH_PRIVATE_KEY_PATH": str(local_secrets_dir / "tenant_ed25519"),
        },
    )
    _write_env(
        local_secrets_dir / "wallets.env",
        {
            "BUYER_PRIVATE_KEY": "0xlocal-buyer-private-key",
        },
    )
    _write_env(
        local_secrets_dir / "shared.env",
        {
            "CHAIN_NAME": "base_sepolia",
            "ZEROTIER_NETWORK": "zt-network",
            "FRP_SERVER_ADDR": "frp.example.internal",
            "FRP_DOMAIN": "example.internal",
            "FRP_DASHBOARD_PASSWORD": "frp-password",
            "DEFAULT_VM_HOST": "btc1",
            "REGISTRY_URL": "http://10.0.0.11:8080",
            "PROVISIONING_SERVICE_URL": "http://10.0.0.12:8081",
        },
    )
    _write_env(
        local_secrets_dir / "contracts.env",
        {
            "IDENTITY_REGISTRY_ADDRESS": "0x3333333333333333333333333333333333333333",
            "REPUTATION_REGISTRY_ADDRESS": "0x4444444444444444444444444444444444444444",
            "VALIDATION_REGISTRY_ADDRESS": "0x5555555555555555555555555555555555555555",
        },
    )
    _write_env(local_secrets_dir / "registry.env", {"DATABASE_URL": "postgresql://registry"})
    _write_env(
        local_secrets_dir / "provisioning.env",
        {
            "DATABASE_URL": "postgresql+psycopg2://prov",
            "REDIS_URL": "redis://redis.internal:6379/0",
            "REDIS_QUEUE_NAME": "provisioning_jobs",
            "ANSIBLE_BECOME_PASS": "sudo-password",
            "MANAGEMENT_VARS_PATH": str(local_secrets_dir / "management-vars.yaml"),
        },
    )
    _write_env(
        local_secrets_dir / "seller-agent.env",
        {"AGENT_ID": "seller-prod", "GEMINI_API_KEY": "seller-gemini-key"},
    )
    _write_env(
        local_secrets_dir / "buyer-agent.env",
        {"AGENT_ID": "buyer-prod", "GEMINI_API_KEY": "buyer-gemini-key"},
    )
    _write_env(
        local_secrets_dir / "prod-canary.env",
        {
            "SELLER_AGENT_URL": "http://10.0.0.21:8000",
            "BUYER_AGENT_URL": "http://10.0.0.22:8000",
            "SELLER_AGENT_ID": "seller-agent-id",
            "BUYER_AGENT_ID": "buyer-agent-id",
        },
    )
    (local_secrets_dir / "management-vars.yaml").write_text("ansible_user: ubuntu\n", encoding="utf-8")
    (local_secrets_dir / "provisioner_ed25519").write_text("provisioner\n", encoding="utf-8")
    (local_secrets_dir / "tenant_ed25519").write_text("tenant\n", encoding="utf-8")

    module.materialize_host_envs(
        local_secrets_dir=local_secrets_dir,
        output_dir=output_dir,
        shared_secrets_dir=shared_secrets_dir,
    )

    seller_text = (output_dir / "seller-agent.env").read_text(encoding="utf-8")
    buyer_text = (output_dir / "buyer-agent.env").read_text(encoding="utf-8")
    assert "CHAIN_RPC_URL=wss://alchemy.example/shared-wss" in seller_text
    assert "AGENT_PRIV_KEY=0xshared-seller-private-key" in seller_text
    assert "AGENT_PRIV_KEY=0xlocal-buyer-private-key" in buyer_text


def test_materialize_host_envs_renders_ethereum_sepolia_bundle(
    tmp_path: Path,
) -> None:
    module = _load_script_module()
    shared_secrets_dir = tmp_path / "shared-secrets"
    local_secrets_dir = tmp_path / "local-secrets"
    output_dir = tmp_path / "rendered"
    shared_secrets_dir.mkdir()
    local_secrets_dir.mkdir()

    _write_env(
        local_secrets_dir / "shared.env",
        {
            "CHAIN_NAME": "ethereum_sepolia",
            "CHAIN_ID": "11155111",
            "ZEROTIER_NETWORK": "zt-network",
            "FRP_SERVER_ADDR": "frp.example.internal",
            "FRP_DOMAIN": "example.internal",
            "FRP_DASHBOARD_PASSWORD": "frp-password",
            "DEFAULT_VM_HOST": "btc1",
            "REGISTRY_URL": "http://10.0.0.11:8080",
            "PROVISIONING_SERVICE_URL": "http://10.0.0.12:8081",
        },
    )
    _write_env(
        shared_secrets_dir / "alchemy.env",
        {
            "ETH_SEPOLIA_HTTP_RPC_URL": "https://alchemy.example/eth-sepolia-http",
            "ETH_SEPOLIA_WSS_RPC_URL": "wss://alchemy.example/eth-sepolia-wss",
        },
    )
    _write_env(
        shared_secrets_dir / "wallets.env",
        {
            "SELLER_PRIVATE_KEY": "0xseller-private-key",
            "SELLER_WALLET_ADDRESS": "0x4444444444444444444444444444444444444444",
            "BUYER_PRIVATE_KEY": "0xbuyer-private-key",
            "BUYER_WALLET_ADDRESS": "0x5555555555555555555555555555555555555555",
            "SSH_PUBLIC_KEY": "ssh-ed25519 AAAAB3NzaC1yc2EAAAADAQABAAABAQCbuyer canary@example",
            "PROVISIONER_SSH_PRIVATE_KEY_PATH": str(local_secrets_dir / "provisioner_ed25519"),
            "CANARY_TENANT_SSH_PRIVATE_KEY_PATH": str(local_secrets_dir / "tenant_ed25519"),
        },
    )
    _write_env(
        local_secrets_dir / "contracts.env",
        {
            "IDENTITY_REGISTRY_ADDRESS": "0x8004A818BFB912233c491871b3d84c89A494BD9e",
            "REPUTATION_REGISTRY_ADDRESS": "0x8004B663056A597Dffe9eCcC1965A193B7388713",
            "VALIDATION_REGISTRY_ADDRESS": "0x8004Cb1BF31DAf7788923b405b754f57acEB4272",
        },
    )
    _write_env(local_secrets_dir / "registry.env", {"DATABASE_URL": "postgresql://registry"})
    _write_env(
        local_secrets_dir / "provisioning.env",
        {
            "DATABASE_URL": "postgresql+psycopg2://prov",
            "REDIS_URL": "redis://redis.internal:6379/0",
            "REDIS_QUEUE_NAME": "provisioning_jobs",
            "ANSIBLE_BECOME_PASS": "sudo-password",
            "MANAGEMENT_VARS_PATH": str(local_secrets_dir / "management-vars.yaml"),
        },
    )
    _write_env(
        local_secrets_dir / "seller-agent.env",
        {"AGENT_ID": "seller-prod", "GEMINI_API_KEY": "seller-gemini-key"},
    )
    _write_env(
        local_secrets_dir / "buyer-agent.env",
        {"AGENT_ID": "buyer-prod", "GEMINI_API_KEY": "buyer-gemini-key"},
    )
    _write_env(
        local_secrets_dir / "prod-canary.env",
        {
            "SELLER_AGENT_URL": "http://10.0.0.21:8000",
            "BUYER_AGENT_URL": "http://10.0.0.22:8000",
            "SELLER_AGENT_ID": "eip155:11155111:0x8004A818BFB912233c491871b3d84c89A494BD9e:101",
            "BUYER_AGENT_ID": "eip155:11155111:0x8004A818BFB912233c491871b3d84c89A494BD9e:202",
        },
    )
    (local_secrets_dir / "management-vars.yaml").write_text("ansible_user: ubuntu\n", encoding="utf-8")
    (local_secrets_dir / "provisioner_ed25519").write_text("provisioner\n", encoding="utf-8")
    (local_secrets_dir / "tenant_ed25519").write_text("tenant\n", encoding="utf-8")

    module.materialize_host_envs(
        local_secrets_dir=local_secrets_dir,
        output_dir=output_dir,
        shared_secrets_dir=shared_secrets_dir,
    )

    seller_text = (output_dir / "seller-agent.env").read_text(encoding="utf-8")
    registry_text = (output_dir / "registry.env").read_text(encoding="utf-8")
    canary_text = (output_dir / "prod-canary.env").read_text(encoding="utf-8")

    assert "CHAIN_NAME=ethereum_sepolia" in seller_text
    assert "CHAIN_ID=11155111" in seller_text
    assert "CHAIN_RPC_URL=wss://alchemy.example/eth-sepolia-wss" in seller_text
    assert "TOKEN_REGISTRY_PATH=/app/core/agent/app/data/token_registry_eth_sepolia.json" in seller_text
    assert "RPC_URL=https://alchemy.example/eth-sepolia-http" in registry_text
    assert "CHAIN_ID=11155111" in registry_text
    assert "CHAIN_NAME=ethereum_sepolia" in canary_text
    assert "CHAIN_RPC_URL=https://alchemy.example/eth-sepolia-http" in canary_text


def test_materialize_host_envs_uses_chain_profile_contract_defaults_when_contracts_env_is_missing(
    tmp_path: Path,
) -> None:
    module = _load_script_module()
    shared_secrets_dir = tmp_path / "shared-secrets"
    local_secrets_dir = tmp_path / "local-secrets"
    output_dir = tmp_path / "rendered"
    shared_secrets_dir.mkdir()
    local_secrets_dir.mkdir()

    _write_env(
        local_secrets_dir / "shared.env",
        {
            "CHAIN_NAME": "ethereum_sepolia",
            "CHAIN_ID": "11155111",
            "ZEROTIER_NETWORK": "zt-network",
            "FRP_SERVER_ADDR": "frp.example.internal",
            "FRP_DOMAIN": "example.internal",
            "FRP_DASHBOARD_PASSWORD": "frp-password",
            "DEFAULT_VM_HOST": "btc1",
            "REGISTRY_URL": "http://10.0.0.11:8080",
            "PROVISIONING_SERVICE_URL": "http://10.0.0.12:8081",
        },
    )
    _write_env(
        shared_secrets_dir / "alchemy.env",
        {
            "ETH_SEPOLIA_HTTP_RPC_URL": "https://alchemy.example/eth-sepolia-http",
            "ETH_SEPOLIA_WSS_RPC_URL": "wss://alchemy.example/eth-sepolia-wss",
        },
    )
    _write_env(
        shared_secrets_dir / "wallets.env",
        {
            "SELLER_PRIVATE_KEY": "0xseller-private-key",
            "SELLER_WALLET_ADDRESS": "0x4444444444444444444444444444444444444444",
            "BUYER_PRIVATE_KEY": "0xbuyer-private-key",
            "BUYER_WALLET_ADDRESS": "0x5555555555555555555555555555555555555555",
            "SSH_PUBLIC_KEY": "ssh-ed25519 AAAAB3NzaC1yc2EAAAADAQABAAABAQCbuyer canary@example",
            "PROVISIONER_SSH_PRIVATE_KEY_PATH": str(local_secrets_dir / "provisioner_ed25519"),
            "CANARY_TENANT_SSH_PRIVATE_KEY_PATH": str(local_secrets_dir / "tenant_ed25519"),
        },
    )
    _write_env(local_secrets_dir / "registry.env", {"DATABASE_URL": "postgresql://registry"})
    _write_env(
        local_secrets_dir / "provisioning.env",
        {
            "DATABASE_URL": "postgresql+psycopg2://prov",
            "REDIS_URL": "redis://redis.internal:6379/0",
            "REDIS_QUEUE_NAME": "provisioning_jobs",
            "ANSIBLE_BECOME_PASS": "sudo-password",
            "MANAGEMENT_VARS_PATH": str(local_secrets_dir / "management-vars.yaml"),
        },
    )
    _write_env(
        local_secrets_dir / "seller-agent.env",
        {"AGENT_ID": "seller-prod", "GEMINI_API_KEY": "seller-gemini-key"},
    )
    _write_env(
        local_secrets_dir / "buyer-agent.env",
        {"AGENT_ID": "buyer-prod", "GEMINI_API_KEY": "buyer-gemini-key"},
    )
    _write_env(
        local_secrets_dir / "prod-canary.env",
        {
            "SELLER_AGENT_URL": "http://10.0.0.21:8000",
            "BUYER_AGENT_URL": "http://10.0.0.22:8000",
            "SELLER_AGENT_ID": "seller-agent-id",
            "BUYER_AGENT_ID": "buyer-agent-id",
        },
    )
    (local_secrets_dir / "management-vars.yaml").write_text("ansible_user: ubuntu\n", encoding="utf-8")
    (local_secrets_dir / "provisioner_ed25519").write_text("provisioner\n", encoding="utf-8")
    (local_secrets_dir / "tenant_ed25519").write_text("tenant\n", encoding="utf-8")

    module.materialize_host_envs(
        local_secrets_dir=local_secrets_dir,
        output_dir=output_dir,
        shared_secrets_dir=shared_secrets_dir,
    )

    seller_text = (output_dir / "seller-agent.env").read_text(encoding="utf-8")
    assert "IDENTITY_REGISTRY_ADDRESS=0x8004A818BFB912233c491871b3d84c89A494BD9e" in seller_text
    assert "REPUTATION_REGISTRY_ADDRESS=0x8004B663056A597Dffe9eCcC1965A193B7388713" in seller_text
    assert "VALIDATION_REGISTRY_ADDRESS=0x8004Cb1BF31DAf7788923b405b754f57acEB4272" in seller_text


def test_materialize_host_envs_requires_shared_credentials_when_not_overridden(
    tmp_path: Path,
) -> None:
    module = _load_script_module()
    shared_secrets_dir = tmp_path / "shared-secrets"
    local_secrets_dir = tmp_path / "local-secrets"
    output_dir = tmp_path / "rendered"
    shared_secrets_dir.mkdir()
    local_secrets_dir.mkdir()

    _write_env(local_secrets_dir / "shared.env", {"CHAIN_NAME": "base_sepolia"})
    _write_env(local_secrets_dir / "contracts.env", {"IDENTITY_REGISTRY_ADDRESS": "0x1"})
    _write_env(local_secrets_dir / "registry.env", {"DATABASE_URL": "postgresql://registry"})
    _write_env(
        local_secrets_dir / "provisioning.env",
        {
            "DATABASE_URL": "postgresql+psycopg2://prov",
            "REDIS_URL": "redis://redis.internal:6379/0",
            "REDIS_QUEUE_NAME": "provisioning_jobs",
            "ANSIBLE_BECOME_PASS": "sudo-password",
        },
    )
    _write_env(local_secrets_dir / "seller-agent.env", {"AGENT_ID": "seller", "GEMINI_API_KEY": "key"})
    _write_env(local_secrets_dir / "buyer-agent.env", {"AGENT_ID": "buyer", "GEMINI_API_KEY": "key"})
    _write_env(
        local_secrets_dir / "prod-canary.env",
        {
            "SELLER_AGENT_URL": "http://seller",
            "BUYER_AGENT_URL": "http://buyer",
            "SELLER_AGENT_ID": "seller-agent-id",
            "BUYER_AGENT_ID": "buyer-agent-id",
        },
    )

    with pytest.raises(
        SystemExit,
        match="Missing required shared or local secret files: alchemy.env, wallets.env",
    ):
        module.materialize_host_envs(
            local_secrets_dir=local_secrets_dir,
            output_dir=output_dir,
            shared_secrets_dir=shared_secrets_dir,
        )
