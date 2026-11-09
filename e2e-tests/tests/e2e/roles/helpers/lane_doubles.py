"""The lane doubles' controls, as the payment scenarios reach them.

A lane runs its own payments and mediation doubles, and its runner profile names
each double's target, CA bundle and control token (PAYMENTS.CONTROL_TOKEN,
MEDIATION.CONTROL_TOKEN). The scenarios reach the doubles' control routes only
through the controls package's typed ``ControlClient``.

A payment scenario's result against the lane's doubles is lane-double evidence,
never live evidence: ``lane_doubles_evidence`` logs that label, with each
double's installed contract hashes read from its status, once per module that
asks for it, as the run's record. A run whose targets are not both the lane's
own doubles records nothing here. The doubles' contracts are identical to their
consumers' by construction, since both are built from one wheelhouse and lock,
so the hashes are information for the record and nothing compares them.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

import pytest
from lane_double_controls import ControlClient

from tests.e2e.roles.helpers.mediation import MediationTarget, mediation_if_configured
from tests.e2e.roles.helpers.payments import payment_flag, payment_setting

log = logging.getLogger(__name__)

#: The evidence class of a result against the lane's own doubles.
LANE_DOUBLES = "lane doubles"


@dataclass(frozen=True)
class LaneDoublesEvidence:
    """What a payment scenario's run records of the doubles it ran against."""

    label: str
    #: Each double's installed contract resources, by name, to their SHA-256.
    payments_contracts: dict[str, str]
    mediation_contracts: dict[str, str]


def payments_controls() -> ControlClient:
    """The lane's payments double's control client."""
    token = str(payment_setting("CONTROL_TOKEN"))
    if not token:
        pytest.fail("PAYMENTS.CONTROL_TOKEN not configured")
    return ControlClient(
        str(payment_setting("SERVICE_URL")).rstrip("/"), token=token,
        ca_bundle_path=str(payment_setting("CA_BUNDLE_PATH")) or None,
    )


def mediation_controls(target: MediationTarget) -> ControlClient:
    """The lane's mediation double's control client."""
    if not target.control_token:
        pytest.fail("MEDIATION.CONTROL_TOKEN not configured")
    return ControlClient(target.service_url, token=target.control_token,
                         ca_bundle_path=target.ca_bundle_path)


def read_lane_doubles_evidence(
    payments: ControlClient, mediation: ControlClient,
) -> LaneDoublesEvidence:
    """The *lane doubles* label and both doubles' contract hashes, from their
    status."""
    return LaneDoublesEvidence(
        label=LANE_DOUBLES,
        payments_contracts=payments.status().contracts,
        mediation_contracts=mediation.status().contracts,
    )


def _read_from_lane(mediation: MediationTarget) -> LaneDoublesEvidence:
    with payments_controls() as payments, mediation_controls(mediation) as controls:
        return read_lane_doubles_evidence(payments, controls)


def lane_doubles_evidence_of(
    mediation: MediationTarget | None,
    *,
    payments_lane_owned: bool,
    read: Callable[[MediationTarget], LaneDoublesEvidence] = _read_from_lane,
) -> LaneDoublesEvidence | None:
    """The run's lane-double evidence, logged, when its payments and mediation
    targets are both the lane's own; otherwise None, and nothing is read."""
    if mediation is None or not mediation.lane_owned or not payments_lane_owned:
        return None
    evidence = read(mediation)
    log.info("[evidence] %s: payments double contracts %s; mediation double contracts %s",
             evidence.label, evidence.payments_contracts, evidence.mediation_contracts)
    return evidence


@pytest.fixture(scope="module")
def lane_doubles_evidence() -> LaneDoublesEvidence | None:
    """The module's lane-double evidence, logged before its first stage, or None
    when the run's payments and mediation targets are not both the lane's own.
    An unready lane-owned mediation target fails the module's setup by name."""
    return lane_doubles_evidence_of(
        mediation_if_configured(), payments_lane_owned=payment_flag("LANE_OWNED"),
    )
