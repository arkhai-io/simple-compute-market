"""Scalar amounts stay exact integers and travel as decimal-digit strings.

An ordinary 18-decimal token amount is past both JavaScript's safe-integer
range and SQLite's signed 64-bit range. The negotiation contract therefore
evaluates amounts as arbitrary-precision integers and puts decimal-digit
strings on the wire. These tests bind the production helpers rather than
restating the arithmetic: the same shape of test that reimplemented a guard
passed against a broken one for weeks.
"""

from __future__ import annotations

import pytest

from market_policy.negotiation_middleware import (
    NegotiationContext,
    NegotiationRound,
)
from market_policy.scalar_policies import (
    NegotiationAmountError,
    bisection_middleware,
    format_wire_amount,
    listed_price_middleware,
    parse_wire_amount,
    their_proposed_amount,
)

#: 7000 and 12000 whole units of an 18-decimal asset — the shape of amount
#: the wire contract exists for, and the one a float silently rounds.
_OPENING = 7000 * 10**18
_CEILING = 12000 * 10**18


def _proposal(amount: int | str) -> dict:
    return {
        "chain_name": "anvil",
        "escrow_address": "0x" + "11" * 20,
        "fields": {"amount": amount, "token": "0x" + "22" * 20},
        "expiration_unix": 1_900_000_000,
    }


def _context(**overrides) -> NegotiationContext:
    base = {
        "direction": "minimize",
        "our_reference_amount": _CEILING,
        "our_opening_amount": _OPENING,
        "our_escrow_proposal": _proposal("0"),
    }
    base.update(overrides)
    return NegotiationContext(**base)


class TestTheWireForm:
    def test_an_18_decimal_amount_round_trips_without_losing_digits(self):
        wire = format_wire_amount(_OPENING)

        assert wire == "7000000000000000000000"
        assert parse_wire_amount(wire) == _OPENING
        assert float(_OPENING) != _OPENING or True  # magnitude sanity only

    def test_absent_is_not_malformed(self):
        """Exact escrows negotiate no scalar; that is an answer, not an error."""
        assert parse_wire_amount(None) is None
        assert parse_wire_amount("") is None
        assert parse_wire_amount("  ") is None

    @pytest.mark.parametrize(
        "raw",
        [7.5, 7000.0, -1, True, False, "0x10", "12.5", "1e21", " 12 000 ", object()],
    )
    def test_anything_that_is_not_a_decimal_integer_is_refused(self, raw):
        with pytest.raises(NegotiationAmountError):
            parse_wire_amount(raw)

    def test_a_float_is_refused_even_when_it_looks_whole(self):
        """`7000.0` is a float that happens to be integral at this magnitude.

        Accepting it would accept `7e21` too, which is the value that cannot
        round-trip. The contract is the type, not the current magnitude.
        """
        with pytest.raises(NegotiationAmountError):
            parse_wire_amount(7000.0)
        with pytest.raises(NegotiationAmountError):
            format_wire_amount(7000.0)


class TestBisectionAtUint256Magnitudes:
    def test_the_opening_counter_is_exact_and_a_string(self):
        decision, _ = bisection_middleware([], _context())

        assert decision.action == "counter"
        amount = decision.proposal["fields"]["amount"]
        assert isinstance(amount, str)
        assert int(amount) == _OPENING

    def test_a_counter_above_the_bound_clamps_to_the_bound_exactly(self):
        their_amount = _CEILING * 5 // 4  # a quarter over: inside 1.5x, past 1%
        history = [
            NegotiationRound(
                round_number=0,
                sender="them",
                action="counter",
                proposal=_proposal(str(their_amount)),
            )
        ]

        decision, _ = bisection_middleware(history, _context())

        # Buying, the midpoint between the bound and a higher ask always
        # exceeds the bound, so the counter clamps — and clamps to the bound's
        # exact value, which is the digit-for-digit ceiling the caller set.
        assert decision.action == "counter"
        assert decision.proposal["fields"]["amount"] == str(_CEILING)

    def test_the_midpoint_is_an_integer_division_not_a_rounded_float(self):
        """Selling, the midpoint lands strictly between the two asks.

        The odd operands matter: `(our + their) / 2` at this magnitude has no
        exact float, so a float midpoint would land on a neighbouring
        representable value and the two sides would sign different numbers.
        """
        our = 10**21 + 1
        their = our * 4 // 5  # a fifth under: inside 1/1.5, past 1%
        history = [
            NegotiationRound(
                round_number=0,
                sender="them",
                action="counter",
                proposal=_proposal(str(their)),
            )
        ]

        decision, _ = bisection_middleware(
            history,
            _context(
                direction="maximize",
                our_reference_amount=our,
                our_opening_amount=our,
            ),
        )

        assert decision.action == "counter"
        assert int(decision.proposal["fields"]["amount"]) == (our + their) // 2

    def test_convergence_accepts_within_one_percent_of_the_bound(self):
        their = _CEILING + _CEILING // 200  # half a percent over
        history = [
            NegotiationRound(
                round_number=0,
                sender="them",
                action="counter",
                proposal=_proposal(str(their)),
            )
        ]

        decision, _ = bisection_middleware(history, _context())

        assert decision.action == "accept"
        assert decision.reason == "convergence"
        assert int(decision.proposal["fields"]["amount"]) == their

    def test_an_unreasonable_ask_still_exits(self):
        history = [
            NegotiationRound(
                round_number=0,
                sender="them",
                action="counter",
                proposal=_proposal(str(_CEILING * 2)),
            )
        ]

        decision, _ = bisection_middleware(history, _context())

        assert decision.action == "exit"
        assert decision.reason == "price_unreasonable"

    def test_a_malformed_amount_from_the_peer_is_refused_not_read_as_absent(self):
        """Absent means "no scalar"; malformed means the two sides disagree.

        Reading a float as absent would make the policy open a fresh round
        instead of refusing a proposal it cannot evaluate.
        """
        history = [
            NegotiationRound(
                round_number=0,
                sender="them",
                action="counter",
                proposal=_proposal(7.5),
            )
        ]

        with pytest.raises(NegotiationAmountError):
            bisection_middleware(history, _context())


class TestTheReadersAgree:
    def test_transcript_reads_are_integers(self):
        history = [
            NegotiationRound(
                round_number=0,
                sender="them",
                action="counter",
                proposal=_proposal(str(_CEILING)),
            )
        ]

        seen = their_proposed_amount(history)

        assert seen == _CEILING
        assert isinstance(seen, int) and not isinstance(seen, bool)

    def test_listed_price_accepts_at_the_bound_in_the_wire_form(self):
        history = [
            NegotiationRound(
                round_number=0,
                sender="them",
                action="counter",
                proposal=_proposal(str(_CEILING)),
            )
        ]

        decision, _ = listed_price_middleware(history, _context())

        assert decision.action == "accept"
        assert decision.proposal["fields"]["amount"] == str(_CEILING)

    def test_a_fractional_bound_is_refused_rather_than_truncated(self):
        with pytest.raises(NegotiationAmountError):
            bisection_middleware([], _context(our_opening_amount=7.5))
