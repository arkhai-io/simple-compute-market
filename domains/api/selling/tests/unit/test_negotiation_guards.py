"""The seller's guards under a neutral domain's bundle, and what an acceptance records."""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest
from market_identity import Ed25519Signer, Identity, IdentityScheme
from market_negotiation_runtime import NegotiationStateError, OfferUnfulfillableError
from market_policy.negotiation_middleware import (
    NegotiationContext,
    NegotiationRound,
    load_negotiation_chain,
)

from arkhai_api_selling.negotiation import (
    _QuotaSnapshot,
    acceptance_artifacts,
    decode_terms,
    default_guards,
    key_owned_by_buyer_principal,
    load_chain,
    make_quota_guard,
    make_round_zero_guard,
    persist_acceptance,
    register_guards,
)
from tests.bundles import DOMAIN, EXAMPLE

# Deterministic development values for these tests only; never used on any network.
_TOKEN = "0x" + "01" * 20
_ESCROW = "0x" + "11" * 20
_BUYER = "0x" + "ab" * 20
_BUYER_PRINCIPAL = Identity(scheme=IdentityScheme.EIP191, identifier=_BUYER)
_ED25519_PRINCIPAL = Ed25519Signer(bytes.fromhex("22" * 32)).identity
_OPTION_ID = "cd" * 32

QUOTA_GUARD = make_quota_guard(EXAMPLE)


def _listing(quota="quota-a"):
    return {
        "listing_id": "L-example",
        "status": "open",
        "listing_resource": {"product": "Example", "quota": quota},
        "accepted_escrows": [
            {
                "chain_name": "anvil",
                "escrow_address": _ESCROW,
                "literal_fields": {"token": _TOKEN},
                "rates": [{"field": "amount", "per": "token", "value": "100"}],
            }
        ],
    }


def _round0(proposal):
    return [
        NegotiationRound(round_number=0, sender="them", action="initial", proposal=proposal)
    ]


def _proposal(amount=300):
    return {
        "chain_name": "anvil",
        "escrow_address": _ESCROW,
        "fields": {"token": _TOKEN, "amount": amount},
    }


def _context(listing=None, *, resources=None, **intermediate):
    return NegotiationContext(
        direction="maximize",
        our_reference_amount=300,
        listing=listing or _listing(),
        available_resources={"resources": resources or []},
        intermediate=intermediate,
    )


def _rejection(decision) -> str | None:
    return decision.reason if decision is not None and decision.action == "reject" else None



def _selection(**extra) -> dict:
    return {
        "mechanism": "example.payments.v1",
        "option_id": _OPTION_ID,
        "expiration_unix": 1_900_000_000,
        **extra,
    }


def _selection_context() -> NegotiationContext:
    context = NegotiationContext(
        direction="maximize",
        our_reference_amount=1000,
        listing={
            "listing_id": "L-example",
            "settlement_options": [
                {"option_id": _OPTION_ID, "mechanism": "example.payments.v1", "asset": "USD/2"}
            ],
        },
    )
    context.intermediate["requested_quantity"] = 10
    return context


def _selecting(selection):
    return _round0({"fields": {}, "settlement_selection": selection})


def test_selection_with_payer_params_is_not_refused_as_malformed():
    guard = make_round_zero_guard(EXAMPLE, None)
    params = {"payer_account": "11111111-1111-4111-8111-111111111111"}
    decision, _ = guard(_selecting(_selection(params=params)), _selection_context())
    assert "selection has invalid fields" not in (_rejection(decision) or "")


def test_selection_with_empty_params_is_not_refused_as_malformed():
    guard = make_round_zero_guard(EXAMPLE, None)
    decision, _ = guard(_selecting(_selection(params=None)), _selection_context())
    assert "selection has invalid fields" not in (_rejection(decision) or "")


def test_selection_with_unknown_fields_or_non_mapping_params_is_refused():
    guard = make_round_zero_guard(EXAMPLE, None)
    for selection in (_selection(amount="5"), _selection(params=["payer"])):
        decision, _ = guard(_selecting(selection), _selection_context())
        assert _rejection(decision) == "invalid_settlement_selection:selection has invalid fields"


def test_the_opening_guard_refuses_a_missing_or_nonpositive_quantity_and_a_bad_key():
    guard = make_round_zero_guard(EXAMPLE, lambda proposal, _accepted: dict(proposal))
    cases = [
        ({}, "credit_quantity_missing"),
        ({"requested_quantity": 0}, "credit_quantity_invalid"),
        ({"requested_quantity": 1, "key_mode": "shared"}, "key_disposition_invalid"),
        ({"requested_quantity": 1, "key_mode": "existing"}, "key_disposition_invalid"),
    ]
    for intermediate, code in cases:
        decision, _ = guard(_round0(_proposal()), _context(**intermediate))
        assert (_rejection(decision) or "").startswith(code), intermediate


def test_the_opening_guard_canonicalizes_an_escrow_proposal_through_the_injected_step():
    seen = {}

    def normalize(proposal, accepted):
        seen["accepted"] = accepted
        return {**proposal, "normalized": True}

    guard = make_round_zero_guard(EXAMPLE, normalize)
    decision, context = guard(_round0(_proposal()), _context(requested_quantity=3))

    assert decision is None
    assert context.intermediate["accepted_escrow_proposal"]["normalized"] is True
    assert seen["accepted"] == _listing()["accepted_escrows"]


def test_the_opening_guard_refuses_an_escrow_proposal_it_cannot_canonicalize():
    def normalize(_proposal, _accepted):
        raise ValueError("no accepted escrow matches")

    decision, _ = make_round_zero_guard(EXAMPLE, normalize)(
        _round0(_proposal()), _context(requested_quantity=3)
    )
    assert _rejection(decision) == "invalid_escrow_proposal:no accepted escrow matches"


def test_without_an_escrow_step_an_escrow_proposal_is_refused():
    decision, _ = make_round_zero_guard(EXAMPLE, None)(
        _round0(_proposal()), _context(requested_quantity=3)
    )
    assert (_rejection(decision) or "").startswith("invalid_escrow_proposal:")



def test_quota_guard_passes_when_covered_and_rejects_when_not():
    resources = [{"resource_id": "quota-a", "available_units": 5}]
    decision, _ = QUOTA_GUARD(_round0(_proposal()), _context(resources=resources, requested_quantity=5))
    assert decision is None

    decision, _ = QUOTA_GUARD(_round0(_proposal()), _context(resources=resources, requested_quantity=6))
    assert (_rejection(decision) or "").startswith("quota_exhausted")


def test_quota_guard_is_not_applicable_without_a_snapshot():
    # No snapshot is captured for a listing availability does not bound; the
    # guard then neither passes nor rejects on quota.
    context = NegotiationContext(
        direction="maximize",
        our_reference_amount=300,
        listing=_listing(),
        available_resources={},
        intermediate={"requested_quantity": 1_000_000},
    )
    decision, _ = QUOTA_GUARD(_round0(_proposal()), context)
    assert decision is None


def test_quota_guard_matches_by_the_projected_quota_resource():
    resources = [
        {"resource_id": "other", "available_units": 100},
        {"resource_id": "quota-a", "available_units": 2},
    ]
    decision, _ = QUOTA_GUARD(_round0(_proposal()), _context(resources=resources, requested_quantity=3))
    assert _rejection(decision) is not None


def test_quota_guard_ignores_another_domains_listing():
    decision, _ = QUOTA_GUARD(
        _round0(_proposal()),
        _context(listing={"listing_resource": {"gpu_model": "H200"}}, requested_quantity=3),
    )
    assert decision is None



def _owned_record(owner=_BUYER, scheme=IdentityScheme.EIP191.value, status="active"):
    return {"key_id": "ak_x", "owner_scheme": scheme, "owner_id": owner, "status": status}


def _existing(**intermediate):
    return _context(key_mode="existing", key_id="ak_x", **intermediate)


def test_ownership_guard_passes_new_key_deals():
    decision, _ = key_owned_by_buyer_principal(_round0(_proposal()), _context(key_mode="new"))
    assert decision is None


def test_ownership_guard_admits_same_canonical_principal():
    decision, _ = key_owned_by_buyer_principal(
        _round0(_proposal()),
        _existing(
            key_record=_owned_record(owner=_BUYER.upper().replace("0X", "0x")),
            buyer_principal=_BUYER_PRINCIPAL,
        ),
    )
    assert decision is None


def test_ownership_guard_rejects_stranger():
    decision, _ = key_owned_by_buyer_principal(
        _round0(_proposal()),
        _existing(
            key_record=_owned_record(),
            buyer_principal=Identity(scheme=IdentityScheme.EIP191, identifier="0x" + "99" * 20),
        ),
    )
    assert (_rejection(decision) or "").startswith("key_not_owned")


def test_ownership_guard_rejects_unknown_and_revoked_keys():
    decision, _ = key_owned_by_buyer_principal(
        _round0(_proposal()), _existing(key_record=None, buyer_principal=_BUYER_PRINCIPAL)
    )
    assert (_rejection(decision) or "").startswith("key_not_found")

    decision, _ = key_owned_by_buyer_principal(
        _round0(_proposal()),
        _existing(key_record=_owned_record(status="revoked"), buyer_principal=_BUYER_PRINCIPAL),
    )
    assert (_rejection(decision) or "").startswith("key_revoked")


def test_ownership_guard_open_key_admits_anyone():
    record = {"key_id": "ak_x", "owner_scheme": None, "owner_id": None, "status": "active"}
    decision, _ = key_owned_by_buyer_principal(
        _round0(_proposal()), _existing(key_record=record, buyer_principal=_ED25519_PRINCIPAL)
    )
    assert decision is None


def test_ownership_guard_rejects_cross_scheme_collision():
    decision, _ = key_owned_by_buyer_principal(
        _round0(_proposal()),
        _existing(
            key_record=_owned_record(
                scheme=IdentityScheme.ED25519.value, owner=_ED25519_PRINCIPAL.identifier
            ),
            buyer_principal=_BUYER_PRINCIPAL,
        ),
    )
    assert (_rejection(decision) or "").startswith("key_not_owned")



def test_the_guards_register_under_the_names_the_bundle_spells():
    register_guards(EXAMPLE)

    chain = load_negotiation_chain(list(default_guards(EXAMPLE)))

    assert [guard.__name__ for guard in chain][0] == "example_round_zero_guard"
    assert default_guards(EXAMPLE) == (
        "example_round_zero_guard",
        "buyer_counter_guard",
        "credit_quota_guard",
        "key_owned_by_buyer_principal",
        "escrow_shape_guard",
    )


def test_a_configured_chain_runs_the_guards_ahead_of_its_policies():
    register_guards(EXAMPLE)

    class Configured:
        policies = ["bisection", "credit_quota_guard"]

    chain = load_chain(EXAMPLE, negotiation_config=Configured())

    assert chain[0].__name__ == "example_round_zero_guard"
    assert [guard.__name__ for guard in chain].count("credit_quota_guard") == 1
    assert len(chain) == 6



class _AcceptanceStore:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def copy_listing_binding_to_thread(self, **_binding) -> None:
        self.calls.append("bind")

    async def save_domain_artifact(self, **_artifact) -> None:
        self.calls.append("record listing")

    async def commit_settlement_plan(self, **_plan) -> None:
        self.calls.append("commit plan")


def _acceptance():
    return SimpleNamespace(
        negotiation_id="neg-1",
        listing_id="L-example",
        listing_record={"listing_resource": {"product": "Example", "quota": "quota-a"}},
        buyer_principal=_BUYER_PRINCIPAL,
        seller_principal=_ED25519_PRINCIPAL,
    )


async def test_the_acceptance_hook_runs_before_the_listing_and_plan_are_recorded():
    store = _AcceptanceStore()

    async def pin(repository, acceptance):
        repository.calls.append(f"hook {acceptance.negotiation_id}")

    await persist_acceptance(
        replace(EXAMPLE, acceptance_hook=pin),
        DOMAIN,
        store,
        _acceptance(),
        {"settlement_plan": {"obligations": []}},
    )

    assert store.calls == ["hook neg-1", "bind", "record listing", "commit plan"]


async def test_without_a_hook_an_acceptance_records_the_listing_alone():
    store = _AcceptanceStore()

    await persist_acceptance(EXAMPLE, DOMAIN, store, _acceptance(), {})

    assert store.calls == ["bind", "record listing"]



def test_decoded_terms_keep_the_message_and_narrow_the_wire_to_provision_terms():
    class Message:
        quantity = 3

        def model_dump(self, mode):
            return {"kind": "example.v1", "version": 1, "payload": {}, "settlement_selection": {}}

    domain = SimpleNamespace(codecs=SimpleNamespace(message=lambda raw: Message()))

    terms = decode_terms(domain, {"kind": "example.v1"})

    assert isinstance(terms.decoded, Message)
    assert terms.wire == {"kind": "example.v1", "version": 1, "payload": {}}
    assert decode_terms(domain, None).decoded is None


def test_without_an_escrow_step_an_escrow_acceptance_is_refused():
    acceptance = SimpleNamespace(
        listing_record={}, pinned_proposal={"chain_name": "dev"}, policy_state={}, binding=None
    )

    with pytest.raises(OfferUnfulfillableError, match="settlement_selection_required"):
        acceptance_artifacts(EXAMPLE, {}, {}, None, dict, acceptance, True)
    assert acceptance_artifacts(
        EXAMPLE, {}, {}, None, dict, SimpleNamespace(**{**vars(acceptance), "pinned_proposal": None}), False
    ) == {}


class _Bindings:
    def __init__(self, binding) -> None:
        self._binding = binding

    async def load_listing_binding(self, *, listing_id):
        return self._binding


async def test_a_quota_snapshot_refuses_an_unbound_listing_or_an_unconfigured_site():
    with pytest.raises(NegotiationStateError, match="no durable capacity binding"):
        await _QuotaSnapshot(_Bindings(None), "L-1", lambda _repo: None).snapshot()

    durable = SimpleNamespace(
        physical_resource_id="quota-a",
        capacity_backing="backed",
        site_id="gone",
        binding=SimpleNamespace(offering_mode="example"),
    )

    class _Client:
        def site(self, site_id):
            raise KeyError(site_id)

    with pytest.raises(NegotiationStateError, match="unconfigured site 'gone'"):
        await _QuotaSnapshot(_Bindings(durable), "L-1", lambda _repo: _Client()).snapshot()
