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

A lane keeps its doubles for every module it runs, so whatever a module changes
in them is undone when it ends, whatever its outcome: ``lane_double_rules``
deletes every rule the module installed, on both doubles, and fails naming one
that still held a case at its gate, which deleting it leaves waiting for good;
``lane_double_clock`` resets both doubles' perceived clocks to wall time and
fails naming a double that still reports an offset, since a later module's
deals would otherwise be dated ahead of their storefronts.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Literal

import pytest
from lane_double_controls import ControlClient, ControlError, Rule, RuleView

from tests.e2e.roles.helpers.cleanup import run_cleanup
from tests.e2e.roles.helpers.mediation import (
    MediationTarget, configured_mediation, mediation_if_configured,
)
from tests.e2e.roles.helpers.payments import payment_flag, payment_setting

#: The lane's two doubles, by the name a scenario addresses each with.
Double = Literal["payments", "mediation"]
DOUBLES: tuple[Double, ...] = ("payments", "mediation")

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


class LaneDoubleRules:
    """The rules one module installs on the lane's doubles.

    ``remove_all`` is the module's cleanup: it reads both doubles' rule
    listings, deletes every rule the module installed and has not deleted
    itself, attempting every deletion whatever read or deletion fails, and only
    then fails naming each failure and each rule that still had a case waiting
    at its gate.
    """

    def __init__(self, controls: Mapping[Double, ControlClient]) -> None:
        self.controls = controls
        self._installed: list[tuple[Double, str]] = []

    def install(self, double: Double, rule: Rule) -> RuleView:
        view = self.controls[double].install_rule(rule)
        self._installed.append((double, rule.rule_id))
        return view

    def view(self, double: Double, rule_id: str) -> RuleView:
        """The installed rule's listing, with its matched and waiting counts."""
        listing = self.controls[double].rules().rules
        views = [view for view in listing if view.rule.rule_id == rule_id]
        assert views, f"the {double} double lists no rule {rule_id}: {listing}"
        return views[0]

    def resume(self, rule_id: str) -> RuleView:
        """Continue every case waiting on a mediation rule."""
        return self.controls["mediation"].resume_rule(rule_id)

    def delete(self, double: Double, rule_id: str) -> None:
        self.controls[double].delete_rule(rule_id)
        self._installed.remove((double, rule_id))

    def remove_all(self) -> None:
        installed, self._installed = self._installed, []
        waiting: list[str] = []

        def read_waiting(double: Double) -> None:
            # A deleted rule leaves the listing, so its waiting count is read first.
            ours = {rule_id for owner, rule_id in installed if owner == double}
            waiting.extend(
                f"{double} rule {view.rule.rule_id} ({view.waiting} waiting)"
                for view in self.controls[double].rules().rules
                if view.rule.rule_id in ours and view.waiting
            )

        def delete(double: Double, rule_id: str) -> None:
            try:
                self.controls[double].delete_rule(rule_id)
            except ControlError as error:
                # Already gone is what cleanup wants.
                if error.code != "rule_not_found":
                    raise

        # Every step is attempted whichever fails, so an unreadable listing
        # still leaves no rule installed.
        run_cleanup([
            *((f"read the {double} double's rules", lambda double=double: read_waiting(double))
              for double in DOUBLES if any(owner == double for owner, _ in installed)),
            *((f"delete the {double} double's rule {rule_id}",
               lambda double=double, rule_id=rule_id: delete(double, rule_id))
              for double, rule_id in installed),
        ])
        if waiting:
            pytest.fail("a rule the module installed still held a case at its gate: "
                        + "; ".join(waiting))


class LaneDoubleClock:
    """Both doubles' perceived clocks, moved together.

    ``reset`` is the module's cleanup: it resets both doubles, then fails
    naming each whose status still reports an offset from wall time.
    """

    def __init__(self, controls: Mapping[Double, ControlClient]) -> None:
        self.controls = controls

    def advance(self, seconds: int) -> dict[Double, int]:
        """Advance both doubles by ``seconds``; each double's perceived now."""
        return {double: self.controls[double].advance_clock(seconds).perceived_now
                for double in DOUBLES}

    def reset(self) -> None:
        run_cleanup([(f"reset the {double} double's clock", self.controls[double].reset_clock)
                     for double in DOUBLES])
        offsets = {double: self.controls[double].status().offset_seconds for double in DOUBLES}
        ahead = [f"{double} ({offset}s ahead)" for double, offset in offsets.items() if offset]
        if ahead:
            pytest.fail("a double still reports an offset from wall time after its reset: "
                        + ", ".join(ahead))


def lane_double_controls() -> dict[Double, ControlClient]:
    """Both doubles' control clients, for a module that controls the lane's
    doubles: a blocked skip when the run's targets are not both the lane's own,
    since only a lane's own doubles offer controls."""
    mediation = configured_mediation()
    if not mediation.lane_owned or not payment_flag("LANE_OWNED"):
        pytest.skip("blocked: controlling the doubles needs the lane's own payments and "
                    "mediation targets (PAYMENTS.LANE_OWNED, MEDIATION.LANE_OWNED)")
    return {"payments": payments_controls(), "mediation": mediation_controls(mediation)}


@contextmanager
def rules_removed_after(controls: Mapping[Double, ControlClient]) -> Iterator[LaneDoubleRules]:
    """Rules on the doubles, every one the body installed deleted when it ends,
    however it ends; the controls are closed after."""
    rules = LaneDoubleRules(controls)
    try:
        yield rules
    finally:
        try:
            rules.remove_all()
        finally:
            for client in controls.values():
                client.close()


@contextmanager
def clocks_reset_after(controls: Mapping[Double, ControlClient]) -> Iterator[LaneDoubleClock]:
    """Both doubles' clocks, reset to wall time when the body ends, however it
    ends; the controls are closed after."""
    clock = LaneDoubleClock(controls)
    try:
        yield clock
    finally:
        try:
            clock.reset()
        finally:
            for client in controls.values():
                client.close()


@pytest.fixture(scope="module")
def lane_double_rules() -> Iterator[LaneDoubleRules]:
    """The module's rules on the lane's doubles, every one deleted when the
    module ends, whatever its outcome; the cleanup fails naming a rule that
    still held a case at its gate."""
    with rules_removed_after(lane_double_controls()) as rules:
        yield rules


@pytest.fixture(scope="module")
def lane_double_clock() -> Iterator[LaneDoubleClock]:
    """Both doubles' perceived clocks, reset to wall time when the module ends,
    whatever its outcome; the cleanup fails naming a double left ahead."""
    with clocks_reset_after(lane_double_controls()) as clock:
        yield clock


@pytest.fixture(scope="module")
def lane_doubles_evidence() -> LaneDoublesEvidence | None:
    """The module's lane-double evidence, logged before its first stage, or None
    when the run's payments and mediation targets are not both the lane's own.
    An unready lane-owned mediation target fails the module's setup by name."""
    return lane_doubles_evidence_of(
        mediation_if_configured(), payments_lane_owned=payment_flag("LANE_OWNED"),
    )
