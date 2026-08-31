from core_storefront.models.listing_models import CreateListingRequest


def test_create_listing_request_keeps_settlement_config_schema_opaque() -> None:
    payload = {"mechanism_payload": {"arbitrary": ["shape"]}}

    request = CreateListingRequest(offer={}, settlement_config=payload)

    assert request.settlement_config == payload
