"""
E2E test: mock provisioning flow.

Tests the full order lifecycle:
  create → negotiate → accept → escrow → fulfill (mock) → arbitrate → close

Requires a running docker-compose stack with PROVISIONING_MODE=mock on seller.
Run with: ACTIVE_PROFILES=local,e2e-mock pytest -m mock_provisioning_happy -v
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

import pytest

from arkhai_e2e_tests.settings import settings
from tests.helpers.cli_client import cli_create_order, cli_order_history, cli_order_show
from tests.helpers.polling import (
    poll_registry_orders,
    poll_until,
)
from tests.helpers.sqlite_reader import get_all_orders, get_latest_order

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants — must match seller's imported resources (ww1-machine.csv)
# ---------------------------------------------------------------------------
SELLER_OFFER = {"gpu_model": "RTX 5080", "quantity": 1, "sla": 90.0, "region": "California, US"}
SELLER_DEMAND = {"token": "MOCK", "amount": 100}

BUYER_OFFER = {"token": "MOCK", "amount": 80}
BUYER_DEMAND = {"gpu_model": "RTX 5080", "quantity": 1, "sla": 90.0, "region": "California, US"}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).resolve().parents[2]


def _buyer_url() -> str:
    return settings.AGENTS.BUYER_URL


def _seller_url() -> str:
    return settings.AGENTS.SELLER_URL


def _buyer_env() -> str:
    return settings.AGENTS.BUYER_ENV


def _seller_env() -> str:
    return settings.AGENTS.SELLER_ENV


def _registry_url() -> str:
    return settings.AGENTS.REGISTRY_URL


def _buyer_db() -> str:
    value = settings.AGENTS.BUYER_DB
    p = Path(value)
    if not p.is_absolute():
        p = _REPO_ROOT / p
    return str(p)


def _seller_db() -> str:
    value = settings.AGENTS.SELLER_DB
    p = Path(value)
    if not p.is_absolute():
        p = _REPO_ROOT / p
    return str(p)


def _poll_timeout() -> float:
    return float(settings.get("TESTS__E2E_POLL_TIMEOUT_S", 120))


def _poll_interval() -> float:
    return float(settings.get("TESTS__E2E_POLL_INTERVAL_S", 3))


# ============================================================================
# HAPPY PATH
# ============================================================================


@pytest.mark.mock_provisioning
@pytest.mark.mock_provisioning_happy
class TestHappyPath:
    """Full deal lifecycle with mock provisioning (success mode)."""

    # Shared state across ordered test methods
    _state: dict = {}

    def test_01_create_seller_order(self):
        """Seller posts a compute-supply order via CLI."""
        resp = cli_create_order(
            agent_url=_seller_url(),
            env_file=_seller_env(),
            offer=SELLER_OFFER,
            demand=SELLER_DEMAND,
        )
        assert resp["status"] == "created", f"Expected 'created', got {resp}"
        self.__class__._state["seller_order_id"] = resp["order_id"]
        log.info("Seller order: %s", resp["order_id"])

    def test_02_registry_indexes_seller_order(self):
        """Registry should have at least 1 open order within 30s."""
        items = poll_registry_orders(
            _registry_url(), status="open", min_count=1,
            timeout_s=30, interval_s=_poll_interval(),
        )
        assert len(items) >= 1
        log.info("Registry has %d open order(s)", len(items))

    def test_03_create_buyer_order(self):
        """Buyer posts a matching compute-demand order via CLI (triggers negotiation)."""
        resp = cli_create_order(
            agent_url=_buyer_url(),
            env_file=_buyer_env(),
            offer=BUYER_OFFER,
            demand=BUYER_DEMAND,
        )
        assert resp["status"] in ("created", "queued"), f"Unexpected: {resp}"
        self.__class__._state["buyer_order_id"] = resp["order_id"]
        log.info("Buyer order: %s", resp["order_id"])

    def test_04_deal_completes(self):
        """Both orders should reach status=closed in the registry."""
        items = poll_registry_orders(
            _registry_url(), status="closed", min_count=2,
            timeout_s=_poll_timeout(), interval_s=_poll_interval(),
        )
        assert len(items) >= 2
        self.__class__._state["closed_registry_orders"] = items
        log.info("Registry has %d closed order(s)", len(items))

    def test_05_cli_buyer_history(self):
        """CLI: buyer order history after deal completes."""
        cli_order_history(env_file=_buyer_env())

    def test_06_cli_seller_history(self):
        """CLI: seller order history after deal completes."""
        cli_order_history(env_file=_seller_env())

    def test_07_cli_buyer_order_show(self):
        """CLI: buyer order show with negotiation + credentials."""
        order_id = self.__class__._state.get("buyer_order_id")
        assert order_id, "No buyer_order_id in state"
        cli_order_show(
            order_id, env_file=_buyer_env(),
            negotiation=True, credentials=True, show_password=True,
        )

    def test_08_cli_seller_order_show(self):
        """CLI: seller order show with negotiation + credentials."""
        order_id = self.__class__._state.get("seller_order_id")
        assert order_id, "No seller_order_id in state"
        cli_order_show(
            order_id, env_file=_seller_env(),
            negotiation=True, credentials=True, show_password=True,
        )

    def test_09_buyer_local_db(self):
        """Buyer's SQLite: status=closed, correct attestation mapping."""
        order = get_latest_order(_buyer_db())
        assert order is not None, "No orders in buyer DB"
        assert order["status"] == "closed", f"Buyer status={order['status']}"
        # Buyer is maker → maker_attestation = escrow_uid
        assert order["maker_attestation"] is not None, "Buyer maker_attestation is null"
        assert order["maker_attestation"] == order["escrow_uid"], (
            f"Buyer maker_attestation ({order['maker_attestation']}) != escrow_uid ({order['escrow_uid']})"
        )
        # Buyer's taker = seller → taker_attestation = fulfillment_uid
        assert order["taker_attestation"] is not None, "Buyer taker_attestation is null"
        assert order["taker_attestation"] != order["escrow_uid"], (
            "Buyer taker_attestation should be fulfillment_uid, not escrow_uid"
        )
        assert order["oracle_address"] is not None, "Buyer oracle_address is null"
        self.__class__._state["buyer_order"] = order
        log.info("Buyer DB OK: ma=%s ta=%s", order["maker_attestation"][:8], order["taker_attestation"][:8])

    def test_10_seller_local_db(self):
        """Seller's SQLite: status=closed, correct attestation mapping."""
        order = get_latest_order(_seller_db())
        assert order is not None, "No orders in seller DB"
        assert order["status"] == "closed", f"Seller status={order['status']}"
        # Seller is maker → maker_attestation = fulfillment_uid
        assert order["maker_attestation"] is not None, "Seller maker_attestation is null"
        # Seller's taker = buyer → taker_attestation = escrow_uid
        assert order["taker_attestation"] is not None, "Seller taker_attestation is null"
        assert order["oracle_address"] is not None, "Seller oracle_address is null"
        self.__class__._state["seller_order"] = order
        log.info("Seller DB OK: ma=%s ta=%s", order["maker_attestation"][:8], order["taker_attestation"][:8])

    def test_11_registry_attestations(self):
        """Both registry orders have attestation fields populated."""
        for item in self.__class__._state["closed_registry_orders"]:
            assert item["maker_attestation"] is not None, (
                f"Registry order {item['order_id'][:8]} has null maker_attestation"
            )
            assert item["taker_attestation"] is not None, (
                f"Registry order {item['order_id'][:8]} has null taker_attestation"
            )
            assert item["oracle_address"] is not None, (
                f"Registry order {item['order_id'][:8]} has null oracle_address"
            )

    def test_12_cross_check_attestations(self):
        """Buyer's maker_attestation == Seller's taker_attestation and vice versa."""
        buyer = self.__class__._state["buyer_order"]
        seller = self.__class__._state["seller_order"]

        assert buyer["maker_attestation"] == seller["taker_attestation"], (
            f"Buyer maker_attestation ({buyer['maker_attestation'][:8]}) "
            f"!= Seller taker_attestation ({seller['taker_attestation'][:8]})"
        )
        assert buyer["taker_attestation"] == seller["maker_attestation"], (
            f"Buyer taker_attestation ({buyer['taker_attestation'][:8]}) "
            f"!= Seller maker_attestation ({seller['maker_attestation'][:8]})"
        )
        log.info(
            "Cross-check OK: escrow_uid=%s fulfillment_uid=%s",
            buyer["maker_attestation"][:8],
            buyer["taker_attestation"][:8],
        )


# ============================================================================
# FAILURE PATH
# ============================================================================


@pytest.mark.mock_provisioning
@pytest.mark.mock_provisioning_failure
class TestFailurePath:
    """Provisioning fails → both orders reopen."""

    _state: dict = {}

    def test_01_create_seller_order(self):
        """Seller posts a compute-supply order via CLI."""
        resp = cli_create_order(
            agent_url=_seller_url(),
            env_file=_seller_env(),
            offer=SELLER_OFFER,
            demand=SELLER_DEMAND,
        )
        assert resp["status"] == "created", f"Expected 'created', got {resp}"
        self.__class__._state["seller_order_id"] = resp["order_id"]

    def test_02_registry_indexes_seller_order(self):
        """Registry should index the seller order."""
        items = poll_registry_orders(
            _registry_url(), status="open", min_count=1,
            timeout_s=30, interval_s=_poll_interval(),
        )
        assert len(items) >= 1

    def test_03_create_buyer_order(self):
        """Buyer posts a matching order via CLI (triggers negotiation + failure)."""
        resp = cli_create_order(
            agent_url=_buyer_url(),
            env_file=_buyer_env(),
            offer=BUYER_OFFER,
            demand=BUYER_DEMAND,
        )
        assert resp["status"] in ("created", "queued"), f"Unexpected: {resp}"
        self.__class__._state["buyer_order_id"] = resp["order_id"]

    def test_04_orders_reopen(self):
        """After provisioning fails, both orders should reopen to status=open.

        The flow is: negotiate → accept → escrow → fulfill FAILS →
        seller reopens → buyer reopens.
        We poll the seller's SQLite for an order that transitions back to 'open'
        after having been 'accepted' (indicated by escrow_uid being set).
        """
        def _seller_reopened():
            orders = get_all_orders(_seller_db())
            for o in orders:
                if o["status"] == "open" and o.get("escrow_uid"):
                    return o
            return None

        seller_order = poll_until(
            _seller_reopened,
            timeout_s=_poll_timeout(),
            interval_s=_poll_interval(),
            description="seller order reopened after failure",
        )
        assert seller_order is not None
        self.__class__._state["seller_order"] = seller_order
        log.info("Seller order reopened: %s", seller_order["order_id"][:8])

    def test_05_cli_buyer_history_failure(self):
        """CLI: buyer order history after failure."""
        cli_order_history(env_file=_buyer_env())

    def test_06_cli_seller_history_failure(self):
        """CLI: seller order history after failure."""
        cli_order_history(env_file=_seller_env())

    def test_07_cli_buyer_order_show_failure(self):
        """CLI: buyer order show with negotiation after failure."""
        order_id = self.__class__._state.get("buyer_order_id")
        assert order_id, "No buyer_order_id in state"
        cli_order_show(
            order_id, env_file=_buyer_env(),
            negotiation=True, credentials=True, show_password=True,
        )

    def test_08_cli_seller_order_show_failure(self):
        """CLI: seller order show with negotiation after failure."""
        order_id = self.__class__._state.get("seller_order_id")
        assert order_id, "No seller_order_id in state"
        cli_order_show(
            order_id, env_file=_seller_env(),
            negotiation=True, credentials=True, show_password=True,
        )

    def test_09_seller_local_db_failure(self):
        """Seller's order: status=open, no maker_attestation (no fulfillment), taker_attestation set (escrow)."""
        order = self.__class__._state["seller_order"]
        assert order["status"] == "open"
        assert order["maker_attestation"] is None, (
            f"Seller maker_attestation should be null after failure, got {order['maker_attestation']}"
        )
        assert order["taker_attestation"] is not None, (
            "Seller taker_attestation (escrow_uid) should be set even after failure"
        )

    def test_10_buyer_local_db_failure(self):
        """Buyer's order: status=open, maker_attestation set (escrow), no taker_attestation."""
        def _buyer_reopened():
            orders = get_all_orders(_buyer_db())
            for o in orders:
                if o["status"] == "open" and o.get("escrow_uid"):
                    return o
            return None

        order = poll_until(
            _buyer_reopened,
            timeout_s=30,
            interval_s=_poll_interval(),
            description="buyer order reopened after failure",
        )
        assert order is not None
        assert order["status"] == "open"
        assert order["maker_attestation"] is not None, (
            "Buyer maker_attestation (escrow_uid) should be set"
        )
        assert order["taker_attestation"] is None, (
            f"Buyer taker_attestation should be null after failure, got {order['taker_attestation']}"
        )
        self.__class__._state["buyer_order"] = order

    def test_11_docker_logs_show_failure(self):
        """Seller container logs should mention provisioning failure."""
        result = subprocess.run(
            ["docker", "logs", "market-agent-sell"],
            capture_output=True, text=True, timeout=10,
        )
        combined = result.stdout + result.stderr
        assert any(
            phrase in combined
            for phrase in ("Provisioning failed", "mock failure", "ProvisioningJobError")
        ), "Expected provisioning failure message in seller logs"
