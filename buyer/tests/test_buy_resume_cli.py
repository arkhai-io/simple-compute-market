"""CLI integration tests for the resume flags.

Drives ``market negotiate --from`` and ``market buy --from`` via
Typer's ``CliRunner``. HTTP is mocked, on-chain hooks are stubbed,
and ``run_settle_from_log`` is patched so we can assert *that* it
was invoked (and with what) without needing alkahest / web3 / a
real wallet.

What these tests catch that the unit layers don't:
- typer wiring: ``--from`` short-circuits the fresh-flow validation
  that requires ``--initial-price`` / ``--max-price``.
- composite branching: when the run-log is mid-stream, ``buy --from``
  resumes the negotiation AND (only on agreed) calls settle; when
  the negotiation exits/rejects, settle is NOT called.
- the same run-log accumulates events from both halves, so
  ``market logs show <id>`` will see the full lifecycle after
  ``buy --from``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from market_buyer.cli import app
from market_buyer.run_log import RunLog, read_run


# Test wallet — derived address must match _BUYER_ADDR below for
# signature checks to pass downstream (we don't verify here, but the
# CLI's resolve_config_value short-circuits on truthy value).
_BUYER_PK = "0x" + "11" * 32
_BUYER_ADDR = "0xCC" + "cc" * 19  # placeholder; not signature-checked here


@pytest.fixture(autouse=True)
def _isolated_runs_dir(tmp_path, monkeypatch):
    """Pin the run-log directory at tmp_path for hermetic tests."""
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    yield


@pytest.fixture
def runner():
    return CliRunner()


@dataclass
class _MockResponse:
    status: int
    text: str

    def read(self):
        return self.text.encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass


def _urlopen_for(responses):
    """Return a urlopen replacement that yields the given responses."""
    it = iter(responses)

    def _fn(req, timeout=None):
        body = next(it)
        return _MockResponse(status=200, text=json.dumps(body))

    return _fn


def _seed_partial_negotiation(seller_url: str, listing_id: str) -> str:
    """Write a run-log resembling an interrupted `market negotiate`:
    one round logged (seller countered at 90), no run_ended yet.
    """
    log = RunLog.start(
        command="market negotiate",
        seller_url=seller_url,
        listing_id=listing_id,
        buyer_address=_BUYER_ADDR,
    )
    log.event(
        "negotiation_round",
        round=0,
        our_message={"action": "initial", "price": 50},
        their_reply={"negotiation_id": "neg-mid", "action": "counter", "price": 90},
    )
    return log.run_id


def _seed_agreed_negotiation(seller_url: str, listing_id: str) -> str:
    """Run-log resembling a completed `market negotiate` that agreed."""
    log = RunLog.start(
        command="market negotiate",
        seller_url=seller_url,
        listing_id=listing_id,
        buyer_address=_BUYER_ADDR,
    )
    log.event(
        "negotiation_round",
        round=0,
        our_message={"action": "initial", "price": 50},
        their_reply={"negotiation_id": "neg-done", "action": "accept", "price": 70},
    )
    log.event(
        "negotiation_completed",
        status="agreed",
        agreed_price=70,
        rounds=0,
        negotiation_id="neg-done",
        listing_id=listing_id,
    )
    log.end("agreed", negotiation_id="neg-done", agreed_price=70, rounds=0)
    return log.run_id


# ---------------------------------------------------------------------------
# `market negotiate --from`
# ---------------------------------------------------------------------------


class TestNegotiateFrom:
    """Mid-negotiation resume via the negotiate command."""

    def test_resume_round_loop_skips_negotiate_new(self, runner, monkeypatch):
        """Round-0 /negotiate/new must not be called; the resume body
        starts straight at /negotiate/{id}."""
        run_id = _seed_partial_negotiation("http://seller:8001", "L-1")

        # Seller's accept response to our resumed continue.
        monkeypatch.setattr(
            "market_buyer.buyer_client.urllib.request.urlopen",
            _urlopen_for([{"action": "accept", "price": 70}]),
        )
        # Best-effort wallet fetch in negotiate.py — make it succeed
        # cheaply so it doesn't perturb the test path.
        monkeypatch.setattr(
            "market_buyer.buy_orchestrator._resolve_seller_wallet",
            lambda *_a, **_kw: "0x" + "ee" * 20,
        )

        result = runner.invoke(app, [
            "negotiate", "--from", run_id,
            "--max-price", "100",
            "--token-decimals", "0",
            "--buyer-address", _BUYER_ADDR,
            "--buyer-priv-key", _BUYER_PK,
        ])

        assert result.exit_code == 0, result.output

    def test_resume_without_max_price_errors(self, runner):
        """The strategy needs the buyer's ceiling — without --max-price
        the resume path bails out before any HTTP work."""
        run_id = _seed_partial_negotiation("http://seller:8001", "L-1")
        result = runner.invoke(app, [
            "negotiate", "--from", run_id,
            "--buyer-address", _BUYER_ADDR,
            "--buyer-priv-key", _BUYER_PK,
        ])
        assert result.exit_code == 2
        assert "max-price" in result.output.lower()

    def test_resume_appends_resumed_from_to_new_log(self, runner, monkeypatch):
        """Each `negotiate` invocation opens its own run-log; resume
        records the source run-id as `resumed_from` in run_started."""
        original_run = _seed_partial_negotiation("http://seller:8001", "L-1")

        monkeypatch.setattr(
            "market_buyer.buyer_client.urllib.request.urlopen",
            _urlopen_for([{"action": "accept", "price": 70}]),
        )
        monkeypatch.setattr(
            "market_buyer.buy_orchestrator._resolve_seller_wallet",
            lambda *_a, **_kw: "0x" + "ee" * 20,
        )

        result = runner.invoke(app, [
            "negotiate", "--from", original_run,
            "--max-price", "100",
            "--token-decimals", "0",
            "--buyer-address", _BUYER_ADDR,
            "--buyer-priv-key", _BUYER_PK,
        ])
        assert result.exit_code == 0, result.output

        # Find the new run-log (the one that wasn't `original_run`).
        from market_buyer.run_log import list_runs
        new_runs = [r for r in list_runs() if r.run_id != original_run]
        assert len(new_runs) == 1
        events = read_run(new_runs[0].run_id)
        run_started = next(e for e in events if e["event"] == "run_started")
        assert run_started.get("resumed_from") == original_run


# ---------------------------------------------------------------------------
# `market buy --from`
# ---------------------------------------------------------------------------


class TestBuyFrom:
    """Composite resume: continue mid-negotiation, then settle.

    `run_settle_from_log` is patched at the `buy.py` import site so
    the test asserts *that* settlement was kicked off without
    actually running on-chain operations.
    """

    def test_buy_from_mid_stream_finishes_negotiation_then_settles(
        self, runner, monkeypatch,
    ):
        """Run-log has a counter mid-stream → buy --from continues
        the round loop, agrees, then invokes run_settle_from_log."""
        run_id = _seed_partial_negotiation("http://seller:8001", "L-1")

        monkeypatch.setattr(
            "market_buyer.buyer_client.urllib.request.urlopen",
            _urlopen_for([{"action": "accept", "price": 70}]),
        )

        settle_calls: list[dict] = []
        def _fake_settle(**kwargs):
            settle_calls.append(kwargs)
            return {"status": "ready"}
        monkeypatch.setattr(
            "market_buyer.groups.buy.run_settle_from_log",
            _fake_settle,
        )

        result = runner.invoke(app, [
            "buy", "--from", run_id,
            "--max-price", "100",
            "--token-decimals", "0",
            "--buyer-address", _BUYER_ADDR,
            "--buyer-priv-key", _BUYER_PK,
        ])

        assert result.exit_code == 0, result.output
        assert len(settle_calls) == 1
        assert settle_calls[0]["run_id"] == run_id

        # The same run-log accumulated negotiation_completed BEFORE
        # settlement was kicked off.
        events = read_run(run_id)
        ev_names = [e["event"] for e in events]
        assert "negotiation_resumed" in ev_names
        assert "negotiation_completed" in ev_names
        agreed = next(e for e in events if e["event"] == "negotiation_completed")
        assert agreed["status"] == "agreed"
        assert agreed["agreed_price"] == 70

    def test_buy_from_already_agreed_skips_negotiation(self, runner, monkeypatch):
        """If the run-log shows an agreed outcome, --from goes
        straight to settlement (no /negotiate/* HTTP)."""
        run_id = _seed_agreed_negotiation("http://seller:8001", "L-1")

        # If urlopen is touched, the test fails — the agreed path
        # must not make any negotiation HTTP calls.
        def _fail_urlopen(*a, **k):
            raise AssertionError("urlopen called on already-agreed --from path")
        monkeypatch.setattr(
            "market_buyer.buyer_client.urllib.request.urlopen",
            _fail_urlopen,
        )

        settle_calls: list[dict] = []
        monkeypatch.setattr(
            "market_buyer.groups.buy.run_settle_from_log",
            lambda **kw: settle_calls.append(kw) or {"status": "ready"},
        )

        result = runner.invoke(app, [
            "buy", "--from", run_id,
            "--buyer-address", _BUYER_ADDR,
            "--buyer-priv-key", _BUYER_PK,
        ])

        assert result.exit_code == 0, result.output
        assert len(settle_calls) == 1
        assert settle_calls[0]["run_id"] == run_id

    def test_buy_from_mid_stream_exit_skips_settlement(
        self, runner, monkeypatch,
    ):
        """If the resumed negotiation exits (seller walks), settlement
        must NOT be invoked — there's nothing to settle."""
        run_id = _seed_partial_negotiation("http://seller:8001", "L-1")

        # Seller exits when we counter.
        monkeypatch.setattr(
            "market_buyer.buyer_client.urllib.request.urlopen",
            _urlopen_for([{"action": "exit", "reason": "price_unreasonable"}]),
        )

        settle_calls: list[dict] = []
        def _fake_settle(**kwargs):
            settle_calls.append(kwargs)
            return {"status": "ready"}
        monkeypatch.setattr(
            "market_buyer.groups.buy.run_settle_from_log",
            _fake_settle,
        )

        result = runner.invoke(app, [
            "buy", "--from", run_id,
            "--max-price", "100",
            "--token-decimals", "0",
            "--buyer-address", _BUYER_ADDR,
            "--buyer-priv-key", _BUYER_PK,
        ])

        assert result.exit_code == 4, result.output
        assert settle_calls == [], (
            "Settlement must not run when negotiation didn't agree"
        )

    def test_buy_fresh_still_requires_duration_hours(self, runner):
        """Fresh `market buy` (no --from) without --duration-hours fails fast.

        Prices are now optional — when omitted they're derived from each
        listing's seller-advertised min_price (interactively confirmed by
        default; non-interactively under --auto-price). Duration is still
        mandatory because it shapes the buyer's lease ask sent at
        /negotiate/new.
        """
        result = runner.invoke(app, [
            "buy",
            "--buyer-address", _BUYER_ADDR,
            "--buyer-priv-key", _BUYER_PK,
        ])
        assert result.exit_code == 2
        assert "duration-hours" in result.output.lower()

    def test_buy_fresh_rejects_only_one_price(self, runner):
        """Pass both prices, or neither — never one half."""
        result = runner.invoke(app, [
            "buy",
            "--buyer-address", _BUYER_ADDR,
            "--buyer-priv-key", _BUYER_PK,
            "--duration-hours", "1",
            "--initial-price", "100",
        ])
        assert result.exit_code == 2
        assert "initial-price" in result.output.lower() or "max-price" in result.output.lower()

    def test_buy_from_mid_stream_without_max_price_errors(
        self, runner, monkeypatch,
    ):
        """`buy --from` with mid-stream negotiation requires --max-price."""
        run_id = _seed_partial_negotiation("http://seller:8001", "L-1")

        # Patch settle so a stray invocation would be visible (it
        # shouldn't be reached at all here).
        monkeypatch.setattr(
            "market_buyer.groups.buy.run_settle_from_log",
            lambda **kw: pytest.fail("settle should not run when validation fails"),
        )

        result = runner.invoke(app, [
            "buy", "--from", run_id,
            "--buyer-address", _BUYER_ADDR,
            "--buyer-priv-key", _BUYER_PK,
        ])
        assert result.exit_code == 2
        assert "max-price" in result.output.lower()
