import uuid
from types import SimpleNamespace

import pytest
import typer
from arkhai_vms import make_vm_provision_terms
from domains.vms.buyer import (
    common,
    hosted_settlement,
    settle_cli,
    settlement_composition,
)
from domains.vms.buyer.escrow_selection import select_escrow_entry
from domains.vms.buyer.settlement_composition import resolve_buyer_settlement_policy
from domains.vms.settlement import escrow_proposal_from_accepted_entry
from market_core.schemas import SettlementOption, derive_settlement_option_id
from core_buyer.buyer_config import ResolvedBuyerIdentity
from core_buyer.action_policy import BuyerActionPolicy
from market_hosted_settlement import (
    FundingMode,
    FundingProfile,
    FundingSelection,
    StripeSettlementConfig,
    stripe_contract_fingerprint,
)
from market_identity import (
    AuthorityBindingState,
    AuthorityPayerBinding,
    Ed25519Signer,
)

_ESCROW = "0x" + "11" * 20
_TOKEN = "0x" + "22" * 20
_OTHER = "0x" + "33" * 20
_ARBITER = "0x" + "44" * 20

def _resolved(signer: Ed25519Signer) -> ResolvedBuyerIdentity:
    return ResolvedBuyerIdentity(
        profile_id=uuid.UUID("11111111-1111-4111-8111-111111111111"),
        principal=signer.identity,
        signer=signer,
        source="recovery",
    )



def test_hosted_start_carries_only_accepted_and_authorization_refs(monkeypatch):
    buyer = Ed25519Signer(b"\x31" * 32)
    captured = {}
    monkeypatch.setattr(
        hosted_settlement,
        "_signed_json",
        lambda url, body, **kwargs: (
            captured.update(url=url, body=body, kwargs=kwargs)
            or {"settlement_ref": "settlement-1"}
        ),
    )

    result = hosted_settlement.start_hosted_settlement(
        seller_url="http://seller/",
        negotiation_id="neg-1",
        obligation_ref="a" * 64,
        funding_authorization_ref="funding-auth-safe-1",
        principal=buyer.identity,
        signer=buyer,
        resolve_seller_principals=lambda: None,
    )

    assert result["settlement_ref"] == "settlement-1"
    assert captured["url"] == "http://seller/api/v1/settlements"
    assert captured["body"] == {
        "negotiation_id": "neg-1",
        "obligation_ref": "a" * 64,
        "funding_authorization_ref": "funding-auth-safe-1",
    }


def test_hosted_wait_returns_expired_for_explicit_reclaim(monkeypatch):
    buyer = Ed25519Signer(b"\x31" * 32)
    monkeypatch.setattr(
        hosted_settlement,
        "_signed_json",
        lambda *_args, **_kwargs: {
            "settlement_ref": "settlement-1",
            "status": "expired",
            "funding_profile": "us_bank_transfer.v1",
            "funding_reason": "funding_deadline_elapsed",
        },
    )

    result = hosted_settlement.wait_for_hosted_settlement(
        seller_url="http://seller/",
        settlement_ref="settlement-1",
        principal=buyer.identity,
        signer=buyer,
        total_timeout=1,
        sleep=lambda _seconds: None,
        resolve_seller_principals=lambda: None,
    )

    assert result["status"] == "expired"
    assert result["settlement_ref"] == "settlement-1"


def test_select_escrow_entry_filters_by_chain_and_token():
    listing = {
        "accepted_escrows": [
            {
                "chain_name": "other",
                "escrow_address": _OTHER,
                "literal_fields": {"token": _OTHER},
            },
            {
                "chain_name": "anvil",
                "escrow_address": _ESCROW,
                "literal_fields": {"token": _TOKEN},
            },
        ],
    }

    assert (
        select_escrow_entry(
            listing,
            chain_name="anvil",
            token_contract_filter=_TOKEN,
            assume_yes=True,
            rpc_url="http://rpc",
            buyer_address="0x" + "aa" * 20,
        )["escrow_address"]
        == _ESCROW
    )


def test_escrow_proposal_from_accepted_entry_selects_first_matching_demand():
    entry = {
        "chain_name": "anvil",
        "escrow_address": _ESCROW,
        "literal_fields": {"token": _TOKEN},
        "rates": [{"field": "amount", "per": "hour", "value": "100"}],
    }
    listing = {
        "demands": [
            {"chain_name": "other", "arbiter": _OTHER, "demand_data": {}},
            {"chain_name": "anvil", "arbiter": _ARBITER, "demand_data": {"x": 1}},
            {"arbiter": _ARBITER, "demand_data": {"global": True}},
        ],
    }

    proposal = escrow_proposal_from_accepted_entry(
        listing=listing,
        entry=entry,
        expiration_unix=123,
    )

    assert proposal.chain_name == "anvil"
    assert proposal.escrow_address == _ESCROW
    assert proposal.fields == {"token": _TOKEN}
    assert proposal.literal_fields == {"token": _TOKEN}
    assert [rate.model_dump() for rate in proposal.rates] == entry["rates"]
    assert proposal.expiration_unix == 123
    assert proposal.demand is not None
    assert proposal.demand.arbiter == _ARBITER
    assert proposal.demand.demand_data == {"x": 1}
    assert proposal.demands is None


def test_make_vm_provision_terms_uses_compute_compat_shape():
    terms = make_vm_provision_terms(
        duration_seconds=3600,
        ssh_public_key="ssh-ed25519 example",
    )
    assert terms.duration_seconds == 3600
    assert terms.ssh_public_key == "ssh-ed25519 example"
    assert terms.kind == "compute.v1"


def test_alkahest_resume_preserves_accepted_ssh_after_config_rotation(monkeypatch):
    buyer = Ed25519Signer(b"\x34" * 32)
    accepted_ssh = "ssh-ed25519 accepted-key"
    deal = SimpleNamespace(
        settlement_selection=None,
        settlement_plan={
            "obligations": [
                {
                    "payer": "buyer",
                    "claimant": "seller",
                    "amount": "25",
                    "asset": _TOKEN,
                    "expiration_unix": 2_000_000_000,
                    "mechanism": "alkahest.v1",
                    "params": {},
                }
            ]
        },
        accepted_provision_terms=make_vm_provision_terms(
            duration_seconds=7200,
            ssh_public_key=accepted_ssh,
        ).model_dump(mode="json"),
        duration_seconds=3600,
        token_contract=_TOKEN,
        token_decimals=18,
        accepted_escrow_proposal={"chain_name": "anvil"},
        accepted_escrow_terms=None,
        escrow_uid="0x" + "55" * 32,
        seller_url="http://seller",
        negotiation_id="neg-accepted-ssh",
        listing_id="listing-1",
        agreed_amount=25,
        seller_wallet_address=None,
        buyer_principal=buyer.identity,
    )
    submitted = {}

    class _Log:
        def event(self, *_args, **_kwargs):
            return None

        def end(self, *_args, **_kwargs):
            return None

    monkeypatch.setattr(
        common,
        "resolve_recovery_buyer_identity",
        lambda _run_id: _resolved(buyer),
    )
    monkeypatch.setattr(
        common,
        "resolve_buyer_wallet",
        lambda: ("0x" + "66" * 20, "0x" + "77" * 32),
    )
    monkeypatch.setattr(
        common,
        "resolve_ssh_public_key",
        lambda: (_ for _ in ()).throw(
            AssertionError("accepted SSH was replaced by rotated config")
        ),
    )
    monkeypatch.setattr(
        common,
        "chain_by_name",
        lambda _name: SimpleNamespace(name="anvil", rpc_url="http://rpc"),
    )
    monkeypatch.setattr(settle_cli, "load_deal_context", lambda *_a, **_k: deal)
    monkeypatch.setattr(
        settle_cli,
        "make_deal_publisher_trust_resolver",
        lambda *_a, **_k: lambda: None,
    )
    monkeypatch.setattr(settle_cli, "open_run_log", lambda *_a, **_k: _Log())
    monkeypatch.setattr(
        settlement_composition,
        "resolve_alkahest_address_config_path",
        lambda: None,
    )
    monkeypatch.setattr(
        settle_cli,
        "submit_settlement_request",
        lambda **kwargs: submitted.update(kwargs) or {"status": "provisioning"},
    )
    monkeypatch.setattr(
        settle_cli,
        "wait_for_settlement",
        lambda **_kwargs: {"status": "ready"},
    )

    result = settle_cli.run_settle_from_log(
        run_id="run-accepted-ssh",
        poll_interval=0,
        settlement_timeout=1,
    )

    assert result == {"status": "ready"}
    assert submitted["payload"]["ssh_public_key"] == accepted_ssh


def test_current_accepted_state_without_provision_terms_never_uses_config():
    deal = SimpleNamespace(
        accepted_provision_terms=None,
        settlement_selection={
            "mechanism": "alkahest.v1",
            "option_id": "a" * 64,
            "expiration_unix": 2_000_000_000,
        },
        settlement_plan={"obligations": []},
        duration_seconds=3600,
    )

    with pytest.raises(
        typer.BadParameter,
        match="current configuration will not reinterpret this run",
    ):
        settle_cli._accepted_provision_inputs(deal)


def test_recovery_never_falls_back_for_uninstalled_accepted_mechanism(
    monkeypatch,
):
    buyer = Ed25519Signer(b"\x31" * 32)
    deal = SimpleNamespace(
        settlement_selection={
            "mechanism": "future.settlement.v1",
            "option_id": "a" * 64,
            "expiration_unix": 2_000_000_000,
        },
        settlement_plan={
            "obligations": [
                {
                    "payer": "buyer",
                    "claimant": "seller",
                    "amount": "1",
                    "asset": "credit",
                    "expiration_unix": 2_000_000_000,
                    "mechanism": "future.settlement.v1",
                    "params": {},
                }
            ]
        },
        negotiation_id="neg-future",
    )

    class _Log:
        def event(self, *_args, **_kwargs):
            return None

    monkeypatch.setattr(
        common,
        "resolve_recovery_buyer_identity",
        lambda _run_id: _resolved(buyer),
    )
    monkeypatch.setattr(
        common,
        "chain_by_name",
        lambda *_args: (_ for _ in ()).throw(
            AssertionError("fallback touched chain config")
        ),
    )
    monkeypatch.setattr(settle_cli, "load_deal_context", lambda *_args, **_kwargs: deal)
    monkeypatch.setattr(
        settle_cli,
        "make_deal_publisher_trust_resolver",
        lambda *_args, **_kwargs: lambda: None,
    )
    monkeypatch.setattr(settle_cli, "open_run_log", lambda *_args, **_kwargs: _Log())

    with pytest.raises(typer.BadParameter, match="will not fall back"):
        settle_cli.run_settle_from_log(
            run_id="run-future",
            poll_interval=0,
            settlement_timeout=1,
        )


def test_hosted_recovery_is_pinned_and_never_touches_chain_config(monkeypatch, capsys):
    buyer = Ed25519Signer(b"\x32" * 32)
    obligation = {
        "payer": "buyer",
        "claimant": "seller",
        "payer_principal": buyer.identity.model_dump(mode="json"),
        "claimant_principal": Ed25519Signer(b"\x33" * 32).identity.model_dump(
            mode="json"
        ),
        "amount": "25",
        "asset": "usd",
        "expiration_unix": 2_000_000_000,
        "mechanism": "fiat.stripe.v1",
        "params": {"condition_profile": "vm"},
    }
    deal = SimpleNamespace(
        settlement_selection={
            "mechanism": "fiat.stripe.v1",
            "option_id": "b" * 64,
            "expiration_unix": 2_000_000_000,
        },
        settlement_plan={"obligations": [obligation]},
        settlement_operation_identities=(),
        negotiation_id="neg-hosted",
        settlement_ref=None,
        seller_url="http://seller",
        buyer_principal=buyer.identity,
        funding_authorization_ref=lambda _ref: "funding-auth-safe-1",
    )

    events: list[tuple[tuple, dict]] = []

    class _Log:
        def event(self, *args, **kwargs):
            events.append((args, kwargs))

        def end(self, *_args, **_kwargs):
            return None

    monkeypatch.setattr(
        common,
        "resolve_recovery_buyer_identity",
        lambda _run_id: _resolved(buyer),
    )
    monkeypatch.setattr(
        common,
        "chain_by_name",
        lambda *_args: (_ for _ in ()).throw(
            AssertionError("hosted recovery touched chain config")
        ),
    )
    monkeypatch.setattr(settle_cli, "load_deal_context", lambda *_args, **_kwargs: deal)
    monkeypatch.setattr(
        settlement_composition,
        "load_user_config",
        lambda: (_ for _ in ()).throw(
            AssertionError("hosted recovery consulted current settlement priority")
        ),
    )
    monkeypatch.setattr(
        settle_cli,
        "make_deal_publisher_trust_resolver",
        lambda *_args, **_kwargs: lambda: None,
    )
    monkeypatch.setattr(settle_cli, "open_run_log", lambda *_args, **_kwargs: _Log())
    monkeypatch.setattr(
        settle_cli,
        "start_hosted_settlement",
        lambda **_kwargs: {
            "settlement_ref": "stripe-operation",
            "status": "funding",
            "action": {
                "kind": "browser_redirect",
                "url": "https://checkout.invalid/transient",
                "expires_at_unix": 1_800_000_000,
            },
        },
    )
    monkeypatch.setattr(
        settle_cli,
        "wait_for_hosted_settlement",
        lambda **_kwargs: {"status": "ready"},
    )

    result = settle_cli.run_settle_from_log(
        run_id="run-hosted",
        poll_interval=0,
        settlement_timeout=1,
        action_policy=BuyerActionPolicy.PRINT,
    )

    assert result == {"status": "ready"}
    assert "https://checkout.invalid/transient" in capsys.readouterr().out
    assert any(args == ("hosted_checkout_required",) for args, _ in events)
    assert "checkout.invalid" not in repr(events)


def test_inflight_legacy_hosted_recovery_skips_new_authorization(monkeypatch):
    buyer = Ed25519Signer(b"\x36" * 32)
    seller = Ed25519Signer(b"\x37" * 32).identity
    obligation = {
        "payer": "buyer",
        "claimant": "seller",
        "payer_principal": buyer.identity.model_dump(mode="json"),
        "claimant_principal": seller.model_dump(mode="json"),
        "amount": "25",
        "asset": "usd",
        "expiration_unix": 2_000_000_000,
        "mechanism": "fiat.stripe.v1",
        "params": {
            "account_ref": "seller-main",
            "condition_profile": "vm",
            "payment_method_types": ["card"],
        },
    }
    deal = SimpleNamespace(
        settlement_selection={
            "mechanism": "fiat.stripe.v1",
            "option_id": "c" * 64,
            "expiration_unix": 2_000_000_000,
        },
        settlement_plan={"obligations": [obligation]},
        settlement_operation_identities=(),
        negotiation_id="neg-legacy",
        settlement_ref="legacy-settlement-ref",
        seller_url="http://seller",
        buyer_principal=buyer.identity,
        funding_authorization_ref=lambda _ref: None,
    )

    class Log:
        def event(self, *_args, **_kwargs):
            return None

        def end(self, *_args, **_kwargs):
            return None

    monkeypatch.setattr(
        common,
        "resolve_recovery_buyer_identity",
        lambda _run_id: _resolved(buyer),
    )
    monkeypatch.setattr(
        settle_cli,
        "load_deal_context",
        lambda *_args, **_kwargs: deal,
    )
    monkeypatch.setattr(
        settle_cli,
        "make_deal_publisher_trust_resolver",
        lambda *_args, **_kwargs: lambda: None,
    )
    monkeypatch.setattr(settle_cli, "open_run_log", lambda *_args, **_kwargs: Log())
    monkeypatch.setattr(
        settle_cli,
        "prepare_hosted_funding_authorization",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("in-flight legacy recovery reauthorized funding")
        ),
    )
    monkeypatch.setattr(
        settle_cli,
        "start_hosted_settlement",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("in-flight legacy recovery started a new settlement")
        ),
    )
    waited = []
    monkeypatch.setattr(
        settle_cli,
        "wait_for_hosted_settlement",
        lambda **kwargs: waited.append(kwargs) or {"status": "ready"},
    )

    result = settle_cli.run_settle_from_log(
        run_id="run-legacy",
        poll_interval=0,
        settlement_timeout=1,
        action_policy=BuyerActionPolicy.PRINT,
    )
    assert result == {"status": "ready"}
    assert waited[0]["settlement_ref"] == "legacy-settlement-ref"


def test_legacy_without_settlement_ref_requires_operator_before_payer_call(
    monkeypatch,
):
    buyer = Ed25519Signer(b"\x38" * 32)
    seller = Ed25519Signer(b"\x39" * 32).identity
    obligation = {
        "payer": "buyer",
        "claimant": "seller",
        "payer_principal": buyer.identity.model_dump(mode="json"),
        "claimant_principal": seller.model_dump(mode="json"),
        "amount": "25",
        "asset": "usd",
        "expiration_unix": 2_000_000_000,
        "mechanism": "fiat.stripe.v1",
        "params": {
            "account_ref": "seller-main",
            "condition_profile": "vm",
            "payment_method_types": ["card"],
        },
    }
    deal = SimpleNamespace(
        settlement_selection={
            "mechanism": "fiat.stripe.v1",
            "option_id": "d" * 64,
            "expiration_unix": 2_000_000_000,
        },
        settlement_plan={"obligations": [obligation]},
        settlement_operation_identities=(),
        negotiation_id="neg-legacy-unstarted",
        settlement_ref=None,
        seller_url="http://seller",
        buyer_principal=buyer.identity,
        funding_authorization_ref=lambda _ref: None,
    )

    class Log:
        def event(self, *_args, **_kwargs):
            return None

    monkeypatch.setattr(
        common,
        "resolve_recovery_buyer_identity",
        lambda _run_id: _resolved(buyer),
    )
    monkeypatch.setattr(
        settle_cli,
        "load_deal_context",
        lambda *_args, **_kwargs: deal,
    )
    monkeypatch.setattr(
        settle_cli,
        "make_deal_publisher_trust_resolver",
        lambda *_args, **_kwargs: lambda: None,
    )
    monkeypatch.setattr(settle_cli, "open_run_log", lambda *_args, **_kwargs: Log())
    monkeypatch.setattr(
        settle_cli,
        "prepare_hosted_funding_authorization",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("legacy recovery called the payer authority")
        ),
    )
    monkeypatch.setattr(
        settle_cli,
        "start_hosted_settlement",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("legacy recovery started a new settlement")
        ),
    )

    with pytest.raises(typer.BadParameter, match="operator recovery is required"):
        settle_cli.run_settle_from_log(
            run_id="run-legacy-unstarted",
            poll_interval=0,
            settlement_timeout=1,
            action_policy=BuyerActionPolicy.PRINT,
        )


def test_fiat_discovery_is_local_only_and_respects_action_capability(monkeypatch):
    monkeypatch.setattr(
        common,
        "buyer_chains",
        lambda: (_ for _ in ()).throw(
            AssertionError("fiat selection resolved chain resources")
        ),
    )
    buyer = Ed25519Signer(b"\x35" * 32)

    class Profiles:
        def authority_payer_binding(self, profile_id, **coordinates):
            return AuthorityPayerBinding(
                authority_id=coordinates["authority_id"],
                environment=coordinates["environment"],
                binding_ref="payer_binding_opaque",
                bound_principal=coordinates["principal"],
                state=AuthorityBindingState.ACTIVE,
            )

    monkeypatch.setattr(settlement_composition, "BuyerProfileService", Profiles)
    monkeypatch.setattr(
        settlement_composition,
        "payer_command_context_from_config",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("discovery performed a hosted network read")
        ),
    )
    stripe = StripeSettlementConfig(
        enabled=True,
        base_url="https://settlement.example",
        authority_id="authority-main",
        environment="production",
        authority={"principals": [buyer.identity.model_dump(mode="json")]},
        expected_manifest_digest="sha256:" + "ab" * 32,
    )
    config = {
        "Settlement": {
            "schema_version": 1,
            "priority": ["fiat.stripe.v1"],
            "stripe": stripe.model_dump(mode="json"),
        }
    }
    params = {
        "account_ref": "seller-main",
        "funding_profile": FundingProfile.CARD.value,
        "interaction": FundingMode.INTERACTIVE.value,
        "funds_flow": "separate_charges_transfers",
        "contract_fingerprint": stripe_contract_fingerprint(stripe),
    }
    option = SettlementOption(
        option_id=derive_settlement_option_id(
            mechanism="fiat.stripe.v1",
            asset="usd",
            rates=[],
            params=params,
        ),
        mechanism="fiat.stripe.v1",
        asset="usd",
        params=params,
    )
    listing = {"settlement_options": [option.model_dump(mode="json")]}
    policy = resolve_buyer_settlement_policy(
        config,
        identity=_resolved(buyer),
        funding_selection=FundingSelection(mode=FundingMode.INTERACTIVE),
        action_capable=True,
    )
    selected = policy.select(listing, expiration_unix=2_000_000_000)
    assert selected is not None
    assert selected.selection.mechanism == "fiat.stripe.v1"

    no_action_policy = resolve_buyer_settlement_policy(
        config,
        identity=_resolved(buyer),
        funding_selection=FundingSelection(mode=FundingMode.INTERACTIVE),
        action_capable=False,
    )
    assert (
        no_action_policy.select(listing, expiration_unix=2_000_000_000)
        is None
    )
