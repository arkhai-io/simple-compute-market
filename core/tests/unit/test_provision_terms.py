from __future__ import annotations

from market_core.schemas import COMPUTE_PROVISION_KIND, ProvisionTerms


def test_compute_provision_terms_dump_as_opaque_payload():
    terms = ProvisionTerms(
        duration_seconds=3600,
        ssh_public_key="ssh-ed25519 AAAA",
        compute_resource={"gpu_model": "H200"},
    )

    assert terms.kind == COMPUTE_PROVISION_KIND
    assert terms.duration_seconds == 3600
    assert terms.ssh_public_key == "ssh-ed25519 AAAA"
    assert terms.compute_resource == {"gpu_model": "H200"}
    assert terms.model_dump() == {
        "kind": "compute.v1",
        "payload": {
            "duration_seconds": 3600,
            "ssh_public_key": "ssh-ed25519 AAAA",
            "compute_resource": {"gpu_model": "H200"},
        },
    }


def test_compute_provision_terms_parse_legacy_flat_shape():
    terms = ProvisionTerms.model_validate({
        "duration_seconds": "7200",
        "ssh_public_key": "",
        "compute_resource": None,
    })

    assert terms.kind == "compute.v1"
    assert terms.duration_seconds == 7200
    assert terms.ssh_public_key == ""
    assert terms.compute_resource is None
    assert terms.model_dump() == {
        "kind": "compute.v1",
        "payload": {
            "duration_seconds": 7200,
            "ssh_public_key": "",
            "compute_resource": None,
        },
    }


def test_provision_terms_do_not_enforce_compute_duration_policy():
    terms = ProvisionTerms(duration_seconds=0, ssh_public_key="")

    assert terms.kind == "compute.v1"
    assert terms.duration_seconds == 0
    assert terms.model_dump() == {
        "kind": "compute.v1",
        "payload": {
            "duration_seconds": 0,
            "ssh_public_key": "",
        },
    }


def test_non_compute_provision_terms_are_opaque():
    terms = ProvisionTerms(kind="fiat.v1", payload={"invoice_id": "inv-1"})

    assert terms.kind == "fiat.v1"
    assert terms.payload == {"invoice_id": "inv-1"}
    assert terms.duration_seconds is None
    assert terms.ssh_public_key == ""
