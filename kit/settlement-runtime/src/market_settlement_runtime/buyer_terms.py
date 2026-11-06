"""Buyer-local recommendations and codec-derived lifecycle disclosure.

Recommendations may be waived explicitly; codec capabilities and authority
acceptance remain mandatory. No payment records, stops or refunds are inferred
from a peer's promise.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

from market_core.schemas import SettlementOption
from market_deal_lifecycle.selection import AuthoritySelection
from market_deal_lifecycle.terms import PARTIAL_PERIOD, TermContext, decode_terms

from .rate_publication import default_buyer_refusals


class BuyerTermsPolicy:
    """Compose the same recommendations sellers diagnose with authority ranking."""

    def __init__(
        self, authority: AuthoritySelection, *, allow_unprotected_terms: bool = False,
    ) -> None:
        self.authority = authority
        self.allow_unprotected_terms = allow_unprotected_terms

    def rank(self, option: SettlementOption, *, registry_url: str = "") -> int:
        context = self.authority.contexts.get(option.settlement_schema)
        refusals = default_buyer_refusals(
            decode_terms(option.lifecycle),
            has_adapter=context.has_adapter if context is not None else False,
        )
        if refusals and not self.allow_unprotected_terms:
            raise ValueError("; ".join(refusals))
        return self.authority.rank(
            option.settlement_schema, option.lifecycle, registry_url=registry_url,
        )

    def __call__(self, option: SettlementOption, listing: Mapping[str, Any]) -> int | None:
        try:
            return self.rank(option, registry_url=str(listing.get("source_registry_url") or ""))
        except ValueError as exc:
            self.authority.report(str(exc))
            return None


def lifecycle_disclosure(option: SettlementOption, *, context: TermContext) -> tuple[tuple[str, str], ...]:
    """Describe only the selected codec values, not a stored product label.

    The caller validates authority acceptance and installed capabilities before
    selecting. Disclosure does not turn unaccepted terms into selectable ones.
    """
    if context.mechanism != option.settlement_schema:
        raise ValueError("disclosure context names another mechanism")
    terms = decode_terms(option.lifecycle)
    if not context.has_adapter:
        if terms is not None:
            raise ValueError(f"{context.mechanism} has no lifecycle adapter")
        return (
            ("Delivery promise", "None: this option has no lifecycle adapter and makes no delivery promise."),
            ("Adjudication", "No lifecycle adjudication is promised by this option."),
        )
    if terms is None:
        raise ValueError("a lifecycle adapter requires adjudication")
    rows = []
    deadline = terms.delivery_deadline_seconds
    rows.append(("Delivery deadline", (
        f"Active within {deadline} seconds after your approval (or the agreed start, if later), "
        "or the seller has not delivered."
        if deadline is not None else "No delivery deadline is promised."
    )))
    early = terms.early_termination
    parties: tuple[tuple[Literal["payer", "payee"], str], ...] = (("payer", "Buyer"), ("payee", "Seller"))
    for stopper, party in parties:
        entitlement = early.entitlements.get(stopper) if early else None
        rows.append((f"{party} stop", (
            f"Entitled with {entitlement.notice_seconds} seconds' notice; "
            f"settles_through={entitlement.settles_through} "
            f"(final partial period {PARTIAL_PERIOD[entitlement.settles_through]})."
            if entitlement else "No entitled payment stop."
        )))
    if early is not None:
        rows.extend((
            ("Term end", f"settles_through={early.settles_through} "
             f"(final partial period {PARTIAL_PERIOD[early.settles_through]})."),
            ("Notice enforcement", "The payment authority hosts pending stops and enforces the priced notice, "
             "not a local seller stop schedule. An unentitled loss of service is handled by adjudication."),
            ("Premature-stop penalty", f"Up to {early.penalty} minor units of {option.price_asset}; "
             "for an unentitled seller end (including spot without notice), not an entitled notice stop; "
             "taken from what the seller has earned and not yet been paid, after refunds. "
             "At the start, only an earned setup charge may be available. "
             "Nothing earned and held means nothing taken. This is a ceiling, not a guaranteed payment."),
            ("Rate start", "Billing starts as a journaled effect after lease activation, "
             "not when buyer credentials are disclosed."),
            ("Reserve protection", "Reserve-ahead is not spend and is not a loss cap. "
             "A lost resource can remain billed while the seller is down until your own stop lands. "
             "Seller recovery within the dispute window returns charges since loss; otherwise a case is the remedy."),
            ("Buyer end", (
                "Stop at the payment authority first under the agreed notice, then hint the seller. "
                if "payer" in early.entitlements else
                "No payer stop is entitled; a case is the financial backstop. "
            ) + "end_delivery means end now; its journaled retry can continue while billing runs. "
             "A receipt-backed delivery_end(cause=payer) may rule automatically; otherwise it is triaged. "
             "A seller hint is not a payment stop or refund."),
            ("Setup charge", "If present, owed from approval. A payment stop alone does not reverse it. "
             "Only established non-delivery returns it: the seller's filing, its agreement "
             "with your claim, or a ruling on your evidence; delivered=true keeps it."),
        ))
    else:
        rows.append(("Early termination", "No entitled payment stops; no early-termination penalty is promised."))
    adjudication = terms.adjudication
    dispute = adjudication.dispute
    rows.extend((
        ("Dispute authority", f"{dispute.interface} at {dispute.origin}; "
         f"account={dispute.account}; record_key={dispute.record_key}; params={dispute.params}"),
        ("Dispute window", f"{adjudication.dispute_window_seconds} seconds"),
        ("Case-hold cap", (
            f"{adjudication.case_hold_max_seconds} seconds"
            if adjudication.case_hold_max_seconds is not None else "Unbounded"
        )),
        ("Cases and holds", "A filed case is not a refund pending. Read the authority's per-part "
         "held answer and extension, or not_held and reason. Paid-out money is not recovered by a case. "
         "For entitled stops, holds last through stop plus the dispute window and accepted case extensions."),
        ("Evidence retention", "Keep signed bytes through at least the dispute window after the latest "
         "delivery end, last payout or case close. Guarantees depend on authority records and retained evidence."),
    ))
    rows.extend(("Default buyer policy", reason) for reason in default_buyer_refusals(terms, has_adapter=True))
    return tuple(rows)
