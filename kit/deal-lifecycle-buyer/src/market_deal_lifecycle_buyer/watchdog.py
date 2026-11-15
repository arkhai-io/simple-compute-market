"""The buyer's watchdog: a foreground probe loop that sends the ordinary rate stop.

The loop runs only inside the buyer's own command; there is no buyer daemon. Its
bound is conditional: a lost resource is detected within at most
``interval × threshold + probe timeout``, and only while the loop runs; the
authority's acknowledgement of the stop it then sends and any priced notice come
after that, and billing runs until the stop lands.

The status a buyer read shows rests on the probes themselves, never on the
opt-in: a killed or hung loop stops recording probes, so its deal reads as
unmonitored once its last probe is stale. The status is the buyer's knowledge of
its own process; it is no field of any lifecycle wire model.
See openspec/specs/deal-lifecycle/spec.md, "The buyer's watchdog bounds detection
only while it runs".
"""

from __future__ import annotations

import asyncio
import base64
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import socket
import sqlite3
import time
from typing import TYPE_CHECKING, Literal

from market_deal_lifecycle_contracts.models import Accepted, EvidenceItem, Rejected
from market_identity import canonical_json

from .ending import EndDeliveryProgress

if TYPE_CHECKING:
    from .lifecycle import BuyerLifecycle

#: Conservative defaults: the stop a probe failure triggers cannot be undone, so
#: a transient outage must persist for minutes before the watchdog acts.
DEFAULT_INTERVAL_SECONDS = 60
DEFAULT_THRESHOLD = 5
DEFAULT_PROBE_TIMEOUT_SECONDS = 10
#: The slack a reader allows beyond one interval and probe timeout before a
#: running loop's last probe reads as stale.
GRACE_SECONDS = 5

WatchdogStatus = Literal["monitored", "stopped", "unmonitored"]
#: One probe of the disclosed access: true when the resource answered. An
#: exception or a probe outlasting its timeout is a failed probe.
Probe = Callable[[], Awaitable[bool]]


@dataclass(frozen=True)
class WatchdogSettings:
    interval_seconds: int = DEFAULT_INTERVAL_SECONDS
    threshold: int = DEFAULT_THRESHOLD
    probe_timeout_seconds: int = DEFAULT_PROBE_TIMEOUT_SECONDS

    def __post_init__(self) -> None:
        if self.interval_seconds < 1 or self.threshold < 1 or self.probe_timeout_seconds < 1:
            raise ValueError("watchdog interval, threshold and probe timeout must each be at least 1")

    @property
    def bound_seconds(self) -> int:
        """The longest a loss goes undetected while the loop runs."""
        return self.interval_seconds * self.threshold + self.probe_timeout_seconds

    def to_json(self) -> dict[str, int]:
        return {"interval_seconds": self.interval_seconds, "threshold": self.threshold,
                "probe_timeout_seconds": self.probe_timeout_seconds}


@dataclass(frozen=True)
class ProbeObservation:
    """One failed probe the buyer observed, kept with its instant."""

    at: int
    detail: str

    def to_json(self) -> dict[str, int | str]:
        return {"at": self.at, "detail": self.detail}


@dataclass(frozen=True)
class WatchdogStop:
    """The probe evidence the watchdog acted on when it decided to stop."""

    decided_at: int
    probes: tuple[ProbeObservation, ...]

    def to_json(self) -> dict:
        return {"decided_at": self.decided_at, "probes": [probe.to_json() for probe in self.probes]}

    @classmethod
    def from_json(cls, data: dict) -> WatchdogStop:
        return cls(data["decided_at"], tuple(ProbeObservation(p["at"], p["detail"]) for p in data["probes"]))


@dataclass(frozen=True)
class WatchdogState:
    settings: WatchdogSettings
    last_probe_at: int | None = None
    stop: WatchdogStop | None = None


class WatchdogJournal:
    """Per-deal opt-in, settings, last-probe instant and stop, beside the end journal."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path.touch(mode=0o600, exist_ok=True)
        with sqlite3.connect(self.path) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS buyer_watchdogs (
                negotiation_id TEXT PRIMARY KEY, settings TEXT NOT NULL,
                last_probe_at INTEGER, stop TEXT
            )""")

    def opt_in(self, negotiation_id: str, settings: WatchdogSettings) -> None:
        """Record that the buyer asked for a monitor, keeping any probe or stop already kept."""
        with sqlite3.connect(self.path, timeout=30) as db:
            db.execute(
                """INSERT INTO buyer_watchdogs (negotiation_id, settings) VALUES (?, ?)
                   ON CONFLICT(negotiation_id) DO UPDATE SET settings=excluded.settings""",
                (negotiation_id, json.dumps(settings.to_json(), sort_keys=True)),
            )

    def state(self, negotiation_id: str) -> WatchdogState | None:
        with sqlite3.connect(self.path, timeout=30) as db:
            row = db.execute(
                "SELECT settings, last_probe_at, stop FROM buyer_watchdogs WHERE negotiation_id=?",
                (negotiation_id,),
            ).fetchone()
        if row is None:
            return None
        settings, last_probe_at, stop = row
        return WatchdogState(
            WatchdogSettings(**json.loads(settings)), last_probe_at,
            WatchdogStop.from_json(json.loads(stop)) if stop is not None else None,
        )

    def record_probe(self, negotiation_id: str, at: int) -> None:
        with sqlite3.connect(self.path, timeout=30) as db:
            db.execute("UPDATE buyer_watchdogs SET last_probe_at=? WHERE negotiation_id=?", (at, negotiation_id))

    def record_stop(self, negotiation_id: str, stop: WatchdogStop) -> WatchdogStop:
        """Journal the stop decision once; a repeated decision keeps the first."""
        with sqlite3.connect(self.path, timeout=30) as db:
            db.execute(
                "UPDATE buyer_watchdogs SET stop=? WHERE negotiation_id=? AND stop IS NULL",
                (json.dumps(stop.to_json(), sort_keys=True), negotiation_id),
            )
            row = db.execute("SELECT stop FROM buyer_watchdogs WHERE negotiation_id=?", (negotiation_id,)).fetchone()
        if row is None or row[0] is None:
            raise ValueError("watchdog stop requires the deal's opt-in")
        return WatchdogStop.from_json(json.loads(row[0]))

    def delete(self, db: sqlite3.Connection, negotiation_id: str) -> None:
        """Delete the deal's row inside the caller's transaction."""
        db.execute("DELETE FROM buyer_watchdogs WHERE negotiation_id = ?", (negotiation_id,))


def watchdog_status(state: WatchdogState | None, now: int) -> WatchdogStatus:
    """``monitored`` only while a probe ran recently; ``stopped`` once the stop is journaled."""
    if state is None:
        return "unmonitored"
    if state.stop is not None:
        return "stopped"
    if state.last_probe_at is None:
        return "unmonitored"
    fresh = state.settings.interval_seconds + state.settings.probe_timeout_seconds + GRACE_SECONDS
    return "monitored" if now - state.last_probe_at <= fresh else "unmonitored"


def watchdog_view(state: WatchdogState | None, now: int) -> dict:
    """The status a buyer read shows, with the instant it rests on."""
    return {
        "status": watchdog_status(state, now),
        "last_probe_at": state.last_probe_at if state is not None else None,
    }


@dataclass(frozen=True)
class WatchdogOutcome:
    """Why the loop exited: it sent the stop, or the deal ended by another path.

    ``resumed`` marks a stop journaled by an earlier run, which this run only
    carried to the authority or found already there.
    """

    reason: Literal["stopped", "ended"]
    progress: EndDeliveryProgress | None = None
    resumed: bool = False


@dataclass(frozen=True)
class WaitClock:
    """The clock a buyer command's waits and probe instants run on.

    ``now`` stamps probes in Unix seconds; ``monotonic`` and ``sleep`` pace the
    waits, so a test drives them in fake time.
    """

    now: Callable[[], int] = lambda: int(time.time())
    monotonic: Callable[[], float] = time.monotonic
    sleep: Callable[[float], Awaitable[object]] = asyncio.sleep


async def tcp_reachable(host: str, port: int) -> bool:
    """Whether ``host:port`` accepts a TCP connection; the caller bounds the wait."""
    _, writer = await asyncio.open_connection(host, port, family=socket.AF_UNSPEC)
    writer.close()
    try:
        await writer.wait_closed()
    except OSError:
        pass
    return True


async def deal_ended(lifecycle: BuyerLifecycle, negotiation_id: str) -> bool:
    """Whether the deal has ended by a path other than the watchdog's own stop.

    The buyer's own end journal, the payment authority and the storefront are
    each read independently, so one unreachable party hides nothing the others show.
    """
    if lifecycle.end_journal is not None and lifecycle.end_journal.read(negotiation_id) is not None:
        return True
    payment = lifecycle.payments.resolve(lifecycle._deal(negotiation_id).payment)
    if payment is not None:
        try:
            view = await payment.read()
        except Exception:
            view = None
        if view is not None and (view.state == "ended" or any(part.final_stop for part in view.parts)):
            return True
    try:
        delivery = (await lifecycle.peer.read(negotiation_id)).delivery
    except Exception:
        return False
    return delivery.recorded_end is not None or delivery.progress in {"end_recorded", "tearing_down", "released"}


async def _keep_evidence(lifecycle: BuyerLifecycle, negotiation_id: str, stop: WatchdogStop,
                         settings: WatchdogSettings) -> None:
    if lifecycle.evidence is None:
        return
    deal = lifecycle._deal(negotiation_id)
    body = canonical_json({
        "kind": "watchdog_stop", "negotiation_id": negotiation_id,
        "settings": settings.to_json(), **stop.to_json(),
    })
    digest = hashlib.sha256(body).hexdigest()
    context: dict = {"digest": digest}
    if deal.buyer is not None:
        context["producer"] = deal.buyer.model_dump(mode="json")
    await lifecycle.evidence.put(negotiation_id, EvidenceItem(
        evidence_id="watchdog-stop:" + digest, kind="watchdog_probe_failures",
        classification="buyer_observation", recorded_at=stop.decided_at,
        body=base64.b64encode(body), context=context,
    ))


async def _send_stop(
    lifecycle: BuyerLifecycle, negotiation_id: str, *, interval: int,
    sleep: Callable[[float], Awaitable[object]],
) -> EndDeliveryProgress:
    """Send the deal's one stop and retry it, every interval, until it lands.

    The end journal keys the stop by deal, so every retry, and a restarted loop,
    resends this one stop under its operation key rather than a second. Billing
    runs until the stop lands, which is why the loop keeps the command running.
    """
    plan = lifecycle.end_journal.read(negotiation_id) if lifecycle.end_journal is not None else None
    if plan is not None and isinstance(plan.progress.payment, (Accepted, Rejected)):
        return plan.progress
    while True:
        progress = await lifecycle.end(negotiation_id)
        if isinstance(progress.payment, (Accepted, Rejected)):
            return progress
        await sleep(interval)


async def _bounded(check: Callable[[], Awaitable[bool]], seconds: int) -> bool:
    # A read that hangs must not stretch the probe schedule the bound rests on;
    # unanswered, the deal is taken as still running.
    try:
        return await asyncio.wait_for(check(), seconds)
    except asyncio.TimeoutError:
        return False


async def watch_deal(
    lifecycle: BuyerLifecycle, negotiation_id: str, *, journal: WatchdogJournal, probe: Probe | None,
    clock: Callable[[], int] = lambda: int(time.time()),
    sleep: Callable[[float], Awaitable[object]] = asyncio.sleep,
    ended: Callable[[], Awaitable[bool]] | None = None,
) -> WatchdogOutcome:
    """Probe the deal's access until ``threshold`` consecutive failures, then stop.

    Probes start on a fixed schedule, one every ``interval`` from the loop's
    start, and each probe and each ended-check is cut off at the probe timeout,
    so the detection bound and the status's freshness window both hold while the
    loop runs. The stop is the buyer's ordinary entitled stop and hint
    (``BuyerLifecycle.end`` for a rate deal), sent after the decision and its
    probe evidence are journaled, and retried until it lands. A loop restarted
    after that decision sends nothing new and needs no probe: it resumes the one
    journaled stop until it lands. The loop exits also when the deal ends by
    another path; the buyer stops it by interrupting its command.
    """
    if not lifecycle._deal(negotiation_id).rate:
        raise ValueError("the watchdog applies to rate deals; a once-only deal ends by surrender")
    state = journal.state(negotiation_id)
    if state is None:
        raise ValueError("the deal has no watchdog opt-in")
    settings = state.settings

    async def stop_landed() -> EndDeliveryProgress:
        return await _send_stop(lifecycle, negotiation_id, interval=settings.interval_seconds, sleep=sleep)

    if state.stop is not None:
        await _keep_evidence(lifecycle, negotiation_id, state.stop, settings)
        return WatchdogOutcome("stopped", await stop_landed(), resumed=True)
    if probe is None:
        raise ValueError("a watchdog with no journaled stop needs a probe of the deal's access")
    check_ended = ended or (lambda: deal_ended(lifecycle, negotiation_id))
    failures: list[ProbeObservation] = []
    due = clock()
    while True:
        if await _bounded(check_ended, settings.probe_timeout_seconds):
            return WatchdogOutcome("ended")
        at = clock()
        try:
            answered = await asyncio.wait_for(probe(), settings.probe_timeout_seconds)
            detail = "" if answered else "access did not answer"
        except asyncio.TimeoutError:
            answered, detail = False, "probe timed out"
        except Exception as exc:
            answered, detail = False, f"probe failed: {type(exc).__name__}"
        journal.record_probe(negotiation_id, at)
        # A passing probe ends the run of failures: only consecutive ones count.
        failures = [] if answered else [*failures, ProbeObservation(at, detail)]
        if len(failures) >= settings.threshold:
            stop = journal.record_stop(negotiation_id, WatchdogStop(clock(), tuple(failures)))
            await _keep_evidence(lifecycle, negotiation_id, stop, settings)
            return WatchdogOutcome("stopped", await stop_landed())
        due += settings.interval_seconds
        await sleep(max(0, due - clock()))
