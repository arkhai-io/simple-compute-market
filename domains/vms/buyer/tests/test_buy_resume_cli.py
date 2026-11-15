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
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from core_buyer.buyer_config import ResolvedBuyerIdentity
from core_buyer.registry_config import RegistryAuthority
from arkhai_vms_buyer import buy_cli, end_cli
from arkhai_vms_buyer.buy_orchestrator import BuyResult
from arkhai_vms_buyer.cli import app
from arkhai_vms_buyer.run_log import RunLog, list_runs, read_run
from market_deal_lifecycle.adapters import (
    DisputeAdapterTable,
    PaymentAdapterTable,
    PaymentBinding,
    PaymentSelector,
)
from market_deal_lifecycle_buyer import (
    BuyerDeal,
    BuyerLifecycle,
    EndDeliveryProgress,
    EndTarget,
    WaitClock,
    WatchdogSettings,
    WatchdogState,
    WatchdogStop,
)
from market_deal_lifecycle_buyer.watchdog import GRACE_SECONDS, ProbeObservation
from market_deal_lifecycle_contracts.models import (
    Accepted,
    AuthorityView,
    DeliveryView,
    LifecycleRead,
    RecordedEnd,
    Rejected,
)
from identity_helpers import (
    BUYER_SIGNER,
    seller_principals,
    signed_response_headers,
    with_accepted_agreement,
)
from market_config.config_loader import ChainConfig
from market_core.schemas import RateValue, derive_settlement_option_id
from typer.testing import CliRunner

# Test wallet — derived address must match _BUYER_ADDR below for
# signature checks to pass downstream (we don't verify here, but the
# CLI's resolve_config_value short-circuits on truthy value).
_BUYER_PK = "0x" + "11" * 32
_BUYER_ADDR = "0xCC" + "cc" * 19  # placeholder; not signature-checked here


_PROFILE_ID = uuid.UUID("11111111-1111-4111-8111-111111111111")
_RESOLVED = ResolvedBuyerIdentity(
    profile_id=_PROFILE_ID,
    principal=BUYER_SIGNER.identity,
    signer=BUYER_SIGNER,
    source="fresh",
)


@pytest.fixture(autouse=True)
def _isolated_runs_dir(tmp_path, monkeypatch):
    """Pin the run-log directory at tmp_path for hermetic tests."""
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    monkeypatch.setattr(
        "arkhai_vms_buyer.common.resolve_fresh_buyer_identity",
        lambda: _RESOLVED,
    )
    monkeypatch.setattr(
        "arkhai_vms_buyer.common.resolve_recovery_buyer_identity",
        lambda _run_id: ResolvedBuyerIdentity(
            profile_id=_PROFILE_ID,
            principal=BUYER_SIGNER.identity,
            signer=BUYER_SIGNER,
            source="recovery",
        ),
    )
    monkeypatch.setattr(
        "arkhai_vms_buyer.common.resolve_buyer_wallet",
        lambda **_kwargs: (_BUYER_ADDR, _BUYER_PK),
    )
    monkeypatch.setattr(
        "arkhai_vms_buyer.deal_helpers._publisher_trust_refresh",
        lambda signer: lambda *_: seller_principals(),
    )
    monkeypatch.setattr(
        "arkhai_vms_buyer.common.resolve_registry_authorities",
        lambda urls: {
            url: RegistryAuthority(
                authority="registry",
                principals=seller_principals(),
            )
            for url in urls
        },
    )
    monkeypatch.setattr(
        "arkhai_vms_buyer.common.resolve_indexer_urls_for_schema",
        lambda _schema, **kwargs: list(kwargs["registry_authorities"]),
    )
    monkeypatch.setattr(
        "arkhai_vms_buyer.common.resolve_registry_api_keys",
        lambda: {},
    )
    yield


@pytest.fixture
def runner():
    return CliRunner()


@dataclass
class _MockResponse:
    status: int
    text: str
    headers: dict[str, str] | None = None

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
        body = with_accepted_agreement(req, next(it))
        return _MockResponse(
            status=200,
            text=json.dumps(body),
            headers=signed_response_headers(req, body),
        )

    return _fn


def _start_log(**fields):
    trust = seller_principals()
    fields.setdefault("publisher_id", "publisher-1")
    fields.setdefault(
        "publisher_principals",
        trust.model_dump(mode="json"),
    )
    fields.setdefault("source_registry_url", "http://registry:8080")
    fields.setdefault("source_registry_authority", "registry")
    return RunLog.start(
        profile_id=_PROFILE_ID,
        principal=BUYER_SIGNER.identity,
        **fields,
    )


def _seed_partial_negotiation(
    seller_url: str,
    listing_id: str,
    *,
    initial_price: float = 50,
    max_price: float = 100,
) -> str:
    """Write an interrupted negotiation with its immutable price policy."""
    log = _start_log(
        command="market negotiate",
        seller_url=seller_url,
        listing_id=listing_id,
        initial_price=initial_price,
        max_price=max_price,
    )
    log.event(
        "negotiation_round",
        round=0,
        our_message={"action": "initial", "proposal": {"fields": {"amount": 50}}},
        their_reply={
            "negotiation_id": "neg-mid",
            "action": "counter",
            "proposal": {"fields": {"amount": 90}},
        },
    )
    return log.run_id


def _seed_agreed_negotiation(seller_url: str, listing_id: str) -> str:
    """Run-log resembling a completed `market negotiate` that agreed."""
    log = _start_log(
        command="market negotiate",
        seller_url=seller_url,
        listing_id=listing_id,
        initial_price=50,
        max_price=100,
    )
    log.event(
        "negotiation_round",
        round=0,
        our_message={"action": "initial", "proposal": {"fields": {"amount": 50}}},
        their_reply={
            "negotiation_id": "neg-done",
            "action": "accept",
            "proposal": {"fields": {"amount": 70}},
        },
    )
    log.event(
        "negotiation_completed",
        status="agreed",
        agreed_amount=70,
        rounds=0,
        negotiation_id="neg-done",
        listing_id=listing_id,
    )
    log.end("agreed", negotiation_id="neg-done", agreed_amount=70, rounds=0)
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
            "core_buyer.negotiation_client.urllib.request.urlopen",
            _urlopen_for(
                [{"action": "accept", "proposal": {"fields": {"amount": 70}}}]
            ),
        )
        result = runner.invoke(
            app,
            [
                "negotiate",
                "--from",
                run_id,
            ],
        )

        assert result.exit_code == 0, result.output

    def test_resume_recovers_scaled_alkahest_ceiling_from_run_log(
        self,
        runner,
        monkeypatch,
    ):
        run_id = _seed_partial_negotiation(
            "http://seller:8001",
            "L-1",
            initial_price=50_000_000,
            max_price=100_000_000,
        )
        monkeypatch.setattr(
            "core_buyer.negotiation_client.urllib.request.urlopen",
            _urlopen_for(
                [{"action": "accept", "proposal": {"fields": {"amount": 70}}}]
            ),
        )

        result = runner.invoke(app, ["negotiate", "--from", run_id])

        assert result.exit_code == 0, result.output
        assert "100000000" in result.output

    def test_resume_appends_resumed_from_to_new_log(self, runner, monkeypatch):
        """Each `negotiate` invocation opens its own run-log; resume
        records the source run-id as `resumed_from` in run_started."""
        original_run = _seed_partial_negotiation("http://seller:8001", "L-1")

        monkeypatch.setattr(
            "core_buyer.negotiation_client.urllib.request.urlopen",
            _urlopen_for(
                [{"action": "accept", "proposal": {"fields": {"amount": 70}}}]
            ),
        )
        result = runner.invoke(
            app,
            [
                "negotiate",
                "--from",
                original_run,
            ],
        )
        assert result.exit_code == 0, result.output

        # Find the new run-log (the one that wasn't `original_run`).
        new_runs = [r for r in list_runs() if r.run_id != original_run]
        assert len(new_runs) == 1
        events = read_run(new_runs[0].run_id, signer=BUYER_SIGNER)
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
        self,
        runner,
        monkeypatch,
    ):
        """Run-log has a counter mid-stream → buy --from continues
        the round loop, agrees, then invokes run_settle_from_log."""
        run_id = _seed_partial_negotiation("http://seller:8001", "L-1")

        monkeypatch.setattr(
            "core_buyer.negotiation_client.urllib.request.urlopen",
            _urlopen_for(
                [{"action": "accept", "proposal": {"fields": {"amount": 70}}}]
            ),
        )

        settle_calls: list[dict] = []

        def _fake_settle(**kwargs):
            settle_calls.append(kwargs)
            return {"status": "ready"}

        monkeypatch.setattr(
            "arkhai_vms_buyer.buy_cli.run_settle_from_log",
            _fake_settle,
        )

        result = runner.invoke(
            app,
            [
                "buy",
                "--from",
                run_id,
            ],
        )

        assert result.exit_code == 0, result.output
        assert len(settle_calls) == 1
        assert settle_calls[0]["run_id"] == run_id

        # The same run-log accumulated negotiation_completed BEFORE
        # settlement was kicked off.
        events = read_run(run_id, signer=BUYER_SIGNER)
        ev_names = [e["event"] for e in events]
        assert "negotiation_resumed" in ev_names
        assert "negotiation_completed" in ev_names
        agreed = next(e for e in events if e["event"] == "negotiation_completed")
        assert agreed["status"] == "agreed"
        assert agreed["agreed_amount"] == 70

    def test_buy_from_already_agreed_skips_negotiation(self, runner, monkeypatch):
        """If the run-log shows an agreed outcome, --from goes
        straight to settlement (no /negotiate/* HTTP)."""
        run_id = _seed_agreed_negotiation("http://seller:8001", "L-1")

        # If urlopen is touched, the test fails — the agreed path
        # must not make any negotiation HTTP calls.
        def _fail_urlopen(*a, **k):
            raise AssertionError("urlopen called on already-agreed --from path")

        monkeypatch.setattr(
            "core_buyer.negotiation_client.urllib.request.urlopen",
            _fail_urlopen,
        )

        settle_calls: list[dict] = []
        monkeypatch.setattr(
            "arkhai_vms_buyer.buy_cli.run_settle_from_log",
            lambda **kw: settle_calls.append(kw) or {"status": "ready"},
        )

        result = runner.invoke(
            app,
            [
                "buy",
                "--from",
                run_id,
            ],
        )

        assert result.exit_code == 0, result.output
        assert len(settle_calls) == 1
        assert settle_calls[0]["run_id"] == run_id

    def test_buy_from_mid_stream_exit_skips_settlement(
        self,
        runner,
        monkeypatch,
    ):
        """If the resumed negotiation exits (seller walks), settlement
        must NOT be invoked — there's nothing to settle."""
        run_id = _seed_partial_negotiation("http://seller:8001", "L-1")

        # Seller exits when we counter.
        monkeypatch.setattr(
            "core_buyer.negotiation_client.urllib.request.urlopen",
            _urlopen_for([{"action": "exit", "reason": "price_unreasonable"}]),
        )

        settle_calls: list[dict] = []

        def _fake_settle(**kwargs):
            settle_calls.append(kwargs)
            return {"status": "ready"}

        monkeypatch.setattr(
            "arkhai_vms_buyer.buy_cli.run_settle_from_log",
            _fake_settle,
        )

        result = runner.invoke(
            app,
            [
                "buy",
                "--from",
                run_id,
            ],
        )

        assert result.exit_code == 4, result.output
        assert settle_calls == [], (
            "Settlement must not run when negotiation didn't agree"
        )

    def test_buy_fresh_rejects_nonpositive_duration_hours(self, runner):
        """An explicit duration must be positive; omission is resolved after selection."""
        result = runner.invoke(app, ["buy", "--duration-hours", "0"])
        assert result.exit_code == 2
        assert "duration-hours" in result.output.lower()

    def test_buy_fresh_rejects_only_one_price(self, runner):
        """Pass both prices, or neither — never one half."""
        result = runner.invoke(
            app,
            [
                "buy",
                "--duration-hours",
                "1",
                "--initial-price",
                "100",
            ],
        )
        assert result.exit_code == 2
        assert (
            "initial-price" in result.output.lower()
            or "max-price" in result.output.lower()
        )

    @pytest.mark.parametrize("command", ["buy", "negotiate"])
    def test_both_duration_flags_are_refused_before_selection(self, runner, monkeypatch, command):
        """One duration, in either spelling; naming both is an error naming the conflict."""
        monkeypatch.setattr(
            "arkhai_vms_buyer.common.resolve_fresh_buyer_identity",
            lambda: pytest.fail("a duration conflict is refused before any identity or registry read"),
        )
        result = runner.invoke(
            app, [command, "--duration-seconds", "3600", "--duration-hours", "1"],
        )
        assert result.exit_code == 2
        assert "Pass --duration-seconds or --duration-hours, not both." in result.output

    @pytest.mark.parametrize("command", ["buy", "negotiate"])
    def test_a_resume_refuses_waiver_flags(self, runner, monkeypatch, command):
        run_id = _seed_partial_negotiation("http://seller:8001", "L-1")
        monkeypatch.setattr(
            "arkhai_vms_buyer.buy_cli.run_settle_from_log",
            lambda **kw: pytest.fail("a refused resume settles nothing"),
        )
        result = runner.invoke(app, [command, "--from", run_id, "--allow-no-penalty"])
        assert result.exit_code == 2
        assert "waivers apply only to fresh" in " ".join(result.output.replace("│", " ").split())

    @pytest.mark.parametrize("command", ["buy", "negotiate"])
    def test_a_nonpositive_duration_in_seconds_is_refused(self, runner, command):
        result = runner.invoke(app, [command, "--duration-seconds", "0"])
        assert result.exit_code == 2
        assert "--duration-seconds must be positive" in result.output

    def test_buy_fresh_constructs_buy_config(self, runner, monkeypatch):
        """Fresh buy reaches run_buy with a valid BuyConfig and chain proposal."""
        listing, captured = _stub_fresh_alkahest_buy(monkeypatch)

        result = runner.invoke(
            app,
            [
                "buy",
                "--duration-hours",
                "1",
                "--ssh-public-key",
                "ssh-ed25519 AAAA buyer@test",
                "--registry-urls",
                "http://reg",
            ],
        )
        assert result.exit_code == 0, result.output

        assert captured["config"].principal == BUYER_SIGNER.identity
        assert captured["config"].registry_urls == ["http://reg"]
        assert captured["proposal"].settlement_schema == "alkahest.v1"
        assert captured["proposal"].option_id == listing["settlement_options"][0]["option_id"]
        assert _fresh_run_started()["duration_seconds"] == 3600
        assert _fresh_run_started()["compute_term_waivers"] == []
        assert "Waivers in force" not in result.output

    @pytest.mark.parametrize(
        ("flags", "recorded"),
        [
            (["--allow-no-penalty", "--allow-charged-term-end"],
             ["--allow-no-penalty", "--allow-charged-term-end"]),
            (["--allow-unprotected-terms"], [
                "--allow-no-delivery-deadline", "--allow-no-penalty",
                "--allow-charged-preemption", "--allow-charged-term-end",
            ]),
        ],
        ids=["two-waivers", "the-shorthand"],
    )
    def test_buy_fresh_records_and_names_each_waiver_and_a_duration_in_seconds(
        self, runner, monkeypatch, flags, recorded,
    ):
        _stub_fresh_alkahest_buy(monkeypatch)

        result = runner.invoke(app, [
            "buy", "--duration-seconds", "5400", "--ssh-public-key", "ssh-ed25519 AAAA buyer@test",
            "--registry-urls", "http://reg", *flags,
        ])

        assert result.exit_code == 0, result.output
        started = _fresh_run_started()
        assert started["duration_seconds"] == 5400
        assert started["compute_term_waivers"] == recorded
        (named,) = [line for line in result.output.splitlines() if "Waivers in force:" in line]
        assert [flag for flag in recorded if flag in named] == recorded

    def test_buy_from_rejects_current_max_price_override(
        self,
        runner,
        monkeypatch,
    ):
        run_id = _seed_partial_negotiation("http://seller:8001", "L-1")
        monkeypatch.setattr(
            "arkhai_vms_buyer.buy_cli.run_settle_from_log",
            lambda **kw: pytest.fail("settle should not run when validation fails"),
        )

        result = runner.invoke(
            app,
            [
                "buy",
                "--from",
                run_id,
                "--max-price",
                "101",
            ],
        )
        assert result.exit_code == 2
        assert "persisted scaled negotiation ceiling" in result.output


def _fresh_run_started() -> dict:
    """The one fresh run's opening event, from the run-log directory the tests isolate."""
    (run,) = list_runs()
    return next(
        event for event in read_run(run.run_id, signer=BUYER_SIGNER) if event["event"] == "run_started"
    )


def _stub_fresh_alkahest_buy(monkeypatch) -> tuple[dict, dict]:
    """A fresh buy over one Alkahest listing, stopped at ``run_buy``.

    Returns the listing and what the stubs captured. The Alkahest option has no
    lifecycle adapter, so no default refusal applies to it; the run's waivers are
    still recorded and named.
    """
    listing: dict = {
        "listing_id": "L-1",
        "storefront_url": "http://seller:8001",
        "accepted_escrows": [
            {
                "chain_name": "anvil",
                "escrow_address": "0x" + "aa" * 20,
                "literal_fields": {"token": "0x" + "bb" * 20},
                "rates": [{"field": "amount", "per": "hour", "value": "100"}],
            }
        ],
    }
    option_params = {"accepted_escrow": listing["accepted_escrows"][0]}
    option_rates = [
        RateValue.model_validate(rate)
        for rate in listing["accepted_escrows"][0]["rates"]
    ]
    listing["settlement_options"] = [
        {
            "option_id": derive_settlement_option_id(
                price={"asset": "0x" + "bb" * 20, "rates": option_rates},
                settlement={"schema": "alkahest.v1", **option_params},
            ),
            "price": {"asset": "0x" + "bb" * 20, "rates": option_rates},
            "settlement": {"schema": "alkahest.v1", **option_params},
        }
    ]
    captured: dict = {}

    monkeypatch.setattr(
        "arkhai_vms_buyer.common.chain_by_name",
        lambda name: ChainConfig(name=name, rpc_url="http://rpc", chain_id=31337),
    )
    monkeypatch.setattr(
        "arkhai_vms_buyer.settlement_composition.load_user_config",
        lambda: {
            "Settlement": {
                "schema_version": 1,
                "priority": ["alkahest.v1"],
                "alkahest": {"enabled": True},
            }
        },
    )
    monkeypatch.setattr(
        "arkhai_vms_buyer.buy_cli.query_registry_for_matches_multi",
        lambda *a, **kw: [listing],
    )
    monkeypatch.setattr(
        "arkhai_vms_buyer.buy_cli._resolve_prices_from_matches",
        lambda **kw: (100, 150),
    )
    monkeypatch.setattr(
        "arkhai_vms_buyer.escrow_client.make_buyer_payment_escrow_terms_fn",
        lambda **kw: lambda *a, **inner_kw: [],
    )
    monkeypatch.setattr(
        "arkhai_vms_buyer.escrow_client.make_create_escrow_fn",
        lambda **kw: lambda escrows: [],
    )

    def fake_make_negotiate_hook(**kwargs):
        captured["proposal_builder"] = kwargs["build_escrow_proposal"]

        def _hook(*_args, **_kwargs):
            raise AssertionError("fake run_buy should not call negotiate hook")

        return _hook

    monkeypatch.setattr(
        "arkhai_vms_buyer.buy_cli.make_legacy_negotiate_hook",
        fake_make_negotiate_hook,
    )

    def fake_run_buy(**kwargs):
        captured["config"] = kwargs["config"]
        captured["proposal"] = captured["proposal_builder"](kwargs["matches"][0])
        assert "negotiate" in kwargs
        assert "settle" in kwargs
        assert "build_escrow_proposal" not in kwargs
        return BuyResult(status="ready", negotiation_id="neg-1", rounds=1)

    monkeypatch.setattr("arkhai_vms_buyer.buy_cli.run_buy", fake_run_buy)
    return listing, captured


# ---------------------------------------------------------------------------
# The watchdog: `market buy --watchdog`, its resume, and `market delivery`
# ---------------------------------------------------------------------------


class _Journal:
    """The watchdog journal's interface, in memory."""

    def __init__(self):
        self.states = {}

    def opt_in(self, negotiation_id, settings):
        state = self.states.get(negotiation_id)
        self.states[negotiation_id] = WatchdogState(
            settings, state.last_probe_at if state else None, state.stop if state else None,
        )

    def state(self, negotiation_id):
        return self.states.get(negotiation_id)

    def record_probe(self, negotiation_id, at):
        state = self.states[negotiation_id]
        self.states[negotiation_id] = WatchdogState(state.settings, at, state.stop)

    def record_stop(self, negotiation_id, stop):
        state = self.states[negotiation_id]
        self.states[negotiation_id] = WatchdogState(state.settings, state.last_probe_at, state.stop or stop)
        return self.states[negotiation_id].stop


#: One failed probe reaches the threshold, so the loop never sleeps.
_IMMEDIATE = WatchdogSettings(interval_seconds=1, threshold=1, probe_timeout_seconds=1)
#: Where a delivered VM's SSH endpoint answers; a documentation address.
_DETAILS = json.dumps({"host": "192.0.2.10", "port": 22, "user": "tenant"})


class _Clock:
    """Fake time: sleeping advances it, and it stamps probes."""

    def __init__(self, now=1000):
        self.now = now

    async def sleep(self, seconds):
        self.now += seconds

    def wait_clock(self):
        return WaitClock(now=lambda: int(self.now), monotonic=lambda: self.now, sleep=self.sleep)


_ACTIVE = DeliveryView(progress="active")
_ENDED = DeliveryView(progress="end_recorded", recorded_end=RecordedEnd(
    ended_at=1, actor=BUYER_SIGNER.identity, cause="payer", source="watch",
))


def _watchdog_seams(monkeypatch, journal, clock=None, *, reads=(_ACTIVE,), answers=(False,),
                    negotiation_id="neg-1"):
    """Replace the buy command's watchdog seams. The storefront answers ``reads``
    in turn, then the last again; each probe answers the next of ``answers``."""
    clock = clock or _Clock()
    stopped = EndDeliveryProgress(negotiation_id=negotiation_id, observed_at=1, mode="normal_stop",
                                  payment=Accepted())
    remaining = list(reads)

    async def read(_negotiation_id):
        return SimpleNamespace(delivery=remaining.pop(0) if len(remaining) > 1 else remaining[0])

    lifecycle = SimpleNamespace(
        _deal=lambda _: SimpleNamespace(rate=True, buyer=None, payment=None),
        end=AsyncMock(return_value=stopped),
        end_journal=SimpleNamespace(read=lambda _: None),
        evidence=None, watchdog=journal,
        payments=SimpleNamespace(resolve=lambda _: None),
        peer=SimpleNamespace(read=AsyncMock(side_effect=read)),
    )
    opened, probed, scripted = [], [], list(answers)

    def watchdog_target(run_id):
        opened.append(run_id)

        @asynccontextmanager
        async def context():
            yield lifecycle

        return EndTarget(negotiation_id=negotiation_id, lifecycle=context())

    def watchdog_probe(details):
        async def probe():
            probed.append(details)
            return scripted.pop(0)

        return probe

    monkeypatch.setattr(buy_cli, "watchdog_journal", lambda: journal)
    monkeypatch.setattr(buy_cli, "watchdog_target", watchdog_target)
    monkeypatch.setattr(buy_cli, "watchdog_probe", watchdog_probe)
    monkeypatch.setattr(buy_cli, "wait_clock", clock.wait_clock)
    return lifecycle, opened, probed


def _paid_run_buy(monkeypatch, status):
    """``run_buy`` approving a payment, then ending at ``status``."""

    def fake_run_buy(**kwargs):
        kwargs["on_event"]("payment_approved", {"transaction_id": "tx-1", "negotiation_id": "neg-1"})
        return BuyResult(status=status, negotiation_id="neg-1", rounds=1, connection_details=_DETAILS)

    monkeypatch.setattr(buy_cli, "buy_orchestration", lambda: fake_run_buy)


def _settled(monkeypatch, settle):
    """The resumed settlement ``buy --from`` runs, through its factory."""
    monkeypatch.setattr(buy_cli, "settle_resumption", lambda: settle)


#: A fresh buy's arguments; the SSH key is a placeholder, never a credential.
_FRESH = ["buy", "--duration-hours", "1", "--ssh-public-key", "ssh-ed25519 AAAA buyer@test",
          "--registry-urls", "http://reg"]


class TestBuyWatchdog:
    def test_the_opt_in_interval_and_threshold_are_persisted_and_the_bound_shown_while_it_runs(
        self, runner, monkeypatch,
    ):
        _stub_fresh_alkahest_buy(monkeypatch)
        _paid_run_buy(monkeypatch, "ready")
        journal = _Journal()
        # The deal ends by another path before the first probe.
        lifecycle, opened, probed = _watchdog_seams(monkeypatch, journal, reads=(_ENDED,))

        result = runner.invoke(app, [*_FRESH, "--watchdog", "--watchdog-interval", "7",
                                     "--watchdog-threshold", "2"])

        assert result.exit_code == 0, result.output
        assert journal.state("neg-1").settings == WatchdogSettings(7, 2, 10)
        events = [event["event"] for event in read_run(list_runs()[0].run_id, signer=BUYER_SIGNER)]
        assert events.index("watchdog_opted_in") < events.index("run_ended")
        output = " ".join(result.output.split())
        assert "at most 24 seconds" in output and "only while this command runs" in output
        assert "the deal ended by another path" in output
        assert len(opened) == 1 and probed == []
        lifecycle.end.assert_not_awaited()

    def test_a_deal_never_ready_keeps_its_opt_in_and_is_never_watched(self, runner, monkeypatch):
        _stub_fresh_alkahest_buy(monkeypatch)
        _paid_run_buy(monkeypatch, "timeout")
        journal = _Journal()
        _, opened, probed = _watchdog_seams(monkeypatch, journal)

        result = runner.invoke(app, [*_FRESH, "--watchdog"])

        assert result.exit_code == 4, result.output
        assert journal.state("neg-1").settings == WatchdogSettings()
        assert opened == [] and probed == []
        assert "Watchdog running" not in result.output

    def test_without_the_opt_in_nothing_is_persisted_or_watched(self, runner, monkeypatch):
        _stub_fresh_alkahest_buy(monkeypatch)
        _paid_run_buy(monkeypatch, "ready")
        journal = _Journal()
        _, opened, _ = _watchdog_seams(monkeypatch, journal)

        result = runner.invoke(app, _FRESH)

        assert result.exit_code == 0, result.output
        assert journal.states == {} and opened == []

    def test_a_resume_re_enters_the_watchdog_and_a_resume_refuses_the_flag(self, runner, monkeypatch):
        run_id = _seed_agreed_negotiation("http://seller:8001", "L-1")
        _settled(monkeypatch, lambda **kw: {"status": "ready", "negotiation_id": "neg-1",
                                            "connection_details": _DETAILS})
        journal = _Journal()
        journal.opt_in("neg-1", _IMMEDIATE)
        lifecycle, opened, probed = _watchdog_seams(monkeypatch, journal)

        refused = runner.invoke(app, ["buy", "--from", run_id, "--watchdog"])
        assert refused.exit_code == 2 and opened == []

        result = runner.invoke(app, ["buy", "--run-id", run_id])

        assert result.exit_code == 0, result.output
        assert opened == [run_id] and probed == [_DETAILS]
        lifecycle.end.assert_awaited_once_with("neg-1")
        assert journal.state("neg-1").stop is not None
        assert "at most 2 seconds" in " ".join(result.output.split())

    def test_the_probe_reaches_the_disclosed_ssh_endpoint_and_refuses_a_delivery_naming_none(self):
        assert callable(buy_cli.watchdog_probe(_DETAILS))
        assert callable(buy_cli.watchdog_probe({"host": "192.0.2.10", "port": 22}))
        with pytest.raises(ValueError, match="no SSH endpoint"):
            buy_cli.watchdog_probe(json.dumps({"user": "tenant"}))

    def test_a_journaled_stop_is_carried_on_resume_with_no_settle_or_probe(self, runner, monkeypatch):
        run_id = _seed_agreed_negotiation("http://seller:8001", "L-1")
        _settled(monkeypatch, lambda **kw: pytest.fail("a journaled stop needs no settle; the storefront may be down"))
        monkeypatch.setattr(buy_cli, "run_negotiation_id", lambda run, signer: "neg-done")
        journal = _Journal()
        # The seeded run's accepted deal.
        journal.opt_in("neg-done", _IMMEDIATE)
        journal.record_stop("neg-done", WatchdogStop(990, (ProbeObservation(980, "probe timed out"),)))
        lifecycle, opened, probed = _watchdog_seams(monkeypatch, journal, negotiation_id="neg-done")

        result = runner.invoke(app, ["buy", "--from", run_id])

        assert result.exit_code == 0, result.output
        assert opened == [run_id] and probed == []
        lifecycle.end.assert_awaited_once_with("neg-done")
        assert lifecycle.peer.read.await_count == 0
        assert "carried to the payment authority" in " ".join(result.output.split())

    def test_the_read_shows_monitored_while_a_resumed_loop_probes_unmonitored_after_a_kill_and_stopped(
        self, runner, monkeypatch,
    ):
        journal = _Journal()
        clock = _Clock()

        class Peer:
            async def read(self, negotiation_id):
                return LifecycleRead(negotiation_id=negotiation_id,
                                     authority=AuthorityView(outcome=Rejected(reason="x")),
                                     delivery=DeliveryView(progress="active"))

        def end_context(run_id, **_kwargs):
            deal = BuyerDeal("neg-1", "commitment", PaymentBinding("neg-1", PaymentSelector("fixture.payment")),
                             rate=True)

            @asynccontextmanager
            async def context():
                yield BuyerLifecycle(deal=lambda _: deal, payments=PaymentAdapterTable([]),
                                     disputes=DisputeAdapterTable([]), operations=None, peer=Peer(),
                                     watchdog=journal, clock=lambda: int(clock.now))

            return SimpleNamespace(negotiation_id="neg-1"), None, context()

        monkeypatch.setattr(end_cli, "end_context", end_context)

        def read():
            result = runner.invoke(app, ["delivery", "--run", "run"])
            assert result.exit_code == 0, result.output
            view = json.loads(result.stdout)
            assert view["delivery"]["progress"] == "active"
            return view["watchdog"]["status"]

        assert read() == "unmonitored"
        journal.opt_in("neg-1", WatchdogSettings(interval_seconds=60, threshold=3, probe_timeout_seconds=10))
        # The opt-in alone is no protection.
        assert read() == "unmonitored"

        run_id = _seed_agreed_negotiation("http://seller:8001", "L-1")
        _settled(monkeypatch, lambda **kw: {"status": "ready", "negotiation_id": "neg-1",
                                            "connection_details": _DETAILS})

        def resume():
            result = runner.invoke(app, ["buy", "--from", run_id])
            assert result.exit_code == 0, result.output

        # A resumed loop probes once, the access answering, and exits when the
        # deal then ends by another path: its probe is the freshest instant.
        _watchdog_seams(monkeypatch, journal, clock, reads=(_ACTIVE, _ENDED), answers=(True,))
        resume()
        assert journal.state("neg-1").last_probe_at == 1000
        clock.now = 1000 + 60 + 10 + GRACE_SECONDS
        assert read() == "monitored"
        # The command is gone: no probe follows, so the last one goes stale.
        clock.now += 1
        assert read() == "unmonitored"

        # Resumed again, the loop finds the access lost and stops the deal.
        journal.opt_in("neg-1", _IMMEDIATE)
        lifecycle, _, _ = _watchdog_seams(monkeypatch, journal, clock)
        resume()
        lifecycle.end.assert_awaited_once_with("neg-1")
        assert read() == "stopped"
