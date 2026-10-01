from __future__ import annotations

import json

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
        public_details={"currency": "usd"} if mechanism == "example.payment.v1" else {},
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
            SettlementConfig(priority=("example.payment.v1",)),
            (_ready("example.payment.v1"), _unready("alkahest.v1")),
        ),
    )

    result = runner.invoke(app, ["settlement", "status", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert [item["mechanism"] for item in payload["mechanisms"]] == [
        "example.payment.v1",
        "alkahest.v1",
    ]
    assert "url" not in result.output.lower()
    assert "secret" not in result.output.lower()


def test_common_status_exits_nonzero_when_none_are_ready(monkeypatch, runner, app):
    from market_storefront.groups import settlement as group

    monkeypatch.setattr(
        group,
        "_readiness",
        lambda: (SettlementConfig(), (_unready("example.payment.v1"),)),
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
            (_ready("example.payment.v1"), _unready("alkahest.v1")),
        ),
    )

    alkahest = runner.invoke(app, ["settlement", "alkahest", "check", "--json"])

    assert alkahest.exit_code == 1
    assert json.loads(alkahest.output)["blockers"][0]["code"] == "test.unready"
