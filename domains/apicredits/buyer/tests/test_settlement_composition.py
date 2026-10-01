from types import SimpleNamespace

from domains.apicredits.buyer.payments import payment_selection_for_listing
from domains.apicredits.buyer.settlement_composition import buyer_settlement_registry
from domains.apicredits.settlement import CONFIG_KEY, MECHANISM_ID


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
            assert key == CONFIG_KEY
            return SimpleNamespace(enabled=True, account_id=account)

    class Policy:
        config = Config()

        def compatible_options(self, advertised):
            assert tuple(advertised) == ({"option_id": option_id},)
            registration = SimpleNamespace(mechanism_id=MECHANISM_ID)
            option = SimpleNamespace(mechanism=MECHANISM_ID, option_id=option_id)
            return ((registration, option),)

    selection = payment_selection_for_listing(
        Policy(),
        {"settlement_options": [{"option_id": option_id}]},
        expiration_unix=1_800_000_000,
        prefer_payment=True,
    )

    assert selection is not None
    assert selection.mechanism == MECHANISM_ID
    assert selection.option_id == option_id
    assert selection.params == {"payer_account": account}
