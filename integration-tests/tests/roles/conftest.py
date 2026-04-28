"""Top-level conftest for role-separated tests.

Re-exports layer fixtures so all downstream tests under roles/ can
consume them:

  - external_world : EVM chain + deployed contracts
  - market_registry: marketplace operator's registry service
  - seller_node   : one seller's machine (agent + provisioning)

There is no buyer_node fixture: the buyer is a pure HTTP client (the
`market` CLI / market_buyer library) invoked as a one-shot subprocess
in roles/cli/test_market_buy.py — it has no long-running node to
fixture out.
"""

from __future__ import annotations

from tests.roles.layers.test_external import external_world  # noqa: F401
from tests.roles.layers.test_market import market_registry  # noqa: F401
from tests.roles.layers.test_seller import seller_node  # noqa: F401
