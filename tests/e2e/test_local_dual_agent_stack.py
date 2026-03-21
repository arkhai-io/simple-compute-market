from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import textwrap
import time
import uuid
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

import pytest

from service.clients.erc8004.signing import sign_eip191


ROOT = Path(__file__).resolve().parents[2]
COMPOSE_TIMEOUT_SECS = 1800
WAIT_TIMEOUT_SECS = 300
REGISTRY_URL = "http://127.0.0.1:18080"
BUYER_URL = "http://127.0.0.1:18000"
SELLER_URL = "http://127.0.0.1:18001"
HOST_RPC_URL = "http://127.0.0.1:8545"
DOCKER_HOST_RPC_URL = "http://host.docker.internal:8545"
BUYER_ENV = ROOT / "core/agent/.env.alice.docker-compose"
SELLER_ENV = ROOT / "core/agent/.env.bob.docker-compose"
TESTNET_IDENTITY_REGISTRY = "0x8004A818BFB912233c491871b3d84c89A494BD9e"
TESTNET_REPUTATION_REGISTRY = "0x8004B663056A597Dffe9eCcC1965A193B7388713"
TESTNET_VALIDATION_REGISTRY = "0x8004Cb1BF31DAf7788923b405b754f57acEB4272"
TESTNET_OWNER_ADDRESS = "0x547289319C3e6aedB179C0b8e8aF0B5ACd062603"


def _run(
    *args: str,
    cwd: Path = ROOT,
    check: bool = True,
    timeout: int = COMPOSE_TIMEOUT_SECS,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        list(args),
        cwd=cwd,
        text=True,
        capture_output=True,
        timeout=timeout,
    )
    if check and result.returncode != 0:
        command = " ".join(args)
        raise AssertionError(
            f"command failed: {command}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    return result


def _run_compose(
    compose_file: Path,
    project_name: str,
    *args: str,
    check: bool = True,
    timeout: int = COMPOSE_TIMEOUT_SECS,
) -> subprocess.CompletedProcess[str]:
    return _run(
        "docker",
        "compose",
        "-f",
        str(compose_file),
        "-p",
        project_name,
        *args,
        check=check,
        timeout=timeout,
    )


def _require_docker() -> None:
    if shutil.which("docker") is None:
        pytest.skip("docker is not installed")

    result = _run("docker", "info", check=False, timeout=30)
    if result.returncode != 0:
        pytest.skip("docker daemon is not available")


def _assert_port_free(port: int) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.25)
        if sock.connect_ex(("127.0.0.1", port)) == 0:
            raise AssertionError(f"host port {port} is already in use")


def _parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key] = value
    return values


def _build_auth_headers(private_key: str, operation: str, resource_id: str) -> dict[str, str]:
    timestamp = str(int(time.time()))
    message = f"{operation}:{resource_id}:{timestamp}"
    signature = sign_eip191(private_key, message)
    assert signature, f"failed to sign auth message for {operation}"
    return {
        "Content-Type": "application/json",
        "X-Timestamp": timestamp,
        "X-Signature": signature,
    }


def _get_json(url: str) -> dict[str, object]:
    with urlopen(url, timeout=10) as response:
        return json.load(response)


def _post_json(url: str, payload: dict[str, object], headers: dict[str, str]) -> dict[str, object]:
    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    with urlopen(request, timeout=20) as response:
        return json.load(response)


def _wait_for_json(url: str) -> dict[str, object]:
    deadline = time.monotonic() + WAIT_TIMEOUT_SECS
    last_error = ""

    while time.monotonic() < deadline:
        try:
            return _get_json(url)
        except (HTTPError, URLError, TimeoutError, ConnectionError, OSError) as exc:
            last_error = str(exc)
            time.sleep(2)

    raise AssertionError(f"Timed out waiting for {url}: {last_error}")


def _canonical_agent_id_from_registration(document: dict[str, object]) -> str:
    registrations = document.get("registrations")
    assert isinstance(registrations, list) and registrations, document
    registration = registrations[0]
    assert isinstance(registration, dict), document
    agent_id = registration.get("agentId")
    agent_registry = registration.get("agentRegistry")
    assert isinstance(agent_id, int), document
    assert isinstance(agent_registry, str) and agent_registry, document
    return f"{agent_registry}:{agent_id}"


def _wait_for_rpc(url: str) -> None:
    deadline = time.monotonic() + WAIT_TIMEOUT_SECS
    last_error = ""
    payload = {
        "jsonrpc": "2.0",
        "method": "eth_blockNumber",
        "params": [],
        "id": 1,
    }

    while time.monotonic() < deadline:
        try:
            request = Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urlopen(request, timeout=10) as response:
                body = json.load(response)
            if "result" in body:
                return
            last_error = json.dumps(body)
        except (HTTPError, URLError, TimeoutError, ConnectionError, OSError) as exc:
            last_error = str(exc)
        time.sleep(1)

    raise AssertionError(f"Timed out waiting for RPC {url}: {last_error}")


def _wait_for_order(order_id: str) -> dict[str, object]:
    deadline = time.monotonic() + WAIT_TIMEOUT_SECS
    last_payload = ""

    while time.monotonic() < deadline:
        payload = _wait_for_json(f"{REGISTRY_URL}/orders/{order_id}")
        order = payload.get("order") if isinstance(payload, dict) else None
        if isinstance(order, dict):
            return order
        last_payload = json.dumps(payload)
        time.sleep(2)

    raise AssertionError(f"Timed out waiting for registry order {order_id}: {last_payload}")


def _wait_for_matching_state(seller_order_id: str, buyer_order_id: str) -> tuple[dict[str, object], dict[str, object]]:
    deadline = time.monotonic() + WAIT_TIMEOUT_SECS
    last_seller = ""
    last_buyer = ""

    while time.monotonic() < deadline:
        seller_order = _wait_for_order(seller_order_id)
        buyer_order = _wait_for_order(buyer_order_id)
        last_seller = json.dumps(seller_order)
        last_buyer = json.dumps(buyer_order)

        statuses = {seller_order.get("status"), buyer_order.get("status")}
        if "accepted" in statuses:
            return seller_order, buyer_order
        time.sleep(2)

    raise AssertionError(
        "Timed out waiting for accepted matching state.\n"
        f"seller={last_seller}\n"
        f"buyer={last_buyer}"
    )


def _wait_for_closed(order_id: str) -> dict[str, object]:
    deadline = time.monotonic() + WAIT_TIMEOUT_SECS
    last_payload = ""

    while time.monotonic() < deadline:
        order = _wait_for_order(order_id)
        last_payload = json.dumps(order)
        if order.get("status") == "closed":
            return order
        time.sleep(2)

    raise AssertionError(f"Timed out waiting for closed order {order_id}: {last_payload}")


def _copy_contracts_context(target_dir: Path) -> None:
    source = ROOT / "erc-8004-contracts"
    shutil.copytree(
        source,
        target_dir,
        ignore=shutil.ignore_patterns(".git", "node_modules", "artifacts", "cache"),
    )
    hardhat_config = target_dir / "hardhat.config.ts"
    config_text = hardhat_config.read_text(encoding="utf-8")
    marker = '    mainnet: {\n'
    localhost_block = textwrap.dedent(
        """
            localhost: {
              type: "http",
              chainType: "l1",
              url: process.env.LOCALHOST_RPC_URL || "http://127.0.0.1:8545",
            },
        """
    )
    if "localhost:" not in config_text:
        config_text = config_text.replace(marker, localhost_block + marker, 1)
        hardhat_config.write_text(config_text, encoding="utf-8")


def _write_contract_addresses_env(path: Path) -> None:
    path.write_text(
        textwrap.dedent(
            f"""
            IDENTITY_REGISTRY_ADDRESS={TESTNET_IDENTITY_REGISTRY}
            REPUTATION_REGISTRY_ADDRESS={TESTNET_REPUTATION_REGISTRY}
            VALIDATION_REGISTRY_ADDRESS={TESTNET_VALIDATION_REGISTRY}
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )


def _write_local_upgrade_script(contracts_dir: Path) -> None:
    (contracts_dir / "scripts/local-upgrade-impersonated.ts").write_text(
        textwrap.dedent(
            f"""
            import hre from "hardhat";
            import {{
              createWalletClient,
              encodeFunctionData,
              getCreate2Address,
              Hex,
              http,
              keccak256,
            }} from "viem";
            import {{
              EXPECTED_OWNER,
              IMPLEMENTATION_SALTS,
              SAFE_SINGLETON_FACTORY,
              getAddresses,
            }} from "./addresses";

            const RPC_URL = process.env.LOCALHOST_RPC_URL || "http://127.0.0.1:8545";

            async function rpc(method: string, params: unknown[] = []): Promise<void> {{
              const response = await fetch(RPC_URL, {{
                method: "POST",
                headers: {{ "content-type": "application/json" }},
                body: JSON.stringify({{
                  jsonrpc: "2.0",
                  id: 1,
                  method,
                  params,
                }}),
              }});
              const payload = await response.json();
              if (payload.error) {{
                throw new Error(`${{method}} failed: ${{payload.error.message}}`);
              }}
            }}

            async function main() {{
              const {{ viem }} = await hre.network.connect("localhost");
              const publicClient = await viem.getPublicClient();
              const chainId = await publicClient.getChainId();
              const addresses = getAddresses(chainId);

              await rpc("anvil_impersonateAccount", [EXPECTED_OWNER]);

              try {{
                const walletClient = createWalletClient({{
                  account: EXPECTED_OWNER,
                  chain: publicClient.chain,
                  transport: http(RPC_URL),
                }});

                const minimalUUPSArtifact = await hre.artifacts.readArtifact("MinimalUUPS");
                const identityImplArtifact = await hre.artifacts.readArtifact("IdentityRegistryUpgradeable");
                const reputationImplArtifact = await hre.artifacts.readArtifact("ReputationRegistryUpgradeable");
                const validationImplArtifact = await hre.artifacts.readArtifact("ValidationRegistryUpgradeable");

                const identityImpl = getCreate2Address({{
                  from: SAFE_SINGLETON_FACTORY,
                  salt: IMPLEMENTATION_SALTS.identityRegistry,
                  bytecodeHash: keccak256(identityImplArtifact.bytecode as Hex),
                }});
                const reputationImpl = getCreate2Address({{
                  from: SAFE_SINGLETON_FACTORY,
                  salt: IMPLEMENTATION_SALTS.reputationRegistry,
                  bytecodeHash: keccak256(reputationImplArtifact.bytecode as Hex),
                }});
                const validationImpl = getCreate2Address({{
                  from: SAFE_SINGLETON_FACTORY,
                  salt: IMPLEMENTATION_SALTS.validationRegistry,
                  bytecodeHash: keccak256(validationImplArtifact.bytecode as Hex),
                }});

                const implSlot =
                  "0x360894a13ba1a3210667c828492db98dca3e2076cc3735a920a3ca505d382bbc" as const;

                async function upgradeProxy(
                  proxyAddress: `0x${{string}}`,
                  expectedImplementation: `0x${{string}}`,
                  initData: `0x${{string}}`,
                ): Promise<void> {{
                  const storageValue = await publicClient.getStorageAt({{
                    address: proxyAddress,
                    slot: implSlot,
                  }});
                  const currentImplementation = storageValue
                    ? (`0x${{storageValue.slice(-40)}}` as `0x${{string}}`)
                    : null;
                  if (
                    currentImplementation &&
                    currentImplementation.toLowerCase() === expectedImplementation.toLowerCase()
                  ) {{
                    return;
                  }}

                  const callData = encodeFunctionData({{
                    abi: minimalUUPSArtifact.abi,
                    functionName: "upgradeToAndCall",
                    args: [expectedImplementation, initData],
                  }});

                  const hash = await walletClient.sendTransaction({{
                    account: EXPECTED_OWNER,
                    to: proxyAddress,
                    data: callData,
                  }});
                  const receipt = await publicClient.waitForTransactionReceipt({{ hash }});
                  if (receipt.status !== "success") {{
                    throw new Error(`Upgrade failed for ${{proxyAddress}}`);
                  }}
                }}

                await upgradeProxy(
                  addresses.identityRegistry,
                  identityImpl,
                  encodeFunctionData({{
                    abi: identityImplArtifact.abi,
                    functionName: "initialize",
                    args: [],
                  }}),
                );
                await upgradeProxy(
                  addresses.reputationRegistry,
                  reputationImpl,
                  encodeFunctionData({{
                    abi: reputationImplArtifact.abi,
                    functionName: "initialize",
                    args: [addresses.identityRegistry],
                  }}),
                );
                await upgradeProxy(
                  addresses.validationRegistry,
                  validationImpl,
                  encodeFunctionData({{
                    abi: validationImplArtifact.abi,
                    functionName: "initialize",
                    args: [addresses.identityRegistry],
                  }}),
                );
              }} finally {{
                await rpc("anvil_stopImpersonatingAccount", [EXPECTED_OWNER]);
              }}
            }}

            main().catch((error) => {{
              console.error(error);
              process.exit(1);
            }});
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )


def _write_contracts_runner_dockerfile(path: Path) -> None:
    path.write_text(
        textwrap.dedent(
            """
            FROM node:22.12.0-bookworm

            WORKDIR /app

            COPY erc-8004-contracts/package.json ./package.json
            COPY erc-8004-contracts/package-lock.json ./package-lock.json

            RUN npm install --legacy-peer-deps

            COPY erc-8004-contracts/ ./
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )


def _write_compose_file(
    path: Path,
    *,
    contracts_context_root: Path,
    contracts_env_path: Path,
) -> None:
    path.write_text(
        textwrap.dedent(
            f"""
            services:
              contracts-deploy:
                build:
                  context: {contracts_context_root.as_posix()}
                  dockerfile: contracts-runner.Dockerfile
                extra_hosts:
                  - "host.docker.internal:host-gateway"
                environment:
                  LOCALHOST_RPC_URL: {DOCKER_HOST_RPC_URL}
                  SEPOLIA_RPC_URL: {DOCKER_HOST_RPC_URL}
                  MAINNET_RPC_URL: {DOCKER_HOST_RPC_URL}
                  ETHERSCAN_API_KEY: local-test-key
                command: >
                  sh -lc "
                  npx hardhat run scripts/deploy-create2-factory.ts --network localhost &&
                  npm run local:fund-owner &&
                  npm run local:deploy:vanity &&
                  npx hardhat run scripts/local-upgrade-impersonated.ts --network localhost &&
                  npm run local:verify:vanity
                  "

              registry:
                build:
                  context: {(ROOT / "erc-8004-registry-py").as_posix()}
                  dockerfile: Dockerfile
                depends_on:
                  contracts-deploy:
                    condition: service_completed_successfully
                extra_hosts:
                  - "host.docker.internal:host-gateway"
                env_file:
                  - {(ROOT / "erc-8004-registry-py/.env.docker-compose").as_posix()}
                  - {contracts_env_path.as_posix()}
                environment:
                  RPC_URL: http://host.docker.internal:8545
                ports:
                  - "18080:8080"
                healthcheck:
                  test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8080/health')"]
                  interval: 5s
                  timeout: 5s
                  retries: 30
                  start_period: 10s

              buy_agent:
                build:
                  context: {ROOT.as_posix()}
                  dockerfile: core/Dockerfile
                  args:
                    INSTALL_RL_DEPS: "false"
                depends_on:
                  registry:
                    condition: service_healthy
                extra_hosts:
                  - "host.docker.internal:host-gateway"
                env_file:
                  - {BUYER_ENV.as_posix()}
                  - {contracts_env_path.as_posix()}
                environment:
                  CHAIN_ID: "31337"
                  CHAIN_RPC_URL: ws://host.docker.internal:8545
                ports:
                  - "18000:8000"

              sell_agent:
                build:
                  context: {ROOT.as_posix()}
                  dockerfile: core/Dockerfile
                  args:
                    INSTALL_RL_DEPS: "false"
                depends_on:
                  registry:
                    condition: service_healthy
                extra_hosts:
                  - "host.docker.internal:host-gateway"
                env_file:
                  - {SELLER_ENV.as_posix()}
                  - {contracts_env_path.as_posix()}
                environment:
                  CHAIN_ID: "31337"
                  CHAIN_RPC_URL: ws://host.docker.internal:8545
                ports:
                  - "18001:8001"
                command:
                  - sh
                  - -lc
                  - |
                    echo "Importing seller resources..."
                    PYTHONPATH="/:/app:/app/core/agent" uv run python core/agent/scripts/import_resources_csv.py \
                      --csv core/agent/app/data/ww1-machine.csv
                    exec ./entrypoint.sh
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )


def _compose_logs(compose_file: Path, project_name: str) -> str:
    result = _run_compose(
        compose_file,
        project_name,
        "logs",
        "--no-color",
        check=False,
        timeout=300,
    )
    return f"{result.stdout}\n{result.stderr}"


def _compose_down(compose_file: Path, project_name: str) -> None:
    _run_compose(
        compose_file,
        project_name,
        "down",
        "--volumes",
        "--remove-orphans",
        check=False,
        timeout=300,
    )


def _start_host_anvil(log_path: Path) -> tuple[subprocess.Popen[str], object]:
    log_file = log_path.open("w", encoding="utf-8")
    process = subprocess.Popen(
        ["anvil", "--host", "0.0.0.0", "--port", "8545"],
        cwd=ROOT,
        stdout=log_file,
        stderr=subprocess.STDOUT,
        text=True,
        env={**os.environ},
    )
    try:
        _wait_for_rpc(HOST_RPC_URL)
    except Exception:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)
        log_file.close()
        raise
    return process, log_file


def _compose_stack_ready() -> None:
    registry_health = _wait_for_json(f"{REGISTRY_URL}/health")
    assert registry_health["status"] == "healthy"

    buyer_card = _wait_for_json(f"{BUYER_URL}/.well-known/agent-card.json")
    seller_card = _wait_for_json(f"{SELLER_URL}/.well-known/agent-card.json")
    buyer_registration = _wait_for_json(f"{BUYER_URL}/.well-known/erc-8004-registration.json")
    seller_registration = _wait_for_json(f"{SELLER_URL}/.well-known/erc-8004-registration.json")
    portfolio = _wait_for_json(f"{SELLER_URL}/resources/portfolio")

    buyer_canonical_id = _canonical_agent_id_from_registration(buyer_registration)
    seller_canonical_id = _canonical_agent_id_from_registration(seller_registration)
    buyer_registry_agent = _wait_for_json(f"{REGISTRY_URL}/agents/{quote(buyer_canonical_id, safe='')}")
    seller_registry_agent = _wait_for_json(f"{REGISTRY_URL}/agents/{quote(seller_canonical_id, safe='')}")

    assert buyer_card["url"] == "http://buy_agent:8000"
    assert seller_card["url"] == "http://sell_agent:8001"
    assert buyer_registry_agent["agentId"] == buyer_canonical_id
    assert seller_registry_agent["agentId"] == seller_canonical_id
    resources = portfolio.get("resources")
    assert isinstance(resources, list) and resources, "seller portfolio is empty"
    assert any(
        resource.get("gpu_model") == "RTX 5080" and resource.get("quantity") == 1
        for resource in resources
        if isinstance(resource, dict)
    ), portfolio


def _build_order_payload(*, offering_compute: bool) -> dict[str, object]:
    compute_resource = {
        "gpu_model": "RTX 5080",
        "quantity": 1,
        "sla": 90.0,
        "region": "California, US",
    }
    token_resource = {
        "token": "MOCK",
        "amount": 1.0,
    }
    if offering_compute:
        offer = compute_resource
        demand = token_resource
    else:
        offer = token_resource
        demand = compute_resource
    return {"offer": offer, "demand": demand, "duration_hours": 1}


def _close_order(agent_url: str, private_key: str, order_id: str) -> dict[str, object]:
    return _post_json(
        f"{agent_url}/orders/close",
        {"order_id": order_id},
        _build_auth_headers(private_key, "close_order", order_id),
    )


def _create_order(
    agent_url: str,
    private_key: str,
    resource_id: str,
    payload: dict[str, object],
) -> dict[str, object]:
    return _post_json(
        f"{agent_url}/orders/create",
        payload,
        _build_auth_headers(private_key, "create_order", resource_id),
    )


def test_local_dual_agent_stack_supports_matching_and_closeout(tmp_path: Path) -> None:
    # This local dual-agent e2e uses docker compose in an isolated temp stack,
    # verifies seller /resources/portfolio visibility, creates signed orders via
    # /orders/create, waits for an accepted match, observes maker_attestation-
    # related registry state, and then drives /orders/close.
    _require_docker()
    for port in (8545, 18080, 18000, 18001):
        _assert_port_free(port)

    buyer_env = _parse_env_file(BUYER_ENV)
    seller_env = _parse_env_file(SELLER_ENV)
    assert buyer_env["AGENT_PRIV_KEY"]
    assert seller_env["AGENT_PRIV_KEY"]

    contracts_context_root = tmp_path / "contracts-build"
    contracts_source = contracts_context_root / "erc-8004-contracts"
    _copy_contracts_context(contracts_source)
    _write_local_upgrade_script(contracts_source)
    _write_contracts_runner_dockerfile(contracts_context_root / "contracts-runner.Dockerfile")

    shared_env_dir = tmp_path / "shared-env"
    shared_env_dir.mkdir(parents=True, exist_ok=True)
    contracts_env_path = shared_env_dir / "contracts.env"
    _write_contract_addresses_env(contracts_env_path)

    compose_file = tmp_path / "docker-compose.yml"
    _write_compose_file(
        compose_file,
        contracts_context_root=contracts_context_root,
        contracts_env_path=contracts_env_path,
    )
    project_name = f"dual-agent-e2e-{uuid.uuid4().hex[:8]}"
    anvil_log_path = tmp_path / "anvil.log"
    anvil_process, anvil_log = _start_host_anvil(anvil_log_path)
    test_failed = True

    try:
        _run_compose(compose_file, project_name, "up", "--build", "-d")
        _compose_stack_ready()

        seller_created = _create_order(
            SELLER_URL,
            seller_env["AGENT_PRIV_KEY"],
            seller_env["BASE_URL_OVERRIDE"].rstrip("/"),
            _build_order_payload(offering_compute=True),
        )
        assert seller_created["status"] == "created", seller_created
        seller_order_id = str(seller_created["order_id"])

        _wait_for_order(seller_order_id)

        buyer_created = _create_order(
            BUYER_URL,
            buyer_env["AGENT_PRIV_KEY"],
            buyer_env["BASE_URL_OVERRIDE"].rstrip("/"),
            _build_order_payload(offering_compute=False),
        )
        assert buyer_created["status"] == "created", buyer_created
        buyer_order_id = str(buyer_created["order_id"])

        seller_order, buyer_order = _wait_for_matching_state(
            seller_order_id,
            buyer_order_id,
        )
        assert {seller_order.get("status"), buyer_order.get("status")} & {"accepted"}
        assert (
            seller_order.get("maker_attestation")
            or buyer_order.get("maker_attestation")
            or seller_order.get("taker_attestation")
            or buyer_order.get("taker_attestation")
        ), {"seller": seller_order, "buyer": buyer_order}

        seller_closed = _close_order(
            SELLER_URL,
            seller_env["AGENT_PRIV_KEY"],
            seller_order_id,
        )
        buyer_closed = _close_order(
            BUYER_URL,
            buyer_env["AGENT_PRIV_KEY"],
            buyer_order_id,
        )
        assert seller_closed["status"] == "closed", seller_closed
        assert buyer_closed["status"] == "closed", buyer_closed
        assert _wait_for_closed(seller_order_id)["status"] == "closed"
        assert _wait_for_closed(buyer_order_id)["status"] == "closed"
        test_failed = False
    finally:
        if test_failed and _run("docker", "ps", check=False, timeout=30).returncode == 0:
            print(_compose_logs(compose_file, project_name))
            anvil_log.flush()
            if anvil_log_path.exists():
                print(anvil_log_path.read_text(encoding="utf-8"))
        _compose_down(compose_file, project_name)
        anvil_process.terminate()
        try:
            anvil_process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            anvil_process.kill()
            anvil_process.wait(timeout=10)
        anvil_log.close()
