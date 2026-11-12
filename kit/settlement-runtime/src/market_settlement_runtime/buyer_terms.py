"""Buyer-local recommendations and codec-derived lifecycle disclosure.

Recommendations may be waived explicitly; codec capabilities and authority
acceptance remain mandatory. No payment records, stops or refunds are inferred
from a peer's promise.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from typing import Any, Literal

from market_core.schemas import AgreedPrice, Agreement, SettlementOption
from market_deal_lifecycle.selection import AuthoritySelection
from market_deal_lifecycle.terms import PARTIAL_PERIOD, TermContext, decode_terms

from .configuration import SettlementConfigurationRegistry
from .rate_publication import default_buyer_refusals
from .terms_policy import (
    BuyerTermsOffer, BuyerTermsPolicy, DefaultBuyerTermsPolicy, preferred_options,
)


class BuyerTermsAdmission:
    """Ask the buyer's terms policy, then admit and rank the dispute authority.

    The policy can only add refusals. Authority acceptance and term validation
    run for every option it does not refuse, and a policy that fails refuses.
    What the policy refused and what was admitted are kept, so a command that
    finds nothing to buy can say that its own policy is why.
    """

    def __init__(
        self, authority: AuthoritySelection, policy: BuyerTermsPolicy | None = None,
    ) -> None:
        self.authority = authority
        self.policy: BuyerTermsPolicy = policy if policy is not None else DefaultBuyerTermsPolicy()
        self.policy_refused: dict[str, tuple[str, ...]] = {}
        self.admitted: set[str] = set()

    def _has_adapter(self, option: SettlementOption) -> bool:
        context = self.authority.contexts.get(option.settlement_schema)
        return context.has_adapter if context is not None else False

    def rank(
        self, option: SettlementOption, *, registry_url: str = "",
        listing: Mapping[str, Any] | None = None,
    ) -> int:
        refusals = policy_refusals(
            self.policy, option, has_adapter=self._has_adapter(option),
            registry_url=registry_url, listing=listing,
        )
        if refusals:
            self.policy_refused[option.option_id] = refusals
            raise ValueError("; ".join(refusals))
        rank = self.authority.rank(
            option.settlement_schema, option.lifecycle, registry_url=registry_url,
        )
        self.admitted.add(option.option_id)
        return rank

    def __call__(self, option: SettlementOption, listing: Mapping[str, Any]) -> int | None:
        try:
            return self.rank(
                option, registry_url=str(listing.get("source_registry_url") or ""),
                listing=listing,
            )
        except ValueError as exc:
            self.authority.report(str(exc))
            return None

    def order(
        self, options: Sequence[SettlementOption], listing: Mapping[str, Any],
    ) -> tuple[SettlementOption, ...]:
        """One listing's admitted options in the policy's preference order."""
        registry_url = str(listing.get("source_registry_url") or "")
        return tuple(offer.option for offer in preferred_options(self.policy, [
            BuyerTermsOffer(
                option, decode_terms(option.lifecycle), self._has_adapter(option),
                registry_url, listing,
            )
            for option in options
        ]))

    def policy_refusal_report(self) -> tuple[str, ...]:
        """Why nothing was selectable, when the terms policy refused options
        and none was admitted; empty otherwise."""
        if self.admitted or not self.policy_refused:
            return ()
        return tuple(
            f"option {option_id}: " + "; ".join(reasons)
            for option_id, reasons in self.policy_refused.items()
        )


def policy_refusals(
    policy: BuyerTermsPolicy, option: SettlementOption, *, has_adapter: bool,
    registry_url: str = "", listing: Mapping[str, Any] | None = None,
) -> tuple[str, ...]:
    """One policy's refusals of one option; a failing policy is a refusal.

    A policy that only orders options leaves refusing to the packaged default.
    """
    if not callable(getattr(policy, "refusals", None)):
        policy = DefaultBuyerTermsPolicy()
    try:
        return tuple(str(reason) for reason in policy.refusals(BuyerTermsOffer(
            option, decode_terms(option.lifecycle), has_adapter, registry_url,
            listing or {},
        )))
    except Exception as exc:  # noqa: BLE001 - installed code; fail closed
        return (f"buyer terms policy failed ({type(exc).__name__}: {exc})",)


def option_quote(
    option: SettlementOption, duration_seconds: int | None, *, registry: SettlementConfigurationRegistry,
) -> AgreedPrice:
    """Ask the owner for the selected monetary quote, not its payment fields."""
    return registry.present_payment(option, duration_seconds=duration_seconds).quote


def compute_disclosure(
    option: SettlementOption, *, registry: SettlementConfigurationRegistry,
    listing: Mapping[str, Any] | None = None, duration_seconds: int | None = None,
    agreement: Agreement | None = None,
) -> tuple[tuple[str, str], ...]:
    """Show selected asks or exact accepted money, never reprice accepted work.

    The supplied listing is used only for pre-negotiation bounds. Accepted end
    and horizon come from the retained Agreement, even if offers have changed.
    """
    if agreement is None and not option.price_rates:
        return (("Price", "No scalar amount price; see the selected mechanism's terms."),)
    if agreement is not None and agreement.settlement != option:
        raise ValueError("disclosure option differs from accepted Agreement")
    charges = registry.present_payment(
        option, duration_seconds=duration_seconds,
        quote=registry.agreed_price(agreement) if agreement is not None else None,
    )
    quote = charges.quote
    terms = decode_terms(option.lifecycle)
    early = terms.early_termination if terms else None
    product = "reserved" if quote.unit == "total" else (
        "spot" if early and "payee" in early.entitlements else "on-demand"
    )
    unit = "total" if quote.unit == "total" else f"per_period ({quote.period}, {quote.period_seconds} seconds)"
    def money(value: int | None) -> str:
        return (
            "Not determined by the mechanism" if value is None
            else f"{value} minor units of {quote.asset}"
        )
    rows = [
        ("Class", product),
        ("Accepted price" if agreement else "Selected price", f"{money(quote.amount)} {unit}"),
        ("Setup once charge", money(charges.setup_once)),
        ("Initial reserve", money(charges.initial_reserve) + "; reserved funds, not spend or a loss cap."),
    ]
    if option.price_rates:
        rows.append(("Asking rate", "; ".join(
            f"{rate.value} minor units of {option.price_asset} per {rate.per} ({rate.field})"
            for rate in option.price_rates
        )))
    if agreement is None:
        bounds = listing or {}
        relative = bounds.get("max_duration_seconds")
        absolute = bounds.get("available_until_utc")
        rows.extend((
            ("Maximum duration", f"{relative} seconds" if relative is not None else "Not stated"),
            ("Available until", str(absolute) if absolute is not None else "Not stated"),
            ("Requested horizon", f"{duration_seconds} seconds (not rounded to periods)" if duration_seconds is not None
             else "Omitted; seller resolves the finite bound at the agreed start; review the accepted horizon before approval."),
        ))
    else:
        start = datetime.fromisoformat(agreement.start_utc.replace("Z", "+00:00"))
        rows.extend((
            ("Accepted start", agreement.start_utc),
            ("Effective horizon", f"{agreement.duration_seconds} seconds (not rounded to periods)"),
            ("Maximum accepted end", (start + timedelta(seconds=agreement.duration_seconds)).isoformat()),
            ("Accepted bounds", "The retained accepted horizon/end is authoritative; current listings are not consulted."),
        ))
    return tuple(rows)


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
