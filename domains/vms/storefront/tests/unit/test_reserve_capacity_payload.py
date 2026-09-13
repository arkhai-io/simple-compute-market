"""A reservation payload missing a required field says which, and from where.

`reserve_capacity` subscripted `resource_id` on the site authority's payload
two lines after the sibling stage event read the same payload with `.get`. When
the key was absent the `KeyError` reached the caller as
`500 Storefront administrator request failed` -- naming neither the field nor
the authority, and costing several rounds to trace back to one subscript.

The fungible pool reservations surfaced it. Per
`openspec/specs/storefront-publication/spec.md` a `specific_resource` pool
publishes one resource-keyed candidate per member while a `fungible` pool
publishes one pooled candidate, so a fungible *listing* has no resource of its
own. Whether a fungible *reservation* reports one is a contract question, and
this error is meant to expose it rather than hide it behind a 500.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

# `server` first: it and `admin_controller` import each other, and importing
# the controller from a cold interpreter hits that cycle part-way.
from market_storefront import server  # noqa: F401
from market_storefront.controllers.admin_controller import (
    require_reservation_fields,
)

_COMPLETE = {
    "capacity_reservation_id": "cap-1",
    "resource_id": "compute-node-1",
    "member_id": None,
    "pool_id": None,
    "state": "available",
    "allocated_gpu_count": 2,
}


class TestACompletePayloadIsAccepted:
    def test_a_payload_with_both_fields_passes(self):
        require_reservation_fields(_COMPLETE, site_id="default")

    def test_present_but_none_is_not_missing(self):
        """Absent and null are different answers and must stay so.

        A null value is the authority answering; an absent key is the two sides
        disagreeing about the payload's shape. Collapsing them would turn a
        contract question into a silent default.
        """
        require_reservation_fields(
            {**_COMPLETE, "member_id": None}, site_id="default"
        )


class TestPhysicalIdentityIsNotRequired:
    """The capacity boundary strips it, so requiring it asks for the impossible.

    `kit/site`'s reserve route removes `resource_id`, `backing_resource_id`,
    `capacity_bucket_id` and `vm_host` from every reservation response: which
    physical resource backs a reservation is the provisioning service's fact,
    not a commercial one. This response required `resource_id` from before that
    strip, so it was unsatisfiable for every reservation rather than only for
    pooled ones -- and the `KeyError` surfaced as a 500 naming a column.
    """

    def test_a_payload_without_any_physical_identity_is_accepted(self):
        stripped = {
            k: v
            for k, v in _COMPLETE.items()
            if k not in {"resource_id", "backing_resource_id", "vm_host"}
        }
        require_reservation_fields(stripped, site_id="default")

    def test_resource_id_is_not_among_the_required_fields(self):
        from market_storefront.controllers.admin_controller import (
            _REQUIRED_RESERVATION_FIELDS,
        )

        assert "resource_id" not in _REQUIRED_RESERVATION_FIELDS, (
            "requiring a field the boundary strips reintroduces a failure no "
            "authority can avoid"
        )


class TestAMissingFieldIsNamed:
    @pytest.mark.parametrize("absent", ["capacity_reservation_id"])
    def test_the_message_names_the_field_and_the_authority(self, absent):
        payload = {k: v for k, v in _COMPLETE.items() if k != absent}

        with pytest.raises(HTTPException) as raised:
            require_reservation_fields(payload, site_id="site-a")

        detail = str(raised.value.detail)
        assert absent in detail, (
            "a caller cannot act on a failure that does not name the field"
        )
        assert "site-a" in detail, "which authority returned it is half the answer"
        assert "member_id" in detail, (
            "the keys the payload did carry are what identify the shape "
            "mismatch; without them the reader is back to guessing"
        )
        assert raised.value.status_code == 502, (
            "the authority returned a payload this storefront cannot use, "
            "which is a bad gateway rather than this service faulting"
        )

    def test_every_missing_field_is_reported_together(self):
        """One round trip per diagnosis, not one per field."""
        with pytest.raises(HTTPException) as raised:
            require_reservation_fields({"state": "available"}, site_id="default")
        detail = str(raised.value.detail)
        for field in ("capacity_reservation_id",):
            assert field in detail
