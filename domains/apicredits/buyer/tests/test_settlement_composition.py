from domains.apicredits.buyer.settlement_composition import buyer_settlement_registry


def test_buyer_registry_installs_alkahest() -> None:
    assert {item.mechanism_id for item in buyer_settlement_registry().registrations} == {
        "alkahest.v1",
    }
