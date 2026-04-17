"""Integration tests for the `market buy` CLI command.

`market buy` is the buyer's entire product surface — one synchronous command
that turns a constraint spec into running credentials. These tests invoke the
CLI as a subprocess against the live compose stack and assert on user-visible
behavior (exit codes + stdout), not internal state.

Tests are marked `roles_cli_buy`. They share the seller's one-resource
inventory with `roles_stage_*` tests; run in separate pytest sessions.
"""

from __future__ import annotations

import logging
import re
import sqlite3

import pytest

from tests.roles.cli.conftest import COMPUTE, PAYMENT, run_market_buy, run_market_buy_recover

log = logging.getLogger(__name__)


@pytest.mark.roles_cli_buy
class TestMarketBuyHappyPath:
    """`market buy` drives the full pipeline and returns credentials on success.

    All three tests read from one session-scoped `market_buy_happy_result`
    fixture — the seller has one resource, so we exercise the CLI once and
    make multiple independent assertions on its output.
    """

    def test_exits_zero(self, market_buy_happy_result):
        """Exit code 0 means the deal closed and credentials are available."""
        assert market_buy_happy_result.returncode == 0, (
            f"Expected exit 0, got {market_buy_happy_result.returncode}\n"
            f"stdout (last 2000):\n{market_buy_happy_result.stdout[-2000:]}\n"
            f"stderr (last 1000):\n{market_buy_happy_result.stderr[-1000:]}"
        )

    def test_prints_credentials_block(self, market_buy_happy_result):
        """Stdout includes a Credentials table with tenant SSH info the buyer can act on."""
        assert market_buy_happy_result.returncode == 0, market_buy_happy_result.stdout[-2000:]
        assert "Credentials" in market_buy_happy_result.stdout, (
            "Expected a Credentials table in stdout\n"
            f"stdout (last 2000):\n{market_buy_happy_result.stdout[-2000:]}"
        )
        # A working SSH access token surfaces as either a password or an ssh command.
        assert re.search(r"ssh|password|tenant", market_buy_happy_result.stdout, re.IGNORECASE), (
            f"Expected credential fields in stdout\n{market_buy_happy_result.stdout[-2000:]}"
        )

    def test_writes_order_to_buyer_db(self, market_buy_happy_result, buyer_node):
        """The CLI left an order row in the buyer DB matching the requested constraints."""
        assert market_buy_happy_result.returncode == 0, market_buy_happy_result.stdout[-2000:]
        # Extract order id from stdout ("Order created: <uuid>")
        m = re.search(r"Order created:\s*([0-9a-f\-]{36})", market_buy_happy_result.stdout)
        assert m, (
            f"Could not find 'Order created: <id>' in stdout\n"
            f"{market_buy_happy_result.stdout[-2000:]}"
        )
        order_id = m.group(1)

        conn = sqlite3.connect(
            f"file:{buyer_node['agent_db_path']}?mode=ro", uri=True, timeout=5
        )
        try:
            row = conn.execute(
                "SELECT status, demand_resource, offer_resource FROM orders WHERE order_id = ?",
                (order_id,),
            ).fetchone()
        finally:
            conn.close()

        assert row is not None, f"Order {order_id} not found in buyer DB"
        status, demand_json, offer_json = row
        assert COMPUTE["gpu_model"] in (demand_json or ""), (
            f"Order demand does not contain requested GPU model\n{demand_json}"
        )
        assert COMPUTE["region"] in (demand_json or ""), demand_json
        # Status should be past 'open' (deal completed)
        assert status in ("accepted", "closed"), (
            f"Expected order past open, got status={status}"
        )


@pytest.mark.roles_cli_buy
class TestMarketBuyInvalidConstraints:
    """Invalid constraints are rejected at the agent boundary — fast & reliable test."""

    def test_exits_non_zero_and_surfaces_agent_error(self, buyer_node):
        """Unknown GPU model: agent returns 400, CLI exits 1 with the validation detail."""
        result = run_market_buy(
            buyer_node=buyer_node,
            compute={
                "gpu_model": "Nonexistent Z999 XYZ",
                "quantity": 1,
                "sla": 90.0,
                "region": "California, US",
            },
            max_price="1",
            timeout_budget=8,
            poll_interval=1.0,
        )
        assert result.returncode != 0, (
            f"Expected non-zero exit, got {result.returncode}\n"
            f"stdout: {result.stdout[-1000:]}"
        )
        # Pydantic's enum validation error must bubble through to the user
        combined = result.stdout + result.stderr
        assert "Agent error" in combined or "validation" in combined.lower(), (
            f"Expected an agent-error message\n{combined[-1000:]}"
        )


@pytest.mark.roles_cli_buy
class TestMarketBuyRecover:
    """`market buy --recover <id>` resumes an existing deal without creating a new order.

    Piggybacks on `market_buy_happy_result`: that fixture created + closed a
    buyer order; recovery should find it via either order_id or escrow_uid.
    """

    def _extract_order_id(self, happy_result) -> str:
        m = re.search(r"Order created:\s*([0-9a-f\-]{36})", happy_result.stdout)
        assert m, f"No 'Order created' line in fixture stdout:\n{happy_result.stdout[-1000:]}"
        return m.group(1)

    def test_recover_by_order_id_exits_zero_and_prints_credentials(
        self, market_buy_happy_result, buyer_node,
    ):
        """Recovering a closed order surfaces credentials and exits cleanly."""
        assert market_buy_happy_result.returncode == 0, "Prereq happy-path must succeed"
        order_id = self._extract_order_id(market_buy_happy_result)

        result = run_market_buy_recover(
            buyer_node=buyer_node,
            recover=order_id,
            timeout_budget=15,
        )
        assert result.returncode == 0, (
            f"Expected exit 0, got {result.returncode}\n"
            f"stdout: {result.stdout[-1500:]}"
        )
        assert "Buy recovery" in result.stdout, (
            f"Expected recovery panel in stdout\n{result.stdout[-1500:]}"
        )
        assert "Credentials" in result.stdout, (
            f"Expected credentials block in stdout\n{result.stdout[-1500:]}"
        )

    def test_recover_by_escrow_uid(self, market_buy_happy_result, buyer_node):
        """Recovery also accepts an on-chain escrow_uid (0x-prefixed hex)."""
        assert market_buy_happy_result.returncode == 0
        order_id = self._extract_order_id(market_buy_happy_result)

        # Read the order's escrow_uid from the buyer DB.
        conn = sqlite3.connect(
            f"file:{buyer_node['agent_db_path']}?mode=ro", uri=True, timeout=5,
        )
        try:
            row = conn.execute(
                "SELECT escrow_uid FROM orders WHERE order_id = ?",
                (order_id,),
            ).fetchone()
        finally:
            conn.close()
        assert row and row[0], f"No escrow_uid on order {order_id}"
        escrow_uid = row[0]

        result = run_market_buy_recover(
            buyer_node=buyer_node,
            recover=escrow_uid,
            timeout_budget=15,
        )
        assert result.returncode == 0, (
            f"Expected exit 0, got {result.returncode}\n{result.stdout[-1500:]}"
        )
        assert order_id in result.stdout, (
            f"Recovery panel should resolve escrow_uid → order_id\n{result.stdout[-1500:]}"
        )

    def test_recover_unknown_id_exits_non_zero_with_clear_message(self, buyer_node):
        """A non-existent id should fail fast with an explanation — not hang or succeed."""
        result = run_market_buy_recover(
            buyer_node=buyer_node,
            recover="00000000-0000-0000-0000-000000000000",
            timeout_budget=5,
        )
        assert result.returncode != 0, result.stdout[-500:]
        combined = result.stdout + result.stderr
        assert "No local order found" in combined or "not found" in combined.lower(), (
            f"Expected 'No local order found' message\n{combined[-500:]}"
        )

    def test_recover_with_max_price_is_rejected(self, buyer_node):
        """--recover and --max-price are mutually exclusive."""
        result = run_market_buy_recover(
            buyer_node=buyer_node,
            recover="00000000-0000-0000-0000-000000000000",
            timeout_budget=5,
            extra_args=["--max-price", "100"],
        )
        assert result.returncode != 0, result.stdout[-500:]
        combined = result.stdout + result.stderr
        assert "mutually exclusive" in combined.lower() or "--max-price" in combined, (
            f"Expected mutex error\n{combined[-500:]}"
        )


@pytest.mark.roles_cli_buy
class TestMarketBuyHonestExit:
    """The CLI never fakes success.

    Whether a deal completes or fails, `market buy` must map the outcome to
    a distinct exit code AND a human-readable explanation in stdout. This is
    the core invariant: a caller script can always trust the exit code and a
    user can always read stdout to know what happened.
    """

    def test_exit_code_matches_stdout_verdict(self, buyer_node):
        """One of: (0 + Credentials shown), (2 + Timed out), (3 + failure)."""
        result = run_market_buy(
            buyer_node=buyer_node,
            compute=COMPUTE,
            max_price=str(PAYMENT["amount"]),
            timeout_budget=20,
            poll_interval=1.0,
        )
        stdout = result.stdout
        code = result.returncode
        if code == 0:
            assert "Credentials" in stdout, (
                f"Exit 0 but no Credentials block in stdout\n{stdout[-1000:]}"
            )
        elif code == 2:
            assert "Timed out" in stdout, (
                f"Exit 2 but no 'Timed out' message\n{stdout[-1000:]}"
            )
        elif code == 3:
            assert "failure" in stdout.lower(), (
                f"Exit 3 but no failure explanation\n{stdout[-1000:]}"
            )
        else:
            pytest.fail(
                f"Unexpected exit code {code} (want 0/2/3)\n"
                f"stdout: {stdout[-1000:]}\n"
                f"stderr: {result.stderr[-500:]}"
            )
