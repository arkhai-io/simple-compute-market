"""Every stage finishes a resumed settlement the same way."""

from __future__ import annotations

import io
from types import SimpleNamespace
from typing import Any

import pytest
import typer
from rich.console import Console

from arkhai_api_buying.stages import SettlementResume
from tests.bundles import CONTRIBUTIONS


class Log:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    def event(self, event: str, **fields: Any) -> None:
        self.events.append((event, fields))

    def end(self, status: str, **fields: Any) -> None:
        self.event("run_ended", status=status, **fields)


def _resume() -> SettlementResume:
    return SettlementResume(
        contributions=CONTRIBUTIONS,
        run_id="run-1",
        deal=SimpleNamespace(),
        identity=SimpleNamespace(),
        settlement_config=lambda: None,
        options={},
        poll_interval=1.0,
        settlement_timeout=2.0,
        console=Console(file=io.StringIO()),
    )


def test_a_ready_settlement_records_its_credentials_and_reference():
    log = Log()
    credentials = {"key_id": "k1", "secret": "s1"}
    final = {"status": "ready", "fulfillment_uid": "f1", "tenant_credentials": credentials}

    assert _resume().finish(
        log, final, reference=("Ref", "r1"), end_fields={"ref": "r1"}, unready_border="red",
    ) is final
    assert log.events == [
        ("credentials_delivered", {"credentials": credentials}),
        ("run_ended", {"status": "ready", "ref": "r1", "fulfillment_uid": "f1"}),
    ]


def test_an_unready_settlement_ends_its_run_and_exits():
    log = Log()
    with pytest.raises(typer.Exit) as exited:
        _resume().finish(
            log, {"status": "failed"}, reference=("Ref", "r1"), end_fields={}, unready_border="red",
        )
    assert exited.value.exit_code == 7
    assert log.events == [("run_ended", {"status": "failed", "fulfillment_uid": None})]
