from __future__ import annotations

import json
from types import SimpleNamespace

from market_settlement_runtime import (
    MechanismReadiness,
    ReadinessBlocker,
    SettlementConfig,
)


def _ready(mechanism: str) -> MechanismReadiness:
    return MechanismReadiness(
        mechanism=mechanism,
        configured=True,
        enabled=True,
        ready=True,
        capabilities=("public-capability",),
        contract_version="1",
        schema_version="1",
        public_details={"currency": "usd"} if mechanism == "fiat.stripe.v1" else {},
    )


def _unready(mechanism: str) -> MechanismReadiness:
    return MechanismReadiness(
        mechanism=mechanism,
        configured=True,
        enabled=True,
        ready=False,
        blockers=(ReadinessBlocker(code="test.unready", message="not ready"),),
    )


def test_common_status_json_is_sanitized_and_side_effect_free(monkeypatch, runner, app):
    from market_storefront.groups import settlement as group

    monkeypatch.setattr(
        group,
        "_readiness",
        lambda: (
            SettlementConfig(priority=("fiat.stripe.v1",)),
            (_ready("fiat.stripe.v1"), _unready("alkahest.v1")),
        ),
    )
    monkeypatch.setattr(
        group,
        "SellerOnboarding",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("side effect")),
    )

    result = runner.invoke(app, ["settlement", "status", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert [item["mechanism"] for item in payload["mechanisms"]] == [
        "fiat.stripe.v1",
        "alkahest.v1",
    ]
    assert "url" not in result.output.lower()
    assert "secret" not in result.output.lower()


def test_common_status_exits_nonzero_when_none_are_ready(monkeypatch, runner, app):
    from market_storefront.groups import settlement as group

    monkeypatch.setattr(
        group,
        "_readiness",
        lambda: (SettlementConfig(), (_unready("fiat.stripe.v1"),)),
    )

    result = runner.invoke(app, ["settlement", "status"])

    assert result.exit_code == 1
    assert "test.unready" in result.output


def test_mechanism_status_and_check_use_common_exit_contract(monkeypatch, runner, app):
    from market_storefront.groups import settlement as group

    monkeypatch.setattr(
        group,
        "_readiness",
        lambda: (
            SettlementConfig(),
            (_ready("fiat.stripe.v1"), _unready("alkahest.v1")),
        ),
    )

    stripe = runner.invoke(app, ["settlement", "stripe", "status", "--json"])
    alkahest = runner.invoke(app, ["settlement", "alkahest", "check", "--json"])

    assert stripe.exit_code == 0
    assert json.loads(stripe.output)["ready"] is True
    assert alkahest.exit_code == 1
    assert json.loads(alkahest.output)["blockers"][0]["code"] == "test.unready"


def test_stripe_onboarding_uses_transient_hosted_workflow(monkeypatch, runner, app):
    from market_storefront.groups import settlement as group

    closed: list[bool] = []
    client = SimpleNamespace(close=lambda: closed.append(True))
    stripe_config = SimpleNamespace(enabled=True, account_ref="seller-main")
    config = SimpleNamespace(mechanism_config=lambda key: stripe_config if key == "stripe" else None)
    monkeypatch.setattr(group, "_settlement_context", lambda: (object(), config, {}))
    monkeypatch.setattr(group, "_stripe_client", lambda config, resources: client)

    class Workflow:
        def __init__(self, actual_client, *, open_url):
            assert actual_client is client
            self.open_url = open_url

        def onboard(self, account_ref, *, open_browser):
            assert account_ref == "seller-main"
            assert open_browser is False
            return SimpleNamespace(
                url="https://connect.stripe.test/transient",
                expires_at_unix=2_000_000_000,
            )

    monkeypatch.setattr(group, "SellerOnboarding", Workflow)

    result = runner.invoke(app, ["settlement", "stripe", "onboard", "--no-browser"])

    assert result.exit_code == 0
    assert "https://connect.stripe.test/transient" in result.output
    assert closed == [True]
