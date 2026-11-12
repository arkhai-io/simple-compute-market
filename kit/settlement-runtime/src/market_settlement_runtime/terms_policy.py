"""Installed terms policies: what a buyer or a seller declines, by its own rule.

A policy states which valid, serviceable options its party will not take,
publish or serve, and a buyer's may order the ones it accepts. It returns
reasons to decline or an order and nothing else, so term validation,
dispute-authority acceptance, mandate derivation and receipt verification run
whatever it answers. A policy implements any of its role's methods; the
packaged default answers for the rest. See
openspec/specs/settlement-configuration/spec.md, "A terms policy declines and
waives nothing else".
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from importlib.metadata import EntryPoint, entry_points
from typing import Any, Literal, Protocol, runtime_checkable

from market_core.schemas import SettlementOption
from market_deal_lifecycle.terms import LifecycleTerms
from market_identity import Identity

from .rate_publication import default_buyer_refusals

BUYER_TERMS_POLICY_GROUP = "market.buyer_terms_policies"
SELLER_TERMS_POLICY_GROUP = "market.seller_terms_policies"
DEFAULT_TERMS_POLICY = "default"
PERMISSIVE_TERMS_POLICY = "permissive"

SELLER_REFUSAL_CODE = "seller_terms_policy_refusal"

TermsPolicyRole = Literal["buyer", "seller"]

logger = logging.getLogger(__name__)


class TermsPolicyError(ValueError):
    """The configured terms policy cannot be selected, loaded or built."""


@dataclass(frozen=True)
class BuyerTermsOffer:
    """One advertised or accepted option, as the buyer's composition reads it."""

    option: SettlementOption
    lifecycle: LifecycleTerms | None
    has_adapter: bool
    registry_url: str = ""
    # The listing advertising the option; empty when the option is read from
    # an accepted Agreement.
    listing: Mapping[str, Any] = field(default_factory=dict)


@runtime_checkable
class BuyerTermsPolicy(Protocol):
    def refusals(self, offer: BuyerTermsOffer) -> Sequence[str]:
        """Reasons this buyer declines the option; empty accepts it."""
        ...


@runtime_checkable
class BuyerTermsPreference(Protocol):
    def prefer(self, offers: Sequence[BuyerTermsOffer]) -> Sequence[BuyerTermsOffer]:
        """One listing's acceptable options, most preferred first.

        They arrive in the default order. An offer left out is not refused: it
        follows the returned ones, in the order it arrived.
        """
        ...


@dataclass(frozen=True)
class SellerTermsOffer:
    """One option a storefront derived and has not yet published."""

    option: SettlementOption
    lifecycle: LifecycleTerms | None


@dataclass(frozen=True)
class SellerTermsReview:
    """Refusals withhold the option; diagnostics are (code, detail) reports."""

    refusals: tuple[str, ...] = ()
    diagnostics: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class SellerTermsSelection:
    """One advertised option a verified buyer selected, before it is accepted.

    The option is None when the buyer opened with an escrow proposal, which
    selects an accepted escrow contract and no settlement option.
    """

    option: SettlementOption | None
    lifecycle: LifecycleTerms | None
    buyer: Identity
    listing: Mapping[str, Any]
    at: datetime


@runtime_checkable
class SellerTermsAdmission(Protocol):
    def admit(self, selection: SellerTermsSelection) -> Sequence[str]:
        """Reasons this seller will not serve the selection; empty admits it.

        The reasons are sent to the buyer.
        """
        ...


@runtime_checkable
class SellerTermsPolicy(Protocol):
    def default_penalty_periods(self) -> int:
        """Premature-stop penalty, in periods of the quoted amount, for an
        on-demand recurring preset whose clause names none."""
        ...

    def review(self, offer: SellerTermsOffer) -> SellerTermsReview:
        """Whether this seller publishes a derived option, and what it reports."""
        ...


@dataclass(frozen=True)
class TermsPolicySelection:
    """The configured policy name and the settings its factory receives."""

    name: str = DEFAULT_TERMS_POLICY
    settings: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name or self.name != self.name.strip():
            raise TermsPolicyError("terms_policy name must be a non-empty trimmed string")


def terms_policy_selection(document: Mapping[str, Any]) -> TermsPolicySelection:
    """Read the root terms_policy key: a name, or a table with a name.

    The key is matched case-insensitively, since settings loaders upper-case
    root keys. Absent selects the packaged default.
    """
    root = {str(key).lower(): value for key, value in document.items()}
    raw = root.get("terms_policy")
    if raw is None:
        return TermsPolicySelection()
    if isinstance(raw, str):
        return TermsPolicySelection(raw)
    if isinstance(raw, Mapping):
        table = {str(key).lower(): value for key, value in raw.items()}
        name = table.pop("name", DEFAULT_TERMS_POLICY)
        if not isinstance(name, str):
            raise TermsPolicyError("terms_policy.name must be a string")
        return TermsPolicySelection(name, table)
    raise TermsPolicyError("terms_policy must be a policy name or a table with a name")


_GROUPS: dict[str, str] = {
    "buyer": BUYER_TERMS_POLICY_GROUP,
    "seller": SELLER_TERMS_POLICY_GROUP,
}
_METHODS: dict[str, tuple[str, ...]] = {
    "buyer": ("refusals", "prefer"),
    "seller": ("default_penalty_periods", "review", "admit"),
}


def _implements(policy: Any, method: str) -> bool:
    return callable(getattr(policy, method, None))


def _entry_point_index(role: str, installed: Iterable[EntryPoint]) -> dict[str, EntryPoint]:
    providers: dict[str, list[EntryPoint]] = {}
    for entry_point in installed:
        providers.setdefault(entry_point.name, []).append(entry_point)
    for name, found in providers.items():
        values = sorted({entry_point.value for entry_point in found})
        if len(values) > 1:
            raise TermsPolicyError(
                f"multiple {role} terms policies named {name!r}: " + ", ".join(values)
            )
    return {name: found[0] for name, found in providers.items()}


def installed_terms_policies(role: TermsPolicyRole) -> tuple[str, ...]:
    """Installed policy names for a role, without importing any policy."""
    return tuple(sorted(_entry_point_index(role, entry_points(group=_GROUPS[role]))))


def load_terms_policy(
    role: TermsPolicyRole,
    selection: TermsPolicySelection | None = None,
    *,
    installed: Iterable[EntryPoint] | None = None,
) -> Any:
    """Build the one selected policy; never fall back to another.

    Only the selected entry point is imported. It names a factory called with
    the selection's settings; the result must satisfy the role's protocol.
    """
    selection = selection or TermsPolicySelection()
    group = _GROUPS[role]
    index = _entry_point_index(
        role, entry_points(group=group) if installed is None else tuple(installed)
    )
    entry_point = index.get(selection.name)
    if entry_point is None:
        available = ", ".join(sorted(index)) or "(none)"
        raise TermsPolicyError(
            f"{role} terms policy {selection.name!r} is not installed; available: {available}"
        )
    try:
        factory = entry_point.load()
    except Exception as exc:  # noqa: BLE001 - identify the broken distribution
        raise TermsPolicyError(
            f"{role} terms policy {selection.name!r} failed to load ({exc})"
        ) from exc
    if not callable(factory):
        raise TermsPolicyError(
            f"{role} terms policy {selection.name!r} must export a factory taking "
            f"its settings, got {type(factory).__name__}"
        )
    try:
        policy = factory(dict(selection.settings))
    except Exception as exc:  # noqa: BLE001 - the operator owns these settings
        raise TermsPolicyError(
            f"{role} terms policy {selection.name!r} rejected its settings: {exc}"
        ) from exc
    if not any(_implements(policy, method) for method in _METHODS[role]):
        raise TermsPolicyError(
            f"{role} terms policy {selection.name!r} must build an object with at "
            f"least one of {', '.join(_METHODS[role])}; got {type(policy).__name__}"
        )
    if role == "seller":
        periods = penalty_periods(policy)
        if type(periods) is not int or periods < 0:
            raise TermsPolicyError(
                f"seller terms policy {selection.name!r} default_penalty_periods "
                "must be a non-negative integer"
            )
    return policy


def load_buyer_terms_policy(
    selection: TermsPolicySelection | None = None,
    *,
    installed: Iterable[EntryPoint] | None = None,
) -> BuyerTermsPolicy:
    return load_terms_policy("buyer", selection, installed=installed)


def load_seller_terms_policy(
    selection: TermsPolicySelection | None = None,
    *,
    installed: Iterable[EntryPoint] | None = None,
) -> SellerTermsPolicy:
    return load_terms_policy("seller", selection, installed=installed)


def _no_settings(name: str, settings: Mapping[str, Any]) -> None:
    if settings:
        raise ValueError(
            f"the packaged {name!r} policy takes no settings: " + ", ".join(sorted(settings))
        )


class DefaultBuyerTermsPolicy:
    """Refuse an adapter option lacking the conservative buyer rights."""

    def refusals(self, offer: BuyerTermsOffer) -> Sequence[str]:
        return default_buyer_refusals(offer.lifecycle, has_adapter=offer.has_adapter)

    def prefer(self, offers: Sequence[BuyerTermsOffer]) -> Sequence[BuyerTermsOffer]:
        return offers


class PermissiveBuyerTermsPolicy:
    """Decline nothing: every option the composition can take is acceptable."""

    def refusals(self, offer: BuyerTermsOffer) -> Sequence[str]:
        return ()

    def prefer(self, offers: Sequence[BuyerTermsOffer]) -> Sequence[BuyerTermsOffer]:
        return offers


class DefaultSellerTermsPolicy:
    """Publish and serve every option, reporting what a default buyer refuses."""

    def default_penalty_periods(self) -> int:
        return 24

    def admit(self, selection: SellerTermsSelection) -> Sequence[str]:
        return ()

    def review(self, offer: SellerTermsOffer) -> SellerTermsReview:
        return SellerTermsReview(diagnostics=tuple(
            ("default_buyer_refusal", detail)
            for detail in default_buyer_refusals(
                offer.lifecycle, has_adapter=offer.lifecycle is not None,
            )
        ))


def default_buyer_terms_policy(settings: Mapping[str, Any]) -> BuyerTermsPolicy:
    _no_settings(DEFAULT_TERMS_POLICY, settings)
    return DefaultBuyerTermsPolicy()


def permissive_buyer_terms_policy(settings: Mapping[str, Any]) -> BuyerTermsPolicy:
    _no_settings(PERMISSIVE_TERMS_POLICY, settings)
    return PermissiveBuyerTermsPolicy()


def default_seller_terms_policy(settings: Mapping[str, Any]) -> SellerTermsPolicy:
    _no_settings(DEFAULT_TERMS_POLICY, settings)
    return DefaultSellerTermsPolicy()


def review_for_publication(
    policy: SellerTermsPolicy,
    option: SettlementOption,
    diagnose: Callable[[dict[str, Any]], None],
) -> bool:
    """Ask the seller's policy about one derived option; True publishes it."""
    if not _implements(policy, "review"):
        policy = DefaultSellerTermsPolicy()
    review = policy.review(SellerTermsOffer(
        option,
        LifecycleTerms.model_validate(option.lifecycle) if option.lifecycle is not None else None,
    ))
    subject = {"mechanism": option.settlement_schema, "option_id": option.option_id}
    for code, detail in review.diagnostics:
        diagnose({"code": code, "detail": detail, **subject})
    for detail in review.refusals:
        diagnose({"code": SELLER_REFUSAL_CODE, "detail": detail, **subject})
    return not review.refusals


def penalty_periods(policy: Any) -> int:
    """The policy's default penalty periods, or the packaged default's."""
    if not _implements(policy, "default_penalty_periods"):
        policy = DefaultSellerTermsPolicy()
    return policy.default_penalty_periods()


def selection_refusal(policy: Any, selection: SellerTermsSelection) -> str | None:
    """The reason a storefront refuses a selection, or None when it is admitted.

    The policy's reasons are what the buyer reads, after the refusal's code. A
    policy that fails refuses, and the buyer is told only that.
    """
    if not _implements(policy, "admit"):
        return None
    try:
        reasons = tuple(str(reason) for reason in policy.admit(selection))
    except Exception:  # noqa: BLE001 - installed code; fail closed
        logger.exception("seller terms policy failed admitting a selection")
        reasons = ("the seller's terms policy failed",)
    return f"{SELLER_REFUSAL_CODE}: " + "; ".join(reasons) if reasons else None


def seller_selection(
    selected: Mapping[str, Any] | None, *, buyer: Identity, listing: Mapping[str, Any],
    at: datetime,
) -> SellerTermsSelection:
    """Describe a selection from the listing's own artifact the buyer selected.

    The artifact is the listing's settlement option, or its accepted escrow
    for an escrow proposal; it is never the buyer's copy.
    """
    option = (
        SettlementOption.model_validate(selected)
        if isinstance(selected, Mapping) and "option_id" in selected else None
    )
    lifecycle = (
        LifecycleTerms.model_validate(option.lifecycle)
        if option is not None and option.lifecycle is not None else None
    )
    return SellerTermsSelection(option, lifecycle, buyer, listing, at)


def preferred_options(
    policy: Any, offers: Sequence[BuyerTermsOffer],
) -> tuple[BuyerTermsOffer, ...]:
    """One listing's acceptable offers in the policy's order.

    Ordering cannot refuse or introduce: an offer the policy leaves out keeps
    its place after the ones it returned, and one it invents is an error.
    """
    offers = tuple(offers)
    if not _implements(policy, "prefer") or len(offers) < 2:
        return offers
    by_id = {offer.option.option_id: offer for offer in offers}
    try:
        returned = [offer.option.option_id for offer in policy.prefer(offers)]
    except Exception as exc:  # noqa: BLE001 - installed code
        raise TermsPolicyError(
            f"buyer terms policy failed ordering options ({type(exc).__name__}: {exc})"
        ) from exc
    unknown = [option_id for option_id in returned if option_id not in by_id]
    if unknown:
        raise TermsPolicyError(
            "buyer terms policy preferred an option it was not offered: " + ", ".join(unknown)
        )
    ordered = list(dict.fromkeys(returned))
    return tuple(by_id[option_id] for option_id in (*ordered, *(i for i in by_id if i not in ordered)))


def flagged_buyer_selection(
    configured: TermsPolicySelection, *, allow_unprotected_terms: bool,
) -> TermsPolicySelection:
    """Apply the buyer commands' shorthand flag to the configured selection.

    The flag selects the packaged permissive policy. It does not replace a
    policy the buyer installed and selected, which would discard that policy's
    refusals unasked.
    """
    if not allow_unprotected_terms:
        return configured
    if configured.name not in (DEFAULT_TERMS_POLICY, PERMISSIVE_TERMS_POLICY):
        raise TermsPolicyError(
            f"--allow-unprotected-terms selects the {PERMISSIVE_TERMS_POLICY!r} terms "
            f"policy, but configuration selects {configured.name!r}; drop the flag "
            "or the configured policy"
        )
    return TermsPolicySelection(PERMISSIVE_TERMS_POLICY)


__all__ = [
    "BUYER_TERMS_POLICY_GROUP",
    "BuyerTermsOffer",
    "BuyerTermsPolicy",
    "BuyerTermsPreference",
    "DEFAULT_TERMS_POLICY",
    "DefaultBuyerTermsPolicy",
    "DefaultSellerTermsPolicy",
    "PERMISSIVE_TERMS_POLICY",
    "PermissiveBuyerTermsPolicy",
    "SELLER_REFUSAL_CODE",
    "SELLER_TERMS_POLICY_GROUP",
    "SellerTermsAdmission",
    "SellerTermsSelection",
    "SellerTermsOffer",
    "SellerTermsPolicy",
    "SellerTermsReview",
    "TermsPolicyError",
    "TermsPolicySelection",
    "default_buyer_terms_policy",
    "default_seller_terms_policy",
    "flagged_buyer_selection",
    "installed_terms_policies",
    "load_buyer_terms_policy",
    "load_seller_terms_policy",
    "load_terms_policy",
    "penalty_periods",
    "permissive_buyer_terms_policy",
    "preferred_options",
    "selection_refusal",
    "seller_selection",
    "review_for_publication",
    "terms_policy_selection",
]
