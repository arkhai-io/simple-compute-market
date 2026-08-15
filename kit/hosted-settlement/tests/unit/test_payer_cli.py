from __future__ import annotations

import json
import uuid
from dataclasses import dataclass

import pytest
import typer
from hosted_settlement_client import (
    InstrumentListResult,
    InstrumentKind,
    InstrumentProjection,
    InstrumentReadiness,
    PayerAction,
    PayerActionKind,
    PayerProfileResult,
    PayerProfileState,
    PayerSetupResult,
)
from market_hosted_settlement import (
    MarketplaceSignerAdapter,
    PayerCommandContext,
    create_stripe_command_group,
)
from market_identity import (
    AuthorityBindingState,
    AuthorityPayerBinding,
    BuyerProfile,
    CredentialProviderKind,
    CredentialReference,
    Ed25519Signer,
    PrincipalState,
    ProfilePrincipal,
)
from typer.testing import CliRunner


_NOW = "2026-08-15T12:00:00+00:00"
_OLD = Ed25519Signer(b"a" * 32)
_NEW = Ed25519Signer(b"b" * 32)


def _credential(name: str) -> CredentialReference:
    return CredentialReference(
        provider=CredentialProviderKind.ENVIRONMENT,
        locator=name,
    )


def _profile(
    signer: Ed25519Signer = _OLD,
    *,
    binding_principal=None,
) -> BuyerProfile:
    principal = signer.identity
    return BuyerProfile(
        profile_id=uuid.UUID("11111111-1111-1111-1111-111111111111"),
        name="buyer",
        primary_principal=principal,
        principal_history=(
            ProfilePrincipal(
                principal=principal,
                credential_reference=_credential("BUYER_SEED"),
                state=PrincipalState.PRIMARY,
                added_at=_NOW,
            ),
        ),
        authority_payer_bindings=(
            AuthorityPayerBinding(
                authority_id="authority-main",
                environment="production",
                binding_ref="payer_binding_opaque",
                bound_principal=binding_principal or principal,
                state=AuthorityBindingState.ACTIVE,
            ),
        )
        if binding_principal is not False
        else (),
        created_at=_NOW,
        updated_at=_NOW,
    )


def _rotated_profile() -> BuyerProfile:
    return BuyerProfile(
        profile_id=uuid.UUID("11111111-1111-1111-1111-111111111111"),
        name="buyer",
        primary_principal=_NEW.identity,
        principal_history=(
            ProfilePrincipal(
                principal=_OLD.identity,
                credential_reference=_credential("OLD_SEED"),
                state=PrincipalState.RETAINED,
                added_at=_NOW,
                overlap_until="2030-03-17T17:46:40+00:00",
                rotation_nonce="rotation-nonce",
                rotation_intent_hash="ab" * 32,
            ),
            ProfilePrincipal(
                principal=_NEW.identity,
                credential_reference=_credential("NEW_SEED"),
                state=PrincipalState.PRIMARY,
                added_at=_NOW,
            ),
        ),
        authority_payer_bindings=(
            AuthorityPayerBinding(
                authority_id="authority-main",
                environment="production",
                binding_ref="payer_binding_opaque",
                bound_principal=_OLD.identity,
                state=AuthorityBindingState.ACTIVE,
            ),
        ),
        created_at=_NOW,
        updated_at=_NOW,
    )


@dataclass
class Access:
    profile: BuyerProfile
    signer: Ed25519Signer
    historical_signer: Ed25519Signer = _OLD
    block_retirement: bool = False

    def __post_init__(self) -> None:
        self.updates: list[AuthorityPayerBinding] = []
        self.retirement_checks = []
        self.retirements = []

    def resolve_fresh_signer(self):
        return self.profile, self.signer

    def resolve_recovery_signer(self, *, profile_id, principal):
        assert profile_id == str(self.profile.profile_id)
        assert principal == self.historical_signer.identity
        return self.profile, self.historical_signer

    def set_authority_payer_binding(self, profile_id, binding):
        assert profile_id == str(self.profile.profile_id)
        self.updates.append(binding)
        self.profile = self.profile.model_copy(
            update={"authority_payer_bindings": (binding,)}
        )
        return self.profile

    def ensure_principal_retirable(self, profile, principal):
        self.retirement_checks.append((profile, principal))
        if self.block_retirement:
            raise RuntimeError("recoverable run retains principal")

    def retire_principal(self, profile, principal):
        self.retirements.append((profile, principal))
        return self.profile.redacted()


class Client:
    def __init__(self) -> None:
        self.calls = []
        self.closed = 0
        self.failure = False

    async def aclose(self):
        self.closed += 1

    async def create_payer_profile(self, request):
        self.calls.append(("create", request))
        return PayerProfileResult(
            payer_profile_ref="payer_binding_created",
            primary_principal=request.principal,
            state=PayerProfileState.ACTIVE,
            version=1,
        )

    async def show_payer_profile(self, payer_profile_ref, *, request_id):
        self.calls.append(("show", payer_profile_ref, request_id))
        return PayerProfileResult(
            payer_profile_ref=payer_profile_ref,
            primary_principal=MarketplaceSignerAdapter(_OLD).principal,
            state=PayerProfileState.ACTIVE,
            version=1,
        )

    async def delete_payer_profile(self, request):
        self.calls.append(("payer-delete", request))
        return PayerProfileResult(
            payer_profile_ref=request.payer_profile_ref,
            primary_principal=MarketplaceSignerAdapter(_OLD).principal,
            state=PayerProfileState.DELETED,
            version=2,
        )

    async def rotate_payer_owner(self, request):
        self.calls.append(("rotate", request))
        return PayerProfileResult(
            payer_profile_ref=request.payer_profile_ref,
            primary_principal=request.new_principal,
            state=PayerProfileState.ACTIVE,
            version=2,
        )
    async def retire_payer_owner(self, request):
        self.calls.append(("retire", request))
        return PayerProfileResult(
            payer_profile_ref=request.payer_profile_ref,
            primary_principal=MarketplaceSignerAdapter(_NEW).principal,
            state=PayerProfileState.ACTIVE,
            version=3,
        )


    async def start_payer_setup(self, request):
        self.calls.append(("setup", request))
        return PayerSetupResult(
            setup_ref="setup_opaque_1234",
            readiness=InstrumentReadiness.REQUIRES_ACTION,
            action=PayerAction(
                kind=PayerActionKind.SETUP,
                operation_ref="operation_opaque_1234",
                expires_at_unix=2_000_000_000,
                url="https://transient.example/secret-action",
            ),
        )
    async def get_payer_setup(self, request):
        self.calls.append(("setup-status", request))
        return PayerSetupResult(
            setup_ref=request.setup_ref,
            readiness=InstrumentReadiness.READY,
        )

    async def list_payer_instruments(self, payer_profile_ref, *, request_id):
        self.calls.append(("instrument-list", payer_profile_ref, request_id))
        return InstrumentListResult(
            payer_profile_ref=payer_profile_ref,
            instruments=(_instrument("instrument_opaque_1234", default=True),),
        )


    async def set_default_instrument(self, request):
        self.calls.append(("default", request))
        return _instrument(request.instrument_ref, default=True)

    async def revoke_instrument(self, request):
        self.calls.append(("revoke", request))
        return _instrument(request.instrument_ref, revoked=True)

    async def delete_instrument(self, request):
        self.calls.append(("delete", request))
        return _instrument(request.instrument_ref, revoked=True)


def _instrument(ref: str, *, default: bool = False, revoked: bool = False):
    return InstrumentProjection(
        instrument_ref=ref,
        label="main card",
        kind=InstrumentKind.CARD,
        readiness=(
            InstrumentReadiness.UNAVAILABLE if revoked else InstrumentReadiness.READY
        ),
        is_default=default,
        revoked=revoked,
    )


def _app(context: PayerCommandContext) -> typer.Typer:
    return create_stripe_command_group(lambda: context)


def test_create_atomically_records_only_opaque_selected_owner_binding() -> None:
    access = Access(_profile(binding_principal=False), _OLD)
    client = Client()
    context = PayerCommandContext(
        authority_id="authority-main",
        environment="production",
        profiles=access,
        client_factory=lambda signer: client,
        dispatch_action=lambda _action, _policy: None,
    )
    result = CliRunner().invoke(_app(context), ["payer", "create", "--json"])
    assert result.exit_code == 0
    body = json.loads(result.stdout)
    assert body == {
        "payer_profile_ref": "payer_binding_created",
        "primary_principal": _OLD.identity.model_dump(mode="json"),
        "state": "active",
        "version": 1,
    }
    assert access.updates == [
        AuthorityPayerBinding(
            authority_id="authority-main",
            environment="production",
            binding_ref="payer_binding_created",
            bound_principal=_OLD.identity,
            state=AuthorityBindingState.ACTIVE,
        )
    ]
    assert "cus_" not in result.stdout
    assert "pm_" not in result.stdout
    assert client.closed == 1


def test_show_and_delete_use_selected_owner_and_retire_local_binding() -> None:
    access = Access(_profile(), _OLD)
    client = Client()
    context = PayerCommandContext(
        authority_id="authority-main",
        environment="production",
        profiles=access,
        client_factory=lambda signer: client,
        dispatch_action=lambda _action, _policy: None,
    )
    shown = CliRunner().invoke(_app(context), ["payer", "show", "--json"])
    deleted = CliRunner().invoke(_app(context), ["payer", "delete", "--json"])
    assert shown.exit_code == 0
    assert deleted.exit_code == 0
    assert [call[0] for call in client.calls] == ["show", "payer-delete"]
    assert access.updates[-1].state is AuthorityBindingState.RETIRED
    assert client.closed == 2


def test_setup_dispatches_action_but_never_outputs_or_stores_its_value() -> None:
    access = Access(_profile(), _OLD)
    client = Client()
    dispatched = []
    context = PayerCommandContext(
        authority_id="authority-main",
        environment="production",
        profiles=access,
        client_factory=lambda signer: client,
        dispatch_action=lambda action, policy: dispatched.append((action, policy)),
    )
    result = CliRunner().invoke(
        _app(context),
        [
            "payer",
            "setup",
            "start",
            "--funding-profile",
            "card.v1",
            "--label",
            "main card",
            "--action",
            "print",
            "--json",
        ],
    )
    assert result.exit_code == 0
    assert dispatched[0][1] == "print"
    assert str(dispatched[0][0].url) == "https://transient.example/secret-action"
    assert "transient.example" not in result.stdout
    assert "secret-action" not in result.stdout
    assert json.loads(result.stdout)["action"] == {
        "expires_at_unix": 2_000_000_000,
        "kind": "setup",
    }
    assert client.closed == 1


def test_setup_status_and_instrument_list_return_only_safe_projections() -> None:
    access = Access(_profile(), _OLD)
    client = Client()
    context = PayerCommandContext(
        authority_id="authority-main",
        environment="production",
        profiles=access,
        client_factory=lambda signer: client,
        dispatch_action=lambda _action, _policy: None,
    )
    status = CliRunner().invoke(
        _app(context),
        ["payer", "setup", "status", "setup_opaque_1234", "--json"],
    )
    listed = CliRunner().invoke(
        _app(context),
        ["payer", "instrument", "list", "--json"],
    )
    assert status.exit_code == 0
    assert listed.exit_code == 0
    assert json.loads(status.stdout) == {
        "setup_ref": "setup_opaque_1234",
        "readiness": "ready",
    }
    assert json.loads(listed.stdout)["instruments"] == [
        {
            "instrument_ref": "instrument_opaque_1234",
            "is_default": True,
            "kind": "card",
            "label": "main card",
            "readiness": "ready",
            "revoked": False,
        }
    ]
    assert client.closed == 2


def test_owner_rotation_uses_historical_signer_and_updates_canonical_owner() -> None:
    access = Access(_rotated_profile(), _NEW)
    client = Client()
    used_signers = []
    context = PayerCommandContext(
        authority_id="authority-main",
        environment="production",
        profiles=access,
        client_factory=lambda signer: used_signers.append(signer) or client,
        dispatch_action=lambda _action, _policy: None,
    )
    result = CliRunner().invoke(
        _app(context), ["payer", "owner", "rotate", "--json"]
    )
    assert result.exit_code == 0
    assert used_signers == [_OLD]
    assert client.calls[0][0] == "rotate"
    assert access.updates[0].bound_principal == _NEW.identity
    assert access.updates[0].binding_ref == "payer_binding_opaque"
    assert client.closed == 1


@pytest.mark.parametrize("operation", ["default", "revoke", "delete"])
def test_instrument_mutations_use_direct_released_client_only(operation: str) -> None:
    access = Access(_profile(), _OLD)
    client = Client()
    context = PayerCommandContext(
        authority_id="authority-main",
        environment="production",
        profiles=access,
        client_factory=lambda signer: client,
        dispatch_action=lambda _action, _policy: None,
    )
    result = CliRunner().invoke(
        _app(context),
        ["payer", "instrument", operation, "instrument_opaque_1234", "--json"],
    )
    assert result.exit_code == 0
    assert client.calls[0][0] == operation
    assert json.loads(result.stdout)["instrument_ref"] == "instrument_opaque_1234"
    assert client.closed == 1


def test_payer_client_closes_after_sanitized_remote_failure() -> None:
    class FailingClient(Client):
        async def create_payer_profile(self, request):
            raise RuntimeError("cus_secret https://action.invalid")

    access = Access(_profile(binding_principal=False), _OLD)
    client = FailingClient()
    context = PayerCommandContext(
        authority_id="authority-main",
        environment="production",
        profiles=access,
        client_factory=lambda signer: client,
        dispatch_action=lambda _action, _policy: None,
    )
    result = CliRunner().invoke(_app(context), ["payer", "create", "--json"])
    assert result.exit_code == 2
    assert client.closed == 1
    assert "cus_secret" not in result.stdout
    assert "action.invalid" not in result.stdout


def test_push_bank_transfer_setup_rejects_before_client_construction() -> None:
    access = Access(_profile(), _OLD)
    clients = []
    context = PayerCommandContext(
        authority_id="authority-main",
        environment="production",
        profiles=access,
        client_factory=lambda signer: clients.append(Client()) or clients[-1],
        dispatch_action=lambda _action, _policy: None,
    )
    result = CliRunner().invoke(
        _app(context),
        [
            "payer",
            "setup",
            "start",
            "--funding-profile",
            "us_bank_transfer.v1",
            "--label",
            "not applicable",
        ],
    )
    assert result.exit_code == 2
    assert clients == []


def test_owner_retirement_blocker_prevents_hosted_mutation() -> None:
    profile = _rotated_profile()
    binding = profile.authority_payer_bindings[0].model_copy(
        update={"bound_principal": _NEW.identity}
    )
    access = Access(
        profile.model_copy(update={"authority_payer_bindings": (binding,)}),
        _NEW,
        block_retirement=True,
    )
    client = Client()
    context = PayerCommandContext(
        authority_id="authority-main",
        environment="production",
        profiles=access,
        client_factory=lambda signer: client,
        dispatch_action=lambda _action, _policy: None,
    )
    target = f"{_OLD.identity.scheme.value}:{_OLD.identity.identifier}"
    result = CliRunner().invoke(
        _app(context),
        ["payer", "owner", "retire", "--principal", target],
    )
    assert result.exit_code == 2
    assert len(access.retirement_checks) == 1
    assert client.calls == []
    assert client.closed == 0


def test_cli_tree_registers_every_exact_namespaced_operation() -> None:
    context = PayerCommandContext(
        authority_id="authority-main",
        environment="production",
        profiles=Access(_profile(), _OLD),
        client_factory=lambda signer: Client(),
        dispatch_action=lambda _action, _policy: None,
    )
    runner = CliRunner()
    assert runner.invoke(_app(context), ["payer", "--help"]).exit_code == 0
    for group, commands in {
        "owner": ("rotate", "retire"),
        "setup": ("start", "status"),
        "instrument": ("list", "default", "revoke", "delete"),
    }.items():
        output = runner.invoke(_app(context), ["payer", group, "--help"]).stdout
        assert all(command in output for command in commands)
