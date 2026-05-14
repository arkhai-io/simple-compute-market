"""Unit tests for negotiate.guard.escrow_fields_strict_match.

The strict per-field equality check used to live in
``sync_negotiation._validate_escrow_proposal`` as protocol-enforced
behaviour. PR (c1) of the generic-escrow plan lifted it into a seller
policy so operators can swap in softer matching by editing the
composite components list — no code changes needed. These tests pin the
default (strict) behaviour and confirm the wiring through
``consult_pre_negotiation_guards``.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from domain.compute.agent.app.policy.store import (
    negotiate_guard_escrow_fields_strict_match,
)
from market_storefront.models.domain_models import (
    ActionType as DomainActionType,
    DecisionContext,
    NegotiationRequestedEvent,
)


def _ctx(
    *,
    listing: dict,
    escrow_proposal: dict | None,
    listing_id: str = "L1",
) -> DecisionContext:
    event = NegotiationRequestedEvent(
        event_id="evt-1",
        source="seller",
        listing_id=listing_id,
        listing=listing,
        proposed_price=1000,
        requested_duration_seconds=3600,
        escrow_proposal=escrow_proposal,
    )
    return DecisionContext(
        event=event,
        agent_id="seller-1",
        available_resources={"resources": []},
        market_state={},
        negotiation_history=[],
        past_experiences=[],
    )


_ADDR = "0x" + "11" * 20
_TOKEN = "0x" + "22" * 20
_OTHER_TOKEN = "0x" + "33" * 20


def _listing_with_one_escrow(**field_overrides) -> dict:
    fields = {"payment_token": _TOKEN}
    fields.update(field_overrides)
    return {
        "listing_id": "L1",
        "accepted_escrows": [
            {
                "chain_name": "anvil",
                "escrow_address": _ADDR,
                "fields": fields,
                "price_per_hour": 1000,
            }
        ],
    }


class TestPassesWhenAllFieldsMatch:
    def test_strict_equality_passes(self):
        ctx = _ctx(
            listing=_listing_with_one_escrow(),
            escrow_proposal={
                "chain_name": "anvil",
                "escrow_address": _ADDR,
                "fields": {"payment_token": _TOKEN},
            },
        )
        assert negotiate_guard_escrow_fields_strict_match(ctx) is None

    def test_address_case_insensitive(self):
        """EIP-55 checksummed addresses keep the ``0x`` prefix but mix
        case in the 40-char body; the guard must compare those as equal
        to their lowercase form to avoid spurious vetoes."""
        # Body-only upper variant (preserves "0x" prefix) — that's the
        # shape that survives EIP-55 round-trips.
        mixed_addr = "0x" + _ADDR[2:].upper()
        mixed_token = "0x" + _TOKEN[2:].upper()
        ctx = _ctx(
            listing=_listing_with_one_escrow(),
            escrow_proposal={
                "chain_name": "anvil",
                "escrow_address": mixed_addr,
                "fields": {"payment_token": mixed_token},
            },
        )
        assert negotiate_guard_escrow_fields_strict_match(ctx) is None

    def test_accepted_escrows_serialized_as_json_string(self):
        """The listing row comes off SQLite with accepted_escrows still
        JSON-encoded. The guard must decode before matching."""
        import json
        listing = _listing_with_one_escrow()
        listing["accepted_escrows"] = json.dumps(listing["accepted_escrows"])
        ctx = _ctx(
            listing=listing,
            escrow_proposal={
                "chain_name": "anvil",
                "escrow_address": _ADDR,
                "fields": {"payment_token": _TOKEN},
            },
        )
        assert negotiate_guard_escrow_fields_strict_match(ctx) is None


class TestRejectsWhenFieldDiverges:
    def test_payment_token_mismatch(self):
        ctx = _ctx(
            listing=_listing_with_one_escrow(),
            escrow_proposal={
                "chain_name": "anvil",
                "escrow_address": _ADDR,
                "fields": {"payment_token": _OTHER_TOKEN},
            },
        )
        action = negotiate_guard_escrow_fields_strict_match(ctx)
        assert action is not None
        assert action.action_type == DomainActionType.REJECT_OFFER
        reason = action.parameters["reason"]
        assert "escrow_field_mismatch" in reason
        assert "'payment_token'" in reason
        assert action.parameters["field"] == "payment_token"

    def test_buyer_omits_a_required_field(self):
        """When the seller pinned a field but the buyer didn't include
        it, the guard still vetoes (None ≠ pinned value)."""
        ctx = _ctx(
            listing=_listing_with_one_escrow(arbiter="0x" + "44" * 20),
            escrow_proposal={
                "chain_name": "anvil",
                "escrow_address": _ADDR,
                "fields": {"payment_token": _TOKEN},  # no arbiter
            },
        )
        action = negotiate_guard_escrow_fields_strict_match(ctx)
        assert action is not None
        assert action.parameters["field"] == "arbiter"


class TestPassesThroughWithoutVetoing:
    """These cases produce ``None`` — the guard declines to veto so
    other layers can decide. The veto is opinionated; absence of data
    isn't a reason to reject."""

    def test_no_proposal_passes(self):
        """Legacy buyer client without an escrow_proposal — the field
        check has nothing to compare against."""
        ctx = _ctx(
            listing=_listing_with_one_escrow(),
            escrow_proposal=None,
        )
        assert negotiate_guard_escrow_fields_strict_match(ctx) is None

    def test_listing_with_no_accepted_escrows_passes(self):
        """Publish-time synthesis couldn't resolve a chain — pinning
        nothing means the buyer is free to propose anything."""
        ctx = _ctx(
            listing={"listing_id": "L1", "accepted_escrows": []},
            escrow_proposal={
                "chain_name": "anvil",
                "escrow_address": _ADDR,
                "fields": {"payment_token": _TOKEN},
            },
        )
        assert negotiate_guard_escrow_fields_strict_match(ctx) is None

    def test_zero_address_passes(self):
        """Legacy buyer client sends the zero placeholder for
        escrow_address; structural match in sync_negotiation skips it,
        and so do we."""
        ctx = _ctx(
            listing=_listing_with_one_escrow(),
            escrow_proposal={
                "chain_name": "anvil",
                "escrow_address": "0x" + "0" * 40,
                "fields": {"payment_token": _TOKEN},
            },
        )
        assert negotiate_guard_escrow_fields_strict_match(ctx) is None

    def test_address_advertised_but_not_in_set_passes(self):
        """The structural "address not in accepted set" rejection lives
        in sync_negotiation._match_accepted_escrow. The policy callable
        declines to double-report — that would surface confusing
        error messages."""
        ctx = _ctx(
            listing=_listing_with_one_escrow(),
            escrow_proposal={
                "chain_name": "anvil",
                "escrow_address": "0x" + "99" * 20,
                "fields": {"payment_token": _TOKEN},
            },
        )
        assert negotiate_guard_escrow_fields_strict_match(ctx) is None

    def test_unrelated_event_type_passes(self):
        """The composite may be evaluated against other events during
        registry seeding probes; non-matching events are a pass."""
        from market_storefront.models.domain_models import ListingClosedEvent

        event = ListingClosedEvent(
            event_id="evt-x", source="seller", listing_id="L1",
        )
        ctx = DecisionContext(
            event=event, agent_id="seller-1",
            available_resources={}, market_state={},
            negotiation_history=[], past_experiences=[],
        )
        assert negotiate_guard_escrow_fields_strict_match(ctx) is None


class TestConsultPreNegotiationGuardsWiring:
    """Verify ``escrow_proposal`` round-trips through PolicyService into
    the event the policy callables see."""

    @pytest.mark.asyncio
    async def test_escrow_proposal_reaches_event(self, monkeypatch):
        from market_storefront.services import policy_service as ps_module
        from market_storefront.services.policy_service import PolicyService

        seen_events = []

        async def _capture(self, domain_event):
            seen_events.append(domain_event)
            return None

        monkeypatch.setattr(PolicyService, "_consult_policy", _capture)

        # Build a barebones PolicyService — we only exercise
        # consult_pre_negotiation_guards which doesn't touch the policy
        # manager when _consult_policy is stubbed.
        svc = PolicyService.__new__(PolicyService)
        svc._config = MagicMock(base_url_override="http://seller")

        proposal = {
            "chain_name": "anvil",
            "escrow_address": _ADDR,
            "fields": {"payment_token": _TOKEN},
            "expiration_unix": 9_999_999_999,
        }
        await svc.consult_pre_negotiation_guards(
            listing_id="L1",
            listing={"accepted_escrows": [], "offer_resource": {}},
            proposed_price=1000,
            requested_duration_seconds=3600,
            escrow_proposal=proposal,
        )
        assert seen_events, "policy_service did not consult policy"
        event = seen_events[0]
        assert isinstance(event, NegotiationRequestedEvent)
        assert event.escrow_proposal == proposal
