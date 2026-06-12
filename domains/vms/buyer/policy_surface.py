"""Compatibility shim — the scalar buyer-policy surface moved to
``core_buyer.policy_surface`` when the API-tokens domain became the
second schema plugin: the ``listed_price``/``bisection`` registrations
are escrow vocabulary shared by every scalar domain (two plugins
re-registering the same names would silently shadow each other), and
prices are per-unit — the VM plugin's unit is the lease hour."""

from core_buyer.policy_surface import (  # noqa: F401
    BISECTION_POLICY,
    LISTED_PRICE_POLICY,
    _SCALAR_PARAMS,
    configured_buyer_policy,
    derive_scalar_prices,
    entry_uses_scalar_amount,
)
