from __future__ import annotations

import pytest

from market_storefront.domain_runtime import build_vm_storefront_domain
from market_storefront.negotiation_runtime import _decode_vm_revised_terms, _decode_vm_terms


_DOMAIN = build_vm_storefront_domain()


def _opening():
    return _decode_vm_terms(_DOMAIN, {
        "kind": "compute.v1", "version": 1,
        "payload": {
            "duration_seconds": 3600,
            "ssh_public_key": "ssh-ed25519 public-development-fixture",
            "start_utc": "2026-11-06T12:00:00Z",
            "compute_resource": {"gpu_count": 2, "gpu_model": "H100"},
        },
    })


def test_a_revision_decodes_a_grouped_shape_without_changing_delivery_terms():
    terms = _decode_vm_revised_terms(_DOMAIN, _opening(), {
        "kind": "compute.v1", "version": 1,
        "payload": {"cpu": {"count": 8}, "memory": {"gib": 32}},
    })
    assert terms.decoded.compute_resource == {"vcpu_count": 8, "ram_gb": 32}
    assert terms.decoded.ssh_public_key == "ssh-ed25519 public-development-fixture"
    assert terms.requested_duration_seconds == 3600
    assert terms.requested_start_utc == "2026-11-06T12:00:00Z"
    assert _decode_vm_terms(_DOMAIN, terms.wire) == terms


@pytest.mark.parametrize("payload", [
    {"cpu": {"count": 0}},
    {"gpu": {"count": 1}},
    {"memory": {"gib": 32, "free_extra": 100}},
    {"cpu": {"count": 8}, "ssh_public_key": "replacement"},
])
def test_an_unreadable_or_unpriced_revision_is_refused(payload):
    with pytest.raises(ValueError):
        _decode_vm_revised_terms(_DOMAIN, _opening(), {
            "kind": "compute.v1", "version": 1, "payload": payload,
        })
