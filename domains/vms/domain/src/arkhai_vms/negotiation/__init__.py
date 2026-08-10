"""VM negotiation policies offered to either market role.

The guards that interpret VM market content, and the reinforcement-learning
strategy. Both roles reach this package: a storefront resolves the guards, and a
buyer may negotiate with the strategy, so it belongs to the distribution both
declare rather than to one role's package.

Storefront-only negotiation machinery — the per-round seller hook and its chain
assembly — stays with the storefront.
"""
