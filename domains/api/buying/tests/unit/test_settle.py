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
    run_id = "run-1"

    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    def event(self, event: str, **fields: Any) -> None:
        self.events.append((event, fields))

    def end(self, status: str, **fields: Any) -> None:
        self.event("run_ended", status=status, **fields)


class Store:
    scheme = "memory"

    def __init__(self) -> None:
        self.saved: dict[str, dict[str, Any]] = {}

    def save(self, run_id: str, credentials: Any) -> str:
        self.saved[run_id] = dict(credentials)
        return f"memory:{run_id}"

    def load(self, reference: str) -> dict[str, Any] | None:
        return self.saved.get(reference.partition(":")[2])


def _resume(store: Store | None = None) -> SettlementResume:
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
        credential_store=store or Store(),
    )


def test_a_ready_settlement_stores_its_secret_and_records_its_reference():
    log = Log()
    store = Store()
    credentials = {"key_id": "k1", "secret": "s1"}
    final = {"status": "ready", "fulfillment_uid": "f1", "tenant_credentials": credentials}

    assert _resume(store).finish(
        log, final, reference=("Ref", "r1"), end_fields={"ref": "r1"}, unready_border="red",
    ) is final
    assert store.saved == {"run-1": credentials}
    assert log.events == [
        ("credentials_delivered", {"key_id": "k1", "delivery_ref": "memory:run-1"}),
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


def test_a_failed_private_write_shows_the_key_records_no_secret_and_exits_8():
    class Failing(Store):
        def save(self, run_id: str, credentials: Any) -> str:
            raise OSError("disk full")

    log = Log()
    resume = _resume(Failing())
    final = {"status": "ready", "tenant_credentials": {"key_id": "k1", "secret": "s1"}}

    with pytest.raises(typer.Exit) as exited:
        resume.finish(log, final, reference=("Ref", "r1"), end_fields={}, unready_border="red")

    assert exited.value.exit_code == 8
    assert log.events[0] == ("credentials_unsaved", {"key_id": "k1", "error": "OSError"})
    assert log.events[1][0] == "run_ended"
    assert "s1" in resume.console.file.getvalue()
    assert "s1" not in repr(log.events)


def test_a_key_that_reaches_neither_store_nor_log_is_still_shown_once():
    class Failing(Store):
        def save(self, run_id: str, credentials: Any) -> str:
            raise OSError("disk full")

    class FullLog(Log):
        def event(self, event: str, **fields: Any) -> None:
            raise OSError("disk full")

    resume = _resume(Failing())
    final = {"status": "ready", "tenant_credentials": {"key_id": "k1", "secret": "s1"}}

    with pytest.raises(typer.Exit) as exited:
        resume.finish(FullLog(), final, reference=("Ref", "r1"), end_fields={}, unready_border="red")

    assert exited.value.exit_code == 8
    assert resume.console.file.getvalue().count("s1") == 1
