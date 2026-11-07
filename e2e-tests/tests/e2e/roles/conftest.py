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

import pytest

from tests.e2e.roles.layers.test_external import external_world  # noqa: F401
from tests.e2e.roles.layers.test_registry import registry_layer  # noqa: F401
from tests.e2e.roles.layers.test_seller import seller_node  # noqa: F401
from tests.e2e.roles.buyer_cli import buyer_cli, buyer_cli_binary  # noqa: F401
from tests.e2e.roles.helpers.qualification import log_unlogged_outcomes, record_report


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(item, call):
    """Keep each qualification stage's report, and log a qualification
    module's per-observation outcomes once it has run
    (``helpers/qualification.py``); every other item is left alone."""
    report = yield
    record_report(item, report)
    return report


def pytest_sessionfinish(session):
    """Log the outcomes of a qualification module a stopped run left unlogged."""
    log_unlogged_outcomes(session)
