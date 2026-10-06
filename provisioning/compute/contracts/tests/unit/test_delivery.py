"""The family's delivery evidence and access delivery."""

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from compute_provisioning_contracts import (
    AccessDelivery,
    AccessEndpoint,
    DeliveredCredential,
    DeliveryEvidence,
)

_READY = datetime(2026, 10, 6, 12, 0, tzinfo=timezone.utc)
_ENDPOINT = {"protocol": "ssh", "host": "203.0.113.7", "port": 2201, "user": "tenant-a"}


def test_evidence_carries_an_endpoint_and_when_access_became_ready():
    evidence = DeliveryEvidence.model_validate(
        {"endpoints": [_ENDPOINT], "ready_at": _READY.isoformat()}
    )

    assert evidence.endpoints == (AccessEndpoint(**_ENDPOINT),)
    assert evidence.ready_at == _READY


@pytest.mark.parametrize(
    "payload",
    [
        {"endpoints": [], "ready_at": _READY.isoformat()},
        {"endpoints": [_ENDPOINT]},
        {"endpoints": [_ENDPOINT], "ready_at": "2026-10-06T12:00:00"},
        {"endpoints": [{**_ENDPOINT, "port": 0}], "ready_at": _READY.isoformat()},
        {"endpoints": [{**_ENDPOINT, "host": ""}], "ready_at": _READY.isoformat()},
        {"endpoints": [_ENDPOINT], "ready_at": _READY.isoformat(), "vm_ip_internal": "10.0.0.2"},
    ],
    ids=["no-endpoint", "no-ready-at", "naive-ready-at", "no-port", "empty-host", "extra-field"],
)
def test_evidence_that_says_nothing_usable_is_refused(payload):
    with pytest.raises(ValidationError):
        DeliveryEvidence.model_validate(payload)


def test_a_credential_outside_the_allowlist_cannot_be_built():
    with pytest.raises(ValidationError):
        DeliveredCredential(role="tenant", password="p", ssh_key_path_host="/keys/vm-a")


def test_a_delivery_carries_no_resource_list_or_lease_window():
    delivery = AccessDelivery(
        endpoints=(AccessEndpoint(**_ENDPOINT),),
        credentials=(DeliveredCredential(role="tenant", password="p"),),
        ready_at=_READY,
    )

    assert set(delivery.model_dump()) == {"endpoints", "credentials", "ready_at"}
    with pytest.raises(ValidationError):
        AccessDelivery.model_validate(
            {**delivery.model_dump(mode="json"), "lease_end_utc": _READY.isoformat()}
        )


def test_a_create_result_carries_evidence_or_none_and_a_detail():
    from compute_provisioning_contracts import CreateJobResult

    with_evidence = CreateJobResult.model_validate({
        "evidence": {"endpoints": [_ENDPOINT], "ready_at": _READY.isoformat()},
        "detail": {"vm_name": "guest-1"},
    })
    without = CreateJobResult(evidence=None, detail={"host": "10.0.0.5"})

    assert with_evidence.evidence.endpoints[0].host == "203.0.113.7"
    assert without.evidence is None
    with pytest.raises(ValidationError):
        CreateJobResult.model_validate({"detail": {}, "raw": "output"})
