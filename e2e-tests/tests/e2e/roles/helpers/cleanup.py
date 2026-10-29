"""Best-effort scenario cleanup that attempts every owned step.

A module that changed shared lane state — paused loops, armed gates, installed
rules, an outstanding deal — must undo all of it even when one undo fails, or
the next module in the lane inherits the leak. So each step is attempted on its
own, a failure is recorded rather than allowed to stop a later step, and the
steps that must always run (resuming held loops) run last, even when an earlier
step was interrupted.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable

CleanupStep = tuple[str, Callable[[], object]]

# What a cleanup step may not swallow: the run itself is being stopped. A
# pytest outcome (``pytest.fail`` inside a step) is a failure like any other.
_INTERRUPTS = (KeyboardInterrupt, SystemExit, GeneratorExit)


class CleanupFailed(AssertionError):
    """One or more cleanup steps raised; each is named with what it raised."""

    def __init__(self, failures: list[tuple[str, BaseException]]) -> None:
        self.failures = failures
        super().__init__(
            "cleanup steps failed: "
            + "; ".join(f"{name}: {error!r}" for name, error in failures)
        )


def run_cleanup(
    steps: Iterable[CleanupStep], *, always: Iterable[CleanupStep] = ()
) -> None:
    """Attempt each step in order, then each always-run step, reporting failures.

    Raises ``CleanupFailed`` naming every step that failed once all have been
    attempted, ``pytest.fail`` inside a step included. An interrupt stops the
    ordinary steps but still lets the always-run steps run before it propagates.
    """

    failures: list[tuple[str, BaseException]] = []

    def attempt(name: str, step: Callable[[], object]) -> None:
        try:
            step()
        except _INTERRUPTS:
            raise
        except BaseException as error:  # noqa: BLE001 - every failure is reported below
            failures.append((name, error))

    try:
        for name, step in steps:
            attempt(name, step)
    finally:
        for name, step in always:
            attempt(name, step)
    if failures:
        raise CleanupFailed(failures)


__all__ = ["CleanupFailed", "CleanupStep", "run_cleanup"]
