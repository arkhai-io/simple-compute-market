"""Shared Unicode and wire inputs for consumer conformance tests."""

from market_contact_exchange.delivery_contract import DELIVERY_POLICY

POLICY = DELIVERY_POLICY.model_dump(mode="json")
REVIEW = {
    "schema_version": 2,
    "negotiation_id": "synthetic-negotiation",
    "obligation_ref": "a" * 64,
    "finalization_id": "12345678-1234-4234-8234-123456789abc",
    "contact_payload": {"name😀": '  Synthetic É\\\n"😀  '},
    "delivery_route": {"kind": "email", "address": "Buyer+Route@Example.invalid"},
}
# Deliberately synthetic values; these must never be used on a public network.
DELIVERY_CONFIG = {
    "schema_version": 2,
    "mode": "two-sided-contact",
    "seller_route": {"kind": "email", "address": "seller-route@example.invalid"},
    "smtp": {
        "host": "smtp.example.invalid",
        "port": 587,
        "sender": "sender@example.invalid",
        "username": "synthetic-user",
        "password": "synthetic-password-never-live",
        "timeout_seconds": 10,
    },
}
