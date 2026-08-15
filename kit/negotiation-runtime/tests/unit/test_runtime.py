from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import pytest
from market_identity import Ed25519Signer, Identity
from market_negotiation_runtime import (
    Acceptance,
    AgreementTerms,
    NegotiationDomainHooks,
    NegotiationRuntime,
    NegotiationStateError,
    NegotiationTerms,
    ResolvedNegotiation,
    RoundEvaluation,
    RoundRequest,
)
from market_policy.negotiation_middleware import NegotiationDecision

_BUYER = Ed25519Signer(b"\x11" * 32).identity
_OTHER_BUYER = Ed25519Signer(b"\x12" * 32).identity
_SELLER = Ed25519Signer(b"\x21" * 32).identity


class RecordingRepository:
    def __init__(self) -> None:
        self.listings = {"listing-1": {"listing_id": "listing-1", "open": True}}
        self.threads: dict[str, dict[str, Any]] = {}
        self.messages: dict[str, list[dict[str, Any]]] = {}
        self.agreements: list[dict[str, Any]] = []
        self.effects: list[tuple[str, Any]] = []

    async def load_listing(self, *, listing_id: str) -> dict[str, Any] | None:
        return self.listings.get(listing_id)

    async def is_listing_paused(self, *, listing_id: str) -> bool:
        return False

    async def create_negotiation_thread(self, **values: Any) -> None:
        negotiation_id = values["negotiation_id"]
        self.threads[negotiation_id] = {
            **values,
            "negotiation_id": negotiation_id,
            "buyer_principal": values["buyer_principal"].model_dump(mode="json"),
            "seller_principal": values["seller_principal"].model_dump(mode="json"),
            "terminal_state": None,
        }
        self.messages[negotiation_id] = []

    async def save_negotiation_message(self, **values: Any) -> int:
        rows = self.messages[values["negotiation_id"]]
        round_number = len(rows)
        rows.append(
            {
                **values,
                "round": round_number,
                "sender_principal": values["sender_principal"].model_dump(
                    mode="json"
                ),
            }
        )
        return round_number

    async def update_negotiation_thread_terminal(
        self,
        *,
        negotiation_id: str,
        terminal_state: str,
    ) -> None:
        self.threads[negotiation_id]["terminal_state"] = terminal_state

    async def load_negotiation_thread_row(
        self,
        *,
        negotiation_id: str,
    ) -> dict[str, Any] | None:
        row = self.threads.get(negotiation_id)
        return dict(row) if row is not None else None

    async def load_negotiation_thread(
        self,
        *,
        negotiation_id: str,
    ) -> list[dict[str, Any]]:
        return [dict(row) for row in self.messages[negotiation_id]]

    async def commit_agreed_terms(self, **values: Any) -> None:
        self.agreements.append(values)


class HookHarness:
    def __init__(self, *, proposal_key: str = "price") -> None:
        self.proposal_key = proposal_key
        self.policy_calls: list[RoundRequest] = []
        self.events: list[tuple[str, str, dict[str, Any]]] = []
        self.next_decision = NegotiationDecision(
            action="counter",
            proposal={proposal_key: 12},
        )

    def amount(self, proposal: Mapping[str, Any] | None) -> int | None:
        if proposal is None or self.proposal_key not in proposal:
            return None
        return int(proposal[self.proposal_key])

    def proposal_from_amount(
        self,
        pinned: Mapping[str, Any] | None,
        amount: int | None,
    ) -> dict[str, Any] | None:
        if pinned is None and amount is None:
            return None
        result = dict(pinned or {})
        if amount is not None:
            result[self.proposal_key] = amount
        return result

    async def evaluate(self, request: RoundRequest) -> RoundEvaluation:
        self.policy_calls.append(request)
        return RoundEvaluation(
            our_amount=15,
            strategy_label="domain-policy",
            decision=self.next_decision,
            pinned_proposal=dict(request.history[0].proposal or {}),
            uses_scalar_amount=True,
            buyer_amount=self.amount(request.history[-1].proposal),
            domain_state={"codec": self.proposal_key},
        )

    def build_artifacts(
        self,
        acceptance: Acceptance,
        accepted: bool,
    ) -> Mapping[str, Any]:
        if not accepted:
            return {"accepted_offer": dict(acceptance.pinned_proposal or {})}
        return {
            "accepted_artifact": {
                "amount": acceptance.agreed_amount,
                "terms": dict(acceptance.terms.wire or {}),
                "buyer": acceptance.buyer_principal.model_dump(mode="json"),
            }
        }

    def event(self, component: str, event: str, **fields: Any) -> None:
        self.events.append((component, event, fields))

    def hooks(self) -> NegotiationDomainHooks:
        async def validate_continuation(
            repository: RecordingRepository,
            _listing: Any,
            _listing_record: Mapping[str, Any],
            _terms: NegotiationTerms,
            thread: Mapping[str, Any],
        ) -> None:
            if thread.get("binding") == "mismatch":
                raise NegotiationStateError("recorded binding mismatch")

        async def listing_is_paused(
            repository: RecordingRepository,
            listing_id: str,
        ) -> bool:
            return await repository.is_listing_paused(listing_id=listing_id)

        async def persist_opening(
            repository: RecordingRepository,
            opening: Any,
        ) -> None:
            repository.effects.append(("opening", opening.terms.decoded))

        async def place_hold(
            repository: RecordingRepository,
            acceptance: Acceptance,
        ) -> None:
            repository.effects.append(("hold", acceptance.agreed_amount))

        async def persist_artifacts(
            repository: RecordingRepository,
            _acceptance: Acceptance,
            artifacts: Mapping[str, Any],
        ) -> None:
            repository.effects.append(("artifacts", dict(artifacts)))

        return NegotiationDomainHooks(
            decode_terms=lambda raw: NegotiationTerms(
                decoded={"decoded": raw["units"]},
                wire={"units": int(raw["units"])},
            ),
            validate_opening=lambda _listing, _record, terms: (
                None
                if terms.decoded["decoded"] > 0
                else (_ for _ in ()).throw(ValueError("units must be positive"))
            ),
            validate_continuation=validate_continuation,
            evaluate_round=self.evaluate,
            determine_strategy=lambda _listing, _record: "domain-policy",
            reference_amount=lambda _listing, _record, _terms, scalar: (
                15 if scalar else 0
            ),
            amount_from_proposal=self.amount,
            proposal_from_amount=self.proposal_from_amount,
            agreement_terms=lambda _listing, _record, _terms: AgreementTerms(0),
            build_artifacts=self.build_artifacts,
            decision_wire=lambda decision: decision.to_dict(),
            listing_is_live=lambda record: bool(record["open"]),
            listing_is_paused=listing_is_paused,
            storefront_is_paused=lambda: False,
            stage_event=self.event,
            persist_opening=persist_opening,
            place_hold=place_hold,
            persist_artifacts=persist_artifacts,
        )


def runtime_for(
    repository: RecordingRepository,
    harness: HookHarness,
) -> NegotiationRuntime:
    hooks = harness.hooks()

    async def resolve_opening(
        candidate: RecordingRepository,
        listing_id: str,
    ) -> ResolvedNegotiation:
        assert candidate is repository
        listing = await candidate.load_listing(listing_id=listing_id)
        assert listing is not None
        return ResolvedNegotiation(listing_id, listing, listing, hooks, "binding-1")

    async def resolve_continuation(
        candidate: RecordingRepository,
        thread: Mapping[str, Any],
    ) -> ResolvedNegotiation:
        assert candidate is repository
        listing_id = str(thread["our_listing_id"])
        listing = await candidate.load_listing(listing_id=listing_id)
        assert listing is not None
        return ResolvedNegotiation(listing_id, listing, listing, hooks, "binding-1")

    return NegotiationRuntime(
        resolve_opening=resolve_opening,
        resolve_continuation=resolve_continuation,
        id_factory=lambda: "neg-fixed",
        now=lambda: datetime(2026, 8, 15, tzinfo=UTC),
    )


@pytest.mark.asyncio
async def test_round_zero_uses_domain_codec_and_persists_canonical_principals() -> None:
    repository = RecordingRepository()
    harness = HookHarness(proposal_key="credits")
    runtime = runtime_for(repository, harness)

    response = await runtime.start(
        repository=repository,
        listing_id="listing-1",
        buyer_principal=_BUYER,
        seller_principal=_SELLER,
        actor_principal=_BUYER,
        proposal={"credits": 10, "opaque": {"domain": True}},
        terms={"units": 3},
        seller_agent_url="https://seller.example",
        buyer_agent_url="https://buyer.example",
    )

    thread = repository.threads["neg-fixed"]
    assert thread["buyer_principal"] == _BUYER.model_dump(mode="json")
    assert thread["seller_principal"] == _SELLER.model_dump(mode="json")
    assert thread["buyer_escrow_proposal"]["opaque"] == {"domain": True}
    assert thread["provision_terms"] == {"units": 3}
    assert harness.policy_calls[0].terms.decoded == {"decoded": 3}
    assert response["buyer_principal"] == _BUYER.model_dump(mode="json")
    assert response["proposal"] == {"credits": 12}


@pytest.mark.asyncio
async def test_opening_actor_mismatch_fails_before_resolution_or_policy() -> None:
    repository = RecordingRepository()
    harness = HookHarness()
    runtime = runtime_for(repository, harness)

    with pytest.raises(NegotiationStateError, match="opening buyer"):
        await runtime.start(
            repository=repository,
            listing_id="listing-1",
            buyer_principal=_BUYER,
            seller_principal=_SELLER,
            actor_principal=_OTHER_BUYER,
            proposal={"price": 10},
            terms={"units": 1},
            seller_agent_url="https://seller.example",
            buyer_agent_url="https://buyer.example",
        )

    assert repository.threads == {}
    assert harness.policy_calls == []


@pytest.mark.asyncio
async def test_continuation_principal_mismatch_fails_before_policy_and_effects() -> None:
    repository = RecordingRepository()
    harness = HookHarness()
    runtime = runtime_for(repository, harness)
    await runtime.start(
        repository=repository,
        listing_id="listing-1",
        buyer_principal=_BUYER,
        seller_principal=_SELLER,
        actor_principal=_BUYER,
        proposal={"price": 10},
        terms={"units": 2},
        seller_agent_url="https://seller.example",
        buyer_agent_url="https://buyer.example",
    )
    policy_count = len(harness.policy_calls)
    effect_count = len(repository.effects)

    with pytest.raises(NegotiationStateError, match="does not own"):
        await runtime.continue_negotiation(
            repository=repository,
            negotiation_id="neg-fixed",
            buyer_action="accept",
            buyer_proposal=None,
            buyer_reason=None,
            buyer_principal=_OTHER_BUYER,
            actor_principal=_OTHER_BUYER,
            actor_role="buyer",
        )

    assert len(harness.policy_calls) == policy_count
    assert len(repository.effects) == effect_count
    assert repository.threads["neg-fixed"]["terminal_state"] is None


@pytest.mark.asyncio
async def test_accept_resumes_recorded_terms_and_builds_artifact_before_effects() -> None:
    repository = RecordingRepository()
    harness = HookHarness()
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

    response = await runtime.continue_negotiation(
        repository=repository,
        negotiation_id="neg-fixed",
        buyer_action="accept",
        buyer_proposal={"price": 999},
        buyer_reason=None,
        buyer_principal=_BUYER,
        actor_principal=_BUYER,
        actor_role="buyer",
    )

    assert response["accepted_artifact"]["terms"] == {"units": 7}
    assert response["accepted_artifact"]["amount"] == 12
    assert repository.agreements[0]["agreed_price"] == 12
    assert repository.threads["neg-fixed"]["terminal_state"] == "success"
    assert repository.effects[-2][0] == "hold"
    assert repository.effects[-1][0] == "artifacts"


@pytest.mark.asyncio
async def test_recorded_binding_mismatch_fails_before_acceptance_effects() -> None:
    repository = RecordingRepository()
    harness = HookHarness()
    runtime = runtime_for(repository, harness)
    await runtime.start(
        repository=repository,
        listing_id="listing-1",
        buyer_principal=_BUYER,
        seller_principal=_SELLER,
        actor_principal=_BUYER,
        proposal={"price": 10},
        terms={"units": 1},
        seller_agent_url="https://seller.example",
        buyer_agent_url="https://buyer.example",
    )
    repository.threads["neg-fixed"]["binding"] = "mismatch"
    effect_count = len(repository.effects)

    with pytest.raises(NegotiationStateError, match="binding mismatch"):
        await runtime.continue_negotiation(
            repository=repository,
            negotiation_id="neg-fixed",
            buyer_action="accept",
            buyer_proposal=None,
            buyer_reason=None,
            buyer_principal=_BUYER,
            actor_principal=_BUYER,
            actor_role="buyer",
        )

    assert len(repository.effects) == effect_count
    assert repository.agreements == []
    assert repository.threads["neg-fixed"]["terminal_state"] is None


@pytest.mark.asyncio
async def test_second_domain_owns_a_different_proposal_schema() -> None:
    repository = RecordingRepository()
    harness = HookHarness(proposal_key="tokens")
    harness.next_decision = NegotiationDecision(
        action="accept",
        proposal={"tokens": 44},
    )
    runtime = runtime_for(repository, harness)

    response = await runtime.start(
        repository=repository,
        listing_id="listing-1",
        buyer_principal=_BUYER,
        seller_principal=_SELLER,
        actor_principal=_BUYER,
        proposal={"tokens": 41},
        terms={"units": 4},
        seller_agent_url="https://seller.example",
        buyer_agent_url="https://buyer.example",
    )

    assert response["accepted_artifact"]["amount"] == 44
    assert repository.agreements[0]["agreed_price"] == 44
    assert repository.threads["neg-fixed"]["buyer_escrow_proposal"] == {
        "tokens": 41
    }
