"""Unit tests for the escrow-shape guard middleware.

The strict per-field equality check is a seller policy expressed as a
middleware (``market_policy.negotiation_middleware.escrow_shape_guard``).
Operators swap in softer matching by editing ``[negotiation].chain`` in
their seller config — no code changes needed.

These tests pin the default (strict) behaviour against the middleware
directly: given a (history, context), assert the returned step.
"""
from __future__ import annotations

from market_policy.negotiation_middleware import (
    NegotiationContext,
    NegotiationRound,
    escrow_shape_guard,
)


def _ctx(
    *,
    listing: dict,
    escrow_proposal: dict | None,
) -> tuple[list[NegotiationRound], NegotiationContext]:
    """Build (history, context) for the seller-side escrow_shape_guard.

    The guard reads the buyer's proposal from the latest "them" round in
    history (not from context). Tests pass the proposal in via this
    helper, which wraps it as a round-0 ``initial`` entry. ``None``
    means the buyer didn't include a proposal (legacy client).
    """
    history: list[NegotiationRound] = []
    if escrow_proposal is not None:
        history.append(NegotiationRound(
            round_number=0,
            sender="them",
            action="initial",
            proposal=escrow_proposal,
        ))
    context = NegotiationContext(
        direction="maximize",
        our_reference_amount=1000.0,
        listing=listing,
        available_resources={},
    )
    return history, context


_ADDR = "0x" + "11" * 20
_TOKEN = "0x" + "22" * 20
_OTHER_TOKEN = "0x" + "33" * 20


def _listing_with_one_escrow(**field_overrides) -> dict:
    fields = {"token": _TOKEN}
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
        history, ctx = _ctx(
            listing=_listing_with_one_escrow(),
            escrow_proposal={
                "chain_name": "anvil",
                "escrow_address": _ADDR,
                "fields": {"token": _TOKEN},
            },
        )
        decision, _ctx_out = escrow_shape_guard(history, ctx)
        assert decision is None

    def test_address_case_insensitive(self):
        """EIP-55 checksummed addresses keep the ``0x`` prefix but mix
        case in the 40-char body; the guard must compare those as equal
        to their lowercase form to avoid spurious vetoes."""
        mixed_addr = "0x" + _ADDR[2:].upper()
        mixed_token = "0x" + _TOKEN[2:].upper()
        history, ctx = _ctx(
            listing=_listing_with_one_escrow(),
            escrow_proposal={
                "chain_name": "anvil",
                "escrow_address": mixed_addr,
                "fields": {"token": mixed_token},
            },
        )
        decision, _ = escrow_shape_guard(history, ctx)
        assert decision is None

    def test_accepted_escrows_serialized_as_json_string(self):
        """The listing row comes off SQLite with accepted_escrows still
        JSON-encoded. The guard must decode before matching."""
        import json
        listing = _listing_with_one_escrow()
        listing["accepted_escrows"] = json.dumps(listing["accepted_escrows"])
        history, ctx = _ctx(
            listing=listing,
            escrow_proposal={
                "chain_name": "anvil",
                "escrow_address": _ADDR,
                "fields": {"token": _TOKEN},
            },
        )
        decision, _ = escrow_shape_guard(history, ctx)
        assert decision is None


class TestRejectsWhenFieldDiverges:
    def test_token_mismatch(self):
        history, ctx = _ctx(
            listing=_listing_with_one_escrow(),
            escrow_proposal={
                "chain_name": "anvil",
                "escrow_address": _ADDR,
                "fields": {"token": _OTHER_TOKEN},
            },
        )
        decision, _ = escrow_shape_guard(history, ctx)
        assert decision is not None
        assert decision.action == "reject"
        assert "escrow_field_mismatch" in (decision.reason or "")
        assert "'token'" in (decision.reason or "")

    def test_buyer_omits_a_required_field(self):
        """When the seller pinned a field but the buyer didn't include
        it, the guard still vetoes (None ≠ pinned value)."""
        history, ctx = _ctx(
            listing=_listing_with_one_escrow(arbiter="0x" + "44" * 20),
            escrow_proposal={
                "chain_name": "anvil",
                "escrow_address": _ADDR,
                "fields": {"token": _TOKEN},  # no arbiter
            },
        )
        decision, _ = escrow_shape_guard(history, ctx)
        assert decision is not None
        assert decision.action == "reject"
        assert "'arbiter'" in (decision.reason or "")


class TestPassesThroughWithoutVetoing:
    """These cases produce ``None`` — the guard declines to veto so
    other layers can decide. The veto is opinionated; absence of data
    isn't a reason to reject."""

    def test_no_proposal_passes(self):
        """Legacy buyer client without an escrow_proposal — the field
        check has nothing to compare against."""
        history, ctx = _ctx(
            listing=_listing_with_one_escrow(),
            escrow_proposal=None,
        )
        decision, _ = escrow_shape_guard(history, ctx)
        assert decision is None

    def test_listing_with_no_accepted_escrows_passes(self):
        """Publish-time synthesis couldn't resolve a chain — pinning
        nothing means the buyer is free to propose anything."""
        history, ctx = _ctx(
            listing={"listing_id": "L1", "accepted_escrows": []},
            escrow_proposal={
                "chain_name": "anvil",
                "escrow_address": _ADDR,
                "fields": {"token": _TOKEN},
            },
        )
        decision, _ = escrow_shape_guard(history, ctx)
        assert decision is None

    def test_zero_address_passes(self):
        """Legacy buyer client sends the zero placeholder for
        escrow_address; structural match in sync_negotiation skips it,
        and so do we."""
        history, ctx = _ctx(
            listing=_listing_with_one_escrow(),
            escrow_proposal={
                "chain_name": "anvil",
                "escrow_address": "0x" + "0" * 40,
                "fields": {"token": _TOKEN},
            },
        )
        decision, _ = escrow_shape_guard(history, ctx)
        assert decision is None

    def test_address_advertised_but_not_in_set_passes(self):
        """The structural "address not in accepted set" rejection lives
        in sync_negotiation._match_accepted_escrow. The middleware
        declines to double-report — that would surface confusing
        error messages."""
        history, ctx = _ctx(
            listing=_listing_with_one_escrow(),
            escrow_proposal={
                "chain_name": "anvil",
                "escrow_address": "0x" + "99" * 20,
                "fields": {"token": _TOKEN},
            },
        )
        decision, _ = escrow_shape_guard(history, ctx)
        assert decision is None
