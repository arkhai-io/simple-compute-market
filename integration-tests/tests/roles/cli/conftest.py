"""Fixtures for `market buy` / `market <future>` CLI integration tests.

These tests invoke the user-facing CLI as a subprocess against a running
compose stack. They share the layer fixtures (external_world, market_registry,
buyer_node, seller_node) but do NOT share the progressive stage fixtures
(`initiated_deal`, `negotiation_output`, …) — those stage tests and these CLI
tests both consume the seller's one-resource inventory, so they are designed
to run in separate sessions.
"""

from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path

import pytest

from tests.helpers.agent_client import query_registry_orders
from tests.helpers.cli_client import cli_create_order
from tests.helpers.polling import poll_until

log = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[4]
_CLI_DIR = _REPO_ROOT / "cli"


# Canonical spec — must match seller's preloaded inventory (ww1-machine.csv).
COMPUTE = {"gpu_model": "RTX 5080", "quantity": 1, "sla": 90.0, "region": "California, US"}
PAYMENT = {"token": "MOCK", "amount": 100}


def run_market_buy(
    *,
    buyer_node: dict,
    compute: dict = COMPUTE,
    max_price: str = str(PAYMENT["amount"]),
    token: str = "MOCK",
    duration_hours: int = 1,
    timeout_budget: int = 180,
    poll_interval: float = 2.0,
    subprocess_grace_s: float = 30,
) -> subprocess.CompletedProcess:
    """Invoke `market buy` as a subprocess. Returns the CompletedProcess.

    `timeout_budget` is the `--timeout` passed to the CLI itself; the
    subprocess timeout is that plus a small grace period.
    """
    cmd = [
        "uv", "run", "market", "buy",
        "-a", buyer_node["agent_url"],
        "-e", buyer_node["agent_env_file"],
        "--db", buyer_node["agent_db_path"],
        "--gpu", compute["gpu_model"],
        "--quantity", str(compute["quantity"]),
        "--sla", str(compute["sla"]),
        "--region", compute["region"],
        "--max-price", max_price,
        "--token", token,
        "--duration-hours", str(duration_hours),
        "--timeout", str(timeout_budget),
        "--poll-interval", str(poll_interval),
        "--show-password",
    ]
    log.info("CLI: %s", " ".join(cmd))
    return subprocess.run(
        cmd,
        cwd=str(_CLI_DIR),
        capture_output=True,
        text=True,
        timeout=timeout_budget + subprocess_grace_s,
        env={**os.environ, "NO_COLOR": "1"},
    )


@pytest.fixture(scope="session")
def market_buy_happy_result(seller_node: dict, buyer_node: dict, seller_publishes_for_cli: dict) -> subprocess.CompletedProcess:
    """Run `market buy` ONCE per test session and share the result across tests.

    The seller has exactly one resource; running the CLI multiple times in
    one session would starve later tests. All happy-path assertions read from
    this single CompletedProcess.
    """
    return run_market_buy(
        buyer_node=buyer_node,
        compute=COMPUTE,
        max_price=str(PAYMENT["amount"]),
        timeout_budget=180,
    )


@pytest.fixture(scope="session")
def seller_publishes_for_cli(seller_node: dict) -> dict:
    """Publish a seller order for the CLI test module.

    Scoped per-module so at most one seller order is published per test run.
    """
    resp = cli_create_order(
        agent_url=seller_node["agent_url"],
        env_file=seller_node["agent_env_file"],
        offer=COMPUTE,
        demand=PAYMENT,
    )
    assert resp["status"] == "created", f"Seller publish failed: {resp}"
    order_id = resp["order_id"]
    log.info("Seller published order %s for CLI tests", order_id)

    # Confirm *this* order has reached the registry's open index (stale
    # orders from prior runs may already satisfy a min_count=1 poll).
    def _this_order_visible():
        data = query_registry_orders(seller_node["market"]["url"], status="open")
        for item in data.get("items", []):
            if item["order_id"] == order_id:
                return item
        return None

    return poll_until(
        _this_order_visible, timeout_s=30, interval_s=2,
        description=f"seller order {order_id} indexed",
    )
