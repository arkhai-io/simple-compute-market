"""Startup wiring is call-compatible with what it calls.

`_startup_tasks` runs only inside a live application lifespan, so nothing below
the end-to-end level executes it. A keyword that does not exist on its callee is
therefore invisible to every suite and fails at container start with
`TypeError: ... got an unexpected keyword argument`, which reads as a broken
deployment rather than as a wiring mistake. That is exactly what happened when a
rename of `logger=` to `task_logger=` across this module caught one call too
many.

These tests bind each startup call site against the real signature without
running the coroutines, so the mismatch fails here instead of in a compose stack.
"""

from __future__ import annotations

import inspect

from core_storefront.app_startup import (
    run_storefront_startup_steps,
    start_storefront_background_task,
)

from market_storefront import startup
from market_storefront.lifecycle import start_registered_loop


class TestStartupCallSignatures:
    def test_the_startup_step_runner_takes_the_keyword_startup_passes(self) -> None:
        """`_startup_tasks` passes `logger=`; the runner must accept it."""
        params = inspect.signature(run_storefront_startup_steps).parameters

        assert "logger" in params
        assert "task_logger" not in params, (
            "if the runner ever gains `task_logger`, this test's premise — that "
            "the two call sites take different keywords — needs revisiting"
        )

    def test_the_loop_starter_takes_the_keyword_the_loop_starters_pass(self) -> None:
        """Each `_start_*` helper passes `task_logger=` to the registry."""
        params = inspect.signature(start_registered_loop).parameters

        assert "task_logger" in params
        assert "logger" in inspect.signature(start_storefront_background_task).parameters, (
            "the registry forwards to the core helper under the core helper's own "
            "keyword; a rename there would strand the registry"
        )

    def test_every_startup_call_site_uses_keywords_its_callee_accepts(self) -> None:
        """Check the calls, not the helpers around them.

        Walks `startup.py` for every call to the startup-step runner and the loop
        registry and validates each keyword against the real signature. An
        earlier version of this test inspected the `_start_*` helpers instead and
        passed against the very defect it was written for — the offending call was
        in `_startup_tasks`, which that inspection never reached.
        """
        import ast

        callees = {
            "run_storefront_startup_steps": run_storefront_startup_steps,
            "start_registered_loop": start_registered_loop,
        }
        tree = ast.parse(inspect.getsource(startup))

        checked = 0
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
            target = callees.get(name)
            if target is None:
                continue
            checked += 1
            accepted = set(inspect.signature(target).parameters)
            passed = {kw.arg for kw in node.keywords if kw.arg is not None}
            unknown = sorted(passed - accepted)
            assert not unknown, (
                f"{name}(...) at line {node.lineno} passes {unknown}, which it does "
                f"not accept; it takes {sorted(accepted)}. This fails at container "
                "start, where it reads as a broken deployment."
            )

        assert checked >= 6, (
            f"expected every loop starter plus the step runner, found {checked} "
            "call sites — has startup.py been restructured?"
        )
