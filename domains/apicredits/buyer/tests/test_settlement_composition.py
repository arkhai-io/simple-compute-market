from types import SimpleNamespace

from market_arkhai_payments import ARKHAI_PAYMENTS_CONFIG_KEY, ARKHAI_PAYMENTS_MECHANISM

from arkhai_apicredits_buyer.payments import payment_selection_for_listing
from arkhai_apicredits_buyer.settlement_composition import (
    buyer_settlement_registry,
    resolve_buyer_settlement_policy,
)
from market_identity import Ed25519Signer


def test_payments_only_registry_resolution_does_not_resolve_wallet(monkeypatch) -> None:
    """A wallet-free buyer is never asked for an EVM wallet."""
    monkeypatch.setattr(
        "arkhai_apicredits_buyer.settlement_composition.resolve_buyer_wallet",
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

    policy = resolve_buyer_settlement_policy(
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
        item.mechanism_id for item in buyer_settlement_registry().registrations
    } == {
        "alkahest.v1",
        "arkhai.payments.v1",
    }


def test_payment_selection_attaches_buyer_account_without_alkahest_resources() -> None:
    account = "00000000-0000-4000-8000-000000000011"
    option_id = "a" * 64

    class Config:
        def mechanism_config(self, key):
            assert key == ARKHAI_PAYMENTS_CONFIG_KEY
            return SimpleNamespace(enabled=True)

    class Policy:
        config = Config()

        def compatible_options(self, advertised):
            assert tuple(advertised) == ({"option_id": option_id},)
            registration = SimpleNamespace(mechanism_id=ARKHAI_PAYMENTS_MECHANISM)
            option = SimpleNamespace(
                mechanism=ARKHAI_PAYMENTS_MECHANISM, option_id=option_id
            )
            return ((registration, option),)

    selection = payment_selection_for_listing(
        Policy(),
        {"settlement_options": [{"option_id": option_id}]},
        expiration_unix=1_800_000_000,
        payer_account=account,
        prefer_payment=True,
    )

    assert selection is not None
    assert selection.mechanism == ARKHAI_PAYMENTS_MECHANISM
    assert selection.option_id == option_id
    assert selection.params == {"payer_account": account}
