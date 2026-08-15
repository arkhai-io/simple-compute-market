"""Direct provider-neutral payer operations over the released hosted client."""

from __future__ import annotations

import hashlib
import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from hosted_settlement_client import (
    ClientConfig,
    FundingProfile,
    HostedSettlementAsyncClient,
    InstrumentMutationRequest,
    PayerOwnerRetirement,
    PayerOwnerRotation,
    PayerProfileRequest,
    PayerSetupRequest,
    PayerSetupStatusRequest,
    Principal,
    sign_payer_owner_retirement,
    sign_payer_owner_rotation,
    sign_payer_profile_creation,
)
from hosted_settlement_client import IdentityScheme as HostedIdentityScheme
from market_identity import AuthorityPayerBinding, BuyerProfile, Identity, Signer

from .adapter import (
    MarketplaceSignerAdapter,
    adapt_expected_authorities,
)
from .settlement_config import StripeSettlementConfig


class HostedPayerError(RuntimeError):
    """A deterministic provider-redacted direct payer failure."""


class PayerProfileAccess(Protocol):
    """Owner-only persistent-profile operations injected by buyer composition."""

    def resolve_fresh_signer(self) -> tuple[BuyerProfile, Signer]: ...

    def resolve_recovery_signer(
        self,
        *,
        profile_id: str,
        principal: Identity,
    ) -> tuple[BuyerProfile, Signer]: ...

    def set_authority_payer_binding(
        self,
        profile_id: str,
        binding: AuthorityPayerBinding,
    ) -> BuyerProfile: ...

    def retire_principal(self, profile: str, principal: Identity) -> dict[str, Any]: ...


PayerClientFactory = Callable[[Signer], Any]
ActionDispatcher = Callable[[Any, str | None], Any]


@dataclass(frozen=True, slots=True)
class PayerCommandContext:
    """Callbacks and public authority coordinates for one payer command."""

    authority_id: str
    environment: str
    profiles: PayerProfileAccess = field(repr=False)
    client_factory: PayerClientFactory = field(repr=False)
    dispatch_action: ActionDispatcher = field(repr=False)

    def facade(self, signer: Signer) -> HostedPayerFacade:
        return HostedPayerFacade(
            client=self.client_factory(signer),
            signer=signer,
            authority_id=self.authority_id,
            environment=self.environment,
        )


def payer_command_context_from_config(
    config: Any,
    *,
    profiles: PayerProfileAccess,
    dispatch_action: ActionDispatcher,
) -> PayerCommandContext:
    """Build direct payer clients from one exact validated hosted config."""


    resolved = StripeSettlementConfig.model_validate(config)
    if (
        not resolved.enabled
        or resolved.base_url is None
        or resolved.authority_id is None
        or resolved.environment is None
        or resolved.authority is None
    ):
        raise ValueError("hosted payer commands require enabled exact authority config")

    def client_factory(signer: Signer) -> HostedSettlementAsyncClient:
        return HostedSettlementAsyncClient(
            ClientConfig(
                base_url=resolved.base_url,
                signer=MarketplaceSignerAdapter(signer),
                caller_role="buyer",
                authority_id=resolved.authority_id,
                environment=resolved.environment,
                expected_authorities=adapt_expected_authorities(
                    resolved.authority.as_trusted_set()
                ),
                timeout_seconds=resolved.request_timeout_seconds,
                allow_insecure_loopback=resolved.allow_insecure_loopback,
            )
        )

    return PayerCommandContext(
        authority_id=resolved.authority_id,
        environment=resolved.environment,
        profiles=profiles,
        client_factory=client_factory,
        dispatch_action=dispatch_action,
    )


async def _await_if_needed(value: Any) -> Any:
    return await value if inspect.isawaitable(value) else value


def _request_id(operation: str, *values: str) -> str:
    digest = hashlib.sha256("\x00".join(values).encode()).hexdigest()
    return f"payer:{operation}:{digest}"


def _hosted_principal(identity: Identity) -> Principal:
    return Principal(
        scheme=HostedIdentityScheme(identity.scheme.value),
        identifier=identity.identifier,
    )


class HostedPayerFacade:
    """Use hosted signing helpers and models without reproducing wire behavior."""

    __slots__ = ("_authority_id", "_client", "_environment", "_signer")

    def __init__(
        self,
        *,
        client: Any,
        signer: Signer,
        authority_id: str,
        environment: str,
    ) -> None:
        if not authority_id or not environment:
            raise ValueError("payer authority and environment are required")
        self._client = client
        self._signer = MarketplaceSignerAdapter(signer)
        self._authority_id = authority_id
        self._environment = environment

    async def _remote(self, operation: str, call: Callable[[], Any]) -> Any:
        try:
            return await _await_if_needed(call())
        except Exception:
            raise HostedPayerError(f"hosted payer {operation} failed") from None

    async def create(self, *, country: Literal["US"] = "US") -> Any:
        if country != "US":
            raise ValueError("hosted payer country must be US")
        request_id = _request_id(
            "create",
            self._authority_id,
            self._environment,
            self._signer.principal.scheme.value,
            self._signer.principal.identifier,
            country,
        )
        request = sign_payer_profile_creation(
            signer=self._signer,
            authority_id=self._authority_id,
            environment=self._environment,
            request_id=request_id,
            country=country,
        )
        return await self._remote(
            "create",
            lambda: self._client.create_payer_profile(request),
        )

    async def show(self, payer_profile_ref: str) -> Any:
        request_id = _request_id("show", payer_profile_ref)
        return await self._remote(
            "show",
            lambda: self._client.show_payer_profile(
                payer_profile_ref,
                request_id=request_id,
            ),
        )

    async def delete(self, payer_profile_ref: str) -> Any:
        request = PayerProfileRequest(
            request_id=_request_id("delete", payer_profile_ref),
            payer_profile_ref=payer_profile_ref,
        )
        return await self._remote(
            "delete",
            lambda: self._client.delete_payer_profile(request),
        )

    async def rotate_owner(
        self,
        *,
        payer_profile_ref: str,
        new_signer: Signer,
        nonce: str,
        overlap_until_unix: int,
        valid_until_unix: int,
    ) -> Any:
        request_id = _request_id(
            "owner-rotate",
            payer_profile_ref,
            self._signer.principal.scheme.value,
            self._signer.principal.identifier,
            new_signer.identity.scheme.value,
            new_signer.identity.identifier,
            nonce,
            str(overlap_until_unix),
            str(valid_until_unix),
        )
        rotation: PayerOwnerRotation = sign_payer_owner_rotation(
            old_signer=self._signer,
            new_signer=MarketplaceSignerAdapter(new_signer),
            authority_id=self._authority_id,
            environment=self._environment,
            request_id=request_id,
            payer_profile_ref=payer_profile_ref,
            nonce=nonce,
            overlap_until_unix=overlap_until_unix,
            valid_until_unix=valid_until_unix,
        )
        return await self._remote(
            "owner rotation",
            lambda: self._client.rotate_payer_owner(rotation),
        )

    async def retire_owner(
        self,
        *,
        payer_profile_ref: str,
        principal: Identity,
    ) -> Any:
        request_id = _request_id(
            "owner-retire",
            payer_profile_ref,
            principal.scheme.value,
            principal.identifier,
        )
        retirement: PayerOwnerRetirement = sign_payer_owner_retirement(
            signer=self._signer,
            authority_id=self._authority_id,
            environment=self._environment,
            request_id=request_id,
            payer_profile_ref=payer_profile_ref,
            principal=_hosted_principal(principal),
        )
        return await self._remote(
            "owner retirement",
            lambda: self._client.retire_payer_owner(retirement),
        )

    async def start_setup(
        self,
        *,
        payer_profile_ref: str,
        funding_profile: FundingProfile,
        label: str,
    ) -> Any:
        request = PayerSetupRequest(
            request_id=_request_id(
                "setup-start",
                payer_profile_ref,
                funding_profile.value,
                label,
            ),
            payer_profile_ref=payer_profile_ref,
            funding_profile=funding_profile,
            label=label,
        )
        return await self._remote(
            "setup start",
            lambda: self._client.start_payer_setup(request),
        )

    async def setup_status(
        self,
        *,
        payer_profile_ref: str,
        setup_ref: str,
    ) -> Any:
        request = PayerSetupStatusRequest(
            request_id=_request_id("setup-status", payer_profile_ref, setup_ref),
            payer_profile_ref=payer_profile_ref,
            setup_ref=setup_ref,
        )
        return await self._remote(
            "setup status",
            lambda: self._client.get_payer_setup(request),
        )

    async def list_instruments(self, payer_profile_ref: str) -> Any:
        request_id = _request_id("instrument-list", payer_profile_ref)
        return await self._remote(
            "instrument list",
            lambda: self._client.list_payer_instruments(
                payer_profile_ref,
                request_id=request_id,
            ),
        )

    async def mutate_instrument(
        self,
        operation: str,
        *,
        payer_profile_ref: str,
        instrument_ref: str,
    ) -> Any:
        methods: dict[str, Callable[[Any], Awaitable[Any] | Any]] = {
            "default": self._client.set_default_instrument,
            "revoke": self._client.revoke_instrument,
            "delete": self._client.delete_instrument,
        }
        if operation not in methods:
            raise ValueError("unknown payer instrument operation")
        request = InstrumentMutationRequest(
            request_id=_request_id(operation, payer_profile_ref, instrument_ref),
            payer_profile_ref=payer_profile_ref,
            instrument_ref=instrument_ref,
        )
        return await self._remote(
            f"instrument {operation}",
            lambda: methods[operation](request),
        )


def payer_profile_projection(result: Any) -> dict[str, Any]:
    """Return only the opaque binding and safe owner lifecycle."""

    principal = result.primary_principal.model_dump(mode="json")
    return {
        "payer_profile_ref": result.payer_profile_ref,
        "primary_principal": principal,
        "state": result.state.value,
        "version": result.version,
    }


def payer_setup_projection(result: Any) -> dict[str, Any]:
    """Exclude all transient action values from command JSON."""

    projection: dict[str, Any] = {
        "setup_ref": result.setup_ref,
        "readiness": result.readiness.value,
    }
    if result.action is not None:
        projection["action"] = {
            "kind": result.action.kind.value,
            "expires_at_unix": result.action.expires_at_unix,
        }
    return projection


def instrument_projection(result: Any) -> dict[str, Any]:
    """Project only released opaque instrument lifecycle fields."""

    return {
        "instrument_ref": result.instrument_ref,
        "label": result.label,
        "kind": result.kind.value,
        "readiness": result.readiness.value,
        "is_default": result.is_default,
        "revoked": result.revoked,
    }


def instrument_list_projection(result: Any) -> dict[str, Any]:
    return {
        "payer_profile_ref": result.payer_profile_ref,
        "instruments": [instrument_projection(item) for item in result.instruments],
    }


__all__ = [
    "ActionDispatcher",
    "HostedPayerError",
    "HostedPayerFacade",
    "PayerClientFactory",
    "PayerCommandContext",
    "PayerProfileAccess",
    "payer_command_context_from_config",
    "instrument_list_projection",
    "instrument_projection",
    "payer_profile_projection",
    "payer_setup_projection",
]
