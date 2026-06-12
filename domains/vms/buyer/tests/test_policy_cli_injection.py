"""Policy-injected CLI flags and the --policy-param escape hatch."""

from __future__ import annotations

from typing import Optional
from unittest.mock import patch

import typer
from typer.testing import CliRunner

from market_policy.buyer_policy import (
    BuyerPolicy,
    PolicyParam,
    inject_policy_cli_params,
)

runner = CliRunner()


def _app_with(policy: BuyerPolicy) -> typer.Typer:
    app = typer.Typer()

    def verb(
        quiet: bool = typer.Option(False, "--quiet"),
        **policy_values,
    ) -> None:
        typer.echo(repr(sorted(policy_values.items())))

    app.command("verb")(inject_policy_cli_params(verb, policy))
    return app


def test_policy_params_become_flags_and_land_in_kwargs():
    policy = BuyerPolicy(
        name="t", middlewares=("listed_price",),
        cli_params=(
            PolicyParam(name="initial_price", help="opening"),
            PolicyParam(name="budget", annotation=Optional[float], help="opaque"),
        ),
    )
    app = _app_with(policy)

    result = runner.invoke(app, ["--help"])
    assert "--initial-price" in result.output
    assert "--budget" in result.output
    assert "--policy-param" in result.output

    result = runner.invoke(app, ["--budget", "9.5", "--quiet"])
    assert result.exit_code == 0, result.output
    assert "('budget', 9.5)" in result.output
    assert "('initial_price', None)" in result.output


def test_escape_hatch_collects_repeated_pairs():
    policy = BuyerPolicy(name="t", middlewares=("listed_price",))
    app = _app_with(policy)
    result = runner.invoke(
        app, ["--policy-param", "a=1", "-P", "b=two"],
    )
    assert result.exit_code == 0, result.output
    assert "('policy_param', ['a=1', 'b=two'])" in result.output


def test_assembled_buy_and_negotiate_surface_the_default_policy_flags():
    from domains.vms.buyer.cli import app

    for verb in ("buy", "negotiate"):
        result = runner.invoke(app, [verb, "--help"])
        assert result.exit_code == 0, result.output
        for flag in ("--initial-price", "--max-price", "--price-markup",
                     "--policy-param"):
            assert flag in result.output, f"{verb} missing {flag}"


def test_negotiate_with_seller_delivers_policy_params_to_the_chain():
    from market_policy.negotiation_middleware import (
        NegotiationDecision,
    )

    from domains.vms.buyer.buyer_client import negotiate_with_seller
    from domains.vms.buyer.tests.test_buyer_client import (
        _BUYER_ADDR,
        _BUYER_PK,
        _MockResponse,
        _escrow_proposal,
        _provision,
    )
    import json

    seen_intermediates = []

    def capturing_terminal(history, context):
        seen_intermediates.append(dict(context.intermediate))
        return NegotiationDecision(
            action="counter",
            proposal=dict(context.our_escrow_proposal or {}),
        ), context

    def fake_urlopen(req, timeout=None):
        return _MockResponse(status=200, text=json.dumps({
            "negotiation_id": "neg-1",
            "action": "accept",
            "proposal": {"fields": {"amount": 100}},
        }))

    with patch(
        "domains.vms.buyer.buyer_client.urllib.request.urlopen",
        side_effect=fake_urlopen,
    ):
        negotiate_with_seller(
            seller_url="http://seller:8001",
            buyer_address=_BUYER_ADDR,
            buyer_private_key=_BUYER_PK,
            listing_id="lst-1",
            initial_price=50,
            max_price=100,
            provision_terms=_provision(3600),
            escrow_proposal=_escrow_proposal(),
            chain=[capturing_terminal],
            policy_params={"oracle": "0xabc"},
        )

    assert seen_intermediates
    assert all(i.get("oracle") == "0xabc" for i in seen_intermediates)


def test_resume_point_carries_the_recorded_policy(tmp_path, monkeypatch):
    import json

    from domains.vms.buyer import deal_helpers, run_log

    monkeypatch.setattr(run_log, "runs_dir", lambda: tmp_path)
    run_file = tmp_path / "run-1.jsonl"
    events = [
        {"event": "run_started", "run_id": "run-1",
         "seller_url": "http://s:8001", "listing_id": "lst-1",
         "policy": "bisection"},
        {"event": "negotiation_round", "round": 0,
         "our_message": {"proposal": {"fields": {"amount": 50}}},
         "their_reply": {"negotiation_id": "neg-1", "action": "counter",
                          "proposal": {"fields": {"amount": 80}}}},
    ]
    run_file.write_text("\n".join(json.dumps(e) for e in events) + "\n")

    point = deal_helpers.load_negotiation_resume_point("run-1")
    assert point.policy == "bisection"
