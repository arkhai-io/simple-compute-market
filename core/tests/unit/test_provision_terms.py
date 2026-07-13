from __future__ import annotations

import pytest
from pydantic import ValidationError

from market_core.schemas import ProvisionTerms


def test_provision_terms_are_a_versioned_opaque_envelope():
    terms = ProvisionTerms(
        kind="fiat",
        version=2,
        payload={"invoice_id": "inv-1"},
    )

    assert terms.model_dump() == {
        "kind": "fiat",
        "version": 2,
        "payload": {"invoice_id": "inv-1"},
    }
    assert not hasattr(terms, "duration_seconds")
    assert not hasattr(terms, "ssh_public_key")
    assert not hasattr(terms, "compute_resource")


@pytest.mark.parametrize(
    "payload",
    [
        {"kind": "fiat", "payload": {"invoice_id": "inv-1"}},
        {"version": 1, "payload": {"invoice_id": "inv-1"}},
        {"kind": "fiat", "version": 0, "payload": {}},
    ],
)
def test_kind_and_positive_version_are_required(payload):
    with pytest.raises(ValidationError):
        ProvisionTerms.model_validate(payload)


def test_legacy_flat_compute_shape_is_rejected():
    with pytest.raises(ValidationError, match="duration_seconds"):
        ProvisionTerms.model_validate({
            "duration_seconds": 7200,
            "ssh_public_key": "",
            "compute_resource": None,
        })


def test_transitional_schema_terms_keys_are_rejected():
    with pytest.raises(ValidationError, match="schema"):
        ProvisionTerms.model_validate({
            "schema": "fiat.v1",
            "terms": {"invoice_id": "inv-2"},
        })


def test_unknown_envelope_fields_are_rejected():
    with pytest.raises(ValidationError, match="unexpected"):
        ProvisionTerms(
            kind="fiat",
            version=1,
            payload={},
            unexpected=True,
        )
