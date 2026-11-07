"""The runtime enforces a listing's source verdict on every path but exit."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest
from market_identity import Ed25519Signer
from market_negotiation_runtime import (
    NegotiationRuntime,
    NegotiationUnavailableError,
    OfferUnfulfillableError,
)
from market_policy import ListingSourceVerdict
from market_policy.negotiation_middleware import NegotiationDecision

from test_runtime import (
    _BUYER,
    _SELLER,
    HookHarness,
    RecordingRepository,
    _continue,
    _open,
    runtime_for,
)

_ADMIN = Ed25519Signer(b"\x31" * 32).identity

_REFUSING = [
    (ListingSourceVerdict("declared_mismatch"), OfferUnfulfillableError, "no_matching_declaration"),
    (ListingSourceVerdict("unavailable"), OfferUnfulfillableError, "no_matching_inventory"),
    (ListingSourceVerdict("unverifiable"), NegotiationUnavailableError, "listing_source_unverifiable"),
]


class SourceHarness(HookHarness):
    """A domain whose listings are checked against their source, and whose chain
    has no inventory guard: what the runtime refuses, it refuses itself."""

    def __init__(self) -> None:
        super().__init__()
        self.verdict = ListingSourceVerdict("matches")
        self.checks = 0

    async def check(self, _repository: Any, _resolved: Any) -> ListingSourceVerdict:
        self.checks += 1
        return self.verdict

    def hooks(self):
        return replace(super().hooks(), check_listing_source=self.check)


async def _opened() -> tuple[RecordingRepository, SourceHarness, NegotiationRuntime]:
    repository = RecordingRepository()
    harness = SourceHarness()
    runtime = runtime_for(repository, harness)
    await _open(runtime, repository)
    return repository, harness, runtime


def _writes(repository: RecordingRepository) -> tuple[int, int, int, Any]:
    return (
        sum(len(rows) for rows in repository.messages.values()),
        len(repository.agreements),
        len(repository.effects),
        {key: row["terminal_state"] for key, row in repository.threads.items()},
    )


@pytest.mark.asyncio
async def test_each_round_receives_its_verdict() -> None:
    repository, harness, runtime = await _opened()
    harness.verdict = ListingSourceVerdict("matches", "fresh")
    await _continue(runtime, repository, "counter", {"price": 14})

    assert [call.listing_source for call in harness.policy_calls] == [
        ListingSourceVerdict("matches"),
        ListingSourceVerdict("matches", "fresh"),
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(("verdict", "error", "reason"), _REFUSING)
async def test_an_opening_is_refused_before_any_write(verdict, error, reason) -> None:
    repository = RecordingRepository()
    harness = SourceHarness()
    harness.verdict = verdict
    runtime = runtime_for(repository, harness)

    with pytest.raises(error) as refused:
        await _open(runtime, repository)

    assert refused.value.reason == reason
    assert repository.threads == {}
    assert repository.effects == []


@pytest.mark.asyncio
@pytest.mark.parametrize(("verdict", "error", "reason"), _REFUSING)
async def test_a_preview_reports_the_refusal_and_writes_nothing(verdict, error, reason) -> None:
    repository = RecordingRepository()
    harness = SourceHarness()
    harness.verdict = verdict

    preview = await runtime_for(repository, harness).preview_opening(
        repository=repository,
        listing_id="listing-1",
        buyer_principal=_BUYER,
        seller_principal=_SELLER,
        proposal={"price": 10},
        terms={"units": 7},
    )

    assert preview.refused
    assert preview.refusal == f"{error.__name__}: {reason}"
    assert repository.threads == {}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("verdict", "reason"),
    [
        (ListingSourceVerdict("declared_mismatch"), "no_matching_declaration"),
        (ListingSourceVerdict("unavailable"), "no_matching_inventory"),
    ],
)
async def test_a_counter_on_a_refused_listing_is_recorded_as_a_rejection(verdict, reason) -> None:
    repository, harness, runtime = await _opened()
    harness.verdict = verdict

    response = await _continue(runtime, repository, "counter", {"price": 14})

    assert (response["action"], response["reason"]) == ("reject", reason)
    assert repository.threads["neg-fixed"]["terminal_state"] == "failure"


@pytest.mark.asyncio
async def test_a_counter_on_an_unverifiable_listing_writes_nothing() -> None:
    repository, harness, runtime = await _opened()
    harness.verdict = ListingSourceVerdict("unverifiable")
    before = _writes(repository)

    with pytest.raises(NegotiationUnavailableError):
        await _continue(runtime, repository, "counter", {"price": 14})

    assert _writes(repository) == before


@pytest.mark.asyncio
async def test_a_policy_rejection_keeps_its_own_reason() -> None:
    repository, harness, runtime = await _opened()
    harness.verdict = ListingSourceVerdict("unverifiable")
    harness.next_decision = NegotiationDecision(action="reject", reason="counter_missing_amount")

    response = await _continue(runtime, repository, "counter", {"price": 14})

    assert response["reason"] == "counter_missing_amount"


@pytest.mark.asyncio
@pytest.mark.parametrize(("verdict", "error", "reason"), _REFUSING)
async def test_a_buyer_accept_is_refused_before_any_write(verdict, error, reason) -> None:
    repository, harness, runtime = await _opened()
    harness.verdict = verdict
    before = _writes(repository)

    with pytest.raises(error) as refused:
        await _continue(runtime, repository, "accept")

    assert refused.value.reason == reason
    assert _writes(repository) == before


@pytest.mark.asyncio
@pytest.mark.parametrize(("verdict", "error", "reason"), _REFUSING)
async def test_a_force_accept_is_refused_before_any_write(verdict, error, reason) -> None:
    repository, harness, runtime = await _opened()
    harness.verdict = verdict
    before = _writes(repository)

    with pytest.raises(error) as refused:
        await runtime.accept_administratively(
            repository=repository,
            listing_id="listing-1",
            negotiation_id="neg-fixed",
            amount=13,
            actor_principal=_ADMIN,
        )

    assert refused.value.reason == reason
    assert _writes(repository) == before


@pytest.mark.asyncio
async def test_an_exit_never_checks_the_source() -> None:
    repository, harness, runtime = await _opened()
    harness.verdict = ListingSourceVerdict("unverifiable")
    checks = harness.checks

    response = await _continue(runtime, repository, "exit")

    assert response["action"] == "exit"
    assert harness.checks == checks


@pytest.mark.asyncio
async def test_a_domain_with_no_source_check_is_never_refused_for_its_source() -> None:
    repository = RecordingRepository()
    harness = HookHarness()
    runtime = runtime_for(repository, harness)
    await _open(runtime, repository)

    response = await _continue(runtime, repository, "accept")

    assert response["action"] == "accept"
    assert harness.policy_calls[0].listing_source is None
