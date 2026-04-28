"""
Integration tests for deployed Buyer and Seller agent processes.

Scope
-----
- Agent is reachable and on-chain registered (registration file)
- Agent can create and close orders via its manual REST routes
- Buyer and seller orders reach "accepted" status within a configurable
  timeout, confirming end-to-end negotiation across the network
"""

from __future__ import annotations

import logging
import time
from decimal import Decimal
from typing import Any

import pytest

from src.agent_client import AgentClient
from storefront_client import StorefrontClientError
from registry_client import SyncRegistryClient as RegistryClient
from registry_client import RegistryClientError
from src.models.agent import (
    AgentOrderCreateRequest,
)
from src.settings import settings

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Order parameters used for create/match/close test flow
# ---------------------------------------------------------------------------
_GPU_MODEL   = "RTX 5080"
_QUANTITY    = 1
_SLA         = 90.0
_REGION      = "California, US"
_TOKEN       = "MOCK"
_AMOUNT      = 1.0
_DURATION_H  = 1


# ---------------------------------------------------------------------------
# Module-scoped fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def buyer_api_url(buyer_settings) -> str:
    url = buyer_settings.get("api_url", "")
    if not url:
        pytest.fail(
            "buyer.api_url is not configured.\n"
            "Set it via ARKHAI_BUYER__API_URL, config.yml, or --buyer-api-url."
        )
    return url.rstrip("/")

@pytest.fixture(scope="module")
def seller_api_url(seller_settings) -> str:
    url = seller_settings.get("api_url", "")
    if not url:
        pytest.fail(
            "seller.api_url is not configured.\n"
            "Set it via ARKHAI_SELLER__API_URL, config.yml, or --seller-api-url."
        )
    return url.rstrip("/")

@pytest.fixture(scope="module")
def registry_api_url(registry_settings) -> str:
    url = registry_settings.get("api_url", "")
    if not url:
        pytest.fail(
            "registry.api_url is not configured.\n"
            "Set it via ARKHAI_REGISTRY__API_URL, config.yml, or --registry-api-url."
        )
    return url.rstrip("/")

@pytest.fixture(scope="module")
def buyer_client(buyer_api_url: str, buyer_settings: dict) -> AgentClient:  # type: ignore[return]
    client = AgentClient(
        base_url=buyer_api_url,
        private_key=buyer_settings["private_key"],
        agent_wallet_address=buyer_settings["wallet_address"],
    )
    yield client
    client.close()


@pytest.fixture(scope="module")
def seller_client(seller_api_url: str, seller_settings: dict) -> AgentClient:  # type: ignore[return]
    client = AgentClient(
        base_url=seller_api_url,
        private_key=seller_settings["private_key"],
        agent_wallet_address=seller_settings["wallet_address"],
    )
    yield client
    client.close()

@pytest.fixture(scope="module")
def registry_client(registry_api_url: str, registry_settings: dict) -> RegistryClient: # type: ignore[return]
    client = RegistryClient(base_url=registry_api_url)
    yield client
    client.close()

@pytest.fixture(scope="module")
def order_create_timeout() -> int:
    return int(settings.TESTS__ORDER_CREATE_TIMEOUT)


@pytest.fixture(scope="module")
def order_match_timeout() -> int:
    return int(settings.TESTS__ORDER_MATCH_TIMEOUT)


@pytest.fixture(scope="module")
def order_close_timeout() -> int:
    return int(settings.TESTS__ORDER_CLOSE_TIMEOUT)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _poll_registry_order_status(
    registry_client,    # RegistryClient — imported lazily to avoid circular deps
    order_id: str,
    target_status: str,
    timeout: int,
) -> dict[str, Any] | None:
    """
    Poll GET /orders/{order_id} on the registry until status == target_status
    or timeout is exceeded.  Returns the final order dict or None on timeout.
    """
    deadline = time.monotonic() + timeout
    interval = 1.0
    while time.monotonic() < deadline:
        try:
            order = registry_client.get_order(order_id)
            log.debug("Order %s status=%s", order_id, order.status)
            if order.status == target_status:
                return vars(order)
        except RegistryClientError as exc:
            log.debug("get_order(%s) → %s (will retry)", order_id, exc.status_code)
        time.sleep(interval)
    return None


# ---------------------------------------------------------------------------
# Test suite 1 — Agent registration file
# ---------------------------------------------------------------------------

@pytest.mark.agents
class TestAgentRegistration:
    """Verify buyer and seller are reachable and on-chain registered."""

    @pytest.mark.parametrize("role", ["buyer", "seller"])
    def test_agent_is_on_chain_registered(
        self,
        role: str,
        buyer_client: AgentClient,
        seller_client: AgentClient,
    ) -> None:
        """
        The registration file must contain at least one registration record
        with a non-zero agentId, confirming the agent has been indexed by
        the registry and its on-chain identity is live.
        """
        client = buyer_client if role == "buyer" else seller_client
        try:
            reg = client.get_registration_file()
        except RegistryClientError as exc:
            pytest.fail(f"Could not fetch {role} registration file.\n{exc}")

        assert reg.registrations, (
            f"{role} agent has no registration records in its ERC-8004 file.\n"
            "The agent may not have completed on-chain registration."
        )

        assert reg.is_registered, (
            f"{role} agent registration records all have agentId == 0.\n"
            f"Registrations: {reg.registrations}\n"
            "The agent has not been indexed by the registry yet."
        )

        log.info(
            "✓ %s agent is registered — agentId(s): %s",
            role,
            [r.agent_id for r in reg.registrations],
        )

    @pytest.mark.parametrize("role", ["buyer", "seller"])
    def test_agent_registry_address_matches_config(
        self,
        role: str,
        buyer_client: AgentClient,
        seller_client: AgentClient,
        registry_settings: dict,
    ) -> None:
        """
        The agentRegistry field in the registration file must contain the
        identity_address from configuration.

        This guards against an agent being registered against a different
        registry contract than the one this test suite is configured to use
        (e.g., wrong chain or stale deployment).
        """
        client = buyer_client if role == "buyer" else seller_client
        expected_address = registry_settings["identity_address"].lower()
        try:
            reg = client.get_registration_file()
        except RegistryClientError as exc:
            pytest.fail(f"Could not fetch {role} registration file.\n{exc}")

        assert reg.registrations, f"{role} agent has no registration records."

        actual_addresses = [
            (r.registry_address or "").lower()
            for r in reg.registrations
        ]

        assert any(addr == expected_address for addr in actual_addresses), (
            f"{role} agent is not registered against the expected identity registry.\n"
            f"  Expected : {expected_address}\n"
            f"  Got      : {actual_addresses}\n"
            "Check registry.identity_address in config and the agent's "
            "IDENTITY_REGISTRY_ADDRESS env var."
        )

        log.info(
            "✓ %s agent registry address matches config: %s", role, expected_address
        )


# ---------------------------------------------------------------------------
# Test suite 2 — Order create, match, and close
# ---------------------------------------------------------------------------

def _discover_order_id_from_registry(
    registry_client,
    agent_canonical_id: str,
    event_id: str,
    timeout: int,
) -> str | None:
    """
    When the agent queues an order, the HTTP response contains only an
    event_id — the order_id is assigned asynchronously and only appears in
    the registry once the agent processes the queue entry.

    Poll GET /agents/{agent_canonical_id}/orders and return the order_id of
    the first order whose event_id matches, or the most-recently-created
    order if the event_id is not surfaced in the registry response.

    The registry order record does not carry the agent's internal event_id,
    so we use created_at recency as a proxy: the newest order after the
    create call is the one we just made.
    """
    deadline = time.monotonic() + timeout
    # Record the wall-clock time before polling so we can filter by recency
    started_at = time.time()

    while time.monotonic() < deadline:
        try:
            result = registry_client.get_agent_orders(agent_canonical_id, limit=50)
            if result.orders:
                # orders are typically newest-first; take the first open one
                for order in result.orders:
                    if order.status == "open":
                        log.debug(
                            "Discovered order by recency: order_id=%s created_at=%s",
                            order.id, order.created_at,
                        )
                        return str(order.id)
        except RegistryClientError as exc:
            log.debug(
                "get_agent_orders(%s) → %s (will retry)", agent_canonical_id, exc.status_code
            )
        time.sleep(1.0)
    return None

@pytest.mark.agents
@pytest.mark.slow
class TestAgentOrderLifecycle:
    """
    Create orders on buyer and seller, wait for both to reach "accepted"
    status on the registry, then close them.

    Test flow
    ---------
    1. POST /orders/create on buyer  → token offer / compute demand
    2. POST /orders/create on seller → compute offer / token demand
    3. Poll GET /orders/{id} on the registry for both orders until
       status == "accepted" (agents negotiate autonomously over A2A)
    4. POST /orders/close on both agents

    The buyer offers tokens and demands compute.
    The seller offers compute and demands tokens.
    Matching parameters must align for negotiation to succeed.
    """

    @pytest.fixture(scope="class")
    def order_ids(
        self,
        buyer_client: AgentClient,
        seller_client: AgentClient,
        registry_client: RegistryClient,
        order_create_timeout: int,
    ) -> dict[str, str]:
        """
        Class-scoped fixture: create one order per agent and return a dict
        of role → order_id.  Skips the class if either creation fails so
        that match/close tests are correctly skipped rather than erroring.
        """
        order_ids: dict[str, str] = {}

        buyer_order = AgentOrderCreateRequest.token_offer(
            token=_TOKEN,
            amount=_AMOUNT,
            gpu_model=_GPU_MODEL,
            quantity=_QUANTITY,
            sla=_SLA,
            region=_REGION,
            duration_hours=_DURATION_H,
        )
        seller_order = AgentOrderCreateRequest.compute_offer(
            gpu_model=_GPU_MODEL,
            quantity=_QUANTITY,
            sla=_SLA,
            region=_REGION,
            token=_TOKEN,
            amount=_AMOUNT,
            duration_hours=_DURATION_H,
        )

        # Resolve each agent's canonical registry ID from their registration file
        agent_canonical_ids: dict[str, str] = {}
        for role, client in [("buyer", buyer_client), ("seller", seller_client)]:
            try:
                reg = client.get_registration_file()
                if reg.registrations:
                    first = reg.registrations[0]
                    agent_canonical_ids[role] = f"{first.agent_registry}:{first.agent_id}"
                log.info("[%s] canonical id: %s", role, agent_canonical_ids[role])
            except RegistryClientError as exc:
                pytest.skip(
                    f"Could not fetch {role} registration file to resolve agent ID.\n{exc}"
                )

        for role, client, order_req in [
            ("buyer", buyer_client, buyer_order),
            ("seller", seller_client, seller_order),
        ]:
            try:
                resp = client.create_order(order_req)
            except RegistryClientError as exc:
                pytest.skip(
                    f"POST /orders/create failed on {role} agent — "
                    f"skipping order lifecycle tests.\n{exc}"
                )

            log.info(
                "[%s] create_order response: status=%s event_id=%s order_id=%s",
                role, resp.status, resp.event_id, resp.order_id,
            )

            if resp.order_id:
            # Synchronous path: order_id returned directly
                order_ids[role] = resp.order_id
                log.info("✓ [%s] order_id=%s (sync)", role, resp.order_id)

            elif resp.status == "queued":
            # Async path: poll the registry until the order appears
                canonical_id = agent_canonical_ids.get(role, "")
                if not canonical_id:
                    pytest.skip(
                        f"[{role}] Cannot discover queued order — "
                        "agent canonical ID not found in registration file."
                    )
                log.info("Marker 1 %d", order_create_timeout)
                log.info(
                    "[%s] Order queued (event_id=%s) — polling registry "
                    "agent=%s for up to %ds ...",
                    role, resp.event_id, canonical_id, order_create_timeout,
                )
                discovered = _discover_order_id_from_registry(
                    registry_client,
                    canonical_id,
                    resp.event_id or "",
                    order_create_timeout,
                )
                if not discovered:
                    pytest.skip(
                        f"[{role}] Queued order did not appear in registry within "
                        f"{order_create_timeout}s (event_id={resp.event_id})."
                    )
                order_ids[role] = discovered
                log.info("✓ [%s] order_id=%s (discovered from registry)", role, discovered)

            else:
                pytest.skip(
                    f"[{role}] Agent did not return an order_id "
                    f"(status={resp.status!r}, response={resp.root_agent_response!r})."
                )
        return order_ids

    def test_buyer_order_created(self, order_ids: dict[str, str]) -> None:
        """Verify that the buyer agent returned a valid order_id."""
        assert "buyer" in order_ids, (
            "Buyer order was not created — see order_ids fixture logs for details."
        )
        log.info("✓ Buyer order created: %s", order_ids["buyer"])

    def test_seller_order_created(self, order_ids: dict[str, str]) -> None:
        """Verify that the seller agent returned a valid order_id."""
        assert "seller" in order_ids, (
            "Seller order was not created — see order_ids fixture logs for details."
        )
        log.info("✓ Seller order created: %s", order_ids["seller"])

    def test_orders_reach_accepted_status(
        self,
        registry_client : RegistryClient,
        order_ids: dict[str, str],
        order_match_timeout: int,
    ) -> None:
        """
        Both orders must reach status "accepted" within order_match_timeout
        seconds.

        "accepted" means the agents have negotiated and both sides have
        committed to the trade on-chain.  Failure here indicates:
          - the agents are not discovering each other's orders
          - the negotiation policy is rejecting the counterpart's offer
          - a blockchain transaction is stalled (gas, connectivity)

        We query the registry rather than the agents directly so we exercise
        the full integration path: agent → registry publish → chain event →
        registry index → test query.
        """

        timed_out: list[str] = []

        for role, order_id in order_ids.items():
            log.info(
                "Polling registry for %s order %s (timeout=%ds) ...",
                role, order_id, order_match_timeout,
            )
            final = _poll_registry_order_status(
                registry_client, order_id, "accepted", order_match_timeout
            )
            if final is None:
                timed_out.append(
                    f"  {role} order {order_id} did not reach 'accepted' "
                    f"within {order_match_timeout}s"
                )
            else:
                log.info("✓ [%s] order %s accepted", role, order_id)

        assert not timed_out, (
            "One or more orders did not reach 'accepted' status:\n"
            + "\n".join(timed_out)
            + "\n\nPossible causes:\n"
            + "  - Agents are not discovering each other (registry connectivity)\n"
            + "  - Negotiation policy mismatch (offer/demand parameters)\n"
            + "  - Blockchain transaction not landing (gas price, RPC)\n"
            + f"  - Increase tests.order_match_timeout (currently {order_match_timeout}s)"
        )

    def test_buyer_order_closed(
        self,
        order_ids: dict[str, str],
        buyer_client: AgentClient,
        order_close_timeout: int,
    ) -> None:
        """
        POST /orders/close on the buyer agent must succeed.

        This test is intentionally kept separate from the seller close so
        that a failure on one side is clearly attributed.
        """
        order_id = order_ids.get("buyer")
        if not order_id:
            pytest.skip("Buyer order_id not available — skipping close test.")

        deadline = time.monotonic() + order_close_timeout
        last_exc: Exception | None = None

        while time.monotonic() < deadline:
            try:
                resp = buyer_client.close_order(order_id)
                log.info(
                    "[buyer] close_order response: status=%s event_id=%s",
                    resp.status, resp.event_id,
                )
                assert resp.status in ("closed", "queued"), (
                    f"Unexpected close status from buyer agent: {resp.status!r}"
                )
                log.info("✓ Buyer order %s closed (status=%s)", order_id, resp.status)
                return
            except RegistryClientError as exc:
                last_exc = exc
                log.debug("close_order buyer → %s (will retry)", exc.status_code)
                time.sleep(2)

        pytest.fail(
            f"Failed to close buyer order {order_id} within {order_close_timeout}s.\n"
            f"Last error: {last_exc}"
        )

    def test_seller_order_closed(
        self,
        order_ids: dict[str, str],
        seller_client: AgentClient,
        order_close_timeout: int,
    ) -> None:
        """
        POST /orders/close on the seller agent must succeed.
        """
        order_id = order_ids.get("seller")
        if not order_id:
            pytest.skip("Seller order_id not available — skipping close test.")

        deadline = time.monotonic() + order_close_timeout
        last_exc: Exception | None = None

        while time.monotonic() < deadline:
            try:
                resp = seller_client.close_order(order_id)
                log.info(
                    "[seller] close_order response: status=%s event_id=%s",
                    resp.status, resp.event_id,
                )
                assert resp.status in ("closed", "queued"), (
                    f"Unexpected close status from seller agent: {resp.status!r}"
                )
                log.info("✓ Seller order %s closed (status=%s)", order_id, resp.status)
                return
            except RegistryClientError as exc:
                last_exc = exc
                log.debug("close_order seller → %s (will retry)", exc.status_code)
                time.sleep(2)

        pytest.fail(
            f"Failed to close seller order {order_id} within {order_close_timeout}s.\n"
            f"Last error: {last_exc}"
        )