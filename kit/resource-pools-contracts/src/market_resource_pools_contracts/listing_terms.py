"""A listing's settlement terms, resolved field by field through five tiers.

Every storefront that publishes from a pool's ``pricing`` hint resolves the
terms a listing publishes -- its settlement clause list and its legacy
accepted-escrow list -- through one order, highest precedence first:

1. the storefront's own override for the pool;
2. the pool's hint for the listing's model, ``pricing.<family>.<model>``;
3. the pool's hint for the whole pool, ``pricing.settlements``;
4. the storefront's configuration for the listing's model;
5. the storefront's flat configuration.

Each field resolves independently, and whole: the highest tier stating a list
supplies all of it, since merging clauses across tiers would publish a
combination nobody stated. An empty list is a statement and stops the lower
tiers. The model is keyed by data -- the caller names the family whose
attribute value keys it, such as a GPU model -- so this module knows no market's
vocabulary. An accepted-escrow list is a per-model term only: the pool-level
hint states clauses and nothing else.

A hint field of the wrong shape (a clause list that is not a list) is treated as
absent and falls through, as an absent one does: the hint is the pool
operator's, read by every storefront selling from the pool, and the reading
storefront owns validating the clauses themselves when it compiles them. The
override and configuration tiers are the storefront's own, validated where they
are written, so any value they state wins.

Capacity bounds are not resolved here: they have their own order, with the
mode-level ``capacity_bounds.<mode>`` hint ahead of any model hint
(``capacity_bounds``). ``model_hint_bounds`` reads the bounds a model hint
states, for a storefront that keeps them as a tier below the mode hint.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, fields
from typing import Any

from .capacity_bounds import CapacityBounds
from .hints import raw_pricing

#: The key, directly under ``pricing``, of the clause list a pool states for
#: every listing it publishes.
POOL_SETTLEMENTS_KEY = "settlements"


@dataclass(frozen=True)
class ListingTerms:
    """One tier's settlement terms for a listing.

    ``None`` on a field means this tier has no opinion, not that the field is
    empty: resolution falls through to the next tier for that field alone.
    """

    accepted_escrows: Any = None
    settlements: Any = None


def _pricing(policy_tags: Mapping[str, Any]) -> Mapping[str, Any] | None:
    pricing = raw_pricing(policy_tags)
    return pricing if isinstance(pricing, Mapping) else None


def model_hint(
    policy_tags: Mapping[str, Any], *, model_family: str, model: str | None
) -> Mapping[str, Any] | None:
    """The pool's ``pricing.<model_family>.<model>`` hint, or None.

    None when no model is given, or when any level of the path is absent or not
    a mapping.
    """
    if not model:
        return None
    pricing = _pricing(policy_tags)
    if pricing is None:
        return None
    family = pricing.get(model_family)
    if not isinstance(family, Mapping):
        return None
    terms = family.get(model)
    return terms if isinstance(terms, Mapping) else None


def pool_hint_terms(policy_tags: Mapping[str, Any]) -> ListingTerms:
    """The terms the pool's hint states for the whole pool."""
    pricing = _pricing(policy_tags)
    if pricing is None:
        return ListingTerms()
    return ListingTerms(settlements=pricing.get(POOL_SETTLEMENTS_KEY))


def model_hint_terms(
    policy_tags: Mapping[str, Any], *, model_family: str, model: str | None
) -> ListingTerms:
    """The terms the pool's hint states for one model."""
    terms = model_hint(policy_tags, model_family=model_family, model=model)
    if terms is None:
        return ListingTerms()
    return ListingTerms(
        accepted_escrows=terms.get("accepted_escrows"),
        settlements=terms.get("settlements"),
    )


def model_hint_bounds(
    policy_tags: Mapping[str, Any], *, model_family: str, model: str | None
) -> CapacityBounds:
    """The capacity bounds the pool's hint states for one model.

    Strict, as every bound tier is: a malformed value raises ``ValueError``
    rather than letting a lower tier's bound stand for it.
    """
    terms = model_hint(policy_tags, model_family=model_family, model=model)
    if terms is None:
        return CapacityBounds()
    return CapacityBounds(
        max_duration_seconds=terms.get("max_duration_seconds"),
        available_until_utc=terms.get("available_until_utc"),
    )


def _hint_value(value: Any) -> Any:
    # A hint field of the wrong shape falls through, as an absent one does.
    return value if isinstance(value, list) else None


def resolve_listing_terms(
    policy_tags: Mapping[str, Any],
    *,
    model_family: str,
    model: str | None,
    storefront_override: ListingTerms = ListingTerms(),
    config_defaults_by_model: Mapping[str, ListingTerms] | None = None,
    flat_default: ListingTerms = ListingTerms(),
) -> ListingTerms:
    """Resolve one listing's terms through the five tiers, field by field.

    ``model`` is the listing's value of the attribute ``model_family`` is keyed
    by, or None for a listing that states none, which resolves only the
    override, the pool-level hint, and the flat configuration.
    """
    config_model = (config_defaults_by_model or {}).get(model) if model else None
    hint_model = model_hint_terms(policy_tags, model_family=model_family, model=model)
    hint_pool = pool_hint_terms(policy_tags)

    def resolve(name: str) -> Any:
        for value in (
            getattr(storefront_override, name),
            _hint_value(getattr(hint_model, name)),
            _hint_value(getattr(hint_pool, name)),
            getattr(config_model, name) if config_model is not None else None,
            getattr(flat_default, name),
        ):
            if value is not None:
                return value
        return None

    return ListingTerms(**{field.name: resolve(field.name) for field in fields(ListingTerms)})


__all__ = [
    "POOL_SETTLEMENTS_KEY",
    "ListingTerms",
    "model_hint",
    "model_hint_bounds",
    "model_hint_terms",
    "pool_hint_terms",
    "resolve_listing_terms",
]
