"""The plugin composes the Alkahest and payments entries into one buyer stage table."""

from arkhai_apicredits_buyer.cli import SETTLEMENT
from market_identity import Ed25519Signer


def test_payments_only_registry_resolution_does_not_resolve_wallet(monkeypatch) -> None:
    """A wallet-free buyer is never asked for an EVM wallet."""
    monkeypatch.setattr(
        "arkhai_api_buying_alkahest.stage.resolve_buyer_wallet",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("payments-only policy resolved wallet")
        ),
    )
    payments = {
        "enabled": True,
        "service_url": "https://payments.example",
        "service_identity": Ed25519Signer(bytes(range(32))).identity.model_dump(mode="json"),
        "fee_bps": 250,
        "dispute_authority": "33333333-3333-4333-8333-333333333333",
        "api_key_env": "ARKHAI_PAYMENTS_API_KEY",
    }

    policy = SETTLEMENT.resolve_policy(
        {
            "Settlement": {
                "schema_version": 1,
                "priority": ["arkhai.payments.v1"],
                "arkhai_payments": payments,
            }
        }
    )

    assert [item.mechanism_id for item in policy.ordered_registrations()] == [
        "arkhai.payments.v1"
    ]


def test_buyer_registry_installs_alkahest_and_payments() -> None:
    assert {
        item.mechanism_id for item in SETTLEMENT.registry().registrations
    } == {
        "alkahest.v1",
        "arkhai.payments.v1",
    }
