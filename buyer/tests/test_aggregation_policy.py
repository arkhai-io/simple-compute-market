"""Aggregation policy tests — the new `(candidates, negotiate) -> winner` seam.

Verifies:
- The policy receives a curried `negotiate` callback.
- `best_price` (the default) picks the lowest *agreed* price, not the lowest advertised.
- Opting into `cheapest_first` preserves the historical first-agreed loop semantics.
- A custom registered policy can short-circuit / re-order arbitrarily.

These tests drive `run_buy` end-to-end so the orchestrator's currying
and asyncio.run wiring is exercised, not just the policy in isolation.
The urlopen stub routes by request host so parallel negotiations
(asyncio.gather) don't depend on call order.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from unittest.mock import patch
from urllib.parse import urlparse

from service.schemas import EscrowProposal, EscrowTerms, ProvisionTerms

_ESCROW_ADDR_AGG = "0x" + "cd" * 20

from market_buyer.aggregation import (
    NegotiateFn,
    gather_outcomes,
    register_aggregation_policy,
)
from market_buyer.buy_orchestrator import (
    AgreedTerms,
    BuyConfig,
    BuyConstraints,
    make_legacy_negotiate_hook,
    make_legacy_settle_hook,
    run_buy,
)
from market_buyer.buyer_client import NegotiationOutcome


_BUYER_PK = "0x" + "11" * 32
_BUYER_ADDR = "0x" + "cc" * 20
_REGISTRY = "http://registry:4000"
_SELLER_WALLET_A = "0x" + "aa" * 20
_SELLER_WALLET_B = "0x" + "bb" * 20


def _config(aggregation_policy: str | None = None) -> BuyConfig:
    return BuyConfig(
        registry_urls=[_REGISTRY],
        buyer_address=_BUYER_ADDR,
        buyer_private_key=_BUYER_PK,
        aggregation_policy=aggregation_policy,
    )


def _constraints() -> BuyConstraints:
    return BuyConstraints(max_price=100, initial_price=50)


def _provision() -> ProvisionTerms:
    return ProvisionTerms(duration_seconds=3600, ssh_public_key="ssh-rsa AAAA...")


def _escrow_proposal() -> EscrowProposal:
    return EscrowProposal(
        chain_name="anvil",
        escrow_address=_ESCROW_ADDR_AGG,
        fields={"token": "0x" + "ab" * 20},
        expiration_unix=1_800_000_000,
    )


def _build_escrow_proposal():
    return lambda _match: _escrow_proposal()


def _build_escrow_terms_stub(proposal, seller_wallet, agreed_amount, duration_seconds):
    """Stub builder for aggregation tests — escrow terms aren't the point here."""
    return [EscrowTerms(
        maker="buyer",
        escrow_contract="0x" + "ee" * 20,
        obligation_data={
            "arbiter": "0x" + "cd" * 20,
            "demand": "0x" + "00" * 32,
            "token": proposal.fields["token"],
            "amount": int(float(agreed_amount) * max(duration_seconds, 1) / 3600),
        },
        expiration_unix=proposal.expiration_unix,
    )]


def _run_buy_with_legacy_hooks(
    *,
    config,
    constraints,
    provision,
    build_escrow_proposal,
    build_escrow_terms,
    create_escrow,
    matches=None,
    max_matches_to_try=5,
    max_negotiation_rounds=10,
    settlement_poll_interval=0,
    settlement_total_timeout=600,
    on_event=None,
    sleep=lambda _s: None,
    derive_prices=None,
    confirm_settlement=None,
    chain=None,
):
    negotiate = make_legacy_negotiate_hook(
        config=config,
        constraints=constraints,
        provision=provision,
        build_escrow_proposal=build_escrow_proposal,
        max_negotiation_rounds=max_negotiation_rounds,
        derive_prices=derive_prices,
        chain=chain,
    )
    settle = make_legacy_settle_hook(
        config=config,
        provision=provision,
        build_escrow_terms=build_escrow_terms,
        create_escrow=create_escrow,
        confirm_settlement=confirm_settlement,
        settlement_poll_interval=settlement_poll_interval,
        settlement_total_timeout=settlement_total_timeout,
        sleep=sleep,
    )
    return run_buy(
        config=config,
        constraints=constraints,
        provision=provision,
        negotiate=negotiate,
        settle=settle,
        matches=matches,
        max_matches_to_try=max_matches_to_try,
        on_event=on_event,
    )


# Echo for /negotiate/new mock replies so _settle_one can read the
# accepted proposal off the outcome.
_ACCEPTED_ECHO_AGG = {
    "accepted_provision_terms": {
        "duration_seconds": 3600,
        "ssh_public_key": "ssh-rsa AAAA...",
        "compute_resource": None,
    },
    "accepted_escrow_proposal": {
        "chain_name": "anvil",
        "escrow_address": _ESCROW_ADDR_AGG,
        "fields": {"token": "0x" + "ab" * 20},
        "expiration_unix": 1_800_000_000,
    },
}


@dataclass
class _FakeResp:
    text: str

    def read(self):
        return self.text.encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass


def _route_by_url(routes: dict[str, list]):
    """urlopen stub: pick the next response from routes[host] each call.

    routes maps a substring of the request URL to a list of responses.
    First matching key wins (so `"seller-a"` matches `"http://seller-a:8001/..."`).
    Each value is consumed in FIFO order — same convention as
    `_urlopen_sequence` but indexed by URL substring.
    """
    def _fn(req, timeout=None):
        # urlopen accepts either a Request object (signed POSTs) or a
        # bare URL string (well-known GETs).
        url = req.full_url if hasattr(req, "full_url") else str(req)
        for key, queue in routes.items():
            if key in url:
                if not queue:
                    raise AssertionError(f"No more responses for {key!r} ({url})")
                nxt = queue.pop(0)
                body = nxt if isinstance(nxt, str) else json.dumps(nxt)
                return _FakeResp(body)
        raise AssertionError(f"Unrouted URL: {url}")

    return _fn


def test_best_price_picks_lowest_agreed_not_lowest_advertised():
    """seller-a advertises lower but agrees to 80; seller-b advertises higher
    but agrees to 60. best_price must pick seller-b."""
    routes = {
        "registry": [
            {"items": [
                {"listing_id": "list-a", "seller": "http://seller-a:8001",
                 "accepted_escrows": [{"chain_name": "anvil", "escrow_address": "0xE",
                                       "literal_fields": {"token": "0x" + "ab" * 20},
                                       "rates": [{"field": "amount", "per": "hour", "value": "50"}]}]},
                {"listing_id": "list-b", "seller": "http://seller-b:8001",
                 "accepted_escrows": [{"chain_name": "anvil", "escrow_address": "0xE",
                                       "literal_fields": {"token": "0x" + "ab" * 20},
                                       "rates": [{"field": "amount", "per": "hour", "value": "70"}]}]},
            ]},
        ],
        "seller-a": [
            # /negotiate/new — seller-a accepts at 80 (worse for buyer)
            {"negotiation_id": "neg-a", "action": "accept", "proposal": {"fields": {"amount": 80}}, **_ACCEPTED_ECHO_AGG},
            # Settlement flow only runs for the *winner*; seller-a never gets here
        ],
        "seller-b": [
            # /negotiate/new — seller-b accepts at 60 (better for buyer)
            {"negotiation_id": "neg-b", "action": "accept", "proposal": {"fields": {"amount": 60}}, **_ACCEPTED_ECHO_AGG},
            # Wallet + settle for the winner
            {"agent_wallet_address": _SELLER_WALLET_B},
            {"escrow_uid": "0xescrow", "status": "provisioning"},
            {"status": "ready", "fulfillment_uid": "0xattest"},
        ],
    }

    with patch(
        "market_buyer.buy_orchestrator.urllib.request.urlopen",
        side_effect=_route_by_url(routes),
    ):
        result = _run_buy_with_legacy_hooks(
            config=_config(aggregation_policy="best_price"),
            constraints=_constraints(),
            provision=_provision(),
            build_escrow_proposal=_build_escrow_proposal(),
            build_escrow_terms=_build_escrow_terms_stub,
            create_escrow=lambda escrows: ["0xescrow"],
            sleep=lambda _: None,
        )

    assert result.status == "ready", (
        f"got status={result.status} reason={result.reason} attempts={result.attempts}"
    )
    assert result.seller_url == "http://seller-b:8001"
    assert result.agreed_amount == 60
    assert result.negotiation_id == "neg-b"
    seller_urls = {a.get("seller_url") for a in result.attempts}
    assert seller_urls == {"http://seller-a:8001", "http://seller-b:8001"}


def test_cheapest_first_preserves_first_agreed_semantics():
    """`cheapest_first` walks in advertised-price order and takes the
    first match that agrees — identical to the pre-callback loop.

    Opted into explicitly via aggregation_policy; the default is now
    `best_price`, which would negotiate with both sellers in parallel.
    """
    routes = {
        "registry": [
            {"items": [
                # Higher advertised price first in the registry response.
                {"listing_id": "expensive", "seller": "http://seller-b:8001",
                 "accepted_escrows": [{"chain_name": "anvil", "escrow_address": "0xE",
                                       "literal_fields": {"token": "0x" + "ab" * 20},
                                       "rates": [{"field": "amount", "per": "hour", "value": "70"}]}]},
                # Cheaper advertised — should be tried first under cheapest_first.
                {"listing_id": "cheap", "seller": "http://seller-a:8001",
                 "accepted_escrows": [{"chain_name": "anvil", "escrow_address": "0xE",
                                       "literal_fields": {"token": "0x" + "ab" * 20},
                                       "rates": [{"field": "amount", "per": "hour", "value": "50"}]}]},
            ]},
        ],
        "seller-a": [
            {"negotiation_id": "neg-a", "action": "accept", "proposal": {"fields": {"amount": 50}}, **_ACCEPTED_ECHO_AGG},
            {"agent_wallet_address": _SELLER_WALLET_A},
            {"escrow_uid": "0xescrow", "status": "provisioning"},
            {"status": "ready", "fulfillment_uid": "0xattest"},
        ],
        # seller-b never gets queried — cheapest_first stops at first agreed.
        "seller-b": [],
    }

    with patch(
        "market_buyer.buy_orchestrator.urllib.request.urlopen",
        side_effect=_route_by_url(routes),
    ):
        result = _run_buy_with_legacy_hooks(
            config=_config(aggregation_policy="cheapest_first"),
            constraints=_constraints(),
            provision=_provision(),
            build_escrow_proposal=_build_escrow_proposal(),
            build_escrow_terms=_build_escrow_terms_stub,
            create_escrow=lambda escrows: ["0xescrow"],
            sleep=lambda _: None,
        )

    assert result.status == "ready"
    assert result.seller_url == "http://seller-a:8001"
    assert result.agreed_amount == 50
    # Only seller-a was negotiated — cheapest_first short-circuited.
    seller_urls = {a.get("seller_url") for a in result.attempts}
    assert seller_urls == {"http://seller-a:8001"}


def test_custom_policy_can_short_circuit():
    """A user-registered policy decides when to stop — here, return the
    second candidate unconditionally without negotiating either."""

    @register_aggregation_policy("pick_second_no_negotiate")
    async def _pick_second(matches, negotiate: NegotiateFn):
        # Demonstrates the contract: the policy isn't obligated to call
        # negotiate at all. Returning a synthetic outcome means the
        # orchestrator will try to settle it — which requires us to
        # populate accepted_escrow_proposal as the seller would
        # normally have echoed back. Policies that don't negotiate are
        # responsible for synthesizing this themselves.
        if len(matches) < 2:
            return None
        return (matches[1], NegotiationOutcome(
            status="agreed",
            negotiation_id="synthetic-1",
            agreed_amount=42,
            duration_seconds=3600,
            accepted_provision_terms=_provision(),
            accepted_escrow_proposal=_escrow_proposal(),
        ))

    routes = {
        "registry": [
            {"items": [
                {"listing_id": "ignored", "seller": "http://seller-a:8001"},
                {"listing_id": "chosen", "seller": "http://seller-b:8001"},
            ]},
        ],
        # Policy didn't call negotiate, so no negotiate responses needed.
        "seller-b": [
            {"agent_wallet_address": _SELLER_WALLET_B},
            {"escrow_uid": "0xescrow", "status": "provisioning"},
            {"status": "ready"},
        ],
    }

    with patch(
        "market_buyer.buy_orchestrator.urllib.request.urlopen",
        side_effect=_route_by_url(routes),
    ):
        result = _run_buy_with_legacy_hooks(
            config=_config(aggregation_policy="pick_second_no_negotiate"),
            constraints=_constraints(),
            provision=_provision(),
            build_escrow_proposal=_build_escrow_proposal(),
            build_escrow_terms=_build_escrow_terms_stub,
            create_escrow=lambda escrows: ["0xescrow"],
            sleep=lambda _: None,
        )

    assert result.status == "ready"
    assert result.seller_url == "http://seller-b:8001"
    assert result.agreed_amount == 42


def test_policy_returning_none_yields_exited():
    @register_aggregation_policy("always_none")
    async def _always_none(matches, negotiate):
        return None

    with patch(
        "market_buyer.buy_orchestrator.urllib.request.urlopen",
        side_effect=_route_by_url({
            "registry": [
                {"items": [{"listing_id": "x", "seller": "http://seller-a:8001"}]},
            ],
        }),
    ):
        result = _run_buy_with_legacy_hooks(
            config=_config(aggregation_policy="always_none"),
            constraints=_constraints(),
            provision=_provision(),
            build_escrow_proposal=_build_escrow_proposal(),
            build_escrow_terms=_build_escrow_terms_stub,
            create_escrow=lambda escrows: ["0xnever"],
            sleep=lambda _: None,
        )

    assert result.status == "exited"
    assert result.reason == "no_match_agreed_to_terms"


def test_gather_outcomes_captures_exceptions_per_candidate():
    """The convenience helper for parallel comparison swallows per-task
    failures so one flaky seller doesn't kill the whole comparison."""
    import asyncio

    async def _flaky_negotiate(match):
        if match["listing_id"] == "broken":
            raise RuntimeError("seller down")
        return NegotiationOutcome(
            status="agreed",
            negotiation_id=f"neg-{match['listing_id']}",
            agreed_amount=50,
        )

    candidates = [
        {"listing_id": "good"},
        {"listing_id": "broken"},
        {"listing_id": "good2"},
    ]

    results = asyncio.run(gather_outcomes(_flaky_negotiate, candidates))
    assert len(results) == 3
    by_id = {c["listing_id"]: r for c, r in results}
    assert isinstance(by_id["good"], NegotiationOutcome)
    assert isinstance(by_id["broken"], RuntimeError)
    assert isinstance(by_id["good2"], NegotiationOutcome)
