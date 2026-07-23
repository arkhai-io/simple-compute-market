from __future__ import annotations

from .conftest import FakeLogConnection


def _event(**overrides):
    row = {
        "ts": "2024-01-01T00:00:00Z",
        "stage": "settlement",
        "event": "escrow_created",
        "negotiation_id": "neg-001",
        "listing_id": "listing-001",
        "escrow_uid": "0xESCROW",
        "data": {"escrow_uid": "0xESCROW", "listing_id": "listing-001"},
    }
    row.update(overrides)
    return row


def _thread(**overrides):
    row = {
        "negotiation_id": "neg-001",
        "our_listing_id": None,
        "their_listing_id": None,
        "status": "active",
        "terminal_state": None,
    }
    row.update(overrides)
    return row


def test_logs_show_no_db_path(monkeypatch, runner, app):
    import market_storefront.cli_logs as logs_mod

    monkeypatch.setattr(logs_mod, "_resolve_db_path", lambda _db: None)

    result = runner.invoke(app, ["logs", "show"])

    assert result.exit_code == 1
    assert "Could not find agent DB" in result.output


def test_logs_show_no_table(fake_log_db, runner, app):
    fake_log_db(FakeLogConnection(fail_stage_events=True))

    result = runner.invoke(app, ["logs", "show", "--db", "/fake/agent.db"])

    assert result.exit_code == 0
    assert "No stage_events table" in result.output


def test_logs_show_no_rows(fake_log_db, runner, app):
    fake_log_db(FakeLogConnection(stage_events=[]))

    result = runner.invoke(app, ["logs", "show", "--db", "/fake/agent.db"])

    assert result.exit_code == 0
    assert "No matching stage events" in result.output


def test_logs_show_rich_table(fake_log_db, runner, app):
    fake_log_db(FakeLogConnection(stage_events=[_event()]))

    result = runner.invoke(app, ["logs", "show", "--db", "/fake/agent.db"])

    assert result.exit_code == 0
    assert "Stage Events" in result.output
    assert "escrow_created" in result.output
    assert "settlement" in result.output


def test_logs_show_raw(fake_log_db, runner, app):
    fake_log_db(FakeLogConnection(stage_events=[_event(data={"hello": "world"})]))

    result = runner.invoke(app, ["logs", "show", "--db", "/fake/agent.db", "--raw"])

    assert result.exit_code == 0
    assert '"hello": "world"' in result.output


def test_logs_show_filters_negotiation_and_stage(fake_log_db, runner, app):
    conn = fake_log_db(FakeLogConnection(stage_events=[_event(), _event(negotiation_id="other", stage="discovery")]))

    result = runner.invoke(
        app,
        ["logs", "show", "--db", "/fake/agent.db", "--negotiation", "neg-001", "--stage", "settlement", "--last", "1"],
    )

    assert result.exit_code == 0
    query, params = conn.queries[0]
    assert "negotiation_id" in query
    assert "stage = ?" in query
    assert params == ["neg-001", "%neg-001%", "settlement", 1]


def test_logs_status_no_db_path(monkeypatch, runner, app):
    import market_storefront.cli_logs as logs_mod

    monkeypatch.setattr(logs_mod, "_resolve_db_path", lambda _db: None)

    result = runner.invoke(app, ["logs", "status", "neg-001"])

    assert result.exit_code == 1
    assert "Could not find agent DB" in result.output


def test_logs_status_not_found(fake_log_db, runner, app):
    fake_log_db(FakeLogConnection(threads=[]))

    result = runner.invoke(app, ["logs", "status", "neg-missing", "--db", "/fake/agent.db"])

    assert result.exit_code == 1
    assert "No negotiation found" in result.output


def test_logs_status_active_negotiation_shows_rounds(fake_log_db, runner, app):
    fake_log_db(
        FakeLogConnection(
            threads=[_thread()],
            messages_count=2,
            stage_events=[_event()],
        )
    )

    result = runner.invoke(app, ["logs", "status", "neg-001", "--db", "/fake/agent.db"])

    assert result.exit_code == 0
    assert "neg-001" in result.output
    assert "rounds" in result.output
    assert "2" in result.output


def test_logs_status_by_listing_id(fake_log_db, runner, app):
    fake_log_db(
        FakeLogConnection(
            threads=[_thread(negotiation_id="neg-abc", our_listing_id="listing-xyz")],
            messages_count=1,
        )
    )

    result = runner.invoke(app, ["logs", "status", "listing-xyz", "--db", "/fake/agent.db"])

    assert result.exit_code == 0
    assert "neg-abc" in result.output


def test_logs_status_terminal_failure(fake_log_db, runner, app):
    fake_log_db(FakeLogConnection(threads=[_thread(terminal_state="failure")]))

    result = runner.invoke(app, ["logs", "status", "neg-001", "--db", "/fake/agent.db"])

    assert result.exit_code == 0
    assert "terminated: failure" in result.output


def test_logs_status_success_no_local_order(fake_log_db, runner, app):
    fake_log_db(FakeLogConnection(threads=[_thread(terminal_state="success")]))

    result = runner.invoke(app, ["logs", "status", "neg-001", "--db", "/fake/agent.db"])

    assert result.exit_code == 0
    assert "agreed (no local order found)" in result.output


def test_logs_status_success_awaiting_escrow(fake_log_db, runner, app):
    fake_log_db(
        FakeLogConnection(
            threads=[_thread(terminal_state="success", our_listing_id="listing-001")],
            listings=[{"listing_id": "listing-001", "status": "open"}],
        )
    )

    result = runner.invoke(app, ["logs", "status", "neg-001", "--db", "/fake/agent.db"])

    assert result.exit_code == 0
    assert "awaiting escrow" in result.output


def test_logs_status_success_awaiting_fulfillment(fake_log_db, runner, app):
    fake_log_db(
        FakeLogConnection(
            threads=[_thread(terminal_state="success", our_listing_id="listing-001")],
            listings=[{"listing_id": "listing-001", "status": "open"}],
            escrows=[{"negotiation_id": "neg-001", "escrow_uid": "0xESCROW", "fulfillment_uid": None}],
        )
    )

    result = runner.invoke(app, ["logs", "status", "neg-001", "--db", "/fake/agent.db"])

    assert result.exit_code == 0
    assert "escrow created, awaiting fulfillment" in result.output


def test_logs_status_success_provision(fake_log_db, runner, app):
    fake_log_db(
        FakeLogConnection(
            threads=[_thread(terminal_state="success", our_listing_id="listing-001")],
            listings=[{"listing_id": "listing-001", "status": "open"}],
            escrows=[{"negotiation_id": "neg-001", "escrow_uid": "0xESCROW", "fulfillment_uid": "0xFULF"}],
        )
    )

    result = runner.invoke(app, ["logs", "status", "neg-001", "--db", "/fake/agent.db"])

    assert result.exit_code == 0
    assert "fulfilled, awaiting buyer claim" in result.output


def test_logs_status_success_closed(fake_log_db, runner, app):
    fake_log_db(
        FakeLogConnection(
            threads=[_thread(terminal_state="success", our_listing_id="listing-001")],
            listings=[{"listing_id": "listing-001", "status": "closed"}],
            escrows=[{"negotiation_id": "neg-001", "escrow_uid": "0xESCROW", "fulfillment_uid": "0xFULF"}],
        )
    )

    result = runner.invoke(app, ["logs", "status", "neg-001", "--db", "/fake/agent.db"])

    assert result.exit_code == 0
    assert "deal complete" in result.output
