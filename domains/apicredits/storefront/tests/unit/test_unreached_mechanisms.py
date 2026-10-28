"""Which mechanisms a create may be refused as retryable for.

A mechanism is unknown when it is enabled, unready, and every blocker it
reports is a reachability blocker. A create that publishes nothing is refused
as retryable only when every unready mechanism it uses is unknown; a caller
that waits for every mechanism, as the seed does, waits on any unknown one.
"""

from __future__ import annotations

import pytest
from market_settlement_runtime import MechanismReadiness, ReadinessBlocker

from apicredits_storefront.services.listing_service import _unreached_mechanisms

UNREACHED = ReadinessBlocker(
    code="alkahest.chain_unreachable", message="no answer", kind="reachability"
)
MISCONFIGURED = ReadinessBlocker(
    code="alkahest.oracle_policy_invalid", message="no oracle", kind="configuration"
)


def _status(mechanism: str, *blockers: ReadinessBlocker, enabled: bool = True):
    return MechanismReadiness(
        mechanism=mechanism,
        configured=True,
        enabled=enabled,
        ready=not blockers,
        blockers=blockers,
    )


@pytest.mark.parametrize("every", [True, False])
def test_a_mechanism_unready_only_for_reachability_is_unknown(every):
    assert _unreached_mechanisms((_status("alkahest.v1", UNREACHED),), every=every) == (
        "alkahest.v1",
    )


@pytest.mark.parametrize("every", [True, False])
def test_a_mechanism_with_a_configuration_blocker_is_not_unknown(every):
    used = (_status("alkahest.v1", UNREACHED, MISCONFIGURED),)

    assert _unreached_mechanisms(used, every=every) == ()


def test_an_unknown_mechanism_beside_a_misconfigured_one():
    """Refused as configuration when nothing publishes; waited on by a seed."""
    used = (
        _status("alkahest.v1", UNREACHED),
        _status("arkhai.payments.v1", MISCONFIGURED),
    )

    assert _unreached_mechanisms(used, every=True) == ()
    assert _unreached_mechanisms(used, every=False) == ("alkahest.v1",)


def test_ready_and_disabled_mechanisms_are_never_unknown():
    used = (
        _status("alkahest.v1"),
        _status("arkhai.payments.v1", UNREACHED, enabled=False),
    )

    assert _unreached_mechanisms(used, every=False) == ()
