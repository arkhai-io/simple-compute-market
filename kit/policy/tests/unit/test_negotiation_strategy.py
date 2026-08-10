"""Unit tests for the generic negotiation chain runner and registry."""

from __future__ import annotations

import pytest
from market_policy import (
    InlineSource,
    UnknownCatalogueEntryError,
    negotiation_catalogue_builder,
)
from market_policy.negotiation_middleware import (
    NegotiationContext,
    NegotiationDecision,
    normalize_policies_by_escrow_kind_config,
    run_negotiation_chain,
)


def _proposal_with_amount(amount: float) -> dict:
    return {"fields": {"amount": int(round(amount))}}


def _decision_amount(d: NegotiationDecision) -> int | None:
    if d.proposal is None:
        return None
    return d.proposal.get("fields", {}).get("amount")


def test_to_dict_omits_none_fields():
    d = NegotiationDecision(action="accept")
    assert d.to_dict() == {"action": "accept"}

    p = _proposal_with_amount(42)
    d = NegotiationDecision(action="counter", proposal=p)
    assert d.to_dict() == {"action": "counter", "proposal": p}

    d = NegotiationDecision(action="accept", proposal=p, reason="convergence")
    assert d.to_dict() == {"action": "accept", "proposal": p, "reason": "convergence"}


def test_normalize_policies_by_escrow_kind_config_accepts_string_and_nested_chain():
    assert normalize_policies_by_escrow_kind_config(
        {
            "erc20": "erc20_bisection",
            "erc721": {"chain": ["accept_exact_listing"]},
            "erc1155": {"policy": "erc1155_bisection"},
        }
    ) == {
        "erc20": ["erc20_bisection"],
        "erc721": ["accept_exact_listing"],
        "erc1155": ["erc1155_bisection"],
    }


def test_a_composed_policy_is_resolvable_and_runnable():
    """Replaces registration-then-load. A source offers the policy; the
    catalogue the role composed is the only thing that resolves it."""

    def _fake(history, context):
        return (
            NegotiationDecision(
                action="accept",
                proposal=_proposal_with_amount(context.our_reference_amount),
            ),
            context,
        )

    catalogue = (
        negotiation_catalogue_builder()
        .add_loader(InlineSource({"test.fake": _fake}, label="test"))
        .build()
    )

    chain = catalogue.resolve(["test.fake"])
    assert len(chain) == 1
    ctx = NegotiationContext(direction="maximize", our_reference_amount=42)
    d = run_negotiation_chain(chain, [], ctx)
    assert d.action == "accept"
    assert _decision_amount(d) == 42


def test_an_unresolvable_name_raises_with_an_actionable_message():
    catalogue = (
        negotiation_catalogue_builder()
        .add_loader(InlineSource({"present": lambda h, c: None}, label="test"))
        .build()
    )

    with pytest.raises(UnknownCatalogueEntryError) as exc_info:
        catalogue.resolve(["does.not.exist"])

    msg = str(exc_info.value)
    assert "does.not.exist" in msg
    # The superseded message said "Registered:", naming a process-global
    # registry. A composed catalogue names what it was composed with.
    assert "Offered by the composed catalogue" in msg
    assert "present" in msg


def test_chain_terminates_on_first_decision():
    calls = []

    def mw_a(history, context):
        calls.append("a")
        return NegotiationDecision(action="exit", reason="from-a"), context

    def mw_b(history, context):
        calls.append("b")
        return NegotiationDecision(action="exit", reason="from-b"), context

    ctx = NegotiationContext(direction="maximize", our_reference_amount=100)
    d = run_negotiation_chain([mw_a, mw_b], [], ctx)
    assert d.reason == "from-a"
    assert calls == ["a"]


def test_chain_threads_context_when_middleware_defers():
    def mw_record(history, context):
        context.intermediate["recorded"] = "by_first"
        return None, context

    def mw_terminal(history, context):
        return (
            NegotiationDecision(
                action="accept",
                proposal=_proposal_with_amount(context.our_reference_amount),
                reason=context.intermediate.get("recorded"),
            ),
            context,
        )

    ctx = NegotiationContext(direction="maximize", our_reference_amount=100)
    d = run_negotiation_chain([mw_record, mw_terminal], [], ctx)
    assert d.reason == "by_first"


def test_chain_exhaustion_raises_the_typed_error():
    from market_policy.negotiation_middleware import NegotiationChainExhausted

    def mw_defer(history, context):
        return None, context

    ctx = NegotiationContext(direction="maximize", our_reference_amount=100)
    with pytest.raises(NegotiationChainExhausted, match="no decision"):
        run_negotiation_chain([mw_defer], [], ctx)
