from __future__ import annotations

import argparse
import json
import re
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path

from market.canary import (
    _env,
    _fetch_order,
    _normalize_base_url,
    _request_json,
    _require,
    _update_order_status,
)


_SELLER_ORDER_PATTERN = re.compile(r"^\[order\] seller order:\s+(?P<value>\S+)", re.MULTILINE)
_BUYER_ORDER_PATTERN = re.compile(r"^\[order\] buyer order:\s+(?P<value>\S+)", re.MULTILINE)
_JOB_PATTERN = re.compile(r"^\[provisioning\] succeeded job:\s+(?P<value>\S+)", re.MULTILINE)


@dataclass(frozen=True)
class RollbackState:
    seller_order_id: str | None = None
    buyer_order_id: str | None = None
    provisioning_job_id: str | None = None
    vm_host: str | None = None
    vm_target: str | None = None


@dataclass(frozen=True)
class RollbackConfig:
    registry_url: str
    provisioning_url: str
    seller_agent_id: str
    buyer_agent_id: str
    seller_private_key: str | None
    buyer_private_key: str | None
    log_path: Path | None = None
    seller_order_id: str | None = None
    buyer_order_id: str | None = None
    provisioning_job_id: str | None = None


def _extract_value(pattern: re.Pattern[str], text: str) -> str | None:
    match = pattern.search(text)
    if match is None:
        return None
    return match.group("value")


def _extract_json_result(text: str) -> dict[str, object]:
    marker = "[success] canary completed"
    if marker not in text:
        return {}
    payload = text.split(marker, 1)[1].strip()
    if not payload:
        return {}
    try:
        value = json.loads(payload)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _extract_state_from_log(text: str) -> RollbackState:
    result = _extract_json_result(text)
    return RollbackState(
        seller_order_id=_extract_value(_SELLER_ORDER_PATTERN, text) or _as_optional_str(result.get("seller_order_id")),
        buyer_order_id=_extract_value(_BUYER_ORDER_PATTERN, text) or _as_optional_str(result.get("buyer_order_id")),
        provisioning_job_id=_extract_value(_JOB_PATTERN, text) or _as_optional_str(result.get("provisioning_job_id")),
        vm_host=_as_optional_str(result.get("vm_host")),
        vm_target=_as_optional_str(result.get("vm_target")),
    )


def _as_optional_str(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _job_vm_host(job: dict[str, object]) -> str | None:
    result = job.get("result")
    params = job.get("params")
    if isinstance(result, dict):
        vm_host = _as_optional_str(result.get("vm_host"))
        if vm_host:
            return vm_host
    if isinstance(params, dict):
        return _as_optional_str(params.get("vm_host"))
    return None


def _job_vm_target(job: dict[str, object]) -> str | None:
    result = job.get("result")
    params = job.get("params")
    if isinstance(result, dict):
        for key in ("vm_name", "vm_target"):
            value = _as_optional_str(result.get(key))
            if value:
                return value
    if isinstance(params, dict):
        return _as_optional_str(params.get("vm_target"))
    return None


class CanaryRollbackGateway:
    def fetch_job(self, provisioning_url: str, job_id: str, agent_id: str) -> dict:
        return _request_json(
            "GET",
            f"{_normalize_base_url(provisioning_url)}/api/v1/jobs/{job_id}",
            headers={"X-Agent-ID": agent_id},
            timeout=60.0,
        )

    def cancel_job(self, provisioning_url: str, job_id: str, agent_id: str) -> dict:
        return _request_json(
            "POST",
            f"{_normalize_base_url(provisioning_url)}/api/v1/jobs/{job_id}/cancel",
            headers={"X-Agent-ID": agent_id},
            timeout=60.0,
        )

    def submit_job(self, *, provisioning_url: str, agent_id: str, payload: dict) -> dict:
        return _request_json(
            "POST",
            f"{_normalize_base_url(provisioning_url)}/api/v1/jobs",
            payload=payload,
            headers={"X-Agent-ID": agent_id},
            timeout=60.0,
        )

    def fetch_order(self, registry_url: str, order_id: str) -> dict:
        return _fetch_order(registry_url, order_id)

    def close_order(
        self,
        *,
        registry_url: str,
        order_id: str,
        signer_agent_id: str,
        private_key: str,
    ) -> dict:
        return _update_order_status(
            registry_url=registry_url,
            order_id=order_id,
            status="closed",
            signer_agent_id=signer_agent_id,
            private_key=private_key,
        )


class RollbackCoordinator:
    def __init__(
        self,
        *,
        config: RollbackConfig,
        gateway: CanaryRollbackGateway,
    ) -> None:
        self.config = config
        self.gateway = gateway

    def _load_state(self) -> RollbackState:
        parsed = RollbackState()
        if self.config.log_path is not None:
            parsed = _extract_state_from_log(self.config.log_path.read_text(encoding="utf-8"))
        state = RollbackState(
            seller_order_id=self.config.seller_order_id or parsed.seller_order_id,
            buyer_order_id=self.config.buyer_order_id or parsed.buyer_order_id,
            provisioning_job_id=self.config.provisioning_job_id or parsed.provisioning_job_id,
            vm_host=parsed.vm_host,
            vm_target=parsed.vm_target,
        )
        if not any(asdict(state).values()):
            raise SystemExit("No canary rollback state could be extracted from the provided inputs")
        return state

    def _close_order(
        self,
        *,
        order_id: str | None,
        signer_agent_id: str,
        private_key: str | None,
    ) -> dict[str, object] | None:
        if not order_id:
            return None
        order = self.gateway.fetch_order(self.config.registry_url, order_id)
        status_before = str(order.get("status") or "")
        summary = {
            "order_id": order_id,
            "status_before": status_before,
            "closed": False,
        }
        if status_before == "closed":
            return summary
        if not private_key:
            raise SystemExit(f"Missing private key required to close order {order_id}")
        self.gateway.close_order(
            registry_url=self.config.registry_url,
            order_id=order_id,
            signer_agent_id=signer_agent_id,
            private_key=private_key,
        )
        summary["closed"] = True
        return summary

    def run(self) -> dict[str, object]:
        state = self._load_state()
        job_payload: dict[str, object] | None = None
        cancel_result: dict[str, object] | None = None
        reclaim_actions: list[dict[str, object]] = []
        initial_status: str | None = None

        if state.provisioning_job_id:
            job_payload = self.gateway.fetch_job(
                self.config.provisioning_url,
                state.provisioning_job_id,
                self.config.seller_agent_id,
            )
            initial_status = _as_optional_str(job_payload.get("status"))
            state = RollbackState(
                seller_order_id=state.seller_order_id,
                buyer_order_id=state.buyer_order_id,
                provisioning_job_id=state.provisioning_job_id,
                vm_host=state.vm_host or _job_vm_host(job_payload),
                vm_target=state.vm_target or _job_vm_target(job_payload),
            )
            reclaim_required = initial_status not in {"queued", "running"}
            if initial_status in {"queued", "running"}:
                cancel_result = self.gateway.cancel_job(
                    self.config.provisioning_url,
                    state.provisioning_job_id,
                    self.config.seller_agent_id,
                )
                reclaim_required = _as_optional_str(cancel_result.get("status")) != "cancelled"
            if reclaim_required and state.vm_host and state.vm_target:
                for vm_action in ("destroy", "undefine"):
                    reclaim_actions.append(
                        self.gateway.submit_job(
                            provisioning_url=self.config.provisioning_url,
                            agent_id=self.config.seller_agent_id,
                            payload={
                                "vm_host": state.vm_host,
                                "vm_target": state.vm_target,
                                "vm_action": vm_action,
                            },
                        )
                    )

        seller_summary = self._close_order(
            order_id=state.seller_order_id,
            signer_agent_id=self.config.seller_agent_id,
            private_key=self.config.seller_private_key,
        )
        buyer_summary = self._close_order(
            order_id=state.buyer_order_id,
            signer_agent_id=self.config.buyer_agent_id,
            private_key=self.config.buyer_private_key,
        )

        return {
            "status": "completed",
            "state": asdict(state),
            "provisioning": {
                "initial_status": initial_status,
                "cancel_result": cancel_result,
                "reclaim_actions": reclaim_actions,
            },
            "orders": {
                "seller": seller_summary,
                "buyer": buyer_summary,
            },
        }


def _parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Rollback a production canary run using captured IDs or a canary log.")
    parser.add_argument("--log-path", type=Path)
    parser.add_argument("--registry-url", default=_env("REGISTRY_URL"))
    parser.add_argument("--provisioning-url", default=_env("PROVISIONING_SERVICE_URL"))
    parser.add_argument("--seller-agent-id", default=_env("SELLER_AGENT_ID"))
    parser.add_argument("--buyer-agent-id", default=_env("BUYER_AGENT_ID"))
    parser.add_argument("--seller-private-key", default=_env("SELLER_PRIVATE_KEY"))
    parser.add_argument("--buyer-private-key", default=_env("BUYER_PRIVATE_KEY"))
    parser.add_argument("--seller-order-id")
    parser.add_argument("--buyer-order-id")
    parser.add_argument("--provisioning-job-id")
    return parser.parse_args(list(argv) if argv is not None else None)


def _build_config(args: argparse.Namespace) -> RollbackConfig:
    if not args.log_path and not any([args.seller_order_id, args.buyer_order_id, args.provisioning_job_id]):
        raise SystemExit(
            "Provide --log-path or at least one explicit emitted id "
            "(--seller-order-id, --buyer-order-id, or --provisioning-job-id)"
        )
    return RollbackConfig(
        registry_url=_normalize_base_url(_require(args.registry_url, "registry-url")),
        provisioning_url=_normalize_base_url(_require(args.provisioning_url, "provisioning-url")),
        seller_agent_id=_require(args.seller_agent_id, "seller-agent-id"),
        buyer_agent_id=_require(args.buyer_agent_id, "buyer-agent-id"),
        seller_private_key=args.seller_private_key,
        buyer_private_key=args.buyer_private_key,
        log_path=args.log_path,
        seller_order_id=args.seller_order_id,
        buyer_order_id=args.buyer_order_id,
        provisioning_job_id=args.provisioning_job_id,
    )


def main(argv: Iterable[str] | None = None) -> int:
    config = _build_config(_parse_args(argv))
    result = RollbackCoordinator(config=config, gateway=CanaryRollbackGateway()).run()
    print("[success] canary rollback completed")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
