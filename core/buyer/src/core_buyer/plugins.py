"""Buyer market-domain contract discovery.

Core owns command assembly and discovers immutable domain contracts without
importing any concrete domain package or branching on domain identity.
"""

from __future__ import annotations

from importlib.metadata import entry_points
from typing import Any, Iterable

from market_core import MarketDomainContract, validate_domain_contracts

DOMAIN_GROUP = "market.buyer_domains"


def _iter_entry_points() -> Iterable[Any]:
    return entry_points(group=DOMAIN_GROUP)


class DomainPluginLoadError(RuntimeError):
    """An installed buyer domain could not be loaded."""


def discover_domains() -> list[MarketDomainContract]:
    """Load and validate every installed buyer domain before CLI startup.

    A declared domain that cannot be imported is a broken install, not a
    domain to omit. Reporting it as an absence produces "no domain is
    installed" for a distribution that is installed and incomplete, which
    hides packaging defects behind a message about configuration.
    """
    domains: list[MarketDomainContract] = []
    for entry_point in _iter_entry_points():
        try:
            loaded = entry_point.load()
        except Exception as exc:
            raise DomainPluginLoadError(
                f"buyer domain {entry_point.name!r} is installed but could "
                f"not be loaded from {getattr(entry_point, 'value', entry_point)!r}: "
                f"{type(exc).__name__}: {exc}"
            ) from exc
        if not isinstance(loaded, MarketDomainContract):
            raise TypeError(
                f"buyer domain {entry_point.name!r} must resolve to a "
                f"MarketDomainContract, got {type(loaded).__name__}"
            )
        domains.append(loaded)
    return list(validate_domain_contracts(domains))
