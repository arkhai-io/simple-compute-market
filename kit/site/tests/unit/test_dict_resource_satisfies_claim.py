"""dict_resource_satisfies_claim: the injectable exact ClaimMatcher for
callers outside kit/site (core/storefront's aggregator injects this for
domains whose backing site needs exact claim semantics, not just the
coarse pool/resource/dimensions check the aggregator defaults to).

The property under test throughout is equivalence: given data describing
the same resource, the plain-dict adapter and the live-object admission
path (resource_feasibility_view + resource_satisfies_requirement) must
agree, because dict_resource_satisfies_claim does no independent
interpretation of the claim or the row -- it only reconstructs a
ResourceFeasibilityView and delegates.
"""

from __future__ import annotations

import pytest

from market_site.ledger import (
    dict_resource_satisfies_claim,
    resource_feasibility_view,
    resource_satisfies_requirement,
)


def _row(**overrides):
    row = {
        "resource_id": "r1",
        "pool_id": "gpu-pool",
        "resource_type": "compute.gpu",
        "resource_subtype": None,
        "available_units": 4,
        "value": 4,
        "available": {"gpu_count": 4, "ram_gb": 128},
        "attributes": {"region": "eu-west", "gpu_model": "A100"},
    }
    row.update(overrides)
    return row


def _authoritative_result(row, claim):
    """The admission-path result for the same data, built the same way
    ledger.py's own call sites build a ResourceFeasibilityView."""
    from market_site.ledger import _requested_dimensions, _split_claim_requirement

    resource_kind, required_attributes = _split_claim_requirement(claim)
    required_dimensions = _requested_dimensions(claim)
    resource = resource_feasibility_view(
        resource_id=row["resource_id"],
        pool_id=row["pool_id"],
        resource_kind=row["resource_type"],
        available=row["available"],
        attributes=row["attributes"],
        resource_subtype=row.get("resource_subtype"),
        value=row.get("value"),
        units=row.get("available_units"),
    )
    return resource_satisfies_requirement(
        resource=resource,
        required_resource_kind=resource_kind,
        required_dimensions=required_dimensions,
        required_attributes=required_attributes,
    )


@pytest.mark.parametrize(
    "claim",
    [
        {},
        {"pool_id": "gpu-pool"},
        {"pool_id": "wrong-pool"},
        {"resource_type": "compute.gpu"},
        {"resource_type": "compute.cpu"},
        {"region": "eu-west"},
        {"region": "us-east"},
        {"gpu_model": "A100"},
        {"gpu_model": "L40"},
        {"pool_id": "gpu-pool", "region": "eu-west", "gpu_model": "A100"},
        {"pool_id": "gpu-pool", "region": "eu-west", "gpu_model": "L40"},
        {"dimensions": {"gpu_count": 2}},
        {"dimensions": {"gpu_count": 2, "ram_gb": 64}},
        {"dimensions": {"gpu_count": 2, "ram_gb": 256}},
        {"units": 2},
        {"units": 10},
        {"resource_id": "r1"},
        {"resource_id": "r2"},
    ],
)
def test_dict_adapter_matches_authoritative_result_for_equivalent_data(claim):
    row = _row()
    assert dict_resource_satisfies_claim(row, claim) == _authoritative_result(row, claim)


def test_missing_projected_attribute_fails_closed_not_unconstrained():
    """A row that doesn't expose an attribute the claim names must not
    match -- reading a missing key returns None, which is only equal to
    the required value if the claim itself requires None."""
    row = _row(attributes={"region": "eu-west"})  # no gpu_model key at all
    assert dict_resource_satisfies_claim(row, {"gpu_model": "A100"}) is False


def test_malformed_dimensions_raises_same_as_admission():
    """Strict by design: an injected exact matcher raises on a malformed
    claim exactly as the ledger's own admission path does, rather than
    silently treating it as unconstrained. Callers are expected to
    validate claims before they reach ranking or admission -- the coarse
    default matcher may remain more permissive, but this one must not
    diverge from what reserve()/probe() would do with the same claim."""
    row = _row()
    with pytest.raises(ValueError):
        dict_resource_satisfies_claim(row, {"dimensions": {}})
    with pytest.raises(ValueError):
        dict_resource_satisfies_claim(row, {"dimensions": "not-a-mapping"})


def test_no_claim_matches_everything():
    assert dict_resource_satisfies_claim(_row(), None) is True
    assert dict_resource_satisfies_claim(_row(), {}) is True


def test_unit_claim_keys_must_match_the_backing_ledger_service_configuration():
    """VM's CapacityLedgerService is composed with
    unit_claim_keys=("units", "gpu_count") in container.py -- the
    adapter must accept the same override so its legacy-claim fallback
    agrees with what that specific domain's admission path accepts,
    not just the module-wide default of ("units",)."""
    row = _row(available_units=3)
    # Bare "gpu_count" is not a recognized legacy unit key under the
    # module default -- falls through as an (unmatched) attribute
    # requirement instead of a quantity check.
    assert dict_resource_satisfies_claim(row, {"gpu_count": 2}) is False
    # With VM's actual configured unit_claim_keys, it's a quantity check.
    assert dict_resource_satisfies_claim(
        row, {"gpu_count": 2}, unit_claim_keys=("units", "gpu_count"),
    ) is True
    assert dict_resource_satisfies_claim(
        row, {"gpu_count": 5}, unit_claim_keys=("units", "gpu_count"),
    ) is False
