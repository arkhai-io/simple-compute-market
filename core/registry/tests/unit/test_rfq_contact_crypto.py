"""A contact ciphertext belongs to exactly one consent context."""

from dataclasses import replace
from datetime import datetime
import json

import pytest

from core_registry.rfq_contact_crypto import (
    PENDING_CONTACT,
    RESPONDENT_CONTACT,
    ContactBinding,
    RfqContactKeys,
    RfqContactUnavailable,
)


def test_ciphertext_cannot_move_between_purposes_records_or_parties():
    # Deterministic key fixture. Never use it on a public network.
    keys = RfqContactKeys.model_validate_json(json.dumps({
        "current": "fixture", "keys": {"fixture": "12" * 32},
    }))
    binding = ContactBinding(
        registry="registry-fixture", rfq_id="rfq-fixture", record_id="response-fixture",
        party_namespace="account-fixture", party_subject="subject-fixture",
        purpose=PENDING_CONTACT, expires_at=datetime(2030, 1, 1),
    )
    contact = {"email": "respondent@example.test"}
    one = keys.encrypt(contact, binding)
    two = keys.encrypt(contact, binding)
    assert one.nonce != two.nonce
    assert b"respondent@example.test" not in one.ciphertext
    assert keys.decrypt(one, binding) == contact

    for changed in (
        replace(binding, purpose=RESPONDENT_CONTACT),
        replace(binding, record_id="response-other"),
        replace(binding, registry="registry-other"),
        replace(binding, party_subject="subject-other"),
        replace(binding, expires_at=datetime(2030, 1, 2)),
    ):
        with pytest.raises(RfqContactUnavailable):
            keys.decrypt(one, changed)
    with pytest.raises(RfqContactUnavailable):
        keys.decrypt(replace(one, key_id="missing"), binding)
