"""The Python middleware reproduces the shared conformance session."""

from __future__ import annotations

from conformance_runner import load_session, run_session


async def test_recorded_session_matches():
    await run_session(load_session())
