"""Unit tests for the buyer orchestrator.

The orchestrator's job is to compose discover → negotiate → create
escrow → submit settle → poll status, sequentially. Because
create_escrow is injected as a hook and all HTTP goes through
urllib.request, everything is mockable.

What the tests verify:
- Empty registry → no_matches, no further work.
- Happy path: match → agreed → escrow → submit → poll-ready → BuyResult.
- Negotiation exited on first match → advances to next.
- Escrow hook raises → exited with reason.
- Settlement ends in failed status → BuyResult.status == "failed".
- Settlement polling times out → BuyResult.status == "timeout".
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from unittest.mock import MagicMock, patch

import pytest

from service.schemas import EscrowTerms, EscrowTermsProposal, ProvisionTerms

from market_buyer.buy_orchestrator import (
    AgreedTerms,
    BuyConfig,
    BuyConstraints,
    BuyResult,
    run_buy,
)


_BUYER_PK = "0x" + "11" * 32
_BUYER_ADDR = "0x" + "cc" * 20
_SELLER_URL = "http://seller:8001"
_SELLER_WALLET = "0x" + "bb" * 20
_REGISTRY = "http://registry:4000"
_ERC20_ESCROW = "0x" + "ee" * 20
_RECIPIENT_ARBITER = "0x" + "cd" * 20
_TOKEN = "0x" + "ab" * 20


def _config(order_id: str = "buyer-1") -> BuyConfig:
    return BuyConfig(
        registry_urls=[_REGISTRY],
        buyer_address=_BUYER_ADDR,
        buyer_private_key=_BUYER_PK,
    )


def _constraints(max_price=100, initial_price=50) -> BuyConstraints:
    return BuyConstraints(
        max_price=max_price,
        initial_price=initial_price,
    )


def _provision(duration_seconds=7200, ssh_public_key="ssh-rsa AAAA...") -> ProvisionTerms:
    return ProvisionTerms(
        duration_seconds=duration_seconds,
        ssh_public_key=ssh_public_key,
    )


def _escrow_proposal() -> EscrowTermsProposal:
    return EscrowTermsProposal(
        escrow_kind="erc20_non_tierable",
        arbiter_kind="recipient",
        payment_token=_TOKEN,
        expiration_unix=1_800_000_000,
    )


def _stub_escrow_terms(seller_wallet, agreed_price, duration_seconds):
    """An ERC20-shaped EscrowTerms for tests that don't care about codec details."""
    return EscrowTerms(
        maker="buyer",
        escrow_contract=_ERC20_ESCROW,
        obligation_data={
            "arbiter": _RECIPIENT_ARBITER,
            "demand": "0x" + "00" * 31 + seller_wallet[2:].rjust(2, "0"),
            "token": _TOKEN,
            "amount": int(agreed_price) * int(max(duration_seconds, 1)) // 3600,
        },
        expiration_unix=1_800_000_000,
    )


def _build_escrow_terms_ok(seller_wallet, agreed_price, duration_seconds):
    return [_stub_escrow_terms(seller_wallet, agreed_price, duration_seconds)]


@dataclass
class _FakeResp:
    text: str

    def read(self):
        return self.text.encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass


def _urlopen_sequence(responses):
    """Return a urlopen stub that yields the given response bodies in order.

    Each item is either a dict (JSON-encoded → 200 OK body) or a raw
    string (used verbatim).
    """
    queue = list(responses)

    def _fn(req, timeout=None):
        if not queue:
            raise AssertionError(f"Unexpected urlopen call: {req.full_url}")
        nxt = queue.pop(0)
        body = nxt if isinstance(nxt, str) else json.dumps(nxt)
        return _FakeResp(body)

    return _fn


# ---------------------------------------------------------------------------
# Discovery path
# ---------------------------------------------------------------------------


def test_no_matches_returns_no_matches_status():
    with patch(
        "market_buyer.buy_orchestrator.urllib.request.urlopen",
        side_effect=_urlopen_sequence([{"items": []}]),
    ):
        result = run_buy(
            config=_config(),
            constraints=_constraints(),
            provision=_provision(),
            escrow_terms_proposal=_escrow_proposal(),
            build_escrow_terms=_build_escrow_terms_ok,
            create_escrow=lambda escrows: ["0xnever"],
        )
    assert result.status == "no_matches"


def test_matches_can_be_preseeded_skipping_registry_query():
    """When caller passes matches directly, registry is never hit."""
    # Negotiation immediately exits so we don't need escrow/settle stubs.
    with patch(
        "market_buyer.buy_orchestrator.urllib.request.urlopen",
        side_effect=_urlopen_sequence([
            # /negotiate/new → seller exits
            {"negotiation_id": "neg-1", "action": "exit",
             "reason": "no_matching_order"},
        ]),
    ):
        result = run_buy(
            config=_config(),
            constraints=_constraints(),
            provision=_provision(),
            escrow_terms_proposal=_escrow_proposal(),
            build_escrow_terms=_build_escrow_terms_ok,
            create_escrow=lambda escrows: ["0xnever"],
            matches=[{"listing_id": "seller-1", "seller": _SELLER_URL}],
        )
    assert result.status == "exited"
    assert result.attempts and result.attempts[0]["outcome"]["status"] == "exited"


# ---------------------------------------------------------------------------
# Happy path end-to-end
# ---------------------------------------------------------------------------


def test_happy_path_drives_to_ready():
    """Full flow: discovery → negotiation (immediate accept) → escrow → submit → poll ready."""
    responses = [
        # 1. registry GET
        {"items": [{"listing_id": "seller-1", "seller": _SELLER_URL,
                      "max_duration_seconds": 7200}]},
        # 2. /negotiate/new — seller accepts immediately
        {"negotiation_id": "neg-1", "action": "accept", "price": 50},
        # 3. GET /.well-known/agent-wallet.json on seller
        {"agent_wallet_address": _SELLER_WALLET},
        # 4. POST /settle/{uid}
        {"escrow_uid": "0xescrow", "status": "provisioning"},
        # 5. GET /settle/{uid}/status → ready
        {"status": "ready",
         "attestation_uid": "0xattest",
         "connection_details": "ssh alice@vm1",
         "tenant_credentials": {"password": "hunter2"}},
    ]

    build_calls: list[tuple[str, int, int]] = []
    create_calls: list[list[EscrowTerms]] = []

    def _build_escrow_terms(seller_wallet, agreed_price, duration_seconds):
        build_calls.append((seller_wallet, agreed_price, duration_seconds))
        return [_stub_escrow_terms(seller_wallet, agreed_price, duration_seconds)]

    def _create_escrow(escrows):
        create_calls.append(escrows)
        return ["0xescrow"]

    events: list[tuple[str, dict]] = []

    with patch(
        "market_buyer.buy_orchestrator.urllib.request.urlopen",
        side_effect=_urlopen_sequence(responses),
    ):
        result = run_buy(
            config=_config(),
            constraints=_constraints(),
            provision=_provision(),
            escrow_terms_proposal=_escrow_proposal(),
            build_escrow_terms=_build_escrow_terms,
            create_escrow=_create_escrow,
            on_event=lambda name, body: events.append((name, body)),
            sleep=lambda _s: None,
        )

    assert result.status == "ready"
    assert result.escrow_uid == "0xescrow"
    assert result.attestation_uid == "0xattest"
    assert result.connection_details == "ssh alice@vm1"
    assert result.tenant_credentials == {"password": "hunter2"}
    assert result.agreed_price == 50
    assert result.negotiation_id == "neg-1"

    # build_escrow_terms received the negotiated agreement.
    assert build_calls == [(_SELLER_WALLET, 50, 7200)]
    # create_escrow received the canonical EscrowTerms list.
    assert len(create_calls) == 1
    assert len(create_calls[0]) == 1
    assert create_calls[0][0].maker == "buyer"
    assert create_calls[0][0].obligation_data["token"] == _TOKEN
    # amount = price × duration / 3600 = 50 × 7200 / 3600 = 100
    assert create_calls[0][0].obligation_data["amount"] == 100

    # Observer saw the key stages.
    stages = [name for name, _ in events]
    assert "discover" in stages
    assert "negotiation_started" in stages
    assert "negotiation_completed" in stages
    assert "escrow_created" in stages
    assert "settlement_submitted" in stages
    assert any(s == "settlement_poll" for s in stages)


# ---------------------------------------------------------------------------
# Negotiation fallthrough
# ---------------------------------------------------------------------------


def test_first_match_exits_second_agrees():
    # Use cheapest_first (sequential) since this test exercises
    # the "first match exits, fall through to second" semantic.
    # The default best_price runs negotiations in parallel, which
    # races for the FIFO urlopen mock and makes the test flaky.
    config = BuyConfig(
        registry_urls=[_REGISTRY],
        buyer_address=_BUYER_ADDR,
        buyer_private_key=_BUYER_PK,
        aggregation_policy="cheapest_first",
    )
    responses = [
        # Registry returns two matches
        {"items": [
            {"listing_id": "seller-1", "seller": "http://seller1:8001"},
            {"listing_id": "seller-2", "seller": "http://seller2:8001",
             "max_duration_seconds": 3600},
        ]},
        # /negotiate/new on seller1 — exits
        {"negotiation_id": "neg-1", "action": "exit",
         "reason": "price_unreasonable"},
        # /negotiate/new on seller2 — accepts
        {"negotiation_id": "neg-2", "action": "accept", "price": 50},
        # Seller2 wallet
        {"agent_wallet_address": _SELLER_WALLET},
        # POST /settle/{uid}
        {"escrow_uid": "0xescrow", "status": "provisioning"},
        # GET /settle/{uid}/status → ready
        {"status": "ready", "attestation_uid": "0xattest"},
    ]
    with patch(
        "market_buyer.buy_orchestrator.urllib.request.urlopen",
        side_effect=_urlopen_sequence(responses),
    ):
        result = run_buy(
            config=config,
            constraints=_constraints(),
            provision=_provision(),
            escrow_terms_proposal=_escrow_proposal(),
            build_escrow_terms=_build_escrow_terms_ok,
            create_escrow=lambda escrows: ["0xescrow"],
            sleep=lambda _: None,
        )
    assert result.status == "ready"
    assert result.seller_url == "http://seller2:8001"
    # Two attempts recorded — first was exit, second was agreed.
    assert len(result.attempts) == 2
    assert result.attempts[0]["outcome"]["status"] == "exited"


# ---------------------------------------------------------------------------
# Escrow hook failure
# ---------------------------------------------------------------------------


def test_escrow_hook_failure_returns_exited_with_reason():
    responses = [
        {"items": [{"listing_id": "seller-1", "seller": _SELLER_URL}]},
        {"negotiation_id": "neg-1", "action": "accept", "price": 50},
        {"agent_wallet_address": _SELLER_WALLET},
    ]

    def _broken_escrow(escrows):
        raise RuntimeError("chain RPC down")

    with patch(
        "market_buyer.buy_orchestrator.urllib.request.urlopen",
        side_effect=_urlopen_sequence(responses),
    ):
        result = run_buy(
            config=_config(),
            constraints=_constraints(),
            provision=_provision(),
            escrow_terms_proposal=_escrow_proposal(),
            build_escrow_terms=_build_escrow_terms_ok,
            create_escrow=_broken_escrow,
            sleep=lambda _: None,
        )
    assert result.status == "exited"
    assert "chain RPC down" in (result.reason or "")


# ---------------------------------------------------------------------------
# Settlement terminal = failed
# ---------------------------------------------------------------------------


def test_provisioning_failed_returns_failed_status():
    responses = [
        {"items": [{"listing_id": "seller-1", "seller": _SELLER_URL}]},
        {"negotiation_id": "neg-1", "action": "accept", "price": 50},
        {"agent_wallet_address": _SELLER_WALLET},
        {"escrow_uid": "0xescrow", "status": "provisioning"},
        {"status": "failed", "reason": "no available VM"},
    ]
    with patch(
        "market_buyer.buy_orchestrator.urllib.request.urlopen",
        side_effect=_urlopen_sequence(responses),
    ):
        result = run_buy(
            config=_config(),
            constraints=_constraints(),
            provision=_provision(),
            escrow_terms_proposal=_escrow_proposal(),
            build_escrow_terms=_build_escrow_terms_ok,
            create_escrow=lambda escrows: ["0xescrow"],
            sleep=lambda _: None,
        )
    assert result.status == "failed"
    assert result.escrow_uid == "0xescrow"
    assert "no available VM" in (result.reason or "")


# ---------------------------------------------------------------------------
# Settlement polling timeout
# ---------------------------------------------------------------------------


def test_settlement_timeout_returns_timeout_status():
    """Seller stays provisioning past the timeout → status=timeout."""
    responses = [
        {"items": [{"listing_id": "seller-1", "seller": _SELLER_URL}]},
        {"negotiation_id": "neg-1", "action": "accept", "price": 50},
        {"agent_wallet_address": _SELLER_WALLET},
        {"escrow_uid": "0xescrow", "status": "provisioning"},
    ] + [{"status": "provisioning"}] * 50  # never terminal

    with patch(
        "market_buyer.buy_orchestrator.urllib.request.urlopen",
        side_effect=_urlopen_sequence(responses),
    ):
        result = run_buy(
            config=_config(),
            constraints=_constraints(),
            provision=_provision(),
            escrow_terms_proposal=_escrow_proposal(),
            build_escrow_terms=_build_escrow_terms_ok,
            create_escrow=lambda escrows: ["0xescrow"],
            settlement_poll_interval=0.01,
            settlement_total_timeout=0.05,  # very short
            sleep=lambda _: None,
        )
    assert result.status == "timeout"
    assert result.escrow_uid == "0xescrow"


# ---------------------------------------------------------------------------
# BuyResult.to_dict shape
# ---------------------------------------------------------------------------


def test_to_dict_omits_none_fields():
    r = BuyResult(
        status="ready",
        negotiation_id="neg-1",
        seller_url=_SELLER_URL,
        agreed_price=50,
        escrow_uid="0xescrow",
        attestation_uid="0xattest",
        connection_details="ssh alice@vm",
        rounds=3,
    )
    d = r.to_dict()
    assert d["status"] == "ready"
    assert d["agreed_price"] == 50
    assert "reason" not in d
    assert "tenant_credentials" not in d


def test_to_dict_skips_empty_attempts_list():
    r = BuyResult(status="no_matches")
    assert r.to_dict() == {"status": "no_matches", "rounds": 0}
