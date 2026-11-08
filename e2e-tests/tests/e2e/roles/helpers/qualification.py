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
  (``OBSERVATIONS``, or ``CYCLE_OBSERVATIONS`` for a module run once per
  cycle), each of its stages requires them unless its class declares its own
  (``stage_observations``), and once the module's last stage has reported, the
  outcome of each is logged: made when every requiring stage passed, failed
  when one failed, and unproven when none failed and one skipped, naming what
  the skip named. Nothing is written to a file: the operator's sanitized
  account of the log is the evidence.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

import pytest

from e2e_harness.real_provisioning_target import (
    SECTION,
    BareMetalHost,
    TargetNotConfigured,
    VmHost,
    load_real_provisioning_target,
)

log = logging.getLogger(__name__)

# ===========================================================================
# The target
# ===========================================================================


def target_host(settings: Any, domain: Literal["vm", "bare_metal"]) -> VmHost | BareMetalHost:
    """The real-provisioning target's host of ``domain``, or a blocked skip.

    A skip names what is missing: the target, or its host of that domain. A
    target that is present and invalid fails, naming the field.
    """
    target = load_real_provisioning_target(settings)
    if isinstance(target, TargetNotConfigured):
        pytest.skip(f"blocked: {target.reason}")
    host = target.host_for(domain)
    if host is None:
        pytest.skip(f"blocked: {SECTION}.hosts holds no {domain} host")
    return host


def run_stage(stage: type, **arguments: Any) -> None:
    """Run a shared stage's body with ``arguments`` as its fixtures.

    A module declares each shared stage once, so a second purchase in the
    same module runs the same definitions on its own state and driver this
    way, from a stage of the module's own, rather than redefining them.
    """
    (name,) = [name for name in dir(stage)
               if name.startswith("test") and callable(getattr(stage, name))]
    getattr(stage(), name)(**arguments)


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
# Registration reapplied
# ===========================================================================


@dataclass(frozen=True)
class QuarantinedPort:
    """A released relay port whose grants have not yet expired."""

    lease_id: str
    remote_port: int
    owner_id: str
    grant_expires_at: datetime
    #: When the lease was released. A release writes it only on a lease not yet
    #: released, so a later value for the same lease means it was un-released
    #: and released again, which its identity alone would not show.
    released_at: datetime


@dataclass(frozen=True)
class RegistrationSnapshot:
    """What one target host's registration amounts to, read from its authorities.

    Each tuple is sorted, so two snapshots compare as values.
    """

    #: The host rows registered under the target's id: (host, pool, enabled).
    hosts: tuple[tuple[str, str | None, bool], ...]
    #: The site's capacity declarations bound to the host, each the allocation
    #: record the site sells the host's capacity from: (resource, pool).
    declarations: tuple[tuple[str, str | None], ...]
    #: The storefront's listings on the host's resource: (listing, status, paused).
    listings: tuple[tuple[str, str, bool], ...]
    #: The relay's quarantined ports, for a relayed target.
    quarantined: tuple[QuarantinedPort, ...] = ()
    #: The relay's ports with an unreleased owner.
    active_ports: tuple[int, ...] = ()


def _utc(moment: datetime) -> datetime:
    """``moment`` in UTC. The provisioning service stores and returns a relay
    lease's times without a zone, in UTC; comparing one with an aware ``now``
    would raise rather than compare."""
    return moment.replace(tzinfo=timezone.utc) if moment.tzinfo is None else moment


def quarantined_ports(leases: Iterable[Any], now: datetime) -> tuple[QuarantinedPort, ...]:
    """The released relay leases whose grants are still unexpired at ``now``,
    an aware time."""
    return tuple(sorted(
        (QuarantinedPort(str(lease.lease_id), int(lease.remote_port), str(lease.owner_id),
                         _utc(lease.grant_expires_at), _utc(lease.released_at))
         for lease in leases
         if lease.released_at is not None and lease.grant_expires_at is not None
         and _utc(lease.grant_expires_at) > now),
        key=lambda port: (port.remote_port, port.lease_id),
    ))


def registration_faults(
    name: str, before: RegistrationSnapshot, after: RegistrationSnapshot, *, now: datetime,
) -> list[str]:
    """How reapplying ``name``'s registration and a publication cycle changed it.

    Nothing may be duplicated or dropped: one host row, one declaration, and
    all existing listings, including closed history, with each identity, state
    and pause intact.
    Every port quarantined before stays quarantined until its grant expires,
    with no new owner, and its lease record unchanged: the same owner, grant
    expiry and release time. Matching the lease by identity alone would let
    relay-port reconciliation, which runs on its own ungated timer, hide a
    quarantine the reapply cleared by releasing the lease again.

    A port active before and released after is not a fault: an unheld lease
    watchdog may end a live lease legitimately, so this comparison makes no
    claim that a live tenancy survives.
    """
    faults = []
    for kind, rows, expected in (
        ("host", after.hosts, 1), ("capacity declaration", after.declarations, 1),
        ("listing", after.listings, max(1, len(before.listings))),
    ):
        if len(rows) != expected:
            faults.append(
                f"{name}: {len(rows)} {kind}s after reapplying, expected {expected}: {rows}"
            )
    for kind, was, now_is in (("hosts", before.hosts, after.hosts),
                              ("capacity declarations", before.declarations, after.declarations),
                              ("listings", before.listings, after.listings)):
        if was != now_is:
            faults.append(f"{name}: {kind} changed from {was} to {now_is}")
    kept = {port.lease_id: port for port in after.quarantined}
    for port in before.quarantined:
        if port.grant_expires_at <= now:
            continue
        now_is = kept.get(port.lease_id)
        if now_is is None:
            faults.append(f"{name}: relay port {port.remote_port} (lease {port.lease_id}) left "
                          f"quarantine before its grants expire at {port.grant_expires_at}")
        elif now_is != port:
            faults.append(f"{name}: relay port {port.remote_port} (lease {port.lease_id}) is "
                          f"still quarantined but its lease record changed from {port} to "
                          f"{now_is}")
        if port.remote_port in after.active_ports:
            faults.append(f"{name}: quarantined relay port {port.remote_port} has a new owner")
    return faults


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


def _qualification_module(item: Any) -> Any | None:
    module = getattr(item, "module", None)
    return module if getattr(module, "OBSERVATIONS", None) else None


def _cycles(module: Any) -> list[Any]:
    """The values of the module's cycle parameter, or one ``None`` for none."""
    by_cycle = getattr(module, "CYCLE_OBSERVATIONS", None)
    return list(by_cycle) if by_cycle else [None]


def _cycle_of(module: Any, item: Any) -> Any:
    param = getattr(module, "CYCLE_PARAM", None)
    callspec = getattr(item, "callspec", None)
    return callspec.params.get(param) if param and callspec is not None else None


def stage_observations(module: Any, cls: Any, cycle: Any = None) -> tuple[str, ...]:
    """The observations requiring a stage of a qualification module.

    A stage class may declare its own (``observations``); otherwise every
    stage requires the module's: ``CYCLE_OBSERVATIONS[cycle]`` in a module run
    once per cycle (by its ``CYCLE_PARAM``), else ``OBSERVATIONS``. A shared
    stage is declared with an empty body, so the module's default is how it
    is required. Either form may map a cycle to its observations.
    """
    declared = getattr(cls, OBSERVATIONS_ATTRIBUTE, None)
    if declared is None:
        declared = getattr(module, "CYCLE_OBSERVATIONS", None) or module.OBSERVATIONS
    if isinstance(declared, Mapping):
        return tuple(declared.get(cycle, ()))
    return tuple(declared)


def item_observations(item: Any) -> tuple[str, ...]:
    module = _qualification_module(item)
    if module is None:
        return ()
    return stage_observations(module, getattr(item, "cls", None), _cycle_of(module, item))


#: The modules whose outcomes a session has logged, so each is logged once.
LOGGED = pytest.StashKey[set[str]]()


def record_report(item: Any, report: Any) -> None:
    """Keep a qualification stage's report, and log its module's outcomes once
    the module's last item has reported its teardown.

    Called from the roles conftest's report hook for every item; only an item
    some observation requires is kept. The last item's teardown is where a
    module's fixtures are finalized, so a failure in the module's own cleanup
    fails that item's stage.
    """
    if item_observations(item):
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
    """Every stage of ``module``: its class and test.

    Read from the module's source, not from the run's items, so a stage the
    run deselected or never collected still counts, as one that did not run.
    """
    return [
        (cls, name)
        for cls in vars(module).values()
        if isinstance(cls, type) and cls.__name__.startswith("Test")
        for name in dir(cls) if name.startswith("test") and callable(getattr(cls, name))
    ]


def stage_results(module: Any, items: Iterable[Any]) -> list[StageResult]:
    """Each stage of ``module``'s outcome over the run's ``items``, per cycle."""
    items = list(items)
    results = []
    for cls, name in declared_stages(module):
        for cycle in _cycles(module):
            observations = stage_observations(module, cls, cycle)
            if not observations:
                continue
            label = f"{cls.__name__}::{name}" + ("" if cycle is None else f"[{cycle}]")
            runs = [
                item for item in items
                if getattr(item, "cls", None) is cls
                and getattr(item, "originalname", item.name) == name
                and _cycle_of(module, item) == cycle
            ]
            if not runs:
                results.append(stage_result(label, observations, {}))
            results.extend(
                stage_result(f"{cls.__name__}::{item.name}", observations,
                             item.stash.get(REPORTS, {}))
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
    "QuarantinedPort",
    "RegistrationSnapshot",
    "StageResult",
    "admission_decisions",
    "admission_log_field",
    "check_admission",
    "declared_stages",
    "item_observations",
    "log_module_outcomes",
    "log_observation_outcomes",
    "log_unlogged_outcomes",
    "observation_outcomes",
    "quarantined_ports",
    "record_report",
    "registration_faults",
    "relay_lease_record",
    "require_admitted",
    "run_stage",
    "stage_observations",
    "stage_result",
    "stage_results",
    "target_host",
]
