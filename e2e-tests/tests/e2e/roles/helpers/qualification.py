"""What the real-provisioning qualification scenarios read besides the deal.

Two parts, neither tied to a domain:

- **Grant admission.** A relayed lease is admitted by the relay's admission
  plugin, whose decision log is a documented contract
  (``tools/frp-grant-admission/README.md#the-log``). The target names a
  harness-local copy of it (``RelayAccess.admission_log``). A delivered lease
  is admitted when the log holds an ``admit`` line, verified, for the lease's
  reservation (the grant's ``jti``), its remote port, and the key that signed
  its latest grant as the relay's lease record names it (``grant_key_id``).
  The relay's active key is not the comparison: a rotation keeps a retired
  key's grants valid on unreleased leases, so an admission before a rotation
  is correct under a key other than the active one, and an earlier ``admit``
  under an older key, left by a job retried across a rotation, is not the
  latest grant's.
- **Per-observation outcome.** A qualification module makes several of the
  runbook's observations
  (``docs/development/VALIDATION_RUNBOOK.md#observations-the-qualification-owes``),
  and a pytest run that passes with a skipped stage has not run every check an
  observation requires. So a qualification module names its observations
  (``OBSERVATIONS``), each of its stages declares the observations requiring
  it (``observations`` on its class), and once the module's last stage has
  reported, the outcome of each is logged: made when every requiring stage
  passed, failed when one failed, and unproven when none failed and one
  skipped, naming what the skip named. Nothing is written to a file: the
  operator's sanitized account of the log is the evidence.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import pytest

from e2e_harness.real_provisioning_target import SECTION, BareMetalHost, VmHost

log = logging.getLogger(__name__)

# ===========================================================================
# Grant admission
# ===========================================================================


def relay_lease_record(provisioning_client: Any, relay_id: str, reservation: str) -> Any:
    """The relay's record of the unreleased port it holds for ``reservation``."""
    holdings = provisioning_client.list_relay_leases(relay_id)
    owned = [
        lease for lease in holdings.leases
        if lease.owner_kind == "fulfillment" and lease.owner_id == reservation
        and lease.released_at is None
    ]
    assert len(owned) == 1, (
        f"relay {relay_id!r} holds {len(owned)} unreleased ports for reservation "
        f"{reservation!r}, where one was expected: "
        f"{[(lease.lease_id, lease.remote_port) for lease in owned]}"
    )
    return owned[0]


def admission_decisions(lines: Iterable[str]) -> list[dict[str, Any]]:
    """The decision lines of an admission log, in order.

    A line that is not a JSON object is not a decision: a copy the deployment
    is still appending to may end in a partial line.
    """
    decisions = []
    for line in lines:
        try:
            decision = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(decision, dict) and decision.get("event") in ("admit", "refuse"):
            decisions.append(decision)
    return decisions


def _summary(decision: Mapping[str, Any]) -> dict[str, Any]:
    keys = ("ts", "event", "reason", "remote_port", "kid", "jti", "verified")
    return {key: decision[key] for key in keys if key in decision}


def require_admitted(lines: Iterable[str], record: Any, *, relay_id: str) -> dict[str, Any]:
    """The admission log's ``admit`` of the lease's latest grant.

    ``record`` is the relay's lease record (``relay_lease_record``). Raises
    naming the lease, and every decision the log holds for its reservation,
    when no line admits it.
    """
    reservation = str(record.owner_id)
    named = (
        f"lease {record.lease_id} of relay {relay_id!r} (reservation {reservation}, "
        f"port {record.remote_port}, grant key {record.grant_key_id})"
    )
    assert record.grant_key_id, f"{named} records no signed grant"
    decisions = admission_decisions(lines)
    for decision in reversed(decisions):
        port = decision.get("remote_port")
        if (
            decision.get("event") == "admit"
            and decision.get("verified") is True
            and decision.get("jti") == reservation
            and type(port) is int and port == record.remote_port
            and decision.get("kid") == record.grant_key_id
        ):
            return decision
    for_reservation = [_summary(d) for d in decisions if d.get("jti") == reservation]
    raise AssertionError(
        f"the admission log holds no verified admit of {named}; its decisions for "
        f"the reservation: {for_reservation}"
    )


def admission_log_field(domain: str) -> str:
    return f"{SECTION}.hosts.{domain}.access.admission_log"


#: How long ``check_admission`` re-reads the log copy for the lease's admit.
#: The deployment copies the relay's log to the harness's machine, so the
#: line may reach the copy a little after the admission it records.
ADMISSION_COPY_BOUND_SECONDS = 60.0
ADMISSION_COPY_POLL_SECONDS = 2.0


def _read_admission_log(path: str, field: str) -> list[str]:
    try:
        return Path(path).read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise AssertionError(f"{field} {path!r} cannot be read: {error}") from None


def check_admission(
    target: VmHost | BareMetalHost, provisioning_client: Any, reservation: str, *,
    bound: float = ADMISSION_COPY_BOUND_SECONDS,
    poll_interval: float = ADMISSION_COPY_POLL_SECONDS,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any] | None:
    """Require the relay's admission of ``reservation``'s delivered lease.

    A target reached directly delivers no relayed lease, so there is nothing to
    admit and ``None`` is returned. A relayed target naming no admission log
    skips, naming the field: the observation requiring this check is then
    unproven, not made. The copy is re-read within ``bound`` while it holds no
    admit of the lease, since the deployment's copy may trail the relay's log;
    a file that cannot be read fails at once, naming the field and the path.
    """
    access = target.access
    if access.mode == "direct":
        log.info("Target %s is reached directly; no relayed lease to admit", target.host_id)
        return None
    field = admission_log_field(target.domain)
    if access.admission_log is None:
        pytest.skip(f"{field} is not set, so grant admission of the relayed lease is unread")
    record = relay_lease_record(provisioning_client, access.relay_id, reservation)
    # The record is read once: a lease with no grant yet has nothing to wait for.
    assert record.grant_key_id, (
        f"lease {record.lease_id} of relay {access.relay_id!r} (reservation "
        f"{reservation}) records no signed grant"
    )
    deadline = clock() + bound
    while True:
        lines = _read_admission_log(access.admission_log, field)
        try:
            admitted = require_admitted(lines, record, relay_id=access.relay_id)
            break
        except AssertionError:
            if clock() >= deadline:
                raise
        sleep(max(0.0, min(poll_interval, deadline - clock())))
    log.info("Relay %s admitted reservation %s on port %s under grant key %s at %s",
             access.relay_id, reservation, record.remote_port, record.grant_key_id,
             admitted.get("ts"))
    return admitted


# ===========================================================================
# Per-observation outcome
# ===========================================================================

#: The class attribute a qualification stage declares the observations
#: requiring it by: the runbook's observation numbers, as strings.
OBSERVATIONS_ATTRIBUTE = "observations"

StageOutcome = Literal["passed", "failed", "skipped"]
Outcome = Literal["made", "failed", "unproven"]


@dataclass(frozen=True)
class StageResult:
    """One stage's outcome, and the observations requiring it."""

    stage: str
    observations: frozenset[str]
    outcome: StageOutcome
    #: What a skip named; empty otherwise.
    reason: str = ""


@dataclass(frozen=True)
class ObservationOutcome:
    observation: str
    outcome: Outcome
    #: The stages deciding the outcome: the failed ones, the skipped ones for
    #: an unproven outcome, or every requiring stage for a made one.
    stages: tuple[str, ...]
    #: For an unproven outcome, what each deciding skip named.
    reasons: tuple[str, ...] = ()


def observation_outcomes(
    observations: Iterable[str], results: Iterable[StageResult],
) -> list[ObservationOutcome]:
    """Each observation's outcome from its requiring stages' outcomes.

    A failure outranks a skip; an observation no stage of the run declares is
    unproven, since none of its checks ran.
    """
    results = list(results)
    outcomes = []
    for observation in observations:
        requiring = [result for result in results if observation in result.observations]
        failed = [result.stage for result in requiring if result.outcome == "failed"]
        skipped = [result for result in requiring if result.outcome == "skipped"]
        if failed:
            outcomes.append(ObservationOutcome(observation, "failed", tuple(failed)))
        elif skipped or not requiring:
            outcomes.append(ObservationOutcome(
                observation, "unproven", tuple(result.stage for result in skipped),
                tuple(result.reason for result in skipped) or ("no stage requiring it ran",),
            ))
        else:
            outcomes.append(ObservationOutcome(
                observation, "made", tuple(result.stage for result in requiring),
            ))
    return outcomes


def _skip_reason(report: Any) -> str:
    longrepr = report.longrepr
    reason = longrepr[2] if isinstance(longrepr, tuple) and len(longrepr) == 3 else str(longrepr)
    return reason.removeprefix("Skipped: ")


def stage_result(stage: str, observations: Iterable[str], reports: Mapping[str, Any]) -> StageResult:
    """A stage's outcome from its pytest reports, by phase.

    A failed phase is a failed stage, a teardown's included; a skipped setup (a
    fixture's skip) or call is a skipped stage. A stage with no report did not
    run, which is no evidence for its observations: it reads as skipped.
    """
    observations = frozenset(observations)
    if any(report.failed for report in reports.values()):
        return StageResult(stage, observations, "failed")
    for when in ("setup", "call"):
        report = reports.get(when)
        if report is not None and report.skipped:
            return StageResult(stage, observations, "skipped", _skip_reason(report))
    if "call" in reports:
        return StageResult(stage, observations, "passed")
    return StageResult(stage, observations, "skipped", "the stage did not run")


#: Where ``record_report`` keeps an item's reports.
REPORTS = pytest.StashKey[dict[str, Any]]()


def declared_observations(item: Any) -> tuple[str, ...]:
    cls = getattr(item, "cls", None)
    return tuple(getattr(cls, OBSERVATIONS_ATTRIBUTE, ()) or ())


#: The modules whose outcomes a session has logged, so each is logged once.
LOGGED = pytest.StashKey[set[str]]()


def _qualification_module(item: Any) -> Any | None:
    module = getattr(item, "module", None)
    return module if getattr(module, "OBSERVATIONS", None) else None


def record_report(item: Any, report: Any) -> None:
    """Keep a qualification stage's report, and log its module's outcomes once
    the module's last item has reported its teardown.

    Called from the roles conftest's report hook for every item; only an item
    whose class declares observations is kept. The last item's teardown is
    where a module's fixtures are finalized, so a failure in the module's own
    cleanup fails that item's stage when it is a declared one.
    """
    if declared_observations(item):
        item.stash.setdefault(REPORTS, {})[report.when] = report
    module = _qualification_module(item)
    if module is None or report.when != "teardown":
        return
    ours = [other for other in item.session.items if getattr(other, "module", None) is module]
    if ours and ours[-1] is item:
        log_module_outcomes(item.session, module)


def log_module_outcomes(session: Any, module: Any) -> None:
    """Log ``module``'s outcomes over the session's items, unless already logged."""
    logged = session.stash.setdefault(LOGGED, set())
    if module.__name__ in logged:
        return
    logged.add(module.__name__)
    log_observation_outcomes(module, session.items)


def log_unlogged_outcomes(session: Any) -> None:
    """At the session's end, log each qualification module not yet logged.

    A run stopped early (``-x``, ``--maxfail``) never tears its module's last
    item down, so its outcomes are logged here, the stages it did not run read
    as not run.
    """
    modules = {id(module): module for module in map(_qualification_module, session.items)
               if module is not None}
    for module in modules.values():
        log_module_outcomes(session, module)


def declared_stages(module: Any) -> list[tuple[type, str]]:
    """Every stage of ``module`` declaring observations: its class and test.

    Read from the module's source, not from the run's items, so a stage the
    run deselected or never collected still counts, as one that did not run.
    """
    return [
        (cls, name)
        for cls in vars(module).values()
        if isinstance(cls, type) and cls.__name__.startswith("Test")
        and getattr(cls, OBSERVATIONS_ATTRIBUTE, ())
        for name in dir(cls) if name.startswith("test") and callable(getattr(cls, name))
    ]


def stage_results(module: Any, items: Iterable[Any]) -> list[StageResult]:
    """Each declared stage of ``module``'s outcome over the run's ``items``."""
    items = list(items)
    results = []
    for cls, name in declared_stages(module):
        runs = [item for item in items
                if getattr(item, "cls", None) is cls and getattr(item, "originalname", item.name) == name]
        observations = getattr(cls, OBSERVATIONS_ATTRIBUTE)
        if not runs:
            results.append(stage_result(f"{cls.__name__}::{name}", observations, {}))
        results.extend(
            stage_result(f"{cls.__name__}::{item.name}", observations, item.stash.get(REPORTS, {}))
            for item in runs
        )
    return results


def log_observation_outcomes(module: Any, items: Iterable[Any]) -> list[ObservationOutcome]:
    """Log the outcome of each observation ``module.OBSERVATIONS`` names."""
    outcomes = observation_outcomes(module.OBSERVATIONS, stage_results(module, items))
    for outcome in outcomes:
        if outcome.outcome == "made":
            log.info("Observation %s: made (%s)", outcome.observation, ", ".join(outcome.stages))
        elif outcome.outcome == "failed":
            log.error("Observation %s: failed at %s", outcome.observation, ", ".join(outcome.stages))
        else:
            named = "; ".join(f"{stage}: {reason}" for stage, reason in
                              zip(outcome.stages, outcome.reasons))
            log.warning("Observation %s: unproven: %s", outcome.observation,
                        named or outcome.reasons[0])
    return outcomes


__all__ = [
    "OBSERVATIONS_ATTRIBUTE",
    "ObservationOutcome",
    "StageResult",
    "admission_decisions",
    "admission_log_field",
    "check_admission",
    "declared_observations",
    "declared_stages",
    "log_module_outcomes",
    "log_observation_outcomes",
    "log_unlogged_outcomes",
    "observation_outcomes",
    "record_report",
    "relay_lease_record",
    "require_admitted",
    "stage_result",
    "stage_results",
]
