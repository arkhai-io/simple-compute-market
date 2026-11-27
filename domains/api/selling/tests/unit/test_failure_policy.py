"""The failure actions dispatch in configured order through the storefront's collaborators."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

from arkhai_api_selling.failure_policy import DEFAULT_FAILURE_ACTIONS, build_failure_policy


class _Repository:
    """A storefront repository holding one listing's durable binding and no accepted thread."""

    async def load_listing_binding(self, *, listing_id):
        return SimpleNamespace(
            physical_resource_id="quota-a",
            capacity_backing="backed",
            site_id="quota",
            pool_id="default",
            binding=SimpleNamespace(offering_mode="example"),
        )

    async def load_negotiation_thread_row(self, *, negotiation_id):
        return None


def _policy(*, actions, capacity=None, reopen=None, webhook=("", 5.0), stages=None, events=None):
    return build_failure_policy(
        actions_provider=lambda: actions,
        capacity_runtime=lambda _db: capacity,
        reopen_listings=reopen or AsyncMock(return_value=[]),
        webhook_target=lambda: webhook,
        stages=stages or {},
        composition=lambda: "composition",
        stage_event=lambda stage, event, **fields: (events if events is not None else []).append((stage, event, fields)),
    )


def _context():
    return {
        "capacity_reservation_id": "alloc-1",
        "settlement_ref": "ref-1",
        "negotiation_id": "neg-1",
        "listing_id": "L-1",
        "resource_id": "quota-a",
        "reason": "quota_exhausted",
        "message": "no units",
        "state": None,
        "reopened_listing_ids": [],
    }


async def test_release_then_event_releases_by_negotiation_and_reopens_what_returned():
    capacity = SimpleNamespace(
        release=AsyncMock(return_value={"capacity_reservation_id": "alloc-1", "resource_id": "quota-a"}),
        availability=AsyncMock(return_value={("quota", "quota-a"): 9}),
    )
    reopen = AsyncMock(return_value=["L-1"])
    events = []

    result = await _policy(
        actions=DEFAULT_FAILURE_ACTIONS, capacity=capacity, reopen=reopen, events=events,
    ).apply(_Repository(), _context())

    assert [action["status"] for action in result.actions] == ["succeeded", "succeeded"]
    release = capacity.release.await_args.kwargs
    assert release["deal_ref"] == {"negotiation_id": "neg-1"}
    assert release["failure_reason"] == "quota_exhausted"
    reopen.assert_awaited_once()
    assert result.actions[0]["reopened_listing_ids"] == ["L-1"]
    # Each action reads the context it was applied with, not another action's edits.
    ((stage, event, fields),) = events
    assert (stage, event, fields["negotiation_id"], fields["state"]) == ("fulfillment", "failed", "neg-1", None)


async def test_an_unconfigured_webhook_is_skipped():
    result = await _policy(actions=("webhook",)).apply(_Repository(), _context())
    assert result.actions[0]["reason"] == "webhook_url_empty"


async def test_a_refund_without_an_accepted_agreement_is_skipped():
    stage = SimpleNamespace(refund_before_delivery=AsyncMock())
    result = await _policy(actions=("refund",), stages={"opaque.future.v1": stage}).apply(
        _Repository(), _context()
    )
    assert result.actions[0]["reason"] == "accepted_agreement_unavailable"
    stage.refund_before_delivery.assert_not_awaited()
