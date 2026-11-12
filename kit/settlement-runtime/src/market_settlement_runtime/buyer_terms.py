"""Buyer-local recommendations and codec-derived lifecycle disclosure.

Each recommendation may be waived explicitly and alone; codec capabilities and
authority acceptance remain mandatory. No payment records, stops or refunds are
inferred from a peer's promise.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Literal

from market_core.schemas import AgreedPrice, Agreement, SettlementOption
from market_deal_lifecycle.selection import AuthoritySelection
from market_deal_lifecycle.terms import PARTIAL_PERIOD, TermContext, decode_terms

from .rate_publication import (
    DEFAULT_REFUSAL_REASONS, DefaultRefusal, default_buyer_refusal, default_buyer_refused_terms,
)
from .configuration import SettlementConfigurationRegistry


@dataclass(frozen=True)
class TermWaiver:
    """A buyer's command-line waiver of exactly one default refusal."""

    term: DefaultRefusal
    flag: str
    help: str


#: One waiver per default refusal, in the order buyers show them. Every buyer
#: command offers all four under these names, so a run's waivers read alike in
#: each domain's run metadata and disclosure.
TERM_WAIVERS: tuple[TermWaiver, ...] = (
    TermWaiver("no_delivery_deadline", "--allow-no-delivery-deadline",
               "Accept a compute option that promises no delivery deadline."),
    TermWaiver("no_penalty", "--allow-no-penalty",
               "Accept an on-demand option with no positive premature-stop penalty."),
    TermWaiver("charged_preemption", "--allow-charged-preemption",
               "Accept a seller stop that charges its started period instead of returning it."),
    TermWaiver("charged_term_end", "--allow-charged-term-end",
               "Accept a term end that charges its started period instead of returning it."),
)
UNPROTECTED_TERMS_FLAG = "--allow-unprotected-terms"
UNPROTECTED_TERMS_HELP = (
    "Shorthand for all four --allow-no-delivery-deadline, --allow-no-penalty, "
    "--allow-charged-preemption and --allow-charged-term-end. No waiver bypasses "
    "codec, payment capability or dispute authority checks."
)

WAIVERS_BY_TERM: Mapping[DefaultRefusal, TermWaiver] = {waiver.term: waiver for waiver in TERM_WAIVERS}
ALL_TERM_WAIVERS: frozenset[DefaultRefusal] = frozenset(WAIVERS_BY_TERM)


def term_waivers(
    *, no_delivery_deadline: bool = False, no_penalty: bool = False,
    charged_preemption: bool = False, charged_term_end: bool = False,
    unprotected_terms: bool = False,
) -> frozenset[DefaultRefusal]:
    """The default refusals a run waives: those named, or all four by the shorthand."""
    if unprotected_terms:
        return ALL_TERM_WAIVERS
    named: dict[DefaultRefusal, bool] = {
        "no_delivery_deadline": no_delivery_deadline, "no_penalty": no_penalty,
        "charged_preemption": charged_preemption, "charged_term_end": charged_term_end,
    }
    return frozenset(term for term, waived in named.items() if waived)


def waiver_flags(waivers: Collection[DefaultRefusal]) -> tuple[str, ...]:
    """Each waiver in force by its flag, in the order buyers show them."""
    return tuple(waiver.flag for waiver in TERM_WAIVERS if waiver.term in waivers)


def waivers_from_flags(flags: Iterable[str]) -> frozenset[DefaultRefusal]:
    """The waivers a run recorded by flag, as a resumed or recovered run reads them.

    An unknown flag is refused rather than dropped, so a recovered run never
    shows fewer waivers than it was bought under.
    """
    flags = tuple(flags)
    by_flag = {waiver.flag: waiver.term for waiver in TERM_WAIVERS}
    unknown = sorted(set(flags) - set(by_flag))
    if unknown:
        raise ValueError(f"unknown recorded waivers: {unknown}")
    return frozenset(by_flag[flag] for flag in flags)


def allows_missing_delivery_deadline(waivers: Collection[DefaultRefusal]) -> bool:
    """Whether the foundation's codec may admit a compute option without a deadline.

    The codec refuses one for a buyer on its own, so the policy's waiver would
    be moot without this; only the deadline's waiver, singly or through the
    shorthand, sets it, so waiving another term never admits a missing deadline.
    """
    return "no_delivery_deadline" in waivers


class BuyerTermsPolicy:
    """Compose the same recommendations sellers diagnose with authority ranking."""

    def __init__(
        self, authority: AuthoritySelection, *, waivers: Collection[DefaultRefusal] = frozenset(),
    ) -> None:
        unknown = set(waivers) - ALL_TERM_WAIVERS
        if unknown:
            raise ValueError(f"unknown default-refusal waivers: {sorted(unknown)}")
        self.authority = authority
        self.waivers = frozenset(waivers)

    def rank(self, option: SettlementOption, *, registry_url: str = "") -> int:
        context = self.authority.contexts.get(option.settlement_schema)
        refused = [
            term for term in default_buyer_refused_terms(
                decode_terms(option.lifecycle),
                has_adapter=context.has_adapter if context is not None else False,
            )
            if term not in self.waivers
        ]
        if refused:
            raise ValueError("; ".join(default_buyer_refusal(term) for term in refused))
        return self.authority.rank(
            option.settlement_schema, option.lifecycle, registry_url=registry_url,
        )

    def __call__(self, option: SettlementOption, listing: Mapping[str, Any]) -> int | None:
        try:
            return self.rank(option, registry_url=str(listing.get("source_registry_url") or ""))
        except ValueError as exc:
            self.authority.report(str(exc))
            return None


def option_quote(
    option: SettlementOption, duration_seconds: int | None, *, registry: SettlementConfigurationRegistry,
) -> AgreedPrice:
    """Ask the owner for the selected monetary quote, not its payment fields."""
    return registry.present_payment(option, duration_seconds=duration_seconds).quote


def compute_disclosure(
    option: SettlementOption, *, registry: SettlementConfigurationRegistry,
    listing: Mapping[str, Any] | None = None, duration_seconds: int | None = None,
    agreement: Agreement | None = None, default_duration: bool = False,
) -> tuple[tuple[str, str], ...]:
    """Show selected asks or exact accepted money, never reprice accepted work.

    The supplied listing is used only for pre-negotiation bounds. Accepted end
    and horizon come from the retained Agreement, even if offers have changed.
    ``default_duration`` says the requested horizon is the buyer command's own
    default rather than one the buyer named, so the buyer sees it was chosen.
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
            ("Requested horizon", (
                "Omitted; seller resolves the finite bound at the agreed start; review the accepted horizon before approval."
                if duration_seconds is None else
                f"{duration_seconds} seconds, this buyer's default for a reserved option; "
                "name a duration to request another (not rounded to periods)"
                if default_duration else f"{duration_seconds} seconds (not rounded to periods)"
            )),
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


def _waiver_rows(waivers: Collection[DefaultRefusal]) -> list[tuple[str, str]]:
    return [("Waivers in force", "; ".join(
        f"{waiver.flag} ({DEFAULT_REFUSAL_REASONS[waiver.term]})"
        for waiver in TERM_WAIVERS if waiver.term in waivers
    ) + ". This run accepts these terms a default buyer refuses.")] if waivers else []


def lifecycle_disclosure(
    option: SettlementOption, *, context: TermContext,
    waivers: Collection[DefaultRefusal] = frozenset(),
) -> tuple[tuple[str, str], ...]:
    """Describe only the selected codec values, not a stored product label.

    The caller validates authority acceptance and installed capabilities before
    selecting. Disclosure does not turn unaccepted terms into selectable ones.
    Every waiver the run carries is named, and a refusal it waives says so.
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
            *_waiver_rows(waivers),
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
    rows.extend(
        ("Default buyer policy", default_buyer_refusal(term) + (
            f"; waived by {WAIVERS_BY_TERM[term].flag}" if term in waivers else ""
        ))
        for term in default_buyer_refused_terms(terms, has_adapter=True)
    )
    rows.extend(_waiver_rows(waivers))
    return tuple(rows)
