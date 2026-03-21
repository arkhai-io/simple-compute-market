from __future__ import annotations

import argparse
import base64
import json
import os
import shlex
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN


_KNOWN_WRAPPED_NATIVE_TOKENS: dict[str, tuple[str, int]] = {
    "base": ("0x4200000000000000000000000000000000000006", 18),
    "base_sepolia": ("0x4200000000000000000000000000000000000006", 18),
    "base-sepolia": ("0x4200000000000000000000000000000000000006", 18),
}
_KNOWN_TOKEN_DECIMALS: dict[str, int] = {
    "USDC": 6,
    "WETH": 18,
}
_WRAP_NATIVE_CALLDATA = "0xd0e30db0"
_WRAP_GAS_LIMIT = 120000
_NATIVE_TRANSFER_GAS_LIMIT = 21000
_MIN_WRAP_GAS_BUFFER_WEI = 1_000_000_000_000
_WRAP_GAS_BUFFER_MULTIPLIER = 2
_ESCROW_APPROVAL_GAS_LIMIT = 100000
_ESCROW_CREATE_GAS_LIMIT = 600000
_MIN_ESCROW_GAS_BUFFER_WEI = 1_000_000_000_000
_ESCROW_GAS_BUFFER_MULTIPLIER = 2


def _env(name: str, default: str | None = None) -> str | None:
    return os.getenv(name, default)


def _require(value: str | None, label: str) -> str:
    if value:
        return value
    raise SystemExit(f"Missing required value for {label}")


def _normalize_base_url(raw_url: str) -> str:
    return raw_url.rstrip("/")


def _registration_agent_ids(document: dict) -> set[str]:
    registrations = document.get("registrations")
    if not isinstance(registrations, list):
        return set()

    agent_ids: set[str] = set()
    for registration in registrations:
        if not isinstance(registration, dict):
            continue
        registry = registration.get("agentRegistry")
        agent_id = registration.get("agentId")
        if not registry or agent_id is None:
            continue
        agent_ids.add(f"{registry}:{agent_id}")
    return agent_ids


def _request_json(
    method: str,
    url: str,
    *,
    payload: dict | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 20.0,
) -> dict:
    body = None
    request_headers = {"Accept": "application/json"}
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        request_headers["Content-Type"] = "application/json"
    if headers:
        request_headers.update(headers)

    request = urllib.request.Request(
        url,
        data=body,
        headers=request_headers,
        method=method,
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = response.read().decode("utf-8")
            return json.loads(data) if data else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8") if exc.fp else str(exc)
        raise SystemExit(f"{method} {url} failed with {exc.code}: {detail}") from exc


def _sign_headers(operation: str, resource_id: str, private_key: str) -> dict[str, str]:
    signature, timestamp = _sign_operation(operation, resource_id, private_key)
    return {
        "X-Signature": signature,
        "X-Timestamp": str(timestamp),
    }


def _sign_operation(operation: str, resource_id: str, private_key: str) -> tuple[str, int]:
    try:
        from eth_account import Account
        from eth_account.messages import encode_defunct
    except ImportError as exc:
        raise SystemExit(
            "eth-account is required for signed canary requests. "
            "Run this script with `cd cli && uv --no-config run python ../scripts/prod_canary_smoke.py ...`."
        ) from exc

    timestamp = int(time.time())
    message = f"{operation}:{resource_id}:{timestamp}"
    signature = Account.sign_message(
        encode_defunct(text=message),
        private_key,
    ).signature.hex()
    return signature, timestamp


def _check_health(label: str, url: str) -> dict:
    print(f"[health] {label}: {url}")
    return _request_json("GET", url)


def _check_frp_dashboard(url: str, password: str) -> dict:
    api_url = f"{_normalize_base_url(url)}/api/proxy/tcp"
    token = base64.b64encode(f"admin:{password}".encode("utf-8")).decode("ascii")
    print(f"[preflight] frp dashboard: {api_url}")
    return _request_json(
        "GET",
        api_url,
        headers={"Authorization": f"Basic {token}"},
    )


def _create_order(
    *,
    agent_url: str,
    private_key: str,
    offer: dict,
    demand: dict,
    duration_hours: int,
    timeout: float,
) -> None:
    url = f"{_normalize_base_url(agent_url)}/orders/create"
    headers = _sign_headers("create_order", _normalize_base_url(agent_url), private_key)
    payload = {
        "offer": offer,
        "demand": demand,
        "duration_hours": duration_hours,
    }
    response = _request_json("POST", url, payload=payload, headers=headers, timeout=timeout)
    status = response.get("status")
    if status not in {"queued", "created"}:
        raise SystemExit(f"Unexpected order creation status from {agent_url}: {response}")


def _fetch_agent_orders(registry_url: str, agent_id: str) -> list[dict]:
    encoded = urllib.parse.quote(agent_id, safe="")
    response = _request_json("GET", f"{_normalize_base_url(registry_url)}/agents/{encoded}/orders")
    return response.get("items", [])


def _wait_for_new_order(
    *,
    registry_url: str,
    agent_id: str,
    baseline_ids: set[str],
    timeout: int,
    poll_interval: int,
) -> str:
    deadline = time.time() + timeout
    while time.time() < deadline:
        items = _fetch_agent_orders(registry_url, agent_id)
        current_ids = {item["order_id"] for item in items}
        new_ids = sorted(current_ids - baseline_ids)
        if new_ids:
            return new_ids[-1]
        time.sleep(poll_interval)
    raise SystemExit(f"Timed out waiting for a new registry order for {agent_id}")


def _fetch_order(registry_url: str, order_id: str) -> dict:
    response = _request_json("GET", f"{_normalize_base_url(registry_url)}/orders/{order_id}")
    return response["order"]


def _update_order_status(
    *,
    registry_url: str,
    order_id: str,
    status: str,
    signer_agent_id: str,
    private_key: str,
) -> dict:
    signature, timestamp = _sign_operation("update_order", order_id, private_key)
    return _request_json(
        "PUT",
        f"{_normalize_base_url(registry_url)}/orders/{order_id}",
        payload={
            "status": status,
            "signer_agent_id": signer_agent_id,
            "signature": signature,
            "timestamp": timestamp,
        },
        timeout=60.0,
    )


def _wait_for_orders_closed(
    *,
    registry_url: str,
    order_ids: list[str],
    timeout: int,
    poll_interval: int,
) -> dict[str, dict]:
    deadline = time.time() + timeout
    while time.time() < deadline:
        orders = {order_id: _fetch_order(registry_url, order_id) for order_id in order_ids}
        if all(order.get("status") == "closed" for order in orders.values()):
            return orders
        time.sleep(poll_interval)
    raise SystemExit(f"Timed out waiting for orders to close: {order_ids}")


def _list_jobs(provisioning_url: str, agent_id: str) -> list[dict]:
    response = _request_json(
        "GET",
        f"{_normalize_base_url(provisioning_url)}/api/v1/jobs?limit=100",
        headers={"X-Agent-ID": agent_id},
    )
    return response.get("jobs", [])


def _job_vm_action(job: dict) -> str | None:
    if job.get("vm_action"):
        return str(job["vm_action"])
    params = job.get("params")
    if isinstance(params, dict) and params.get("vm_action"):
        return str(params["vm_action"])
    return None


def _job_error(job: dict) -> str | None:
    error = job.get("error")
    if error:
        return str(error)
    result = job.get("result")
    if isinstance(result, dict):
        result_error = result.get("error")
        if result_error:
            return str(result_error)
    return None


def _wait_for_new_succeeded_job(
    *,
    provisioning_url: str,
    seller_agent_id: str,
    baseline_job_ids: set[str],
    timeout: int,
    poll_interval: int,
    expected_vm_action: str = "create",
) -> dict:
    deadline = time.time() + timeout
    observed_job_ids: set[str] = set()
    while time.time() < deadline:
        jobs = _list_jobs(provisioning_url, seller_agent_id)
        for job in jobs:
            job_id = job.get("job_id")
            if not job_id or job_id in baseline_job_ids:
                continue
            if _job_vm_action(job) != expected_vm_action:
                continue
            status = str(job.get("status", ""))
            if job_id not in observed_job_ids:
                params = job.get("params") if isinstance(job.get("params"), dict) else {}
                result = job.get("result") if isinstance(job.get("result"), dict) else {}
                vm_host = result.get("vm_host") or params.get("vm_host") or "<unknown>"
                vm_target = (
                    result.get("vm_name")
                    or result.get("vm_target")
                    or params.get("vm_target")
                    or "<unknown>"
                )
                print(
                    f"[provisioning] observed job: {job_id} "
                    f"status={status} vm_host={vm_host} vm_target={vm_target}"
                )
                observed_job_ids.add(str(job_id))
            if status == "succeeded":
                return job
            if status in {"failed", "cancelled", "canceled"}:
                error = _job_error(job) or f"status={status}"
                raise SystemExit(f"Provisioning job {job_id} failed: {error}")
        time.sleep(poll_interval)
    raise SystemExit(
        f"Timed out waiting for a new succeeded provisioning job with vm_action={expected_vm_action}"
    )


def _fetch_credentials(provisioning_url: str, job_id: str, agent_id: str) -> list[dict]:
    response = _request_json(
        "GET",
        f"{_normalize_base_url(provisioning_url)}/api/v1/jobs/{job_id}/credentials",
        headers={"X-Agent-ID": agent_id},
    )
    return response.get("credentials", [])


def _submit_job(provisioning_url: str, agent_id: str, payload: dict) -> dict:
    return _request_json(
        "POST",
        f"{_normalize_base_url(provisioning_url)}/api/v1/jobs",
        payload=payload,
        headers={"X-Agent-ID": agent_id},
        timeout=60.0,
    )


def _summary_int(summary: dict, bucket: str, key: str) -> int:
    value = summary.get(bucket)
    if not isinstance(value, dict):
        return 0
    raw = value.get(key, 0)
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 0


def _capacity_summary(result: dict | None) -> dict:
    if not isinstance(result, dict):
        return {}
    summary = result.get("summary")
    if isinstance(summary, dict):
        return summary
    ansible_result = result.get("ansible_result")
    if isinstance(ansible_result, dict):
        return ansible_result
    return {}


def _verify_ssh(
    credentials: list[dict],
    ssh_private_key_path: str | None,
    *,
    ready_timeout: int = 0,
    retry_interval: int = 5,
) -> None:
    if not ssh_private_key_path:
        print("[ssh] skipped: no --ssh-private-key-path provided")
        return

    tenant_credential = next((cred for cred in credentials if cred.get("role") == "tenant"), None)
    if not tenant_credential:
        raise SystemExit("Tenant credential not returned by provisioning service")

    ssh_commands = tenant_credential.get("ssh_commands") or {}
    external = ssh_commands.get("external")
    if not external:
        raise SystemExit("Tenant credential did not include an external SSH command")

    command = external.replace("<your_private_key>", ssh_private_key_path)
    parts = shlex.split(command)
    if parts and parts[0] == "ssh" and "-i" not in parts:
        parts[1:1] = ["-i", ssh_private_key_path]
    if parts and parts[0] == "ssh":
        parts[1:1] = [
            "-o",
            "StrictHostKeyChecking=no",
            "-o",
            "UserKnownHostsFile=/dev/null",
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=10",
        ]
    parts.extend(["hostname"])

    print(f"[ssh] verifying remote access via: {' '.join(parts)}")
    deadline = time.monotonic() + max(ready_timeout, 0)
    attempt = 1
    while True:
        try:
            subprocess.run(parts, check=True)
            return
        except subprocess.CalledProcessError as exc:
            if time.monotonic() >= deadline:
                raise SystemExit(
                    f"SSH verification failed after {attempt} attempt(s): {' '.join(parts)}"
                ) from exc
            sleep_seconds = max(retry_interval, 0)
            print(
                f"[ssh] remote access not ready yet (attempt {attempt}); "
                f"retrying in {sleep_seconds}s"
            )
            time.sleep(sleep_seconds)
            attempt += 1


def _rpc_url_for_http_provider(rpc_url: str) -> str:
    parsed = urllib.parse.urlparse(rpc_url.strip())
    if parsed.scheme == "ws":
        parsed = parsed._replace(scheme="http")
    elif parsed.scheme == "wss":
        parsed = parsed._replace(scheme="https")
    return urllib.parse.urlunparse(parsed)


def _rpc_request(rpc_url: str, method: str, params: list) -> object:
    response = _request_json(
        "POST",
        _rpc_url_for_http_provider(rpc_url),
        payload={
            "jsonrpc": "2.0",
            "id": 1,
            "method": method,
            "params": params,
        },
        timeout=30.0,
    )
    if "error" in response:
        raise SystemExit(f"{method} failed: {response['error']}")
    return response.get("result")


def _normalize_chain_name(chain_name: str | None) -> str:
    return (chain_name or "").strip().lower()


def _resolve_wrapped_native_token(config: "CanaryConfig") -> tuple[str, int] | None:
    if config.token_symbol.upper() != "WETH":
        return None
    return _KNOWN_WRAPPED_NATIVE_TOKENS.get(_normalize_chain_name(config.chain_name))


def _to_base_units(amount: Decimal | float, decimals: int) -> int:
    raw = Decimal(str(amount)) * (Decimal(10) ** decimals)
    return int(raw)


def _pad_address(address: str) -> str:
    normalized = address.lower().removeprefix("0x")
    return normalized.rjust(64, "0")


def _erc20_balance_of(rpc_url: str, token_address: str, owner_address: str) -> int:
    data = f"0x70a08231{_pad_address(owner_address)}"
    result = _rpc_request(
        rpc_url,
        "eth_call",
        [{"to": token_address, "data": data}, "latest"],
    )
    return int(str(result), 16)


def _native_balance_of(rpc_url: str, owner_address: str) -> int:
    result = _rpc_request(rpc_url, "eth_getBalance", [owner_address, "latest"])
    return int(str(result), 16)


def _chain_id(rpc_url: str) -> int:
    result = _rpc_request(rpc_url, "eth_chainId", [])
    return int(str(result), 16)


def _gas_price(rpc_url: str) -> int:
    result = _rpc_request(rpc_url, "eth_gasPrice", [])
    return int(str(result), 16)


def _wrap_gas_buffer_wei(*, gas_price: int) -> int:
    estimated_wrap_cost = gas_price * _WRAP_GAS_LIMIT
    return max(
        _MIN_WRAP_GAS_BUFFER_WEI,
        estimated_wrap_cost * _WRAP_GAS_BUFFER_MULTIPLIER,
    )


def _escrow_gas_buffer_wei(*, gas_price: int) -> int:
    estimated_escrow_cost = gas_price * (
        _ESCROW_APPROVAL_GAS_LIMIT + _ESCROW_CREATE_GAS_LIMIT
    )
    return max(
        _MIN_ESCROW_GAS_BUFFER_WEI,
        estimated_escrow_cost * _ESCROW_GAS_BUFFER_MULTIPLIER,
    )


def _nonce(rpc_url: str, owner_address: str) -> int:
    result = _rpc_request(rpc_url, "eth_getTransactionCount", [owner_address, "pending"])
    return int(str(result), 16)


def _wait_for_transaction_receipt(rpc_url: str, tx_hash: str, *, timeout: int = 120) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        receipt = _rpc_request(rpc_url, "eth_getTransactionReceipt", [tx_hash])
        if receipt:
            return dict(receipt)
        time.sleep(2)
    raise SystemExit(f"Timed out waiting for transaction receipt: {tx_hash}")


def _wait_for_native_balance(
    rpc_url: str,
    owner_address: str,
    *,
    minimum_wei: int,
    timeout: int = 30,
    poll_interval: int = 2,
) -> int:
    deadline = time.time() + timeout
    while time.time() < deadline:
        balance = _native_balance_of(rpc_url, owner_address)
        if balance >= minimum_wei:
            return balance
        time.sleep(poll_interval)
    raise SystemExit(
        f"Timed out waiting for native balance >= {minimum_wei} for {owner_address}"
    )


def _wrap_native_to_wrapped_token(
    rpc_url: str,
    private_key: str,
    token_address: str,
    amount_wei: int,
) -> None:
    from eth_account import Account

    if amount_wei <= 0:
        return

    account = Account.from_key(private_key)
    tx = {
        "chainId": _chain_id(rpc_url),
        "nonce": _nonce(rpc_url, account.address),
        "to": token_address,
        "value": amount_wei,
        "data": _WRAP_NATIVE_CALLDATA,
        "gas": _WRAP_GAS_LIMIT,
        "gasPrice": _gas_price(rpc_url),
    }
    signed = Account.sign_transaction(tx, private_key)
    tx_hash = _rpc_request(
        rpc_url,
        "eth_sendRawTransaction",
        [f"0x{signed.raw_transaction.hex()}"],
    )
    receipt = _wait_for_transaction_receipt(rpc_url, str(tx_hash))
    if int(str(receipt.get("status", "0x0")), 16) != 1:
        raise SystemExit(f"WETH wrap transaction failed: {tx_hash}")


def _transfer_native_token(
    rpc_url: str,
    private_key: str,
    recipient_address: str,
    amount_wei: int,
) -> None:
    from eth_account import Account

    if amount_wei <= 0:
        return

    account = Account.from_key(private_key)
    tx = {
        "chainId": _chain_id(rpc_url),
        "nonce": _nonce(rpc_url, account.address),
        "to": recipient_address,
        "value": amount_wei,
        "gas": _NATIVE_TRANSFER_GAS_LIMIT,
        "gasPrice": _gas_price(rpc_url),
    }
    signed = Account.sign_transaction(tx, private_key)
    tx_hash = _rpc_request(
        rpc_url,
        "eth_sendRawTransaction",
        [f"0x{signed.raw_transaction.hex()}"],
    )
    receipt = _wait_for_transaction_receipt(rpc_url, str(tx_hash))
    if int(str(receipt.get("status", "0x0")), 16) != 1:
        raise SystemExit(f"Native token transfer failed: {tx_hash}")


def _ensure_buyer_wrapped_balance(config: "CanaryConfig") -> None:
    wrapped_token = _resolve_wrapped_native_token(config)
    if wrapped_token is None:
        return

    rpc_url = _require(
        config.chain_rpc_url,
        "chain-rpc-url (required when CANARY_TOKEN_SYMBOL=WETH)",
    )
    token_address, decimals = wrapped_token

    from eth_account import Account

    buyer_address = Account.from_key(config.buyer_private_key).address
    required_units = _to_base_units(
        Decimal(str(config.effective_token_amount)) * Decimal(config.duration_hours),
        decimals,
    )
    current_balance = _erc20_balance_of(rpc_url, token_address, buyer_address)
    native_balance = _native_balance_of(rpc_url, buyer_address)
    gas_price = _gas_price(rpc_url)
    escrow_gas_reserve = _escrow_gas_buffer_wei(gas_price=gas_price)

    if current_balance >= required_units:
        if native_balance >= escrow_gas_reserve:
            print(f"[funding] buyer WETH balance already sufficient: {current_balance} wei")
            return

        seller_address = Account.from_key(config.seller_private_key).address
        seller_balance = _native_balance_of(rpc_url, seller_address)
        top_up_amount = escrow_gas_reserve - native_balance
        transfer_gas_reserve = gas_price * _NATIVE_TRANSFER_GAS_LIMIT
        if seller_balance < top_up_amount + transfer_gas_reserve:
            raise SystemExit(
                "Buyer wallet lacks sufficient native ETH for escrow transactions"
            )

        print(f"[funding] transferring {top_up_amount} wei to buyer for escrow gas")
        _transfer_native_token(
            rpc_url,
            config.seller_private_key,
            buyer_address,
            top_up_amount,
        )
        _wait_for_native_balance(
            rpc_url,
            buyer_address,
            minimum_wei=escrow_gas_reserve,
        )
        print(f"[funding] buyer WETH balance already sufficient: {current_balance} wei")
        return

    deficit = required_units - current_balance
    required_native_balance = (
        deficit
        + _wrap_gas_buffer_wei(gas_price=gas_price)
        + escrow_gas_reserve
    )
    if native_balance < required_native_balance:
        seller_address = Account.from_key(config.seller_private_key).address
        seller_balance = _native_balance_of(rpc_url, seller_address)
        top_up_amount = required_native_balance - native_balance
        transfer_gas_reserve = gas_price * _NATIVE_TRANSFER_GAS_LIMIT
        if seller_balance < top_up_amount + transfer_gas_reserve:
            raise SystemExit(
                "Buyer wallet lacks sufficient WETH and native ETH for automatic wrap"
            )

        print(
            f"[funding] transferring {top_up_amount} wei to buyer for "
            "WETH wrap principal and on-chain gas reserve"
        )
        _transfer_native_token(
            rpc_url,
            config.seller_private_key,
            buyer_address,
            top_up_amount,
        )
        native_balance = _wait_for_native_balance(
            rpc_url,
            buyer_address,
            minimum_wei=required_native_balance,
        )

    if native_balance < required_native_balance:
        raise SystemExit(
            "Buyer wallet lacks sufficient WETH and native ETH for automatic wrap"
        )

    print(f"[funding] wrapping {deficit} wei into WETH for buyer")
    _wrap_native_to_wrapped_token(rpc_url, config.buyer_private_key, token_address, deficit)


@dataclass(frozen=True)
class CanaryConfig:
    registry_url: str
    provisioning_url: str
    seller_agent_url: str
    buyer_agent_url: str
    frp_dashboard_url: str | None
    frp_dashboard_password: str | None
    seller_agent_id: str
    buyer_agent_id: str
    seller_private_key: str
    buyer_private_key: str
    ssh_private_key_path: str | None
    gpu_model: str
    region: str
    token_symbol: str
    token_amount: float
    quantity: int
    sla: float
    duration_hours: int
    timeout: int
    poll_interval: int
    match_salt: int
    chain_rpc_url: str | None
    chain_name: str
    vm_hosts: tuple[str, ...] = ()

    @property
    def compute_resource(self) -> dict:
        return {
            "gpu_model": self.gpu_model,
            "quantity": self.quantity,
            "sla": self.sla,
            "region": self.region,
        }

    @property
    def effective_token_amount(self) -> float:
        base = Decimal(str(self.token_amount))
        offset = Decimal(self.match_salt % 1000) / Decimal("100000000")
        precision = _KNOWN_TOKEN_DECIMALS.get(self.token_symbol.upper(), 6)
        quantizer = Decimal(1).scaleb(-precision)
        return float((base + offset).quantize(quantizer, rounding=ROUND_DOWN))

    @property
    def token_resource(self) -> dict:
        return {
            "token": self.token_symbol,
            "amount": self.effective_token_amount,
        }


class IdentityPreflightValidator:
    def __init__(self, config: CanaryConfig) -> None:
        self.config = config

    def validate(self) -> None:
        if (
            self.config.seller_agent_id == self.config.buyer_agent_id
            or self.config.seller_private_key == self.config.buyer_private_key
            or _normalize_base_url(self.config.seller_agent_url)
            == _normalize_base_url(self.config.buyer_agent_url)
        ):
            raise SystemExit("buyer and seller actors must use distinct identities")


class CanaryGateway:
    def check_health(self, label: str, url: str) -> dict:
        return _check_health(label, url)

    def check_frp_dashboard(self, url: str, password: str) -> dict:
        return _check_frp_dashboard(url, password)

    def fetch_agent_card(self, agent_url: str) -> dict:
        return _request_json("GET", f"{_normalize_base_url(agent_url)}/.well-known/agent-card.json")

    def fetch_registration_document(self, agent_url: str) -> dict:
        return _request_json(
            "GET",
            f"{_normalize_base_url(agent_url)}/.well-known/erc-8004-registration.json",
        )

    def fetch_resource_portfolio(self, agent_url: str) -> dict:
        return _request_json("GET", f"{_normalize_base_url(agent_url)}/resources/portfolio")

    def create_order(
        self,
        *,
        agent_url: str,
        private_key: str,
        offer: dict,
        demand: dict,
        duration_hours: int,
        timeout: int,
    ) -> None:
        _create_order(
            agent_url=agent_url,
            private_key=private_key,
            offer=offer,
            demand=demand,
            duration_hours=duration_hours,
            timeout=timeout,
        )

    def fetch_agent_orders(self, registry_url: str, agent_id: str) -> list[dict]:
        return _fetch_agent_orders(registry_url, agent_id)

    def wait_for_new_order(
        self,
        *,
        registry_url: str,
        agent_id: str,
        baseline_ids: set[str],
        timeout: int,
        poll_interval: int,
    ) -> str:
        return _wait_for_new_order(
            registry_url=registry_url,
            agent_id=agent_id,
            baseline_ids=baseline_ids,
            timeout=timeout,
            poll_interval=poll_interval,
        )

    def list_jobs(self, provisioning_url: str, agent_id: str) -> list[dict]:
        return _list_jobs(provisioning_url, agent_id)

    def wait_for_new_succeeded_job(
        self,
        *,
        provisioning_url: str,
        seller_agent_id: str,
        baseline_job_ids: set[str],
        timeout: int,
        poll_interval: int,
        expected_vm_action: str = "create",
    ) -> dict:
        return _wait_for_new_succeeded_job(
            provisioning_url=provisioning_url,
            seller_agent_id=seller_agent_id,
            baseline_job_ids=baseline_job_ids,
            timeout=timeout,
            poll_interval=poll_interval,
            expected_vm_action=expected_vm_action,
        )

    def fetch_credentials(self, provisioning_url: str, job_id: str, agent_id: str) -> list[dict]:
        return _fetch_credentials(provisioning_url, job_id, agent_id)

    def submit_job(self, *, provisioning_url: str, agent_id: str, payload: dict) -> dict:
        return _submit_job(provisioning_url, agent_id, payload)

    def verify_ssh(
        self,
        credentials: list[dict],
        ssh_private_key_path: str | None,
        *,
        ready_timeout: int,
        retry_interval: int,
    ) -> None:
        _verify_ssh(
            credentials,
            ssh_private_key_path,
            ready_timeout=ready_timeout,
            retry_interval=retry_interval,
        )

    def wait_for_orders_closed(
        self,
        *,
        registry_url: str,
        order_ids: list[str],
        timeout: int,
        poll_interval: int,
        ) -> dict[str, dict]:
        return _wait_for_orders_closed(
            registry_url=registry_url,
            order_ids=order_ids,
            timeout=timeout,
            poll_interval=poll_interval,
        )

    def update_order_status(
        self,
        *,
        registry_url: str,
        order_id: str,
        status: str,
        signer_agent_id: str,
        private_key: str,
    ) -> dict:
        return _update_order_status(
            registry_url=registry_url,
            order_id=order_id,
            status=status,
            signer_agent_id=signer_agent_id,
            private_key=private_key,
        )


class NetworkProbe:
    def __init__(self, config: CanaryConfig, gateway: CanaryGateway) -> None:
        self.config = config
        self.gateway = gateway

    def _verify_registration_identity(self, label: str, agent_url: str, expected_agent_id: str) -> None:
        registration = self.gateway.fetch_registration_document(agent_url)
        registered_ids = _registration_agent_ids(registration)
        if expected_agent_id not in registered_ids:
            registered = ", ".join(sorted(registered_ids)) or "<none>"
            raise SystemExit(
                f"{label} agent registration does not include configured agent id "
                f"{expected_agent_id}; registered ids: {registered}"
            )

    def _verify_seller_inventory(self) -> None:
        portfolio = self.gateway.fetch_resource_portfolio(self.config.seller_agent_url)
        resources = portfolio.get("resources", []) if isinstance(portfolio, dict) else []
        matching_resources: list[dict] = []
        total_quantity = 0

        for resource in resources:
            if not isinstance(resource, dict):
                continue
            resource_type = resource.get("resource_type")
            if resource_type is not None and resource_type != "compute.gpu":
                continue
            if resource.get("gpu_model") != self.config.gpu_model:
                continue
            if resource.get("region") != self.config.region:
                continue
            resource_sla = resource.get("sla")
            if resource_sla is not None and float(resource_sla) < self.config.sla:
                continue
            quantity = int(resource.get("quantity", 1) or 1)
            total_quantity += quantity
            matching_resources.append(resource)

        print(
            f"[preflight] seller matching resources: count={len(matching_resources)} "
            f"quantity={total_quantity}"
        )
        if total_quantity < self.config.quantity:
            raise SystemExit(
                "seller has no available compute resource matching "
                f"gpu_model={self.config.gpu_model}, region={self.config.region}, "
                f"sla>={self.config.sla}, quantity={self.config.quantity}"
            )

    def verify(self) -> None:
        self.gateway.check_health("registry", f"{self.config.registry_url}/health")
        self.gateway.check_health("provisioning", f"{self.config.provisioning_url}/health")
        if bool(self.config.frp_dashboard_url) != bool(self.config.frp_dashboard_password):
            raise SystemExit("frp dashboard url and password must be provided together")
        if self.config.frp_dashboard_url and self.config.frp_dashboard_password:
            self.gateway.check_frp_dashboard(
                self.config.frp_dashboard_url,
                self.config.frp_dashboard_password,
            )
        self.gateway.fetch_agent_card(self.config.seller_agent_url)
        self.gateway.fetch_agent_card(self.config.buyer_agent_url)
        self._verify_registration_identity(
            "seller",
            self.config.seller_agent_url,
            self.config.seller_agent_id,
        )
        self._verify_registration_identity(
            "buyer",
            self.config.buyer_agent_url,
            self.config.buyer_agent_id,
        )
        self._verify_seller_inventory()


class ChainProbe:
    def __init__(self, config: CanaryConfig) -> None:
        self.config = config

    def verify(self) -> None:
        _ensure_buyer_wrapped_balance(self.config)


class RegistryProbe:
    def __init__(self, config: CanaryConfig, gateway: CanaryGateway) -> None:
        self.config = config
        self.gateway = gateway

    def fetch_agent_orders(self, agent_id: str) -> list[dict]:
        return self.gateway.fetch_agent_orders(self.config.registry_url, agent_id)

    def await_new_order(self, *, agent_id: str, baseline_ids: set[str]) -> str:
        return self.gateway.wait_for_new_order(
            registry_url=self.config.registry_url,
            agent_id=agent_id,
            baseline_ids=baseline_ids,
            timeout=self.config.timeout,
            poll_interval=self.config.poll_interval,
        )

    def await_orders_closed(self, *, order_ids: list[str]) -> dict[str, dict]:
        return self.gateway.wait_for_orders_closed(
            registry_url=self.config.registry_url,
            order_ids=order_ids,
            timeout=self.config.timeout,
            poll_interval=self.config.poll_interval,
        )

    def close_active_orders(self, *, agent_id: str, private_key: str) -> list[str]:
        closed_order_ids: list[str] = []
        for item in self.fetch_agent_orders(agent_id):
            order_id = item.get("order_id")
            if not order_id or item.get("status") == "closed":
                continue
            self.gateway.update_order_status(
                registry_url=self.config.registry_url,
                order_id=order_id,
                status="closed",
                signer_agent_id=agent_id,
                private_key=private_key,
            )
            closed_order_ids.append(order_id)
        return closed_order_ids


class ProvisioningProbe:
    def __init__(self, config: CanaryConfig, gateway: CanaryGateway) -> None:
        self.config = config
        self.gateway = gateway

    def capture_baseline_job_ids(self) -> set[str]:
        jobs = self.gateway.list_jobs(self.config.provisioning_url, self.config.seller_agent_id)
        return {job["job_id"] for job in jobs if job.get("job_id")}

    def verify_vm_hosts(self) -> None:
        if not self.config.vm_hosts:
            return

        baseline_job_ids = self.capture_baseline_job_ids()
        failures: list[str] = []
        for vm_host in self.config.vm_hosts:
            self.gateway.submit_job(
                provisioning_url=self.config.provisioning_url,
                agent_id=self.config.seller_agent_id,
                payload={"vm_host": vm_host, "vm_action": "check"},
            )
            job = self.gateway.wait_for_new_succeeded_job(
                provisioning_url=self.config.provisioning_url,
                seller_agent_id=self.config.seller_agent_id,
                baseline_job_ids=baseline_job_ids,
                timeout=self.config.timeout,
                poll_interval=self.config.poll_interval,
                expected_vm_action="check",
            )
            job_id = job.get("job_id")
            if job_id:
                baseline_job_ids.add(job_id)

            result = job.get("result")
            summary = _capacity_summary(result)
            total_gpus = _summary_int(summary, "total", "gpus")
            available_gpus = _summary_int(summary, "available", "gpus")
            allocated_gpus = _summary_int(summary, "allocated", "gpus")
            print(
                f"[preflight] vm host {vm_host}: total_gpus={total_gpus} "
                f"available_gpus={available_gpus} allocated_gpus={allocated_gpus}"
            )

            if total_gpus < self.config.quantity:
                failures.append(
                    f"{vm_host} does not report enough total GPUs "
                    f"(required={self.config.quantity}, total={total_gpus})"
                )
                continue
            if available_gpus < self.config.quantity:
                failures.append(
                    f"{vm_host} does not have enough available GPUs "
                    f"(required={self.config.quantity}, available={available_gpus})"
                )

        if failures:
            raise SystemExit("; ".join(failures))

    def await_succeeded_job(self, *, baseline_job_ids: set[str]) -> dict:
        return self.gateway.wait_for_new_succeeded_job(
            provisioning_url=self.config.provisioning_url,
            seller_agent_id=self.config.seller_agent_id,
            baseline_job_ids=baseline_job_ids,
            timeout=self.config.timeout,
            poll_interval=self.config.poll_interval,
            expected_vm_action="create",
        )

    def fetch_credentials(self, *, job_id: str) -> list[dict]:
        return self.gateway.fetch_credentials(
            self.config.provisioning_url,
            job_id,
            self.config.buyer_agent_id,
        )

    def verify_access(self, credentials: list[dict]) -> None:
        self.gateway.verify_ssh(
            credentials,
            self.config.ssh_private_key_path,
            ready_timeout=self.config.timeout,
            retry_interval=self.config.poll_interval,
        )


class SellerActor:
    def __init__(
        self,
        config: CanaryConfig,
        registry_probe: RegistryProbe,
        gateway: CanaryGateway,
    ) -> None:
        self.config = config
        self.registry_probe = registry_probe
        self.gateway = gateway
        self._baseline_ids: set[str] = set()

    def cleanup_open_orders(self) -> list[str]:
        order_ids = self.registry_probe.close_active_orders(
            agent_id=self.config.seller_agent_id,
            private_key=self.config.seller_private_key,
        )
        if order_ids:
            print(f"[cleanup] closed seller open orders: {', '.join(order_ids)}")
        return order_ids

    def capture_baseline_order_ids(self) -> set[str]:
        self._baseline_ids = {
            item["order_id"] for item in self.registry_probe.fetch_agent_orders(self.config.seller_agent_id)
        }
        return set(self._baseline_ids)

    def create_canary_order(self) -> str:
        print("[order] creating seller canary order")
        self.gateway.create_order(
            agent_url=self.config.seller_agent_url,
            private_key=self.config.seller_private_key,
            offer=self.config.compute_resource,
            demand=self.config.token_resource,
            duration_hours=self.config.duration_hours,
            timeout=self.config.timeout,
        )
        order_id = self.registry_probe.await_new_order(
            agent_id=self.config.seller_agent_id,
            baseline_ids=self._baseline_ids,
        )
        print(f"[order] seller order: {order_id}")
        return order_id


class BuyerActor:
    def __init__(
        self,
        config: CanaryConfig,
        registry_probe: RegistryProbe,
        gateway: CanaryGateway,
    ) -> None:
        self.config = config
        self.registry_probe = registry_probe
        self.gateway = gateway
        self._baseline_ids: set[str] = set()

    def cleanup_open_orders(self) -> list[str]:
        order_ids = self.registry_probe.close_active_orders(
            agent_id=self.config.buyer_agent_id,
            private_key=self.config.buyer_private_key,
        )
        if order_ids:
            print(f"[cleanup] closed buyer open orders: {', '.join(order_ids)}")
        return order_ids

    def capture_baseline_order_ids(self) -> set[str]:
        self._baseline_ids = {
            item["order_id"] for item in self.registry_probe.fetch_agent_orders(self.config.buyer_agent_id)
        }
        return set(self._baseline_ids)

    def create_canary_order(self) -> str:
        print("[order] creating buyer canary order")
        self.gateway.create_order(
            agent_url=self.config.buyer_agent_url,
            private_key=self.config.buyer_private_key,
            offer=self.config.token_resource,
            demand=self.config.compute_resource,
            duration_hours=self.config.duration_hours,
            timeout=self.config.timeout,
        )
        order_id = self.registry_probe.await_new_order(
            agent_id=self.config.buyer_agent_id,
            baseline_ids=self._baseline_ids,
        )
        print(f"[order] buyer order: {order_id}")
        return order_id


class CanaryCoordinator:
    def __init__(
        self,
        *,
        validator: IdentityPreflightValidator,
        network_probe: NetworkProbe,
        chain_probe: ChainProbe,
        seller: SellerActor,
        buyer: BuyerActor,
        provisioning_probe: ProvisioningProbe,
        registry_probe: RegistryProbe,
    ) -> None:
        self.validator = validator
        self.network_probe = network_probe
        self.chain_probe = chain_probe
        self.seller = seller
        self.buyer = buyer
        self.provisioning_probe = provisioning_probe
        self.registry_probe = registry_probe

    def run(self) -> dict[str, object]:
        self.validator.validate()
        self.network_probe.verify()
        self.chain_probe.verify()
        seller_preexisting_closed = self.seller.cleanup_open_orders()
        buyer_preexisting_closed = self.buyer.cleanup_open_orders()
        seller_config = getattr(self.seller, "config", None)
        if seller_config is not None:
            print(
                f"[match] using token amount {seller_config.effective_token_amount} "
                f"(base={seller_config.token_amount}, salt={seller_config.match_salt})"
            )
        self.seller.capture_baseline_order_ids()
        self.buyer.capture_baseline_order_ids()
        self.provisioning_probe.verify_vm_hosts()
        baseline_job_ids = self.provisioning_probe.capture_baseline_job_ids()

        seller_order_id = self.seller.create_canary_order()
        buyer_order_id = self.buyer.create_canary_order()

        job = self.provisioning_probe.await_succeeded_job(
            baseline_job_ids=baseline_job_ids,
        )
        print(f"[provisioning] succeeded job: {job['job_id']}")

        credentials = self.provisioning_probe.fetch_credentials(job_id=job["job_id"])
        tenant_credentials = [cred for cred in credentials if cred.get("role") == "tenant"]
        if not tenant_credentials:
            raise SystemExit("No tenant credentials returned for buyer agent")
        self.provisioning_probe.verify_access(credentials)

        seller_post_provision_closed = self.seller.cleanup_open_orders()
        buyer_post_provision_closed = self.buyer.cleanup_open_orders()
        final_order_ids = list(
            dict.fromkeys(
                [
                    seller_order_id,
                    buyer_order_id,
                    *seller_post_provision_closed,
                    *buyer_post_provision_closed,
                ]
            )
        )
        orders = self.registry_probe.await_orders_closed(
            order_ids=final_order_ids,
        )
        job_params = job.get("params") if isinstance(job.get("params"), dict) else {}
        job_result = job.get("result") if isinstance(job.get("result"), dict) else {}
        return {
            "status": "succeeded",
            "seller_order_id": seller_order_id,
            "buyer_order_id": buyer_order_id,
            "provisioning_job_id": job.get("job_id"),
            "vm_host": job_result.get("vm_host") or job_params.get("vm_host"),
            "vm_target": job_result.get("vm_target") or job_params.get("vm_target"),
            "cleanup": {
                "preexisting_closed_order_ids": {
                    "seller": seller_preexisting_closed,
                    "buyer": buyer_preexisting_closed,
                },
                "post_provisioning_closed_order_ids": {
                    "seller": seller_post_provision_closed,
                    "buyer": buyer_post_provision_closed,
                },
                "final_order_ids": final_order_ids,
            },
            "job": job,
            "orders": orders,
        }


def build_coordinator(config: CanaryConfig) -> CanaryCoordinator:
    gateway = CanaryGateway()
    registry_probe = RegistryProbe(config, gateway)
    provisioning_probe = ProvisioningProbe(config, gateway)
    return CanaryCoordinator(
        validator=IdentityPreflightValidator(config),
        network_probe=NetworkProbe(config, gateway),
        chain_probe=ChainProbe(config),
        seller=SellerActor(config, registry_probe, gateway),
        buyer=BuyerActor(config, registry_probe, gateway),
        provisioning_probe=provisioning_probe,
        registry_probe=registry_probe,
    )


def _parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Production canary smoke test for the deployed full stack.")
    parser.add_argument("--registry-url", default=_env("REGISTRY_URL"))
    parser.add_argument("--provisioning-url", default=_env("PROVISIONING_SERVICE_URL"))
    parser.add_argument("--seller-agent-url", default=_env("SELLER_AGENT_URL"))
    parser.add_argument("--buyer-agent-url", default=_env("BUYER_AGENT_URL"))
    parser.add_argument("--frp-dashboard-url", default=_env("FRP_DASHBOARD_URL"))
    parser.add_argument("--frp-dashboard-password", default=_env("FRP_DASHBOARD_PASSWORD"))
    parser.add_argument("--seller-agent-id", default=_env("SELLER_AGENT_ID"))
    parser.add_argument("--buyer-agent-id", default=_env("BUYER_AGENT_ID"))
    parser.add_argument("--seller-private-key", default=_env("SELLER_PRIVATE_KEY"))
    parser.add_argument("--buyer-private-key", default=_env("BUYER_PRIVATE_KEY"))
    parser.add_argument("--ssh-private-key-path", default=_env("SSH_PRIVATE_KEY_PATH"))
    parser.add_argument("--gpu-model", default=_env("CANARY_GPU_MODEL", "H200"))
    parser.add_argument("--region", default=_env("CANARY_REGION", "California, US"))
    parser.add_argument("--token-symbol", default=_env("CANARY_TOKEN_SYMBOL", "USDC"))
    parser.add_argument("--token-amount", type=float, default=float(_env("CANARY_TOKEN_AMOUNT", "1.0")))
    parser.add_argument("--quantity", type=int, default=int(_env("CANARY_GPU_QUANTITY", "1")))
    parser.add_argument("--sla", type=float, default=float(_env("CANARY_SLA", "90.0")))
    parser.add_argument("--duration-hours", type=int, default=int(_env("CANARY_DURATION_HOURS", "1")))
    parser.add_argument("--timeout", type=int, default=int(_env("CANARY_TIMEOUT_SECONDS", "600")))
    parser.add_argument("--poll-interval", type=int, default=int(_env("CANARY_POLL_INTERVAL", "5")))
    parser.add_argument("--match-salt", type=int, default=int(_env("CANARY_MATCH_SALT", str(int(time.time())))))
    parser.add_argument("--chain-rpc-url", default=_env("CHAIN_RPC_URL"))
    parser.add_argument("--chain-name", default=_env("CHAIN_NAME", "base_sepolia"))
    parser.add_argument("--vm-host", action="append", default=None, help="Candidate provisioning host to preflight before order creation. Repeat for multiple hosts.")
    return parser.parse_args(list(argv) if argv is not None else None)


def _build_config(args: argparse.Namespace) -> CanaryConfig:
    env_vm_hosts = tuple(
        item.strip() for item in (_env("CANARY_VM_HOSTS", "") or "").split(",") if item.strip()
    )
    cli_vm_hosts = tuple(item.strip() for item in (args.vm_host or []) if item.strip())
    return CanaryConfig(
        registry_url=_normalize_base_url(_require(args.registry_url, "registry-url")),
        provisioning_url=_normalize_base_url(_require(args.provisioning_url, "provisioning-url")),
        seller_agent_url=_normalize_base_url(_require(args.seller_agent_url, "seller-agent-url")),
        buyer_agent_url=_normalize_base_url(_require(args.buyer_agent_url, "buyer-agent-url")),
        frp_dashboard_url=(
            _normalize_base_url(args.frp_dashboard_url)
            if args.frp_dashboard_url
            else None
        ),
        frp_dashboard_password=args.frp_dashboard_password,
        seller_agent_id=_require(args.seller_agent_id, "seller-agent-id"),
        buyer_agent_id=_require(args.buyer_agent_id, "buyer-agent-id"),
        seller_private_key=_require(args.seller_private_key, "seller-private-key"),
        buyer_private_key=_require(args.buyer_private_key, "buyer-private-key"),
        ssh_private_key_path=args.ssh_private_key_path,
        gpu_model=args.gpu_model,
        region=args.region,
        token_symbol=args.token_symbol,
        token_amount=args.token_amount,
        quantity=args.quantity,
        sla=args.sla,
        duration_hours=args.duration_hours,
        timeout=args.timeout,
        poll_interval=args.poll_interval,
        match_salt=args.match_salt,
        chain_rpc_url=args.chain_rpc_url,
        chain_name=args.chain_name,
        vm_hosts=cli_vm_hosts or env_vm_hosts,
    )


def main(argv: Iterable[str] | None = None) -> int:
    args = _parse_args(argv)
    config = _build_config(args)
    result = build_coordinator(config).run()
    print("[success] canary completed")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0
