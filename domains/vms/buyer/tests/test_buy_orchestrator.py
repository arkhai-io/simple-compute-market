"""Unit tests for the buyer orchestrator.

The orchestrator's job is to compose discover → negotiate → settle.
The current compute instantiation still adapts create_escrow into the
settle hook, and all HTTP goes through urllib.request, so everything is
mockable.

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

from market_core.schemas import EscrowProposal, EscrowTerms
from arkhai_vms_common import VmProvisionTerms, make_vm_provision_terms

_ESCROW_ADDR = "0x" + "cd" * 20

from domains.vms.buyer.buy_orchestrator import (
    AgreedTerms,
    BuyConfig,
    BuyConstraints,
    NegotiationResult,
    BuyResult,
    make_legacy_negotiate_hook,
    make_legacy_settle_hook,
    run_buy,
    submit_settlement,
)
from domains.vms.buyer.buyer_client import NegotiationOutcome


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


def _provision(duration_seconds=7200, ssh_public_key="ssh-rsa AAAA...") -> VmProvisionTerms:
    return make_vm_provision_terms(
        duration_seconds=duration_seconds,
        ssh_public_key=ssh_public_key,
    )


def _escrow_proposal() -> EscrowProposal:
    return EscrowProposal(
        chain_name="anvil",
        escrow_address=_ESCROW_ADDR,
        fields={"token": _TOKEN},
        expiration_unix=1_800_000_000,
    )


def _build_escrow_proposal():
    """Test-fixture factory: returns the same proposal regardless of match."""
    return lambda _match: _escrow_proposal()


# Seller-echoed accept-time terms: must be included in /negotiate/new mock
# replies so _settle_one can read outcome.accepted_escrow_proposal
# and dispatch escrow construction off it.
_ACCEPTED_ECHO = {
    "accepted_provision_terms": _provision().model_dump(),
    "accepted_escrow_proposal": {
        "chain_name": "anvil",
        "escrow_address": _ESCROW_ADDR,
        "fields": {"token": _TOKEN},
        "demands": [{
            "chain_name": "anvil",
            "arbiter": _RECIPIENT_ARBITER,
            "demand_data": {"recipient": _SELLER_WALLET},
        }],
        "expiration_unix": 1_800_000_000,
    },
}


def _stub_escrow_terms(seller_wallet, agreed_amount, duration_seconds):
    """An ERC20-shaped EscrowTerms for tests that don't care about codec details."""
    return EscrowTerms(
        maker="buyer",
        escrow_contract=_ERC20_ESCROW,
        obligation_data={
            "arbiter": _RECIPIENT_ARBITER,
            "demand": "0x" + "00" * 31 + seller_wallet[2:].rjust(2, "0"),
            "token": _TOKEN,
            "amount": int(float(agreed_amount) * max(duration_seconds, 1) / 3600),
        },
        expiration_unix=1_800_000_000,
    )


def _build_escrow_terms_ok(proposal, seller_wallet, agreed_amount, duration_seconds):
    return [_stub_escrow_terms(seller_wallet, agreed_amount, duration_seconds)]


def _run_buy_with_legacy_hooks(
    *,
    config,
    constraints,
    provision,
    build_escrow_proposal=None,
    build_escrow_terms=None,
    create_escrow=None,
    negotiate=None,
    settle=None,
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
    if negotiate is None:
        negotiate = make_legacy_negotiate_hook(
            config=config,
            constraints=constraints,
            provision=provision,
            build_escrow_proposal=build_escrow_proposal,
            max_negotiation_rounds=max_negotiation_rounds,
            derive_prices=derive_prices,
            chain=chain,
        )
    if settle is None:
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
        "core_buyer.orchestration.urllib.request.urlopen",
        side_effect=_urlopen_sequence([{"items": []}]),
    ):
        result = _run_buy_with_legacy_hooks(
            config=_config(),
            constraints=_constraints(),
            provision=_provision(),
            build_escrow_proposal=_build_escrow_proposal(),
            build_escrow_terms=_build_escrow_terms_ok,
            create_escrow=lambda escrows: ["0xnever"],
        )
    assert result.status == "no_matches"


def test_matches_can_be_preseeded_skipping_registry_query():
    """When caller passes matches directly, registry is never hit."""
    # Negotiation immediately exits so we don't need escrow/settle stubs.
    with patch(
        "core_buyer.orchestration.urllib.request.urlopen",
        side_effect=_urlopen_sequence([
            # /negotiate/new → seller exits
            {"negotiation_id": "neg-1", "action": "exit",
             "reason": "no_matching_order"},
        ]),
    ):
        result = _run_buy_with_legacy_hooks(
            config=_config(),
            constraints=_constraints(),
            provision=_provision(),
            build_escrow_proposal=_build_escrow_proposal(),
            build_escrow_terms=_build_escrow_terms_ok,
            create_escrow=lambda escrows: ["0xnever"],
            matches=[{"listing_id": "seller-1", "seller": _SELLER_URL}],
        )
    assert result.status == "exited"
    assert result.attempts and result.attempts[0]["outcome"]["status"] == "exited"


def test_run_buy_composes_high_level_negotiate_and_settle_hooks():
    """The core surface can be driven with only negotiate + settle hooks."""
    matches = [
        {"listing_id": "seller-1", "seller": _SELLER_URL},
        {"listing_id": "seller-2", "seller": "http://other-seller:8001"},
    ]
    calls: list[tuple[str, object]] = []

    def _negotiate(candidate_matches, emit):
        calls.append(("negotiate_matches", candidate_matches))
        emit("custom_negotiate", {"count": len(candidate_matches)})
        return NegotiationResult(
            match=candidate_matches[0],
            outcome=NegotiationOutcome(
                status="agreed",
                negotiation_id="neg-custom",
                agreed_amount=77,
                rounds=1,
            ),
            attempts=[{"listing_id": "seller-1", "outcome": {"status": "agreed"}}],
        )

    def _settle(negotiation, emit):
        calls.append(("settle", negotiation.match))
        emit("custom_settle", {"negotiation_id": negotiation.outcome.negotiation_id})
        return BuyResult(
            status="ready",
            negotiation_id=negotiation.outcome.negotiation_id,
            seller_url=negotiation.match["seller"],
            agreed_amount=negotiation.outcome.agreed_amount,
            escrow_uid="0xcustom",
            rounds=negotiation.outcome.rounds,
            attempts=negotiation.attempts,
        )

    events: list[tuple[str, dict]] = []
    result = _run_buy_with_legacy_hooks(
        config=_config(),
        constraints=_constraints(),
        provision=_provision(),
        matches=matches,
        max_matches_to_try=1,
        negotiate=_negotiate,
        settle=_settle,
        on_event=lambda name, body: events.append((name, body)),
    )

    assert result.status == "ready"
    assert result.negotiation_id == "neg-custom"
    assert result.escrow_uid == "0xcustom"
    assert calls == [
        ("negotiate_matches", [matches[0]]),
        ("settle", matches[0]),
    ]
    assert ("custom_negotiate", {"count": 1}) in events
    assert ("custom_settle", {"negotiation_id": "neg-custom"}) in events


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
        {"negotiation_id": "neg-1", "action": "accept", "proposal": {"fields": {"amount": 50}}, **_ACCEPTED_ECHO},
        # 3. POST /settle/{uid}
        {"escrow_uid": "0xescrow", "status": "provisioning"},
        # 4. GET /settle/{uid}/status -> ready
        {"status": "ready",
         "fulfillment_uid": "0xattest",
         "connection_details": "ssh alice@vm1",
         "tenant_credentials": {"password": "hunter2"}},
    ]

    build_calls: list[tuple[EscrowProposal, str, int, int]] = []
    create_calls: list[list[EscrowTerms]] = []

    def _build_escrow_terms(proposal, seller_wallet, agreed_amount, duration_seconds):
        build_calls.append((proposal, seller_wallet, agreed_amount, duration_seconds))
        return [_stub_escrow_terms(seller_wallet, agreed_amount, duration_seconds)]

    def _create_escrow(escrows):
        create_calls.append(escrows)
        return ["0xescrow"]

    events: list[tuple[str, dict]] = []

    with patch(
        "core_buyer.orchestration.urllib.request.urlopen",
        side_effect=_urlopen_sequence(responses),
    ):
        result = _run_buy_with_legacy_hooks(
            config=_config(),
            constraints=_constraints(),
            provision=_provision(),
            build_escrow_proposal=_build_escrow_proposal(),
            build_escrow_terms=_build_escrow_terms,
            create_escrow=_create_escrow,
            on_event=lambda name, body: events.append((name, body)),
            sleep=lambda _s: None,
        )

    assert result.status == "ready"
    assert result.escrow_uid == "0xescrow"
    assert result.fulfillment_uid == "0xattest"
    assert result.connection_details == "ssh alice@vm1"
    assert result.tenant_credentials == {"password": "hunter2"}
    assert result.agreed_amount == 50
    assert result.negotiation_id == "neg-1"

    # build_escrow_terms received the proposal echoed by the seller +
    # the negotiated agreement.
    assert len(build_calls) == 1
    captured_proposal, captured_seller, captured_price, captured_duration = build_calls[0]
    assert captured_proposal.chain_name == "anvil"
    assert captured_proposal.escrow_address == _ESCROW_ADDR
    assert captured_proposal.fields["token"] == _TOKEN
    assert (captured_seller, captured_price, captured_duration) == (_SELLER_WALLET, 50, 7200)
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
        {"negotiation_id": "neg-2", "action": "accept", "proposal": {"fields": {"amount": 50}}, **_ACCEPTED_ECHO},
        # POST /settle/{uid}
        {"escrow_uid": "0xescrow", "status": "provisioning"},
        # GET /settle/{uid}/status → ready
        {"status": "ready", "fulfillment_uid": "0xattest"},
    ]
    with patch(
        "core_buyer.orchestration.urllib.request.urlopen",
        side_effect=_urlopen_sequence(responses),
    ):
        result = _run_buy_with_legacy_hooks(
            config=config,
            constraints=_constraints(),
            provision=_provision(),
            build_escrow_proposal=_build_escrow_proposal(),
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
        {"negotiation_id": "neg-1", "action": "accept", "proposal": {"fields": {"amount": 50}}, **_ACCEPTED_ECHO},
    ]

    def _broken_escrow(escrows):
        raise RuntimeError("chain RPC down")

    with patch(
        "core_buyer.orchestration.urllib.request.urlopen",
        side_effect=_urlopen_sequence(responses),
    ):
        result = _run_buy_with_legacy_hooks(
            config=_config(),
            constraints=_constraints(),
            provision=_provision(),
            build_escrow_proposal=_build_escrow_proposal(),
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
        {"negotiation_id": "neg-1", "action": "accept", "proposal": {"fields": {"amount": 50}}, **_ACCEPTED_ECHO},
        {"escrow_uid": "0xescrow", "status": "provisioning"},
        {"status": "failed", "reason": "no available VM"},
    ]
    with patch(
        "core_buyer.orchestration.urllib.request.urlopen",
        side_effect=_urlopen_sequence(responses),
    ):
        result = _run_buy_with_legacy_hooks(
            config=_config(),
            constraints=_constraints(),
            provision=_provision(),
            build_escrow_proposal=_build_escrow_proposal(),
            build_escrow_terms=_build_escrow_terms_ok,
            create_escrow=lambda escrows: ["0xescrow"],
            sleep=lambda _: None,
        )
    assert result.status == "failed"
    assert result.escrow_uid == "0xescrow"
    assert "no available VM" in (result.reason or "")


# ---------------------------------------------------------------------------
# Counter policy
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Settlement polling timeout
# ---------------------------------------------------------------------------


def test_settlement_timeout_returns_timeout_status():
    """Seller stays provisioning past the timeout → status=timeout."""
    responses = [
        {"items": [{"listing_id": "seller-1", "seller": _SELLER_URL}]},
        {"negotiation_id": "neg-1", "action": "accept", "proposal": {"fields": {"amount": 50}}, **_ACCEPTED_ECHO},
        {"escrow_uid": "0xescrow", "status": "provisioning"},
    ] + [{"status": "provisioning"}] * 50  # never terminal

    with patch(
        "core_buyer.orchestration.urllib.request.urlopen",
        side_effect=_urlopen_sequence(responses),
    ):
        result = _run_buy_with_legacy_hooks(
            config=_config(),
            constraints=_constraints(),
            provision=_provision(),
            build_escrow_proposal=_build_escrow_proposal(),
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
        agreed_amount=50,
        escrow_uid="0xescrow",
        fulfillment_uid="0xattest",
        connection_details="ssh alice@vm",
        rounds=3,
    )
    d = r.to_dict()
    assert d["status"] == "ready"
    assert d["agreed_amount"] == 50
    assert "reason" not in d
    assert "tenant_credentials" not in d


def test_to_dict_skips_empty_attempts_list():
    r = BuyResult(status="no_matches")
    assert r.to_dict() == {"status": "no_matches", "rounds": 0}


def _settle_kwargs():
    return dict(
        seller_url=_SELLER_URL,
        escrow_uid="0x" + "ff" * 32,
        negotiation_id="neg-1",
        ssh_public_key="ssh-rsa AAAA...",
        buyer_address=_BUYER_ADDR,
        buyer_private_key=_BUYER_PK,
        chain_name="anvil",
    )


def test_submit_settlement_retries_on_propagation_lag(monkeypatch):
    """A 400 with the seller's chain-read-failed detail should retry."""
    calls = {"n": 0}

    def fake_signed_json(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError(
                "POST .../settle/0xff... -> HTTP 400: "
                "{\"detail\":\"Failed to read escrow 0xff... from chain: "
                "ABI decoding failed: buffer overrun while deserializing\"}"
            )
        return {"escrow_uid": "0x" + "ff" * 32, "status": "provisioning"}

    sleeps: list[float] = []
    monkeypatch.setattr("core_buyer.orchestration._signed_json", fake_signed_json)
    out = submit_settlement(**_settle_kwargs(), sleep=sleeps.append, retry_backoff=0.0)

    assert out["status"] == "provisioning"
    assert calls["n"] == 3
    assert sleeps == [0.0, 0.0]


def test_submit_settlement_does_not_retry_other_400s(monkeypatch):
    """A 400 that's not the propagation-lag pattern bubbles up immediately."""
    calls = {"n": 0}

    def fake_signed_json(*args, **kwargs):
        calls["n"] += 1
        raise RuntimeError(
            "POST .../settle/0xff... -> HTTP 400: "
            "{\"detail\":\"agreed_amount mismatch: 1000000 vs 2000000\"}"
        )

    monkeypatch.setattr("core_buyer.orchestration._signed_json", fake_signed_json)
    with pytest.raises(RuntimeError, match="agreed_amount mismatch"):
        submit_settlement(**_settle_kwargs(), sleep=lambda _s: None)
    assert calls["n"] == 1


def test_submit_settlement_gives_up_after_max_attempts(monkeypatch):
    """Persistent propagation-lag errors eventually raise."""
    calls = {"n": 0}

    def fake_signed_json(*args, **kwargs):
        calls["n"] += 1
        raise RuntimeError(
            "POST .../settle/0xff... -> HTTP 400: "
            "{\"detail\":\"Failed to read escrow 0xff... from chain: "
            "ABI decoding failed: buffer overrun while deserializing\"}"
        )

    monkeypatch.setattr("core_buyer.orchestration._signed_json", fake_signed_json)
    with pytest.raises(RuntimeError, match="buffer overrun"):
        submit_settlement(
            **_settle_kwargs(),
            sleep=lambda _s: None,
            max_attempts=4,
            retry_backoff=0.0,
        )
    assert calls["n"] == 4
