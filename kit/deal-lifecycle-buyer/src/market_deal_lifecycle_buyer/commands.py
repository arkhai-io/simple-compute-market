"""Reusable buyer commands over a composition-owned store and lifecycle."""

import asyncio
from collections.abc import Awaitable, Callable, Coroutine
from concurrent.futures import ThreadPoolExecutor
from contextlib import AbstractAsyncContextManager
from dataclasses import asdict, dataclass
import inspect
import json
import time
from typing import Any, Literal, TypeVar

import typer

from market_deal_lifecycle.terms import LifecycleTerms
from market_deal_lifecycle_contracts.models import Accepted
from market_deal_lifecycle_buyer.export import export_case
from market_deal_lifecycle_buyer.lifecycle import BuyerLifecycle
from market_deal_lifecycle_buyer.retention import DealReader, prune_command
from market_deal_lifecycle_buyer.store import FileEvidenceStore
from market_deal_lifecycle_buyer.watchdog import (
    DEFAULT_INTERVAL_SECONDS, DEFAULT_PROBE_TIMEOUT_SECONDS, DEFAULT_THRESHOLD, Probe, WaitClock,
    WatchdogJournal, WatchdogOutcome, WatchdogSettings, watch_deal,
)

T = TypeVar("T")


@dataclass(frozen=True)
class EndTarget:
    """One run's deal, as a domain opens it for the ``end`` verb.

    ``record`` writes a named event to the run's log, where the domain keeps one.
    """

    negotiation_id: str
    lifecycle: AbstractAsyncContextManager[BuyerLifecycle]
    record: Callable[[str, dict[str, Any]], None] | None = None


def _run(action: Callable[[], Coroutine[Any, Any, T]]) -> T:
    # A command may be invoked from inside a running event loop, as a test or an
    # embedding caller does; its own loop runs on a thread of its own.
    with ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(lambda: asyncio.run(action())).result()


async def end_deal(
    target: EndTarget, *, surrender: bool, wait_timeout: float, poll_interval: float,
    sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    """End the deal, then read its delivery back, waiting up to ``wait_timeout`` for release.

    A rate deal's normal end stops billing through the payer's notice and keeps
    service until the authority's stop takes effect; ``surrender`` gives service
    up now. The delivery read is the storefront's signed answer and is kept
    whether or not either authority is reachable, so its failure is reported
    beside the end's outcome rather than replacing it.
    """
    async with target.lifecycle as lifecycle:
        progress = await lifecycle.end(target.negotiation_id, surrender=surrender)
        if target.record is not None:
            target.record("delivery_end", progress.model_dump(mode="json"))
        delivery = progress.acknowledgement.delivery if progress.acknowledgement else None
        deadline = monotonic() + wait_timeout
        delivery_read_error = None
        while True:
            try:
                observed = await lifecycle.peer.read(target.negotiation_id)
            except Exception:
                delivery_read_error = "storefront delivery read unavailable; authority outcome is retained"
                break
            delivery = observed.delivery
            if delivery.progress == "released" or monotonic() >= deadline:
                break
            await sleep(min(poll_interval, max(0.0, deadline - monotonic())))
    result = {
        "progress": progress.model_dump(mode="json"),
        "delivery_view": delivery.model_dump(mode="json") if delivery else None,
        "capacity_released": delivery is not None and delivery.progress == "released",
        "delivery_read_error": delivery_read_error,
    }
    if target.record is not None:
        target.record("delivery_end_observed", result)
    return result


def end_exit_code(result: dict[str, Any], *, wait_timeout: float) -> int:
    """1 when the end's governing outcome is not accepted, or a wait ended unreleased."""
    outcome = "payment" if result["progress"]["mode"] == "normal_stop" else "delivery"
    if result["progress"][outcome]["status"] != Accepted().status:
        return 1
    return 1 if wait_timeout > 0 and not result["capacity_released"] else 0


_END_HELP = """Stop rate billing and keep service through the payer's notice; otherwise surrender.

--end-now-regardless gives service up before any paid notice expires. The
output reports payment, delivery, case and capacity separately; a queued
teardown is never reported as released. There is no historical end-time flag,
and a once-only deal's end invents no refund. Retry the same command to recover
an unavailable stop or filing.
"""


def register_end_command(
    app: typer.Typer, open_end: Callable[[str, str | None], EndTarget], *,
    configurable: bool = False, deprecated_alias: str | None = None,
) -> None:
    """Register the buyer's canonical ``end`` verb on a domain's command group.

    ``open_end`` opens a run's deal from its run ID and, when ``configurable``,
    the ``--config`` path the domain reads; otherwise it receives ``None``. A
    ``deprecated_alias`` ends the deal the same way after a notice naming
    ``end``, and keeps the output its callers parse: the end's progress alone,
    exiting 0 whatever its outcome.
    """

    def run(
        run_id: str, config: str | None, wait_timeout: float, poll_interval: float, surrender: bool,
        *, progress_only: bool = False,
    ) -> None:
        try:
            target = open_end(run_id, config)
            result = _run(lambda: end_deal(
                target, surrender=surrender, wait_timeout=wait_timeout, poll_interval=poll_interval,
            ))
        except ValueError as exc:
            raise typer.BadParameter(str(exc)) from exc
        if progress_only:
            typer.echo(json.dumps(result["progress"], sort_keys=True))
            return
        typer.echo(json.dumps(result, sort_keys=True))
        code = end_exit_code(result, wait_timeout=wait_timeout)
        if code:
            raise typer.Exit(code)

    run_option = typer.Option(..., *RUN_SPELLINGS, help="The run whose deal to end.")
    wait_option = typer.Option(0, "--wait-timeout", min=0, help="Seconds to wait for capacity release.")
    poll_option = typer.Option(1, "--poll-interval", min=0.01)
    surrender_option = typer.Option(
        False, "--end-now-regardless", help="Surrender service now, even while paid notice remains.",
    )

    if configurable:
        def command(
            run_id: str = run_option, config: str | None = typer.Option(None, "--config"),
            wait_timeout: float = wait_option, poll_interval: float = poll_option,
            surrender: bool = surrender_option,
        ) -> None:
            run(run_id, config, wait_timeout, poll_interval, surrender)
    else:
        def command(  # type: ignore[misc]
            run_id: str = run_option, wait_timeout: float = wait_option,
            poll_interval: float = poll_option, surrender: bool = surrender_option,
        ) -> None:
            run(run_id, None, wait_timeout, poll_interval, surrender)

    command.__doc__ = _END_HELP
    app.command("end")(command)
    if deprecated_alias is not None:
        def alias(**options: Any) -> None:
            typer.echo(
                f"'{deprecated_alias}' is deprecated and will be removed; use 'end', which ends the deal "
                "the same way and prints its progress, delivery read and capacity release.",
                err=True,
            )
            run(
                options["run_id"], options.get("config"), options["wait_timeout"], options["poll_interval"],
                options["surrender"], progress_only=True,
            )

        # The alias takes exactly the verb's options, so its help and parsing match.
        alias.__signature__ = inspect.signature(command)  # type: ignore[attr-defined]
        alias.__doc__ = (
            "Deprecated: use 'end'. Ends the deal as 'end' does, then prints the end's\n"
            "progress alone and exits 0, without the delivery read or capacity release.\n"
        )
        app.command(deprecated_alias)(alias)


#: The run spellings every verb that opens a run's deal accepts.
RUN_SPELLINGS = ("--from", "--run", "--run-id", "-r")


async def read_deal(target: EndTarget) -> dict[str, Any]:
    """The buyer's read of the run's deal, with the watchdog's status."""
    async with target.lifecycle as lifecycle:
        return await lifecycle.buyer_read(target.negotiation_id)


def register_read_command(
    app: typer.Typer, open_target: Callable[[str, str | None], EndTarget], *,
    name: str = "delivery", configurable: bool = False,
) -> None:
    """Register the buyer's read of a run's deal on a domain's command group.

    ``open_target`` is the domain's ``end`` seam, called as ``register_end_command``
    calls it. The output is the lifecycle read with the watchdog's status beside it:
    ``monitored`` only while a probe ran recently, ``stopped`` once the watchdog
    journaled its stop, and ``unmonitored`` otherwise.
    """

    def run(run_id: str, config: str | None) -> None:
        try:
            result = _run(lambda: read_deal(open_target(run_id, config)))
        except ValueError as exc:
            raise typer.BadParameter(str(exc)) from exc
        typer.echo(json.dumps(result, sort_keys=True))

    run_option = typer.Option(..., *RUN_SPELLINGS, help="The run whose deal to read.")
    if configurable:
        def command(run_id: str = run_option, config: str | None = typer.Option(None, "--config")) -> None:
            run(run_id, config)
    else:
        def command(run_id: str = run_option) -> None:  # type: ignore[misc]
            run(run_id, None)

    command.__doc__ = "Read delivery, site reports, authority progress and the watchdog's status independently."
    app.command(name)(command)


def watchdog_option() -> Any:
    return typer.Option(
        False, "--watchdog",
        help="Stay in the foreground once the deal is available, probing whether its disclosed SSH "
        "endpoint accepts connections, and send the ordinary rate stop after --watchdog-threshold "
        "consecutive failed probes. Only while this command runs, if that endpoint stops accepting "
        "connections, the loss is detected within at most interval x threshold + probe timeout; "
        "the authority's acknowledgement and any priced notice come after that, and billing "
        "continues until the stop lands.",
    )


def watchdog_interval_option() -> Any:
    return typer.Option(DEFAULT_INTERVAL_SECONDS, "--watchdog-interval", min=1,
                        help="Seconds between the watchdog's probes. Each probe's timeout is "
                        f"{DEFAULT_PROBE_TIMEOUT_SECONDS} s, or the interval when that is shorter.")


def watchdog_threshold_option() -> Any:
    return typer.Option(DEFAULT_THRESHOLD, "--watchdog-threshold", min=1,
                        help="Consecutive failed probes before the watchdog stops the deal.")


def watchdog_settings(enabled: bool, interval: int, threshold: int) -> WatchdogSettings | None:
    """The settings a ``buy`` opt-in persists, or ``None`` without the opt-in.

    The probe timeout is the default, shortened to an interval shorter than it.
    """
    if not enabled:
        return None
    return WatchdogSettings(interval_seconds=interval, threshold=threshold,
                            probe_timeout_seconds=min(DEFAULT_PROBE_TIMEOUT_SECONDS, interval))


def bound_notice(settings: WatchdogSettings) -> str:
    """The conditional detection bound, stated only while the monitor runs."""
    return (
        "Watchdog running: if the deal's disclosed SSH endpoint stops accepting connections, the loss "
        f"is detected within at most {settings.bound_seconds} seconds (interval "
        f"{settings.interval_seconds} s x threshold {settings.threshold} + probe timeout "
        f"{settings.probe_timeout_seconds} s), only while this command runs. The authority's "
        "acknowledgement of the stop it sends and any priced notice come after that, and billing "
        "continues until the stop lands."
    )


async def wait_until_available(
    target: EndTarget, *, timeout: float, poll_interval: float, clock: WaitClock = WaitClock(),
) -> Literal["available", "ended", "timeout"]:
    """Poll the deal's delivery read until it is available or has ended, or ``timeout`` passes.

    An unreadable storefront is polled again rather than ending the wait, since
    only its read says the deal is available.
    """
    monotonic, sleep = clock.monotonic, clock.sleep
    deadline = monotonic() + timeout
    async with target.lifecycle as lifecycle:
        while True:
            try:
                delivery = (await lifecycle.peer.read(target.negotiation_id)).delivery
            except Exception:
                delivery = None
            if delivery is not None and delivery.progress == "active":
                return "available"
            if delivery is not None and delivery.recorded_end is not None:
                return "ended"
            remaining = deadline - monotonic()
            if remaining <= 0:
                return "timeout"
            await sleep(min(poll_interval, remaining))


def run_monitor(
    target: EndTarget, *, probe: Probe | None, clock: WaitClock = WaitClock(),
    echo: Callable[[str], None] = lambda text: typer.echo(text, err=True),
) -> WatchdogOutcome | None:
    """Run the watchdog over the run's deal in the foreground, when it opted in.

    Returns ``None`` when the deal never opted in, is once-only, or the buyer
    interrupted the loop; the outcome otherwise. A deal whose watchdog already
    journaled its stop resumes that stop and sends nothing new; that needs no
    ``probe``, nor the storefront.
    """
    kept: list[WatchdogJournal] = []

    async def watch() -> WatchdogOutcome | None:
        async with target.lifecycle as lifecycle:
            journal = lifecycle.watchdog
            state = journal.state(target.negotiation_id) if journal is not None else None
            if journal is None or state is None:
                return None
            kept.append(journal)
            if not lifecycle._deal(target.negotiation_id).rate:
                echo("Watchdog not running: it applies to rate deals, and this deal is once-only.")
                return None
            if state.stop is None:
                echo(bound_notice(state.settings))
            if target.record is not None:
                target.record("watchdog_started", state.settings.to_json())
            outcome = await watch_deal(lifecycle, target.negotiation_id, journal=journal, probe=probe,
                                       clock=clock.now, sleep=clock.sleep)
            if target.record is not None:
                target.record("watchdog_exited", {
                    "reason": outcome.reason, "resumed": outcome.resumed,
                    "progress": outcome.progress.model_dump(mode="json") if outcome.progress else None,
                })
            return outcome

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        # The buyer's interrupt reaches a loop on the main thread; a loop on a
        # worker thread would keep the command waiting for it.
        runner: Callable[[], WatchdogOutcome | None] = lambda: asyncio.run(watch())
    else:
        runner = lambda: _run(watch)
    try:
        outcome = runner()
    except KeyboardInterrupt:
        # The interrupt may land after the stop was journaled, even mid-send.
        state = kept[0].state(target.negotiation_id) if kept else None
        echo("Watchdog interrupted after it journaled the buyer's stop; resume the run, or run "
             "'end', to carry that stop to the payment authority." if state is not None and state.stop
             else "Watchdog stopped by the buyer before deciding to stop; the deal is unmonitored "
             "and nothing was sent.")
        return None
    if outcome is not None:
        payment = outcome.progress.payment.status if outcome.progress else None
        echo("Watchdog exited: the deal ended by another path." if outcome.reason == "ended"
             else f"Watchdog's journaled stop carried to the payment authority: {payment}."
             if outcome.resumed else f"Watchdog sent the buyer's stop: {payment}.")
    return outcome


def create_evidence_command_group(
    store_factory: Callable[[], FileEvidenceStore],
    reader: DealReader,
    *,
    terms_from_agreement: Callable[[bytes], LifecycleTerms | dict | None],
    clock: Callable[[], int] = lambda: int(time.time()),
) -> typer.Typer:
    app = typer.Typer(help="Keep and export the buyer's signed deal evidence.")

    @app.command("prune")
    def prune() -> None:
        """Read every deal, then prune only evidence beyond every retention boundary."""
        report = asyncio.run(prune_command(store_factory(), reader, now=clock()))
        typer.echo(json.dumps(asdict(report), sort_keys=True))

    @app.command("export")
    def export(
        negotiation_id: str,
        claim: str = typer.Option(..., "--claim"),
        requested_outcome: str = typer.Option(..., "--requested-outcome"),
        commitment_ref: str | None = typer.Option(None, "--commitment-ref"),
    ) -> None:
        """Export one case as JSON; evidence and Agreement bodies remain base64 bytes."""
        try:
            requested = json.loads(requested_outcome)
            if not isinstance(requested, dict):
                raise ValueError("requested outcome must be a JSON object")
            case = asyncio.run(export_case(store_factory(), negotiation_id, claim=claim,
                                           requested_outcome=requested, commitment_ref=commitment_ref,
                                           terms_from_agreement=terms_from_agreement))
        except ValueError as exc:
            raise typer.BadParameter(str(exc)) from exc
        typer.echo(case.model_dump_json())

    return app
