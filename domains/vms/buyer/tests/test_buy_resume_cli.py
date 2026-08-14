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

import pytest
from core_buyer.registry_config import RegistryAuthority
from domains.vms.buyer.buy_orchestrator import BuyResult
from domains.vms.buyer.cli import app
from domains.vms.buyer.run_log import RunLog, read_run
from identity_helpers import (
    BUYER_SIGNER,
    seller_principals,
    signed_response_headers,
)
from market_config.config_loader import ChainConfig
from market_core.schemas import RateValue
from typer.testing import CliRunner

# Test wallet — derived address must match _BUYER_ADDR below for
# signature checks to pass downstream (we don't verify here, but the
# CLI's resolve_config_value short-circuits on truthy value).
_BUYER_PK = "0x" + "11" * 32
_BUYER_ADDR = "0xCC" + "cc" * 19  # placeholder; not signature-checked here


@pytest.fixture(autouse=True)
def _isolated_runs_dir(tmp_path, monkeypatch):
    """Pin the run-log directory at tmp_path for hermetic tests."""
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    monkeypatch.setattr(
        "domains.vms.buyer.common.resolve_identity_config",
        lambda: type("IdentityConfig", (), {"principal": BUYER_SIGNER.identity})(),
    )
    monkeypatch.setattr(
        "domains.vms.buyer.common.resolve_identity_credential",
        lambda: b"unused-test-credential",
    )
    monkeypatch.setattr(
        "domains.vms.buyer.common.resolve_buyer_signer",
        lambda *_: BUYER_SIGNER,
    )
    monkeypatch.setattr(
        "domains.vms.buyer.common.resolve_buyer_wallet",
        lambda **_kwargs: (_BUYER_ADDR, _BUYER_PK),
    )
    monkeypatch.setattr(
        "domains.vms.buyer.deal_helpers._publisher_trust_refresh",
        lambda signer: lambda *_: seller_principals(),
    )
    monkeypatch.setattr(
        "domains.vms.buyer.common.resolve_registry_authorities",
        lambda urls: {
            url: RegistryAuthority(
                authority="registry",
                principals=seller_principals(),
            )
            for url in urls
        },
    )
    monkeypatch.setattr(
        "domains.vms.buyer.common.resolve_indexer_urls_for_schema",
        lambda _schema, **kwargs: list(kwargs["registry_authorities"]),
    )
    monkeypatch.setattr(
        "domains.vms.buyer.common.resolve_registry_api_keys",
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
        body = next(it)
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
    return RunLog.start(principal=BUYER_SIGNER.identity, **fields)


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
        from domains.vms.buyer.run_log import list_runs

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
            "domains.vms.buyer.buy_cli.run_settle_from_log",
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
            "domains.vms.buyer.buy_cli.run_settle_from_log",
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
            "domains.vms.buyer.buy_cli.run_settle_from_log",
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

    def test_buy_fresh_still_requires_duration_hours(self, runner):
        """Fresh `market buy` (no --from) without --duration-hours fails fast.

        Prices are now optional — when omitted they're derived from each
        listing's seller-advertised min_price (interactively confirmed by
        default; non-interactively under --auto-price). Duration is still
        mandatory because it shapes the buyer's lease ask sent at
        /negotiate/new.
        """
        result = runner.invoke(
            app,
            [
                "buy",
            ],
        )
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

    def test_buy_fresh_constructs_buy_config(self, runner, monkeypatch):
        """Fresh buy reaches run_buy with a valid BuyConfig and chain proposal."""
        listing = {
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
        from market_core.schemas import derive_settlement_option_id

        option_params = {"accepted_escrow": listing["accepted_escrows"][0]}
        option_rates = [
            RateValue.model_validate(rate)
            for rate in listing["accepted_escrows"][0]["rates"]
        ]
        listing["settlement_options"] = [
            {
                "option_id": derive_settlement_option_id(
                    mechanism="alkahest.v1",
                    asset="0x" + "bb" * 20,
                    rates=option_rates,
                    params=option_params,
                ),
                "mechanism": "alkahest.v1",
                "asset": "0x" + "bb" * 20,
                "rates": option_rates,
                "params": option_params,
            }
        ]
        captured = {}

        monkeypatch.setattr(
            "domains.vms.buyer.common.chain_by_name",
            lambda name: ChainConfig(
                name=name,
                rpc_url="http://rpc",
                chain_id=31337,
                alkahest_address_config_path="/tmp/alkahest.json",
            ),
        )
        monkeypatch.setattr(
            "domains.vms.buyer.settlement_composition.load_user_config",
            lambda: {
                "Settlement": {
                    "schema_version": 1,
                    "priority": ["alkahest.v1"],
                    "alkahest": {"enabled": True},
                }
            },
        )
        monkeypatch.setattr(
            "domains.vms.buyer.buy_cli.query_registry_for_matches_multi",
            lambda *a, **kw: [listing],
        )
        monkeypatch.setattr(
            "domains.vms.buyer.buy_cli._resolve_prices_from_matches",
            lambda **kw: (100, 150),
        )
        monkeypatch.setattr(
            "domains.vms.buyer.escrow_client.make_buyer_payment_escrow_terms_fn",
            lambda **kw: lambda *a, **inner_kw: [],
        )
        monkeypatch.setattr(
            "domains.vms.buyer.escrow_client.make_create_escrow_fn",
            lambda **kw: lambda escrows: [],
        )

        def fake_make_negotiate_hook(**kwargs):
            captured["proposal_builder"] = kwargs["build_escrow_proposal"]

            def _hook(*_args, **_kwargs):
                raise AssertionError("fake run_buy should not call negotiate hook")

            return _hook

        monkeypatch.setattr(
            "domains.vms.buyer.buy_cli.make_legacy_negotiate_hook",
            fake_make_negotiate_hook,
        )

        def fake_run_buy(**kwargs):
            captured["config"] = kwargs["config"]
            captured["proposal"] = captured["proposal_builder"](kwargs["matches"][0])
            assert "negotiate" in kwargs
            assert "settle" in kwargs
            assert "build_escrow_proposal" not in kwargs
            return BuyResult(status="ready", negotiation_id="neg-1", rounds=1)

        monkeypatch.setattr("domains.vms.buyer.buy_cli.run_buy", fake_run_buy)

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
        assert captured["proposal"].chain_name == "anvil"

    def test_buy_from_rejects_current_max_price_override(
        self,
        runner,
        monkeypatch,
    ):
        run_id = _seed_partial_negotiation("http://seller:8001", "L-1")
        monkeypatch.setattr(
            "domains.vms.buyer.buy_cli.run_settle_from_log",
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
