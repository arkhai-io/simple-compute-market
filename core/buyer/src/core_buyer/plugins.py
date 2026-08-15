"""Buyer market-domain contract discovery.

Core owns command assembly and discovers immutable domain contracts without
importing any concrete domain package or branching on domain identity.
"""

from __future__ import annotations

import sys
from importlib.metadata import entry_points
from typing import Any, Iterable

from market_core import MarketDomainContract, validate_domain_contracts

DOMAIN_GROUP = "market.buyer_domains"


def _iter_entry_points() -> Iterable[Any]:
    return entry_points(group=DOMAIN_GROUP)


def discover_domains() -> list[MarketDomainContract]:
    """Load and validate every installed buyer domain before CLI startup."""
    domains: list[MarketDomainContract] = []
    for entry_point in _iter_entry_points():
        try:
            loaded = entry_point.load()
        except Exception as exc:  # noqa: BLE001 - identify broken distributions
            print(
                f"[market] skipping buyer domain {entry_point.name!r}: "
                f"failed to load ({exc})",
                file=sys.stderr,
            )
            continue
        if not isinstance(loaded, MarketDomainContract):
            raise TypeError(
                f"buyer domain {entry_point.name!r} must resolve to a "
                f"MarketDomainContract, got {type(loaded).__name__}"
            )
        domains.append(loaded)
    return list(validate_domain_contracts(domains))
