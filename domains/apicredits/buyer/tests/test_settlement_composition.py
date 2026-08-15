from __future__ import annotations

from market_hosted_settlement import StripeSettlementConfig

from domains.apicredits.buyer.settlement_composition import (
    buyer_settlement_registry,
    resolve_buyer_settlement_policy,
)


def test_hosted_only_registry_resolution_does_not_resolve_wallet(monkeypatch) -> None:
    monkeypatch.setattr(
        "domains.apicredits.buyer.settlement_composition.resolve_buyer_wallet",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("hosted-only policy resolved wallet")
        ),
    )
    stripe = StripeSettlementConfig(
        enabled=True,
        authority_id="authority-main",
        environment="test",
    ).model_dump(mode="json", exclude_defaults=True)

    policy = resolve_buyer_settlement_policy(
        {
            "Settlement": {
                "schema_version": 1,
                "priority": ["fiat.stripe.v1"],
                "stripe": stripe,
            }
        }
    )

    assert [item.mechanism_id for item in policy.ordered_registrations()] == [
        "fiat.stripe.v1"
    ]


def test_buyer_registry_installs_peer_mechanisms() -> None:
    assert {item.mechanism_id for item in buyer_settlement_registry().registrations} == {
        "alkahest.v1",
        "fiat.stripe.v1",
    }
