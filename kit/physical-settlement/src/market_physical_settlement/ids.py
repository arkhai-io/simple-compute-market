"""Globally unique opaque identifiers for the physical-settlement lifecycle.

Format decision (design.md, pools-7-storefront-fulfillment-cutover, "Final
planning decisions" -> "Cross-domain identities and terminology"): UUIDv7 via
the pure-Python ``uuid6`` package, not stdlib ``uuid4``.

This is a deliberate, isolated deviation from the rest of the repository,
which uses plain ``uuid.uuid4()`` everywhere else (``kit/site``,
``compute_provisioning_service``). Two things motivated it, together:

- UUIDv7 embeds a millisecond timestamp in its high bits, so IDs generated
  close in time sort close together. The settlement/fulfillment tables this
  package's later sections add (``SettlementRecord`` and friends) are
  expected to be high-write, primary-keyed-by-this-ID tables — time-ordered
  inserts keep B-tree/index locality instead of scattering writes randomly
  across the whole index, the way uuid4's fully-random bits would.
- Python's stdlib ``uuid`` module does not gain native ``uuid7()`` support
  until 3.14; this repository is pinned to ``>=3.12`` and there was no
  appetite to move that floor just for this. ``uuid6`` is a small,
  dependency-free, pure-Python (``py3-none-any``) package that backports
  ``uuid7()`` without requiring a newer interpreter.

Every ID in this module is an opaque ``str`` at the type level (matching
every existing ID type elsewhere in the repository, e.g. ``allocation_id``/
``capacity_reservation_id`` on ``SiteAllocation``) -- callers must not parse
structure out of the string beyond treating it as a UUID. Ownership is
carried by an explicit ``site_id`` field wherever routing/integrity needs
it, never encoded into the identifier itself (design.md, same section:
"ownership remains explicit via site_id rather than encoded into
identifier strings").

No site-plus-pool composite identifier type is introduced: explicit
``site_id`` plus a globally unique ``pool_id`` was decided to be sufficient
for routing and integrity (design.md, same section).
"""
from __future__ import annotations

from uuid6 import uuid7


def new_capacity_reservation_id() -> str:
    """A new opaque ``capacity_reservation_id``.

    Identifies admitted capacity and is the idempotency boundary for
    ``schedule_resource``/``begin_fulfillment`` (design.md, "Cross-domain
    identities and terminology").
    """
    return str(uuid7())


def new_fulfillment_id() -> str:
    """A new opaque ``fulfillment_id``, identifying the durable
    post-acceptance provisioning lifecycle aggregate returned by
    ``begin_fulfillment``."""
    return str(uuid7())


def new_provisioned_resource_id() -> str:
    """A new opaque ``provisioned_resource_id`` for one output of a
    fulfillment (e.g. one VM/pod). A fulfillment may produce zero or more
    of these."""
    return str(uuid7())


def new_settlement_resource_id() -> str:
    """A new opaque ``settlement_resource_id``, identifying the selected
    underlying physical supply resource -- not the provisioned VM/pod
    identity."""
    return str(uuid7())


def new_result_id() -> str:
    """A new opaque ``result_id`` for one recorded ``SettlementResult``."""
    return str(uuid7())
