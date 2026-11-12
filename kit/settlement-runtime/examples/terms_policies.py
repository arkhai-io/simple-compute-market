"""Example terms policies, as a third-party package would ship them.

docs/terms-policy-authoring.md walks through this module. A package registers
each factory under an entry-point group:

    [project.entry-points."market.buyer_terms_policies"]
    example = "terms_policies:example_buyer"

    [project.entry-points."market.seller_terms_policies"]
    example = "terms_policies:example_seller"
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from market_settlement_runtime.terms_policy import (
    BuyerTermsOffer,
    BuyerTermsPolicy,
    SellerTermsOffer,
    SellerTermsPolicy,
    SellerTermsReview,
)


def _settings(settings: Mapping[str, Any], defaults: Mapping[str, Any]) -> dict[str, Any]:
    unknown = sorted(set(settings) - set(defaults))
    if unknown:
        raise ValueError("unknown settings: " + ", ".join(unknown))
    merged = {**defaults, **settings}
    for key, default in defaults.items():
        if type(merged[key]) is not type(default):
            raise ValueError(f"{key} must be a {type(default).__name__}")
    return merged


class ExampleBuyer:
    """Take an option without a delivery deadline, but only with a real penalty.

    The packaged policies waive every right or none. This one states each right
    on its own: the deadline is optional, the on-demand penalty has a floor.
    """

    def __init__(self, *, require_delivery_deadline: bool, minimum_penalty: int) -> None:
        self.require_delivery_deadline = require_delivery_deadline
        self.minimum_penalty = minimum_penalty

    def refusals(self, offer: BuyerTermsOffer) -> Sequence[str]:
        terms = offer.lifecycle
        if not offer.has_adapter or terms is None:
            # No lifecycle adapter: the option promises nothing to weigh.
            return ()
        reasons = []
        if self.require_delivery_deadline and terms.delivery_deadline_seconds is None:
            reasons.append("no delivery deadline")
        early = terms.early_termination
        if early is not None and "payee" not in early.entitlements and early.penalty < self.minimum_penalty:
            reasons.append(
                f"premature-stop penalty {early.penalty} is below {self.minimum_penalty}"
            )
        return tuple(f"example buyer policy: {reason}" for reason in reasons)


def example_buyer(settings: Mapping[str, Any]) -> BuyerTermsPolicy:
    return ExampleBuyer(**_settings(
        settings, {"require_delivery_deadline": False, "minimum_penalty": 1},
    ))


class ExampleSeller:
    """Publish only options that promise a delivery deadline."""

    def __init__(self, *, penalty_periods: int) -> None:
        self.penalty_periods = penalty_periods

    def default_penalty_periods(self) -> int:
        return self.penalty_periods

    def review(self, offer: SellerTermsOffer) -> SellerTermsReview:
        terms = offer.lifecycle
        if terms is not None and terms.delivery_deadline_seconds is None:
            return SellerTermsReview(refusals=("no delivery deadline to promise",))
        return SellerTermsReview()


def example_seller(settings: Mapping[str, Any]) -> SellerTermsPolicy:
    return ExampleSeller(**_settings(settings, {"penalty_periods": 12}))
