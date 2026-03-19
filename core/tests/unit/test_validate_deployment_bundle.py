from __future__ import annotations

import importlib.util
from pathlib import Path
from textwrap import dedent


ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = ROOT / "scripts/validate_deployment_bundle.py"


def _load_script_module():
    spec = importlib.util.spec_from_file_location("validate_deployment_bundle", SCRIPT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write(path: Path, contents: str) -> Path:
    path.write_text(dedent(contents).strip() + "\n", encoding="utf-8")
    return path


def _valid_agent_env() -> str:
    return """
    GEMINI_API_KEY=gemini-secret
    BASE_URL_OVERRIDE=http://{ZEROTIER_IP}:8000/
    PORT=8000
    AGENT_DB_PATH=/var/lib/market/agent.db
    AGENT_ID=agent_prod_canary
    LOG_FILE_PATH=/var/log/market/agent.log
    AUTO_REGISTER=true
    IDENTITY_REGISTRY_ADDRESS=0x1111111111111111111111111111111111111111
    REPUTATION_REGISTRY_ADDRESS=0x2222222222222222222222222222222222222222
    VALIDATION_REGISTRY_ADDRESS=0x3333333333333333333333333333333333333333
    REGISTRY_URL=http://100.64.0.10:8080/
    CHAIN_RPC_URL=https://base-sepolia.example-rpc.invalid
    AGENT_PRIV_KEY=0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
    AGENT_WALLET_ADDRESS=0xbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
    CHAIN_NAME=base-sepolia
    TOKEN_REGISTRY_PATH=../core/agent/app/data/token_registry.json
    SSH_PUBLIC_KEY=ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIGp1c3QtYS10ZXN0LWtleQ== canary@test
    ZEROTIER_NETWORK=8056c2e21c000001
    PROVISIONING_MODE=http
    PROVISIONING_SERVICE_URL=http://100.64.0.11:8081
    PROVISIONING_TIMEOUT=3600
    PROVISIONING_POLL_INTERVAL=15
    DEFAULT_VM_HOST=ww1
    RESOURCE_CHECK_INTERVAL=60
    FRP_SERVER_ADDR=100.64.0.12
    FRP_DOMAIN=arkhainet.example
    FRP_DASHBOARD_PASSWORD=frp-secret
    NEGOTIATION_POLICY_MODE=bisection
    """


def _valid_provisioning_env() -> str:
    return """
    HOST=0.0.0.0
    PORT=8081
    LOG_LEVEL=info
    DATABASE_URL=postgresql+psycopg2://postgres:postgres@postgres.internal:5432/provisioning
    REDIS_URL=redis://redis.internal:6379/0
    REDIS_QUEUE_NAME=provisioning_jobs
    ANSIBLE_TIMEOUT_SECONDS=1800
    DEFAULT_VM_HOST=ww1
    ANSIBLE_BECOME_PASS=become-secret
    ZEROTIER_NETWORK=8056c2e21c000001
    ENABLE_AUTH=true
    AUTH_FAIL_OPEN=false
    REGISTRY_URL=http://100.64.0.10:8080/
    REGISTRY_CACHE_TTL_SECONDS=300
    REGISTRY_CACHE_MAX_SIZE=256
    ENABLE_RATE_LIMITING=true
    RATE_LIMIT_REQUESTS_PER_MINUTE=30
    FRP_SERVER_ADDR=100.64.0.12
    FRP_DOMAIN=arkhainet.example
    FRP_DASHBOARD_PASSWORD=frp-secret
    SSH_PRIVATE_KEY=-----BEGIN OPENSSH PRIVATE KEY-----fake-----END OPENSSH PRIVATE KEY-----
    MANAGEMENT_VARS_YAML=root_ssh_filename: root_ed25519
    """


def _valid_registry_env() -> str:
    return """
    DATABASE_URL=postgresql+psycopg2://postgres:postgres@postgres.internal:5432/indexer
    CHAIN_ID=84532
    RPC_URL=https://base-sepolia.example-rpc.invalid
    IDENTITY_REGISTRY_ADDRESS=0x1111111111111111111111111111111111111111
    REPUTATION_REGISTRY_ADDRESS=0x2222222222222222222222222222222222222222
    VALIDATION_REGISTRY_ADDRESS=0x3333333333333333333333333333333333333333
    PORT=8080
    HOST=0.0.0.0
    ZEROTIER_NETWORK=8056c2e21c000001
    ENABLE_HEALTH_CHECKS=true
    HEALTH_CHECK_INTERVAL=60
    ENDPOINT_CHECK_TIMEOUT=10
    HEARTBEAT_TTL_SECS=60
    LOG_LEVEL=info
    """


def _inventory() -> str:
    return """
    [frp_servers]
    proxy-dev ansible_host=100.64.0.20
    proxy-staging ansible_host=100.64.0.21
    proxy-production ansible_host=100.64.0.22

    [provisioning_servers]
    provisioning-dev ansible_host=100.64.0.30
    provisioning-staging ansible_host=100.64.0.31
    provisioning-production ansible_host=100.64.0.32

    [kvm_hosts]
    ww1 ansible_host=100.64.0.40
    """


def test_validator_accepts_valid_bundle(tmp_path: Path) -> None:
    module = _load_script_module()
    agent_env = _write(tmp_path / "agent.env", _valid_agent_env())
    provisioning_env = _write(tmp_path / "provisioning.env", _valid_provisioning_env())
    registry_env = _write(tmp_path / "registry.env", _valid_registry_env())
    inventory = _write(tmp_path / "hosts", _inventory())
    ssh_key = _write(tmp_path / "id_ed25519", "not-a-real-key")

    errors = module.validate_bundle(
        agent_env_path=agent_env,
        provisioning_env_path=provisioning_env,
        registry_env_path=registry_env,
        inventory_path=inventory,
        seller_agent_url="http://100.64.0.50:8001",
        buyer_agent_url="http://100.64.0.51:8000",
        seller_agent_id="eip155:84532:0x1111111111111111111111111111111111111111:101",
        buyer_agent_id="eip155:84532:0x1111111111111111111111111111111111111111:202",
        seller_private_key="0xcccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
        buyer_private_key="0xdddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd",
        ssh_private_key_path=str(ssh_key),
    )

    assert errors == []


def test_validator_rejects_placeholder_urls_and_local_hosts(tmp_path: Path) -> None:
    module = _load_script_module()
    agent_env = _write(
        tmp_path / "agent.env",
        _valid_agent_env()
        .replace("http://100.64.0.10:8080/", "http://localhost:8080/")
        .replace("http://100.64.0.11:8081", "http://<provisioner-ip>:8081"),
    )
    provisioning_env = _write(tmp_path / "provisioning.env", _valid_provisioning_env())
    registry_env = _write(tmp_path / "registry.env", _valid_registry_env())
    inventory = _write(tmp_path / "hosts", _inventory())

    errors = module.validate_bundle(
        agent_env_path=agent_env,
        provisioning_env_path=provisioning_env,
        registry_env_path=registry_env,
        inventory_path=inventory,
    )

    assert any("agent env:REGISTRY_URL: local-only host is not allowed" in error for error in errors)
    assert any(
        "agent env:PROVISIONING_SERVICE_URL: placeholder value is not allowed" in error
        for error in errors
    )


def test_validator_rejects_auth_and_inventory_drift(tmp_path: Path) -> None:
    module = _load_script_module()
    agent_env = _write(
        tmp_path / "agent.env",
        _valid_agent_env().replace("DEFAULT_VM_HOST=ww1", "DEFAULT_VM_HOST=missing-kvm"),
    )
    provisioning_env = _write(
        tmp_path / "provisioning.env",
        _valid_provisioning_env()
        .replace("DEFAULT_VM_HOST=ww1", "DEFAULT_VM_HOST=missing-kvm")
        .replace("ENABLE_AUTH=true", "ENABLE_AUTH=false")
        .replace("AUTH_FAIL_OPEN=false", "AUTH_FAIL_OPEN=true"),
    )
    registry_env = _write(tmp_path / "registry.env", _valid_registry_env())
    inventory = _write(tmp_path / "hosts", _inventory())

    errors = module.validate_bundle(
        agent_env_path=agent_env,
        provisioning_env_path=provisioning_env,
        registry_env_path=registry_env,
        inventory_path=inventory,
    )

    assert "agent env:DEFAULT_VM_HOST is not in inventory: missing-kvm" in errors
    assert "provisioning env:DEFAULT_VM_HOST is not in inventory: missing-kvm" in errors
    assert "provisioning env:ENABLE_AUTH must be true" in errors
    assert "provisioning env:AUTH_FAIL_OPEN must be false" in errors


def test_validator_rejects_chain_and_identity_mismatches(tmp_path: Path) -> None:
    module = _load_script_module()
    agent_env = _write(
        tmp_path / "agent.env",
        _valid_agent_env()
        .replace("CHAIN_NAME=base-sepolia", "CHAIN_NAME=ethereum-sepolia")
        .replace(
            "IDENTITY_REGISTRY_ADDRESS=0x1111111111111111111111111111111111111111",
            "IDENTITY_REGISTRY_ADDRESS=0x4444444444444444444444444444444444444444",
        ),
    )
    provisioning_env = _write(tmp_path / "provisioning.env", _valid_provisioning_env())
    registry_env = _write(
        tmp_path / "registry.env",
        _valid_registry_env().replace("CHAIN_ID=84532", "CHAIN_ID=11155111"),
    )
    inventory = _write(tmp_path / "hosts", _inventory())

    errors = module.validate_bundle(
        agent_env_path=agent_env,
        provisioning_env_path=provisioning_env,
        registry_env_path=registry_env,
        inventory_path=inventory,
        seller_agent_id="eip155:11155111:0x1111111111111111111111111111111111111111:101",
    )

    assert "agent env:CHAIN_NAME must be base-sepolia, got ethereum-sepolia" in errors
    assert "registry env:CHAIN_ID must be 84532, got 11155111" in errors
    assert any(
        error.startswith(
            "agent env:IDENTITY_REGISTRY_ADDRESS must match registry env:IDENTITY_REGISTRY_ADDRESS"
        )
        for error in errors
    )
    assert any("seller-agent-id: chain id 11155111 does not match expected 84532" in error for error in errors)


def test_validator_rejects_invalid_canary_inputs(tmp_path: Path) -> None:
    module = _load_script_module()
    agent_env = _write(tmp_path / "agent.env", _valid_agent_env())
    provisioning_env = _write(tmp_path / "provisioning.env", _valid_provisioning_env())
    registry_env = _write(tmp_path / "registry.env", _valid_registry_env())
    inventory = _write(tmp_path / "hosts", _inventory())

    errors = module.validate_bundle(
        agent_env_path=agent_env,
        provisioning_env_path=provisioning_env,
        registry_env_path=registry_env,
        inventory_path=inventory,
        seller_agent_url="http://host.docker.internal:8001",
        buyer_agent_id="not-an-agent-id",
        seller_private_key="0x1234",
        ssh_private_key_path=str(tmp_path / "missing-key"),
    )

    assert "seller-agent-url: local-only host is not allowed: http://host.docker.internal:8001" in errors
    assert "buyer-agent-id: expected canonical agent id, got: not-an-agent-id" in errors
    assert "seller-private-key: invalid hex private key" in errors
    assert any("ssh-private-key-path does not exist" in error for error in errors)
