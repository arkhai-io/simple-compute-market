"""The relist helper must decode what the buyer CLI actually emits.

Shapes here are produced by the real `ListingListResponse`/`ListingSummary`
models and serialized the way the CLI serializes them, rather than hand-written
to match the consumer. A flattened fixture would have hidden that the envelope
field is `listings` and that domain facts are nested under `offer`.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic_core import to_jsonable_python
from registry_client.models import ListingListResponse, ListingSummary

from tests.e2e.roles.scenarios.bare_metal.test_bare_metal_deal import (
    LeasedHost,
    _leased_host,
    _purchasable_offers,
)

LEASED = LeasedHost(machine_id="node-a", physical_host_id="host-a")


def _published(
    *,
    machine_id: str = "node-a",
    physical_host_id: str = "host-a",
    status: str = "open",
    settlement_options: list | None = None,
) -> ListingSummary:
    return ListingSummary(
        id="listing-1",
        status=status,
        storefront_url="https://seller.example/",
        offer={
            "kind": "bare_metal.v1",
            "virtualization_type": "bare_metal",
            "machine_id": machine_id,
            "physical_host_id": physical_host_id,
        },
        settlement_options=(
            [{"mechanism": "alkahest"}]
            if settlement_options is None
            else settlement_options
        ),
    )


class _Run:
    def __init__(self, payload: Any) -> None:
        self._payload = payload
        self.returncode = 0

    def stdout(self) -> str:
        import json

        return json.dumps(to_jsonable_python(self._payload))


class _Cli:
    def __init__(self, payload: Any) -> None:
        self._payload = payload
        self.calls: list[list[str]] = []

    def run(self, args, **kwargs):
        self.calls.append(list(args))
        return _Run(self._payload)


@pytest.fixture(autouse=True)
def _accept_any_run(monkeypatch):
    monkeypatch.setattr(
        "tests.e2e.roles.scenarios.bare_metal.test_bare_metal_deal"
        ".assert_market_run_succeeded",
        lambda run, command: None,
    )


def test_producer_envelope_is_decoded() -> None:
    cli = _Cli(ListingListResponse(listings=[_published()], total=1))

    assert _purchasable_offers(cli, LEASED)


def test_flattened_consumer_shape_is_not_what_the_producer_emits() -> None:
    """Guards the defect this test file exists for."""
    payload = to_jsonable_python(ListingListResponse(listings=[_published()]))

    assert "listings" in payload and "items" not in payload
    assert "machine_id" not in payload["listings"][0]
    assert payload["listings"][0]["offer"]["machine_id"] == "node-a"


def test_a_different_host_is_not_this_capacity() -> None:
    cli = _Cli(ListingListResponse(listings=[_published(machine_id="node-b")]))

    assert _purchasable_offers(cli, LEASED) == []


def test_identifier_fields_are_not_interchangeable() -> None:
    """Another seller's machine id may equal this host's physical id."""
    cli = _Cli(
        ListingListResponse(
            listings=[_published(machine_id="host-a", physical_host_id="host-z")]
        )
    )

    assert _purchasable_offers(cli, LEASED) == []


def test_a_closed_listing_is_not_purchasable() -> None:
    cli = _Cli(ListingListResponse(listings=[_published(status="closed")]))

    assert _purchasable_offers(cli, LEASED) == []


def test_a_listing_with_no_settlement_option_is_not_purchasable() -> None:
    cli = _Cli(ListingListResponse(listings=[_published(settlement_options=[])]))

    assert _purchasable_offers(cli, LEASED) == []


def test_a_partial_page_is_refused_rather_than_judged() -> None:
    cli = _Cli(ListingListResponse(listings=[_published()], total=500))

    with pytest.raises(AssertionError, match="partial page"):
        _purchasable_offers(cli, LEASED)


def test_pagination_limit_is_requested_explicitly() -> None:
    cli = _Cli(ListingListResponse(listings=[], total=0))

    _purchasable_offers(cli, LEASED)

    assert "--limit" in cli.calls[0]


def test_leased_host_requires_both_identity_fields() -> None:
    """Read out of the `result` envelope's receipt, which is where they live."""
    assert _leased_host(
        {"receipt": {"machine_id": "node-a", "physical_host_id": "host-a"}}
    ) == LEASED

    partials = (
        {"receipt": {"machine_id": "node-a"}},
        {"receipt": {"physical_host_id": "host-a"}},
        {"receipt": {}},
        {},
        # The flattened view an earlier caller assumed the command returned.
        {"machine_id": "node-a", "physical_host_id": "host-a"},
    )
    for partial in partials:
        with pytest.raises(AssertionError):
            _leased_host(partial)
