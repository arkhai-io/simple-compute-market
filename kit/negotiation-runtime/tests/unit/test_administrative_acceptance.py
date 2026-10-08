from __future__ import annotations

import pytest
from market_identity import Ed25519Signer
from market_negotiation_runtime import NegotiationStateError

from test_runtime import _BUYER, _SELLER, HookHarness, RecordingRepository, runtime_for

_ADMIN = Ed25519Signer(b"\x31" * 32).identity


async def _opened(repository: RecordingRepository, harness: HookHarness):
    runtime = runtime_for(repository, harness)
    await runtime.start(
        repository=repository,
        listing_id="listing-1",
        buyer_principal=_BUYER,
        seller_principal=_SELLER,
        actor_principal=_BUYER,
        proposal={"price": 10},
        terms={"units": 7},
        seller_agent_url="https://seller.example",
        buyer_agent_url="https://buyer.example",
    )
    repository.effects.clear()
    return runtime


@pytest.mark.asyncio
async def test_administrative_acceptance_runs_the_domain_acceptance_hooks() -> None:
    repository = RecordingRepository()
    harness = HookHarness()
    runtime = await _opened(repository, harness)

    response = await runtime.accept_administratively(
        repository=repository,
        listing_id="listing-1",
        negotiation_id="neg-fixed",
        amount=13,
        actor_principal=_ADMIN,
    )

    assert response["action"] == "accept"
    assert response["amount"] == 13
    assert response["source"] == "admin_force_accept"
    assert response["accepted_artifact"]["amount"] == 13
    assert response["accepted_artifact"]["terms"] == {"units": 7}
    assert repository.agreements[-1]["agreed_price"] == 13
    assert repository.threads["neg-fixed"]["terminal_state"] == "success"
    assert [effect[0] for effect in repository.effects] == ["hold", "artifacts"]
    accepted = repository.messages["neg-fixed"][-1]
    assert accepted["sender_role"] == "admin"
    assert accepted["sender_principal"] == _ADMIN.model_dump(mode="json")
    assert accepted["message_type"] == "accepted"
    assert harness.events[-1][1] == "force_accepted"


@pytest.mark.asyncio
async def test_administrative_acceptance_refuses_a_terminal_negotiation() -> None:
    repository = RecordingRepository()
    runtime = await _opened(repository, HookHarness())
    await runtime.accept_administratively(
        repository=repository,
        listing_id="listing-1",
        negotiation_id="neg-fixed",
        amount=13,
        actor_principal=_ADMIN,
    )

    with pytest.raises(NegotiationStateError, match="terminal"):
        await runtime.accept_administratively(
            repository=repository,
            listing_id="listing-1",
            negotiation_id="neg-fixed",
            amount=13,
            actor_principal=_ADMIN,
        )


@pytest.mark.asyncio
async def test_administrative_acceptance_refuses_another_listing() -> None:
    repository = RecordingRepository()
    runtime = await _opened(repository, HookHarness())

    with pytest.raises(NegotiationStateError, match="does not belong"):
        await runtime.accept_administratively(
            repository=repository,
            listing_id="listing-2",
            negotiation_id="neg-fixed",
            amount=13,
            actor_principal=_ADMIN,
        )
    assert repository.effects == []


@pytest.mark.asyncio
async def test_administrative_acceptance_refuses_a_recorded_binding_mismatch() -> None:
    repository = RecordingRepository()
    runtime = await _opened(repository, HookHarness())
    repository.threads["neg-fixed"]["binding"] = "mismatch"

    with pytest.raises(NegotiationStateError, match="binding mismatch"):
        await runtime.accept_administratively(
            repository=repository,
            listing_id="listing-1",
            negotiation_id="neg-fixed",
            amount=13,
            actor_principal=_ADMIN,
        )
    assert repository.effects == []
    assert repository.threads["neg-fixed"]["terminal_state"] is None
