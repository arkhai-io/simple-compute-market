"""Installed terms policies: what a buyer or a seller declines, by its own rule.

A policy states which valid, serviceable options its party will not take or
publish. It returns reasons to decline and nothing else, so term validation,
dispute-authority acceptance, mandate derivation and receipt verification run
whatever it answers. See
openspec/specs/settlement-configuration/spec.md, "A terms policy declines and
waives nothing else".
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from importlib.metadata import EntryPoint, entry_points
from typing import Any, Literal, Protocol, runtime_checkable

from market_core.schemas import SettlementOption
from market_deal_lifecycle.terms import LifecycleTerms

from .rate_publication import default_buyer_refusals

BUYER_TERMS_POLICY_GROUP = "market.buyer_terms_policies"
SELLER_TERMS_POLICY_GROUP = "market.seller_terms_policies"
DEFAULT_TERMS_POLICY = "default"
PERMISSIVE_TERMS_POLICY = "permissive"

TermsPolicyRole = Literal["buyer", "seller"]


class TermsPolicyError(ValueError):
    """The configured terms policy cannot be selected, loaded or built."""


@dataclass(frozen=True)
class BuyerTermsOffer:
    """One advertised or accepted option, as the buyer's composition reads it."""

    option: SettlementOption
    lifecycle: LifecycleTerms | None
    has_adapter: bool
    registry_url: str = ""


@runtime_checkable
class BuyerTermsPolicy(Protocol):
    def refusals(self, offer: BuyerTermsOffer) -> Sequence[str]:
        """Reasons this buyer declines the option; empty accepts it."""
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
_PROTOCOLS: dict[str, type] = {"buyer": BuyerTermsPolicy, "seller": SellerTermsPolicy}


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
    if not isinstance(policy, _PROTOCOLS[role]):
        raise TermsPolicyError(
            f"{role} terms policy {selection.name!r} must build a "
            f"{_PROTOCOLS[role].__name__}, got {type(policy).__name__}"
        )
    if role == "seller":
        periods = policy.default_penalty_periods()
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


class PermissiveBuyerTermsPolicy:
    """Decline nothing: every option the composition can take is acceptable."""

    def refusals(self, offer: BuyerTermsOffer) -> Sequence[str]:
        return ()


class DefaultSellerTermsPolicy:
    """Publish every derived option, reporting what a default buyer refuses."""

    def default_penalty_periods(self) -> int:
        return 24

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
    review = policy.review(SellerTermsOffer(
        option,
        LifecycleTerms.model_validate(option.lifecycle) if option.lifecycle is not None else None,
    ))
    subject = {"mechanism": option.settlement_schema, "option_id": option.option_id}
    for code, detail in review.diagnostics:
        diagnose({"code": code, "detail": detail, **subject})
    for detail in review.refusals:
        diagnose({"code": "seller_terms_policy_refusal", "detail": detail, **subject})
    return not review.refusals


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
    "DEFAULT_TERMS_POLICY",
    "DefaultBuyerTermsPolicy",
    "DefaultSellerTermsPolicy",
    "PERMISSIVE_TERMS_POLICY",
    "PermissiveBuyerTermsPolicy",
    "SELLER_TERMS_POLICY_GROUP",
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
    "permissive_buyer_terms_policy",
    "review_for_publication",
    "terms_policy_selection",
]
