"""Local identity injected into the policy engine.

The engine doesn't read agent identity from any global config; callers
construct an `Identity` and hand it to the negotiation thread store at
init. This keeps the engine free of dependencies on
`core.agent.app.utils.config.CONFIG` (or any other party's runtime
config) and lets buyer-side and provider-side callers each construct
their own.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Identity:
    """The local participant's identity for negotiation bookkeeping.

    `agent_url` is the canonical handle used as `owner_id` in the
    private-state side of the thread store (so that one SQLite file can
    in principle hold threads owned by multiple participants without
    collision).

    `agent_id` is currently unused by the engine itself but is kept
    here for symmetry with the registration data model and for future
    use (e.g., logging, metrics tagging).
    """

    agent_url: str
    agent_id: str = ""
