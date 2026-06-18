from __future__ import annotations

import subprocess

import pytest

from .conftest import fake_chain


def _patch_publish_prereqs(monkeypatch, *, db_path: str = "/fake/agent.db") -> None:
    monkeypatch.setattr("market_storefront.cli_publish._resolve_db_path", lambda _db: db_path)
    monkeypatch.setattr("market_storefront.utils.config.CHAINS", {"anvil": fake_chain()})


def _published_entry(resource_id: str = "r1") -> dict:
    return {
        "resource": {
            "resource_id": resource_id,
            "gpu_model": "A100",
            "gpu_count": 1,
            "region": "us-west",
        },
        "response": {"listing_id": "l1", "status": "published"},
        "accepted_escrows": [],
    }


def _failed_resource(resource_id: str = "r1") -> dict:
    return {
        "resource_id": resource_id,
        "gpu_model": "A100",
        "gpu_count": 1,
        "region": "us-west",
    }


def test_publish_exits_when_db_not_resolvable(monkeypatch, runner, app):
    monkeypatch.setattr("market_storefront.cli_publish._resolve_db_path", lambda _db: None)
    monkeypatch.setattr("market_storefront.utils.config.CHAINS", {"anvil": fake_chain()})

    result = runner.invoke(app, ["publish"])

    assert result.exit_code == 1
    assert "db" in result.output.lower() or "db" in (result.stderr or "").lower()


def test_publish_exits_when_no_chains_configured(monkeypatch, runner, app):
    monkeypatch.setattr("market_storefront.cli_publish._resolve_db_path", lambda _db: "/fake/agent.db")
    monkeypatch.setattr("market_storefront.utils.config.CHAINS", {})

    result = runner.invoke(app, ["publish"])

    assert result.exit_code == 1
    assert "chain" in result.output.lower() or "chain" in (result.stderr or "").lower()


def test_publish_abort_all_exclusive_with_inventory(monkeypatch, tmp_path, runner, app):
    _patch_publish_prereqs(monkeypatch)
    csv = tmp_path / "resources.csv"
    csv.write_text("resource_id\n")

    result = runner.invoke(app, ["publish", "--abort-all", "--inventory", str(csv)])

    assert result.exit_code != 0
    assert "mutually exclusive" in result.output.lower() or "abort-all" in result.output.lower()


def test_publish_abort_all_exclusive_with_watch(monkeypatch, runner, app):
    _patch_publish_prereqs(monkeypatch)

    result = runner.invoke(app, ["publish", "--abort-all", "--watch"])

    assert result.exit_code != 0
    assert "mutually exclusive" in result.output.lower() or "abort-all" in result.output.lower()


def test_publish_abort_all_no_open_orders(monkeypatch, runner, app):
    _patch_publish_prereqs(monkeypatch)
    monkeypatch.setattr("market_storefront.cli_publish._open_listing_ids", lambda _db: [])

    result = runner.invoke(app, ["publish", "--abort-all"])

    assert result.exit_code == 0
    assert "nothing to abort" in result.output.lower()


def test_publish_abort_all_all_succeed(monkeypatch, runner, app):
    _patch_publish_prereqs(monkeypatch)
    monkeypatch.setattr("market_storefront.cli_publish._open_listing_ids", lambda _db: ["o1", "o2"])
    monkeypatch.setattr("market_storefront.cli_publish._close_order", lambda _url, _oid, _key: {"status": "closed"})

    result = runner.invoke(app, ["publish", "--abort-all"])

    assert result.exit_code == 0
    assert "2/2" in result.output or "Closed 2" in result.output


def test_publish_abort_all_some_fail(monkeypatch, runner, app):
    _patch_publish_prereqs(monkeypatch)
    monkeypatch.setattr("market_storefront.cli_publish._open_listing_ids", lambda _db: ["o1", "o2"])

    def fake_close(_url, oid, _key):
        if oid == "o2":
            raise RuntimeError("network error")
        return {"status": "closed"}

    monkeypatch.setattr("market_storefront.cli_publish._close_order", fake_close)

    result = runner.invoke(app, ["publish", "--abort-all"])

    assert result.exit_code == 5


def test_publish_inventory_file_not_found(monkeypatch, runner, app):
    _patch_publish_prereqs(monkeypatch)

    result = runner.invoke(app, ["publish", "--inventory", "/nonexistent/resources.csv"])

    assert result.exit_code != 0
    assert "not found" in result.output.lower() or "invalid" in result.output.lower()


def test_publish_inventory_import_failure(monkeypatch, tmp_path, runner, app):
    _patch_publish_prereqs(monkeypatch)
    csv = tmp_path / "resources.csv"
    csv.write_text("resource_id\n")

    monkeypatch.setattr(
        "market_storefront.cli_publish._import_csv",
        lambda _csv, _db: (_ for _ in ()).throw(subprocess.CalledProcessError(1, "python")),
    )
    monkeypatch.setattr("market_storefront.cli_publish._publish_round", lambda **_kwargs: ([], [], []))

    result = runner.invoke(app, ["publish", "--inventory", str(csv)])

    assert result.exit_code == 2


def test_publish_inventory_success_then_publishes_with_cli_args(monkeypatch, tmp_path, runner, app):
    _patch_publish_prereqs(monkeypatch, db_path="/fake/seller.db")
    csv = tmp_path / "resources.csv"
    csv.write_text("resource_id\n")
    imports: list[tuple[str, str | None]] = []
    publish_calls: list[dict] = []

    monkeypatch.setattr("market_storefront.cli_publish._import_csv", lambda csv_path, db: imports.append((csv_path, db)))
    monkeypatch.setattr("market_storefront.cli_publish._close_stale_derived_listings", lambda **_kwargs: [])
    monkeypatch.setattr("market_storefront.cli_publish._open_listing_resource_keys", lambda _db: {"already-open"})
    monkeypatch.setattr(
        "market_storefront.cli_publish._publish_round",
        lambda **kwargs: publish_calls.append(kwargs) or ([_published_entry()], [], []),
    )

    result = runner.invoke(
        app,
        [
            "publish",
            "--inventory",
            str(csv),
            "--db",
            "/fake/seller.db",
            "--storefront-url",
            "http://seller.test",
            "--max-duration-seconds",
            "120",
        ],
    )

    assert result.exit_code == 0
    assert imports == [(str(csv), "/fake/seller.db")]
    assert publish_calls[0]["base_url"] == "http://seller.test"
    assert publish_calls[0]["db_path"] == "/fake/seller.db"
    assert publish_calls[0]["default_max_duration_seconds"] == 120
    assert publish_calls[0]["skip_ids"] == {"already-open"}


def test_publish_oneshot_no_resources(monkeypatch, runner, app):
    _patch_publish_prereqs(monkeypatch)
    monkeypatch.setattr("market_storefront.cli_publish._close_stale_derived_listings", lambda **_kwargs: [])
    monkeypatch.setattr("market_storefront.cli_publish._open_listing_resource_keys", lambda _db: set())
    monkeypatch.setattr("market_storefront.cli_publish._publish_round", lambda **_kwargs: ([], [], []))

    result = runner.invoke(app, ["publish"])

    assert result.exit_code == 3


def test_publish_oneshot_all_published(monkeypatch, runner, app):
    _patch_publish_prereqs(monkeypatch)
    monkeypatch.setattr("market_storefront.cli_publish._close_stale_derived_listings", lambda **_kwargs: [])
    monkeypatch.setattr("market_storefront.cli_publish._open_listing_resource_keys", lambda _db: set())
    monkeypatch.setattr(
        "market_storefront.cli_publish._publish_round",
        lambda **_kwargs: ([_published_entry()], [], []),
    )

    result = runner.invoke(app, ["publish"])

    assert result.exit_code == 0


def test_publish_oneshot_all_failed(monkeypatch, runner, app):
    _patch_publish_prereqs(monkeypatch)
    monkeypatch.setattr("market_storefront.cli_publish._close_stale_derived_listings", lambda **_kwargs: [])
    monkeypatch.setattr("market_storefront.cli_publish._open_listing_resource_keys", lambda _db: set())
    monkeypatch.setattr("market_storefront.cli_publish._publish_round", lambda **_kwargs: ([], [(_failed_resource(), "RPC error")], []))

    result = runner.invoke(app, ["publish"])

    assert result.exit_code == 4


def test_publish_watch_calls_run_watch_loop(monkeypatch, runner, app):
    _patch_publish_prereqs(monkeypatch)
    watch_calls: list[dict] = []
    monkeypatch.setattr("market_storefront.cli_publish.run_watch_loop", lambda **kwargs: watch_calls.append(kwargs))
    monkeypatch.setattr("market_storefront.cli_publish._publish_round", lambda **_kwargs: pytest.fail("_publish_round must not be called"))

    result = runner.invoke(app, ["publish", "--watch", "--poll-interval", "5"])

    assert result.exit_code == 0
    assert watch_calls[0]["poll_interval"] == 5.0
