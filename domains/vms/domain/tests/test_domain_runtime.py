from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

pytest.importorskip("market_core")

from arkhai_vms import (  # noqa: E402
    VM_PROVISION_KIND,
    VmListing,
    VmMaterialization,
    VmMessage,
    VmReceipt,
    VmResult,
    VmTerms,
)
from arkhai_vms.domain_runtime import market_domain  # noqa: E402
from market_core import (  # noqa: E402
    DomainCapability,
    DomainCodecExample,
    DomainConformanceCase,
    assert_domain_conformance,
)


def test_storefront_runtime_normalizes_vm_schema_slots() -> None:
    runtime = market_domain()
    lease_end = datetime.now(UTC) + timedelta(hours=1)

    listing = runtime.codecs.listing({
        "gpu_model": "H200",
        "gpu_count": 1,
        "sla": 0.99,
        "region": "California, US",
    })
    message = runtime.codecs.message({
        "duration_seconds": 3600,
        "ssh_public_key": "ssh-ed25519 AAAA test",
    })
    terms = runtime.codecs.terms({
        "duration_seconds": 3600,
        "ssh_public_key": "ssh-ed25519 AAAA test",
    })
    materialization = runtime.codecs.materialization({
        "escrow_uid": "escrow-1",
        "duration_seconds": 3600,
        "ssh_public_key": "ssh-ed25519 AAAA test",
        "lease_end_utc": lease_end,
    })
    receipt = runtime.codecs.receipt({
        "status": "leased",
        "vm_name": "vm-1",
    })
    result = runtime.codecs.result({
        "action": "vm_create",
        "vm_name": "vm-1",
    })

    assert runtime.identity == VM_PROVISION_KIND
    assert isinstance(listing, VmListing)
    assert isinstance(message, VmMessage)
    assert isinstance(terms, VmTerms)
    assert isinstance(materialization, VmMaterialization)
    assert isinstance(receipt, VmReceipt)
    assert isinstance(result, VmResult)

    assert_domain_conformance(
        DomainConformanceCase(
            contract=runtime,
            listing=DomainCodecExample(listing, listing),
            message=DomainCodecExample(message, message),
            terms=DomainCodecExample(terms, terms),
            materialization=DomainCodecExample(
                materialization,
                materialization,
            ),
            receipt=DomainCodecExample(receipt, receipt),
            result=DomainCodecExample(result, result),
            capabilities=frozenset({DomainCapability.PUBLICATION}),
        )
    )


def test_storefront_runtime_surfaces_vm_validation_errors() -> None:
    runtime = market_domain()

    with pytest.raises(ValidationError, match="duration_seconds"):
        runtime.codecs.message({
            "duration_seconds": "not-an-int",
        })
