"""Top-level conftest for role-separated tests.

Re-exports layer fixtures so all downstream tests under roles/ can
consume them:

  - external_world : EVM chain + deployed contracts
  - registry_layer : marketplace operator's registry service
  - seller_node    : one seller's machine (agent + provisioning)
  - buyer_cli      : a buyer's `market` CLI invoked as a subprocess

There is no buyer_node fixture because the buyer doesn't run a server.
Instead ``buyer_cli`` spawns the same ``market`` binary they would run
on their own machine, against a hermetic XDG state/config dir.
"""

from __future__ import annotations

from tests.e2e.roles.layers.test_external import external_world  # noqa: F401
from tests.e2e.roles.layers.test_registry import registry_layer  # noqa: F401
from tests.e2e.roles.layers.test_seller import seller_node  # noqa: F401
from tests.e2e.roles.buyer_cli import buyer_cli, buyer_cli_binary  # noqa: F401
