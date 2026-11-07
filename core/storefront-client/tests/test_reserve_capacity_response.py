"""The admin reserve response reads a GPU count only when one was reserved."""

from __future__ import annotations

import pytest

from storefront_client.models import ReserveCapacityResponse


def test_a_reserved_gpu_count_is_read():
    response = ReserveCapacityResponse.from_dict(
        {"capacity_reservation_id": "r-1", "gpu_count": 2}
    )

    assert response.gpu_count == 2


@pytest.mark.parametrize("body", [{}, {"gpu_count": None}], ids=["absent", "null"])
def test_a_reservation_allocating_no_gpus_has_no_count(body):
    response = ReserveCapacityResponse.from_dict({"capacity_reservation_id": "r-1", **body})

    assert response.gpu_count is None
    assert "gpu_count" not in response.extra
