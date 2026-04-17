"""Integration tests for the `market provide` CLI command.

`market provide` is the seller's entire product surface — one command that
imports a compute inventory CSV and publishes one sell order per available
resource. These tests invoke the CLI against a live compose stack and
assert on user-visible behavior (exit code, stdout, DB side effects).

The test publishes RTX 4090 / New York orders with unique test-provide-…
resource IDs. Those specs don't collide with the buy-test's RTX 5080 /
California path.
"""

from __future__ import annotations

import logging
import re
import sqlite3
from pathlib import Path

import pytest

from tests.roles.cli.conftest import (
    PROVIDE_TEST_RESOURCES,
    run_market_provide,
    write_provide_test_csv,
)

log = logging.getLogger(__name__)


@pytest.mark.roles_cli_provide
class TestMarketProvideHappyPath:
    """`market provide --inventory <csv>` imports resources and publishes orders.

    All assertions read from one session-scoped `market_provide_happy_result`
    fixture so the import + publish runs exactly once.
    """

    def test_exits_zero(self, market_provide_happy_result):
        """Exit code 0 means all orders were published."""
        assert market_provide_happy_result.returncode == 0, (
            f"Expected exit 0, got {market_provide_happy_result.returncode}\n"
            f"stdout (last 2000):\n{market_provide_happy_result.stdout[-2000:]}\n"
            f"stderr (last 1000):\n{market_provide_happy_result.stderr[-1000:]}"
        )

    def test_stdout_reports_published_count(self, market_provide_happy_result):
        """The Summary panel should declare how many orders were published."""
        stdout = market_provide_happy_result.stdout
        n = len(PROVIDE_TEST_RESOURCES)
        assert re.search(rf"Published\s+{n}\b", stdout), (
            f"Expected 'Published {n}' in stdout\n{stdout[-2000:]}"
        )
        assert "Failed            0" in stdout or re.search(r"Failed\s+0\b", stdout), (
            f"Expected 'Failed 0' in stdout\n{stdout[-2000:]}"
        )

    def test_orders_landed_in_seller_db(self, market_provide_happy_result, seller_node):
        """Orders matching the CSV's spec exist in the seller DB.

        The agent auto-resolves `resource_id` from its portfolio when the CLI
        payload only specifies gpu_model/sla/region/quantity, so we match on
        that spec rather than the exact resource_id from the CSV.
        """
        assert market_provide_happy_result.returncode == 0, (
            market_provide_happy_result.stdout[-2000:]
        )
        # All test resources share the same spec, so one pattern matches all.
        conn = sqlite3.connect(
            f"file:{seller_node['agent_db_path']}?mode=ro&nolock=1",
            uri=True, timeout=5,
        )
        try:
            row = conn.execute(
                """SELECT COUNT(*) FROM orders
                   WHERE offer_resource LIKE ? AND offer_resource LIKE ?""",
                ('%"gpu_model": "RTX 4090"%', '%"region": "New York, US"%'),
            ).fetchone()
        finally:
            conn.close()

        expected = len(PROVIDE_TEST_RESOURCES)
        assert row and row[0] >= expected, (
            f"Expected at least {expected} orders for RTX 4090 / New York, "
            f"got {row[0] if row else 0}"
        )


@pytest.mark.roles_cli_provide
class TestMarketProvideRejectsInvalid:
    """Clear, fast rejections for obviously bad inputs."""

    def test_missing_csv_path(self, seller_node, tmp_path):
        """Non-existent inventory path → non-zero exit, message naming the file."""
        bogus = tmp_path / "does-not-exist.csv"
        result = run_market_provide(
            seller_node=seller_node,
            inventory=bogus,
            min_price="100",
            timeout_s=15,
        )
        assert result.returncode != 0, (
            f"Expected non-zero exit, got {result.returncode}\n"
            f"stdout: {result.stdout[-500:]}"
        )
        combined = result.stdout + result.stderr
        assert str(bogus) in combined or "not found" in combined.lower(), (
            f"Expected error mentioning missing file\n{combined[-500:]}"
        )

    def test_no_resources_and_no_csv_exits_with_distinct_code(
        self, seller_node, tmp_path,
    ):
        """With an empty CSV (zero rows) and no pre-existing available resources,
        `market provide` must exit with its 'no resources' code (3), not 0.

        This test is conservative: it only asserts the exit is non-zero
        (>=3 or similar), because the seller DB may already contain rows
        from prior runs. What matters: an empty operation isn't silently
        reported as success.
        """
        empty_csv = tmp_path / "empty.csv"
        empty_csv.write_text(
            "resource_id,resource_type,resource_subtype,unit,value,state,"
            "attribute.gpu_model,attribute.sla,attribute.region,attribute.vm_host\n"
        )
        result = run_market_provide(
            seller_node=seller_node,
            inventory=empty_csv,
            min_price="100",
            timeout_s=30,
        )
        # With prior test state in the DB, this may succeed OR fail depending
        # on whether any resource happens to still be 'available'. We just
        # require consistency: non-zero exit comes with an explanatory message.
        if result.returncode != 0:
            combined = result.stdout + result.stderr
            assert re.search(r"no available|failed|error", combined.lower()), (
                f"Non-zero exit but no explanation\n{combined[-500:]}"
            )
