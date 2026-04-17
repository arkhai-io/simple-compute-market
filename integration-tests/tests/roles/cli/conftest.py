"""Fixtures for `market buy` / `market provide` CLI integration tests.

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
from typing import Optional

import pytest

from tests.helpers.agent_client import query_registry_orders
from tests.helpers.cli_client import cli_create_order
from tests.helpers.polling import poll_until

log = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[4]
_CLI_DIR = _REPO_ROOT / "cli"


def ro_query(db_path: str, sql: str, params: tuple = ()) -> list[tuple]:
    """Read-only SQLite query that tolerates Podman's 9p write-through quirks.

    Opens the DB read-only (mode=ro&nolock=1) and retries on OperationalError
    — the agent writes concurrently, and the shared-volume layer can briefly
    return 'attempt to write a readonly database' even without any actual
    write from this side. 5 retries at 0.2s is enough in practice.
    """
    import sqlite3
    import time as _time

    last: Exception | None = None
    for _ in range(5):
        try:
            conn = sqlite3.connect(
                f"file:{db_path}?mode=ro&nolock=1", uri=True, timeout=5,
            )
            try:
                return conn.execute(sql, params).fetchall()
            finally:
                conn.close()
        except sqlite3.OperationalError as exc:
            last = exc
            _time.sleep(0.2)
    assert last is not None
    raise last


# Canonical spec — must match seller's preloaded inventory (ww1-machine.csv).
COMPUTE = {"gpu_model": "RTX 5080", "quantity": 1, "sla": 90.0, "region": "California, US"}
PAYMENT = {"token": "MOCK", "amount": 100}


def run_market_buy_abort(
    *,
    buyer_node: dict,
    abort: str,
    extra_args: Optional[list[str]] = None,
    timeout_s: float = 30,
) -> subprocess.CompletedProcess:
    """Invoke `market buy --abort <id>` and return the CompletedProcess."""
    cmd = [
        "uv", "run", "market", "buy",
        "-a", buyer_node["agent_url"],
        "-e", buyer_node["agent_env_file"],
        "--db", buyer_node["agent_db_path"],
        "--abort", abort,
    ]
    if extra_args:
        cmd.extend(extra_args)
    log.info("CLI: %s", " ".join(cmd))
    return subprocess.run(
        cmd,
        cwd=str(_CLI_DIR),
        capture_output=True,
        text=True,
        timeout=timeout_s,
        env={**os.environ, "NO_COLOR": "1"},
    )


def run_market_buy_recover(
    *,
    buyer_node: dict,
    recover: str,
    timeout_budget: int = 20,
    poll_interval: float = 1.0,
    extra_args: Optional[list[str]] = None,
    subprocess_grace_s: float = 30,
) -> subprocess.CompletedProcess:
    """Invoke `market buy --recover <id>` and return the CompletedProcess."""
    cmd = [
        "uv", "run", "market", "buy",
        "-a", buyer_node["agent_url"],
        "-e", buyer_node["agent_env_file"],
        "--db", buyer_node["agent_db_path"],
        "--recover", recover,
        "--timeout", str(timeout_budget),
        "--poll-interval", str(poll_interval),
        "--show-password",
    ]
    if extra_args:
        cmd.extend(extra_args)
    log.info("CLI: %s", " ".join(cmd))
    return subprocess.run(
        cmd,
        cwd=str(_CLI_DIR),
        capture_output=True,
        text=True,
        timeout=timeout_budget + subprocess_grace_s,
        env={**os.environ, "NO_COLOR": "1"},
    )


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


# ---------------------------------------------------------------------------
# `market provide` helpers
# ---------------------------------------------------------------------------


# Unique resource IDs used ONLY in the provide test — keeps these rows
# distinct from any real inventory so assertions can filter precisely.
PROVIDE_TEST_RESOURCES = [
    {
        "resource_id": "test-provide-ny-4090-001",
        "gpu_model": "RTX 4090",
        "sla": 95.0,
        "region": "New York, US",
        "vm_host": "test-ny",
    },
    {
        "resource_id": "test-provide-ny-4090-002",
        "gpu_model": "RTX 4090",
        "sla": 95.0,
        "region": "New York, US",
        "vm_host": "test-ny",
    },
]


def write_provide_test_csv(path: Path) -> Path:
    """Emit a CSV with the test resources above, matching the import schema."""
    header = (
        "resource_id,resource_type,resource_subtype,unit,value,state,"
        "attribute.gpu_model,attribute.sla,attribute.region,attribute.vm_host\n"
    )
    rows = [
        f"{r['resource_id']},compute.gpu,rtx4090,count,1,available,"
        f"{r['gpu_model']},{r['sla']},\"{r['region']}\",{r['vm_host']}\n"
        for r in PROVIDE_TEST_RESOURCES
    ]
    path.write_text(header + "".join(rows))
    return path


def run_market_provide(
    *,
    seller_node: dict,
    inventory: Optional[Path] = None,
    min_price: str = "150",
    token: str = "MOCK",
    duration_hours: int = 1,
    timeout_s: float = 120,
) -> subprocess.CompletedProcess:
    """Invoke `market provide` as a subprocess."""
    cmd = [
        "uv", "run", "market", "provide",
        "-a", seller_node["agent_url"],
        "-e", seller_node["agent_env_file"],
        "--db", seller_node["agent_db_path"],
        "--min-price", min_price,
        "--token", token,
        "--duration-hours", str(duration_hours),
    ]
    if inventory is not None:
        cmd.extend(["--inventory", str(inventory)])
    log.info("CLI: %s", " ".join(cmd))
    return subprocess.run(
        cmd,
        cwd=str(_CLI_DIR),
        capture_output=True,
        text=True,
        timeout=timeout_s,
        env={**os.environ, "NO_COLOR": "1"},
    )


def run_market_provide_abort_all(
    *,
    seller_node: dict,
    extra_args: Optional[list[str]] = None,
    timeout_s: float = 30,
) -> subprocess.CompletedProcess:
    """Invoke `market provide --abort-all` as a subprocess."""
    cmd = [
        "uv", "run", "market", "provide",
        "-a", seller_node["agent_url"],
        "-e", seller_node["agent_env_file"],
        "--db", seller_node["agent_db_path"],
        "--abort-all",
    ]
    if extra_args:
        cmd.extend(extra_args)
    log.info("CLI: %s", " ".join(cmd))
    return subprocess.run(
        cmd,
        cwd=str(_CLI_DIR),
        capture_output=True,
        text=True,
        timeout=timeout_s,
        env={**os.environ, "NO_COLOR": "1"},
    )


@pytest.fixture(scope="session")
def market_provide_happy_result(seller_node: dict, tmp_path_factory) -> subprocess.CompletedProcess:
    """Run `market provide` ONCE per session with a throwaway CSV.

    Scoped session to avoid re-importing or re-publishing on every test —
    three assertions read from this same CompletedProcess.
    """
    csv_path = tmp_path_factory.mktemp("provide") / "inventory.csv"
    write_provide_test_csv(csv_path)
    return run_market_provide(
        seller_node=seller_node,
        inventory=csv_path,
        min_price="150",
    )
