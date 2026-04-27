"""Domain-agnostic policy engine.

Provides:
- A callable registry (`@policy_callable`) plus discovery helpers.
- A composable policy store backed by a persistence port.
- A negotiation thread store keyed off an injected `Identity`.
- Action builders that produce symmetric, transport-agnostic outputs.

Both buyer and provider can drive negotiation through this engine; the
data model is symmetric and nothing here depends on a specific server
runtime or protocol.
"""
