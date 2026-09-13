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

        A null `resource_id` is the authority saying "this reservation has no
        single backing resource"; an absent key is the two sides disagreeing
        about the payload's shape. Collapsing them would turn a contract
        question into a silent empty string.
        """
        require_reservation_fields(
            {**_COMPLETE, "resource_id": None}, site_id="default"
        )


class TestAMissingFieldIsNamed:
    @pytest.mark.parametrize("absent", ["resource_id", "capacity_reservation_id"])
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

    def test_both_missing_are_reported_together(self):
        """One round trip per diagnosis, not one per field."""
        with pytest.raises(HTTPException) as raised:
            require_reservation_fields({"state": "available"}, site_id="default")
        detail = str(raised.value.detail)
        assert "capacity_reservation_id" in detail and "resource_id" in detail
