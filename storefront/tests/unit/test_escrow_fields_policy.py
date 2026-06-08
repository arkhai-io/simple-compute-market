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
    accept_exact_listing_middleware,
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
_ARBITER = "0x" + "44" * 20
_RECIPIENT = "0x" + "55" * 20


def _listing_with_one_escrow(**field_overrides) -> dict:
    fields = {"token": _TOKEN}
    fields.update(field_overrides)
    return {
        "listing_id": "L1",
        "accepted_escrows": [
            {
                "chain_name": "anvil",
                "escrow_address": _ADDR,
                "literal_fields": fields,
                "rates": [{"field": "amount", "per": "hour", "value": "1000"}],
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
                "literal_fields": {"token": _TOKEN},
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
                "literal_fields": {"token": mixed_token},
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
                "literal_fields": {"token": _TOKEN},
            },
        )
        decision, _ = escrow_shape_guard(history, ctx)
        assert decision is None


class TestAcceptExactListing:
    def _proposal(self, **overrides) -> dict:
        proposal = {
            "chain_name": "anvil",
            "escrow_address": _ADDR,
            "fields": {"token": _TOKEN, "amount": 1000},
            "literal_fields": {"token": _TOKEN},
            "rates": [{"field": "amount", "per": "hour", "value": "1000"}],
            "demands": [],
        }
        proposal.update(overrides)
        return proposal

    def test_accepts_exact_listing_escrow(self):
        history, ctx = _ctx(
            listing=_listing_with_one_escrow(),
            escrow_proposal=self._proposal(),
        )
        decision, _ = accept_exact_listing_middleware(history, ctx)
        assert decision is not None
        assert decision.action == "accept"
        assert decision.reason == "exact_listing"
        assert decision.proposal["fields"]["amount"] == 1000

    def test_accepted_escrows_can_be_serialized_json(self):
        import json
        listing = _listing_with_one_escrow()
        listing["accepted_escrows"] = json.dumps(listing["accepted_escrows"])
        history, ctx = _ctx(
            listing=listing,
            escrow_proposal=self._proposal(),
        )
        decision, _ = accept_exact_listing_middleware(history, ctx)
        assert decision is not None
        assert decision.action == "accept"

    def test_rejects_when_escrow_not_advertised(self):
        history, ctx = _ctx(
            listing=_listing_with_one_escrow(),
            escrow_proposal=self._proposal(escrow_address="0x" + "99" * 20),
        )
        decision, _ = accept_exact_listing_middleware(history, ctx)
        assert decision is not None
        assert decision.action == "reject"
        assert "exact_listing:escrow_not_in_accepted_set" in (decision.reason or "")

    def test_rejects_amount_mismatch(self):
        history, ctx = _ctx(
            listing=_listing_with_one_escrow(),
            escrow_proposal=self._proposal(fields={"token": _TOKEN, "amount": 999}),
        )
        decision, _ = accept_exact_listing_middleware(history, ctx)
        assert decision is not None
        assert decision.action == "reject"
        assert "exact_listing:amount_mismatch" in (decision.reason or "")

    def test_rejects_literal_mismatch(self):
        history, ctx = _ctx(
            listing=_listing_with_one_escrow(),
            escrow_proposal=self._proposal(
                fields={"token": _OTHER_TOKEN, "amount": 1000},
                literal_fields={"token": _OTHER_TOKEN},
            ),
        )
        decision, _ = accept_exact_listing_middleware(history, ctx)
        assert decision is not None
        assert decision.action == "reject"
        assert "exact_listing:literal_fields_mismatch" in (decision.reason or "")

    def test_rejects_extra_field_not_in_listing_literals(self):
        history, ctx = _ctx(
            listing=_listing_with_one_escrow(),
            escrow_proposal=self._proposal(
                fields={"token": _TOKEN, "arbiter": _ARBITER, "amount": 1000},
            ),
        )
        decision, _ = accept_exact_listing_middleware(history, ctx)
        assert decision is not None
        assert decision.action == "reject"
        assert "exact_listing:field_mismatch" in (decision.reason or "")

    def test_rejects_rate_mismatch(self):
        history, ctx = _ctx(
            listing=_listing_with_one_escrow(),
            escrow_proposal=self._proposal(
                rates=[{"field": "amount", "per": "hour", "value": "999"}],
            ),
        )
        decision, _ = accept_exact_listing_middleware(history, ctx)
        assert decision is not None
        assert decision.action == "reject"
        assert "exact_listing:rates_mismatch" in (decision.reason or "")

    def test_accepts_matching_demands(self):
        demand = {
            "chain_name": "anvil",
            "arbiter": _ARBITER,
            "demand_data": {"recipient": _RECIPIENT},
        }
        listing = _listing_with_one_escrow()
        listing["demands"] = [demand]
        history, ctx = _ctx(
            listing=listing,
            escrow_proposal=self._proposal(demands=[demand]),
        )
        decision, _ = accept_exact_listing_middleware(history, ctx)
        assert decision is not None
        assert decision.action == "accept"

    def test_rejects_missing_demands(self):
        listing = _listing_with_one_escrow()
        listing["demands"] = [
            {
                "chain_name": "anvil",
                "arbiter": _ARBITER,
                "demand_data": {"recipient": _RECIPIENT},
            }
        ]
        history, ctx = _ctx(
            listing=listing,
            escrow_proposal=self._proposal(),
        )
        decision, _ = accept_exact_listing_middleware(history, ctx)
        assert decision is not None
        assert decision.action == "reject"
        assert "exact_listing:demands_mismatch" in (decision.reason or "")

    def test_accepts_amountless_exact_attestation_escrow(self):
        attestation_uid = "0x" + "aa" * 32
        listing = {
            "listing_id": "L1",
            "accepted_escrows": [
                {
                    "chain_name": "anvil",
                    "escrow_address": _ADDR,
                    "literal_fields": {"attestationUid": attestation_uid},
                    "rates": [],
                }
            ],
        }
        history, ctx = _ctx(
            listing=listing,
            escrow_proposal={
                "chain_name": "anvil",
                "escrow_address": _ADDR,
                "fields": {},
                "literal_fields": {"attestationUid": attestation_uid},
                "rates": [],
                "demands": [],
            },
        )
        decision, _ = accept_exact_listing_middleware(history, ctx)
        assert decision is not None
        assert decision.action == "accept"
        assert "amount" not in (decision.proposal["fields"] or {})

    def test_rejects_unexpected_amount_on_amountless_exact_escrow(self):
        attestation_uid = "0x" + "aa" * 32
        listing = {
            "listing_id": "L1",
            "accepted_escrows": [
                {
                    "chain_name": "anvil",
                    "escrow_address": _ADDR,
                    "literal_fields": {"attestationUid": attestation_uid},
                    "rates": [],
                }
            ],
        }
        history, ctx = _ctx(
            listing=listing,
            escrow_proposal={
                "chain_name": "anvil",
                "escrow_address": _ADDR,
                "fields": {"amount": 1000},
                "literal_fields": {"attestationUid": attestation_uid},
                "rates": [],
                "demands": [],
            },
        )
        decision, _ = accept_exact_listing_middleware(history, ctx)
        assert decision is not None
        assert decision.action == "reject"
        assert "exact_listing:field_mismatch" in (decision.reason or "")


class TestRejectsWhenFieldDiverges:
    def test_token_mismatch(self):
        history, ctx = _ctx(
            listing=_listing_with_one_escrow(),
            escrow_proposal={
                "chain_name": "anvil",
                "escrow_address": _ADDR,
                "literal_fields": {"token": _OTHER_TOKEN},
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
                "literal_fields": {"token": _TOKEN},  # no arbiter
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
                "literal_fields": {"token": _TOKEN},
            },
        )
        decision, _ = escrow_shape_guard(history, ctx)
        assert decision is None

    def test_zero_address_passes(self):
        """Legacy buyer client sends the zero placeholder for
        escrow_address; the default guard skips it too."""
        history, ctx = _ctx(
            listing=_listing_with_one_escrow(),
            escrow_proposal={
                "chain_name": "anvil",
                "escrow_address": "0x" + "0" * 40,
                "literal_fields": {"token": _TOKEN},
            },
        )
        decision, _ = escrow_shape_guard(history, ctx)
        assert decision is None


class TestRejectsWhenEscrowNotAdvertised:
    def test_address_advertised_but_not_in_set_rejects(self):
        """The structural accepted-set membership check is policy, so the
        default guard rejects a real proposal outside the listing set."""
        history, ctx = _ctx(
            listing=_listing_with_one_escrow(),
            escrow_proposal={
                "chain_name": "anvil",
                "escrow_address": "0x" + "99" * 20,
                "literal_fields": {"token": _TOKEN},
            },
        )
        decision, _ = escrow_shape_guard(history, ctx)
        assert decision is not None
        assert decision.action == "reject"
        assert "escrow_not_in_accepted_set" in (decision.reason or "")

    def test_chain_advertised_but_not_in_set_rejects(self):
        history, ctx = _ctx(
            listing=_listing_with_one_escrow(),
            escrow_proposal={
                "chain_name": "other-chain",
                "escrow_address": _ADDR,
                "literal_fields": {"token": _TOKEN},
            },
        )
        decision, _ = escrow_shape_guard(history, ctx)
        assert decision is not None
        assert decision.action == "reject"
        assert "escrow_not_in_accepted_set" in (decision.reason or "")
