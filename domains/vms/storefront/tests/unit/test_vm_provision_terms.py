"""VM-domain interpretation of the compute.v1 provision payload.

The core carrier (``market_core.schemas.ProvisionTerms``) is an opaque
``{kind, payload}`` envelope; these are the domain accessors that
interpret it, used by the storefront on wire-received terms.
"""

from __future__ import annotations

from domains.vms.provisioning import (
    make_vm_provision_terms,
    provision_compute_resource,
    provision_duration_seconds,
    provision_payload,
    provision_ssh_public_key,
)
from market_core.schemas import ProvisionTerms


def test_accessors_read_a_core_envelope():
    terms = ProvisionTerms.model_validate({
        "kind": "compute.v1",
        "payload": {
            "duration_seconds": 3600,
            "ssh_public_key": "ssh-ed25519 AAAA",
            "compute_resource": {"gpu_model": "H200"},
        },
    })

    assert provision_duration_seconds(terms) == 3600
    assert provision_ssh_public_key(terms) == "ssh-ed25519 AAAA"
    assert provision_compute_resource(terms) == {"gpu_model": "H200"}


def test_accessors_read_a_plain_dict():
    raw = {"payload": {"duration_seconds": "7200"}}

    assert provision_payload(raw) == {"duration_seconds": "7200"}
    assert provision_duration_seconds(raw) == 7200
    assert provision_ssh_public_key(raw) == ""
    assert provision_compute_resource(raw) is None


def test_accessors_tolerate_missing_or_foreign_payloads():
    foreign = ProvisionTerms(kind="fiat.v1", payload={"invoice_id": "inv-1"})

    assert provision_duration_seconds(foreign) is None
    assert provision_ssh_public_key(foreign) == ""
    assert provision_compute_resource(foreign) is None
    assert provision_payload(None) == {}


def test_make_vm_provision_terms_matches_the_wire_shape():
    terms = make_vm_provision_terms(
        duration_seconds=3600,
        ssh_public_key="ssh-ed25519 AAAA",
        compute_resource={"gpu_model": "H200"},
    )

    assert terms.model_dump() == {
        "kind": "compute.v1",
        "payload": {
            "duration_seconds": 3600,
            "ssh_public_key": "ssh-ed25519 AAAA",
            "compute_resource": {"gpu_model": "H200"},
        },
    }
    # Properties mirror the module accessors for domain-constructed terms.
    assert terms.duration_seconds == 3600
    assert terms.ssh_public_key == "ssh-ed25519 AAAA"
    assert terms.compute_resource == {"gpu_model": "H200"}


def test_make_vm_provision_terms_omits_absent_compute_resource():
    terms = make_vm_provision_terms(duration_seconds=60, ssh_public_key="k")

    assert terms.model_dump() == {
        "kind": "compute.v1",
        "payload": {"duration_seconds": 60, "ssh_public_key": "k"},
    }
