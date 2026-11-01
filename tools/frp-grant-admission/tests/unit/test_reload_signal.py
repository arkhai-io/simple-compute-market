from __future__ import annotations

import os
import signal
from typing import cast

import pytest

from frp_grant_admission.server import Plugin, install_reload_on_sighup


class FailingReload:
    """A plugin whose reload raises, as an unforeseen loader or log failure would."""

    def __init__(self) -> None:
        self.calls = 0

    def reload(self) -> bool:
        self.calls += 1
        raise RuntimeError("reload failed")


def test_a_reload_that_raises_leaves_the_signal_handler_quietly(
    capsys: pytest.CaptureFixture[str],
) -> None:
    plugin = FailingReload()
    previous = install_reload_on_sighup(cast(Plugin, plugin))
    try:
        os.kill(os.getpid(), signal.SIGHUP)
        os.kill(os.getpid(), signal.SIGHUP)
    finally:
        signal.signal(signal.SIGHUP, previous)

    assert plugin.calls == 2
    assert "RuntimeError: reload failed" in capsys.readouterr().err
