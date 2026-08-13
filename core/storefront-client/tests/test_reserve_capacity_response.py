"""`ReserveCapacityResponse` parsing: absent placement identity stays absent.

`pool_id` and `resource_id` echo whichever the storefront's own claim pinned. A
claim that pinned neither yields neither, and the distinction between "absent"
and "empty string" is load-bearing: a caller checking truthiness sees the same
thing either way, but a caller comparing against a real identifier does not, and
`""` reads as a resource that exists and has no name.

Both the sync and async clients construct this through the same `from_dict`, so
this covers the parsing contract for both.
"""

from __future__ import annotations

from storefront_client.models import ReserveCapacityResponse


class TestPlacementIdentityParsing:
    def test_a_resource_pinned_claim_reports_its_resource_and_no_pool(self) -> None:
        parsed = ReserveCapacityResponse.from_dict({
            "capacity_reservation_id": "cap-1",
            "resource_id": "pool-h200-1",
            "gpu_count": 2,
        })

        assert parsed.resource_id == "pool-h200-1"
        assert parsed.pool_id is None

    def test_a_pool_scoped_claim_reports_its_pool_and_no_resource(self) -> None:
        parsed = ReserveCapacityResponse.from_dict({
            "capacity_reservation_id": "cap-2",
            "pool_id": "pool-h200",
            "gpu_count": 2,
        })

        assert parsed.pool_id == "pool-h200"
        assert parsed.resource_id is None

    def test_neither_pinned_reports_neither_as_absent_not_empty(self) -> None:
        parsed = ReserveCapacityResponse.from_dict({
            "capacity_reservation_id": "cap-3",
            "gpu_count": 1,
        })

        assert parsed.resource_id is None
        assert parsed.pool_id is None

    def test_an_explicit_null_is_absent_rather_than_the_string_none(self) -> None:
        """A JSON `null` must not become the three-character string "None".

        The same conversion mistake this field's own history records: a
        `str(...)` around a missing value produces a plausible-looking
        identifier that matches nothing.
        """
        parsed = ReserveCapacityResponse.from_dict({
            "capacity_reservation_id": "cap-4",
            "resource_id": None,
            "pool_id": None,
            "gpu_count": 1,
        })

        assert parsed.resource_id is None
        assert parsed.pool_id is None
