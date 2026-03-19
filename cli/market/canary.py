from __future__ import annotations

import argparse
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


def _env(name: str, default: str | None = None) -> str | None:
    return os.getenv(name, default)


def _require(value: str | None, label: str) -> str:
    if value:
        return value
    raise SystemExit(f"Missing required value for {label}")


def _normalize_base_url(raw_url: str) -> str:
    return raw_url.rstrip("/")


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
    return {
        "X-Signature": signature,
        "X-Timestamp": str(timestamp),
    }


def _check_health(label: str, url: str) -> dict:
    print(f"[health] {label}: {url}")
    return _request_json("GET", url)


def _create_order(
    *,
    agent_url: str,
    private_key: str,
    offer: dict,
    demand: dict,
    duration_hours: int,
) -> None:
    url = f"{_normalize_base_url(agent_url)}/orders/create"
    headers = _sign_headers("create_order", _normalize_base_url(agent_url), private_key)
    payload = {
        "offer": offer,
        "demand": demand,
        "duration_hours": duration_hours,
    }
    response = _request_json("POST", url, payload=payload, headers=headers, timeout=120.0)
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


def _wait_for_new_succeeded_job(
    *,
    provisioning_url: str,
    seller_agent_id: str,
    baseline_job_ids: set[str],
    timeout: int,
    poll_interval: int,
) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        jobs = _list_jobs(provisioning_url, seller_agent_id)
        for job in jobs:
            job_id = job.get("job_id")
            if not job_id or job_id in baseline_job_ids:
                continue
            if job.get("status") == "succeeded":
                return job
        time.sleep(poll_interval)
    raise SystemExit("Timed out waiting for a new succeeded provisioning job")


def _fetch_credentials(provisioning_url: str, job_id: str, agent_id: str) -> list[dict]:
    response = _request_json(
        "GET",
        f"{_normalize_base_url(provisioning_url)}/api/v1/jobs/{job_id}/credentials",
        headers={"X-Agent-ID": agent_id},
    )
    return response.get("credentials", [])


def _verify_ssh(credentials: list[dict], ssh_private_key_path: str | None) -> None:
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
    subprocess.run(parts, check=True)


@dataclass(frozen=True)
class CanaryConfig:
    registry_url: str
    provisioning_url: str
    seller_agent_url: str
    buyer_agent_url: str
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

    @property
    def compute_resource(self) -> dict:
        return {
            "gpu_model": self.gpu_model,
            "quantity": self.quantity,
            "sla": self.sla,
            "region": self.region,
        }

    @property
    def token_resource(self) -> dict:
        return {
            "token": self.token_symbol,
            "amount": self.token_amount,
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

    def fetch_agent_card(self, agent_url: str) -> dict:
        return _request_json("GET", f"{_normalize_base_url(agent_url)}/.well-known/agent-card.json")

    def create_order(
        self,
        *,
        agent_url: str,
        private_key: str,
        offer: dict,
        demand: dict,
        duration_hours: int,
    ) -> None:
        _create_order(
            agent_url=agent_url,
            private_key=private_key,
            offer=offer,
            demand=demand,
            duration_hours=duration_hours,
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
    ) -> dict:
        return _wait_for_new_succeeded_job(
            provisioning_url=provisioning_url,
            seller_agent_id=seller_agent_id,
            baseline_job_ids=baseline_job_ids,
            timeout=timeout,
            poll_interval=poll_interval,
        )

    def fetch_credentials(self, provisioning_url: str, job_id: str, agent_id: str) -> list[dict]:
        return _fetch_credentials(provisioning_url, job_id, agent_id)

    def verify_ssh(self, credentials: list[dict], ssh_private_key_path: str | None) -> None:
        _verify_ssh(credentials, ssh_private_key_path)

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


class NetworkProbe:
    def __init__(self, config: CanaryConfig, gateway: CanaryGateway) -> None:
        self.config = config
        self.gateway = gateway

    def verify(self) -> None:
        self.gateway.check_health("registry", f"{self.config.registry_url}/health")
        self.gateway.check_health("provisioning", f"{self.config.provisioning_url}/health")
        self.gateway.fetch_agent_card(self.config.seller_agent_url)
        self.gateway.fetch_agent_card(self.config.buyer_agent_url)


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


class ProvisioningProbe:
    def __init__(self, config: CanaryConfig, gateway: CanaryGateway) -> None:
        self.config = config
        self.gateway = gateway

    def capture_baseline_job_ids(self) -> set[str]:
        jobs = self.gateway.list_jobs(self.config.provisioning_url, self.config.seller_agent_id)
        return {job["job_id"] for job in jobs if job.get("job_id")}

    def await_succeeded_job(self, *, baseline_job_ids: set[str]) -> dict:
        return self.gateway.wait_for_new_succeeded_job(
            provisioning_url=self.config.provisioning_url,
            seller_agent_id=self.config.seller_agent_id,
            baseline_job_ids=baseline_job_ids,
            timeout=self.config.timeout,
            poll_interval=self.config.poll_interval,
        )

    def fetch_credentials(self, *, job_id: str) -> list[dict]:
        return self.gateway.fetch_credentials(
            self.config.provisioning_url,
            job_id,
            self.config.buyer_agent_id,
        )

    def verify_access(self, credentials: list[dict]) -> None:
        self.gateway.verify_ssh(credentials, self.config.ssh_private_key_path)


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
        seller: SellerActor,
        buyer: BuyerActor,
        provisioning_probe: ProvisioningProbe,
        registry_probe: RegistryProbe,
    ) -> None:
        self.validator = validator
        self.network_probe = network_probe
        self.seller = seller
        self.buyer = buyer
        self.provisioning_probe = provisioning_probe
        self.registry_probe = registry_probe

    def run(self) -> dict[str, dict]:
        self.validator.validate()
        self.network_probe.verify()
        self.seller.capture_baseline_order_ids()
        self.buyer.capture_baseline_order_ids()
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

        orders = self.registry_probe.await_orders_closed(
            order_ids=[seller_order_id, buyer_order_id],
        )
        return {"job": job, "orders": orders}


def build_coordinator(config: CanaryConfig) -> CanaryCoordinator:
    gateway = CanaryGateway()
    registry_probe = RegistryProbe(config, gateway)
    provisioning_probe = ProvisioningProbe(config, gateway)
    return CanaryCoordinator(
        validator=IdentityPreflightValidator(config),
        network_probe=NetworkProbe(config, gateway),
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
    return parser.parse_args(list(argv) if argv is not None else None)


def _build_config(args: argparse.Namespace) -> CanaryConfig:
    return CanaryConfig(
        registry_url=_normalize_base_url(_require(args.registry_url, "registry-url")),
        provisioning_url=_normalize_base_url(_require(args.provisioning_url, "provisioning-url")),
        seller_agent_url=_normalize_base_url(_require(args.seller_agent_url, "seller-agent-url")),
        buyer_agent_url=_normalize_base_url(_require(args.buyer_agent_url, "buyer-agent-url")),
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
    )


def main(argv: Iterable[str] | None = None) -> int:
    args = _parse_args(argv)
    config = _build_config(args)
    result = build_coordinator(config).run()
    print("[success] canary completed")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0
