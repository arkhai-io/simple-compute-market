from __future__ import annotations

import pytest
from pydantic import ValidationError

from market_core.schemas import ProvisionTerms


def test_provision_terms_are_an_opaque_envelope():
    terms = ProvisionTerms(kind="fiat.v1", payload={"invoice_id": "inv-1"})

    assert terms.kind == "fiat.v1"
    assert terms.payload == {"invoice_id": "inv-1"}
    assert terms.model_dump() == {
        "kind": "fiat.v1",
        "payload": {"invoice_id": "inv-1"},
    }
    # Core does not interpret the payload — no schema-specific accessors.
    assert not hasattr(terms, "duration_seconds")
    assert not hasattr(terms, "ssh_public_key")
    assert not hasattr(terms, "compute_resource")


def test_kind_is_required_for_envelope_construction():
    with pytest.raises(ValidationError):
        ProvisionTerms(payload={"invoice_id": "inv-1"})


def test_legacy_flat_compute_shape_normalizes_into_payload():
    # Old compute clients send a flat dict with no kind/payload envelope;
    # the carrier normalizes it and tags the legacy compute wire kind.
    terms = ProvisionTerms.model_validate({
        "duration_seconds": "7200",
        "ssh_public_key": "",
        "compute_resource": None,
    })

    assert terms.kind == "compute.v1"
    assert terms.model_dump() == {
        "kind": "compute.v1",
        "payload": {
            "duration_seconds": 7200,
            "ssh_public_key": "",
            "compute_resource": None,
        },
    }


def test_legacy_flat_shape_does_not_enforce_compute_duration_policy():
    terms = ProvisionTerms(duration_seconds=0, ssh_public_key="")

    assert terms.kind == "compute.v1"
    assert terms.model_dump() == {
        "kind": "compute.v1",
        "payload": {
            "duration_seconds": 0,
            "ssh_public_key": "",
        },
    }


def test_transitional_schema_terms_key_names_normalize():
    terms = ProvisionTerms.model_validate({
        "schema": "fiat.v1",
        "terms": {"invoice_id": "inv-2"},
    })

    assert terms.kind == "fiat.v1"
    assert terms.payload == {"invoice_id": "inv-2"}
