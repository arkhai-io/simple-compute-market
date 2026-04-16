"""Top-level conftest for role-separated tests.

Re-exports layer fixtures so all downstream tests under roles/ can
consume them:

  - external_world : EVM chain + deployed contracts
  - market_registry: marketplace operator's registry service
  - seller_node   : one seller's machine (agent + provisioning)
  - buyer_node    : one buyer's machine (agent)

A seller test depends on external_world + market_registry + seller_node.
A buyer test depends on external_world + market_registry + buyer_node.
A test that spans both roles (e.g. "buyer can find seller's offer")
depends on all four.
"""

from __future__ import annotations

from tests.roles.layers.test_external import external_world  # noqa: F401
from tests.roles.layers.test_market import market_registry  # noqa: F401
from tests.roles.layers.test_seller import seller_node  # noqa: F401
from tests.roles.layers.test_buyer import buyer_node  # noqa: F401
