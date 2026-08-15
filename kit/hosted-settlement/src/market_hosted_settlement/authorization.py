"""Exact accepted-obligation funding authorization through the released client."""

from __future__ import annotations

import hashlib
import inspect
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Annotated, Any, Literal

from hosted_settlement_client import (
    ConditionDescriptor,
    FundingMode,
    FundingProfile,
    HostedSettlementError,
    InstrumentKind,
    InstrumentReadiness,
    PayerProfileState,
    Principal,
    sign_funding_authorization,
)
from market_identity import (
    AuthorityBindingState,
    AuthorityPayerBinding,
    Identity,
    Signer,
)
from market_settlement_runtime import obligation_payload_hash
from pydantic import BaseModel, ConfigDict, Field

from .adapter import MECHANISM, MarketplaceSignerAdapter
from .automation import (
    AuthorizationReservationJournal,
    AutomationCandidate,
    OffSessionPolicy,
)
from .payer import HostedPayerFacade
from .settlement_config import (
    StripeSettlementConfig,
    stripe_contract_fingerprint,
    stripe_preflight,
)


class AuthorizationModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class _AcceptedAuthorizationParams(AuthorizationModel):
    account_ref: str = Field(min_length=1, max_length=256)
    claimant_principal: Principal
    funds_flow: Literal["separate_charges_transfers"]
    funding_profile: Annotated[FundingProfile, Field(strict=False)]
    interaction: Annotated[FundingMode, Field(strict=False)]
    contract_fingerprint: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    condition: ConditionDescriptor


class AcceptedFundingAuthorization(AuthorizationModel):
    """Immutable accepted commercial facts that the payer may authorize."""

    obligation_ref: str = Field(pattern=r"^[0-9a-f]{64}$")
    obligation_hash: str = Field(pattern=r"^0x[0-9a-f]{64}$")
    payer_principal: Identity
    seller_principal: Identity
    amount: int = Field(gt=0)
    currency: Literal["usd"]
    destination_account_ref: str = Field(min_length=1, max_length=256)
    funding_profile: Annotated[FundingProfile, Field(strict=False)]
    interaction: Annotated[FundingMode, Field(strict=False)]
    funds_flow: Literal["separate_charges_transfers"]
    contract_fingerprint: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    expires_at_unix: int = Field(gt=0)

    @property
    def marketplace_operation_id(self) -> str:
        return self.obligation_ref


@dataclass(frozen=True, slots=True)
class FundingSelection:
    """Transient buyer selection; raw saved instrument never enters repr."""

    mode: FundingMode
    instrument_ref: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if self.mode is FundingMode.INTERACTIVE and self.instrument_ref is not None:
            raise ValueError("interactive funding cannot select an instrument")
        if self.mode is FundingMode.SAVED_INSTRUMENT and not self.instrument_ref:
            raise ValueError("saved funding requires one opaque instrument reference")


class AuthorizationReadiness(AuthorizationModel):
    binding_ready: bool
    profile_ready: bool
    instrument_ready: bool
    mandate_or_consent_ready: bool

    @property
    def ready(self) -> bool:
        return (
            self.binding_ready
            and self.profile_ready
            and self.instrument_ready
            and self.mandate_or_consent_ready
        )


class FundingAuthorizationReceipt(AuthorizationModel):
    funding_profile: Annotated[FundingProfile, Field(strict=False)]
    marketplace_operation_id: str = Field(min_length=1, max_length=256)
    funding_authorization_ref: str = Field(min_length=1, max_length=256)
    expires_at_unix: int = Field(gt=0)


class HostedAuthorizationError(RuntimeError):
    """A provider-redacted exact authorization failure."""

    def __init__(self, message: str, *, uncertain: bool = False) -> None:
        self.uncertain = uncertain
        super().__init__(message)


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"accepted obligation {name} is malformed")
    return value


def derive_accepted_funding_authorization(
    *,
    obligation_ref: str,
    obligation: Mapping[str, Any],
) -> AcceptedFundingAuthorization:
    """Derive exact producer inputs only from one durable accepted obligation."""

    if (
        obligation.get("mechanism") != MECHANISM
        or obligation.get("payer") != "buyer"
        or obligation.get("claimant") != "seller"
    ):
        raise ValueError("accepted obligation is not a buyer-funded hosted payment")
    params = _AcceptedAuthorizationParams.model_validate(
        _mapping(obligation.get("params"), "params")
    )
    amount_value = obligation.get("amount")
    amount: Any = (
        int(amount_value)
        if isinstance(amount_value, str) and amount_value.isdecimal()
        else amount_value
    )
    payer = Identity.model_validate(obligation.get("payer_principal"))
    seller = Identity.model_validate(obligation.get("claimant_principal"))
    params_seller = Identity.model_validate(
        params.claimant_principal.model_dump(mode="json")
    )
    if params_seller != seller:
        raise ValueError("accepted hosted claimant principal is inconsistent")
    return AcceptedFundingAuthorization(
        obligation_ref=obligation_ref,
        obligation_hash="0x" + obligation_payload_hash(obligation),
        payer_principal=payer,
        seller_principal=seller,
        amount=amount,
        currency=obligation.get("asset"),
        destination_account_ref=params.account_ref,
        funding_profile=params.funding_profile,
        interaction=params.interaction,
        funds_flow=params.funds_flow,
        contract_fingerprint=params.contract_fingerprint,
        expires_at_unix=obligation.get("expiration_unix"),
    )


def authorization_input_fingerprint(
    accepted: AcceptedFundingAuthorization,
    *,
    binding: AuthorityPayerBinding,
    selection: FundingSelection,
) -> str:
    """Hash every exact direct input without persisting opaque stable refs."""

    payload = {
        "accepted": accepted.model_dump(mode="json"),
        "authority_id": binding.authority_id,
        "environment": binding.environment,
        "binding_ref": binding.binding_ref,
        "mode": selection.mode.value,
        "instrument_ref": selection.instrument_ref,
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


async def _await_if_needed(value: Any) -> Any:
    return await value if inspect.isawaitable(value) else value


class HostedFundingAuthorizer:
    """Revalidate exact public readiness, sign, and authorize one accepted input."""

    __slots__ = ("_client", "_config", "_signer")

    def __init__(
        self,
        *,
        config: StripeSettlementConfig,
        client: Any,
        signer: Signer,
    ) -> None:
        self._config = StripeSettlementConfig.model_validate(config)
        self._client = client
        self._signer = signer

    def _validate_binding(self, binding: AuthorityPayerBinding) -> None:
        if (
            binding.authority_id != self._config.authority_id
            or binding.environment != self._config.environment
            or binding.state is not AuthorityBindingState.ACTIVE
            or binding.bound_principal != self._signer.identity
        ):
            raise HostedAuthorizationError("hosted payer binding is not active")

    async def revalidate(
        self,
        accepted: AcceptedFundingAuthorization,
        *,
        binding: AuthorityPayerBinding,
        selection: FundingSelection,
    ) -> AuthorizationReadiness:
        """Re-fetch release, payer, profile, instrument, and consent readiness."""

        self._validate_binding(binding)
        if selection.mode is not accepted.interaction:
            raise HostedAuthorizationError(
                "funding selection differs from the accepted interaction"
            )
        if accepted.contract_fingerprint != stripe_contract_fingerprint(self._config):
            raise HostedAuthorizationError(
                "accepted hosted contract does not match current consumer contract"
            )
        if (
            accepted.funding_profile is FundingProfile.US_BANK_TRANSFER
            and selection.mode is FundingMode.SAVED_INSTRUMENT
        ):
            raise HostedAuthorizationError(
                "push bank transfer requires interactive funding"
            )
        status = await stripe_preflight(
            self._config,
            {
                "marketplace_signer": self._signer,
                "preflight_client": self._client,
            },
            "buyer",
        )
        profile_state = status.public_details.get("profiles", {}).get(
            accepted.funding_profile.value,
            {},
        )
        if not status.ready or profile_state.get("ready") is not True:
            raise HostedAuthorizationError("hosted funding profile is not ready")
        facade = HostedPayerFacade(
            client=self._client,
            signer=self._signer,
            authority_id=binding.authority_id,
            environment=binding.environment,
        )
        payer = await facade.show(binding.binding_ref)
        if payer.state is not PayerProfileState.ACTIVE:
            raise HostedAuthorizationError("hosted payer ownership is not active")
        instrument_ready = selection.mode is FundingMode.INTERACTIVE
        consent_ready = selection.mode is FundingMode.INTERACTIVE
        if selection.mode is FundingMode.SAVED_INSTRUMENT:
            instruments = await facade.list_instruments(binding.binding_ref)
            selected = next(
                (
                    item
                    for item in instruments.instruments
                    if item.instrument_ref == selection.instrument_ref
                ),
                None,
            )
            expected_kind = (
                InstrumentKind.CARD
                if accepted.funding_profile is FundingProfile.CARD
                else InstrumentKind.US_BANK_ACCOUNT
            )
            instrument_ready = bool(
                selected is not None
                and selected.kind is expected_kind
                and selected.readiness is InstrumentReadiness.READY
                and not selected.revoked
            )
            consent_ready = instrument_ready
        readiness = AuthorizationReadiness(
            binding_ready=True,
            profile_ready=True,
            instrument_ready=instrument_ready,
            mandate_or_consent_ready=consent_ready,
        )
        if not readiness.ready:
            raise HostedAuthorizationError(
                "saved instrument or mandate readiness is unavailable"
            )
        return readiness

    async def _send(
        self,
        accepted: AcceptedFundingAuthorization,
        *,
        binding: AuthorityPayerBinding,
        selection: FundingSelection,
        fingerprint: str,
    ) -> FundingAuthorizationReceipt:
        try:
            request = sign_funding_authorization(
                signer=MarketplaceSignerAdapter(self._signer),
                authority_id=binding.authority_id,
                environment=binding.environment,
                request_id=(
                    "funding-authorization:"
                    + fingerprint.removeprefix("sha256:")
                ),
                payer_profile_ref=binding.binding_ref,
                instrument_ref=selection.instrument_ref,
                mode=selection.mode,
                obligation_hash=accepted.obligation_hash,
                amount=accepted.amount,
                currency=accepted.currency,
                destination_account_ref=accepted.destination_account_ref,
                funding_profile=accepted.funding_profile,
                marketplace_operation_id=accepted.marketplace_operation_id,
                expires_at_unix=accepted.expires_at_unix,
            )
        except (TypeError, ValueError):
            raise HostedAuthorizationError(
                "accepted funding authorization input is invalid"
            ) from None
        try:
            result = await _await_if_needed(self._client.authorize_funding(request))
        except HostedSettlementError as exc:
            raise HostedAuthorizationError(
                "hosted funding authorization failed",
                uncertain=exc.retryable,
            ) from None
        except Exception:
            raise HostedAuthorizationError(
                "hosted funding authorization failed",
                uncertain=True,
            ) from None
        if result.expires_at_unix != accepted.expires_at_unix:
            raise HostedAuthorizationError(
                "hosted authorization expiry does not match",
                uncertain=True,
            )
        return FundingAuthorizationReceipt(
            funding_profile=accepted.funding_profile,
            marketplace_operation_id=accepted.marketplace_operation_id,
            funding_authorization_ref=result.funding_authorization_ref,
            expires_at_unix=result.expires_at_unix,
        )

    async def authorize(
        self,
        accepted: AcceptedFundingAuthorization,
        *,
        binding: AuthorityPayerBinding,
        selection: FundingSelection,
    ) -> FundingAuthorizationReceipt:
        """Authorize the immutable accepted operation after immediate revalidation."""

        if accepted.payer_principal != self._signer.identity:
            raise HostedAuthorizationError("accepted payer does not match selected signer")
        await self.revalidate(accepted, binding=binding, selection=selection)
        fingerprint = authorization_input_fingerprint(
            accepted,
            binding=binding,
            selection=selection,
        )
        return await self._send(
            accepted,
            binding=binding,
            selection=selection,
            fingerprint=fingerprint,
        )

    async def authorize_automatically(
        self,
        accepted: AcceptedFundingAuthorization,
        *,
        binding: AuthorityPayerBinding,
        selection: FundingSelection,
        policy: OffSessionPolicy,
        journal: AuthorizationReservationJournal,
        now_unix: int,
    ) -> FundingAuthorizationReceipt:
        """Reserve aggregate capacity then sign the same exact authorization."""

        readiness = await self.revalidate(
            accepted,
            binding=binding,
            selection=selection,
        )
        fingerprint = authorization_input_fingerprint(
            accepted,
            binding=binding,
            selection=selection,
        )
        candidate = AutomationCandidate(
            authority_id=binding.authority_id,
            environment=binding.environment,
            funding_profile=accepted.funding_profile,
            currency=accepted.currency,
            amount=accepted.amount,
            seller_principal=accepted.seller_principal,
            mode=selection.mode,
            binding_ready=readiness.binding_ready,
            instrument_ready=readiness.instrument_ready,
            mandate_or_consent_ready=readiness.mandate_or_consent_ready,
        )
        journal.reserve(
            policy=policy,
            candidate=candidate,
            marketplace_operation_id=accepted.marketplace_operation_id,
            input_fingerprint=fingerprint,
            expires_at_unix=accepted.expires_at_unix,
            now_unix=now_unix,
        )
        receipt = await self._send(
            accepted,
            binding=binding,
            selection=selection,
            fingerprint=fingerprint,
        )
        journal.record_authorized(
            marketplace_operation_id=accepted.marketplace_operation_id,
            input_fingerprint=fingerprint,
            funding_authorization_ref=receipt.funding_authorization_ref,
        )
        return receipt


__all__ = [
    "AcceptedFundingAuthorization",
    "AuthorizationReadiness",
    "FundingAuthorizationReceipt",
    "FundingSelection",
    "HostedAuthorizationError",
    "HostedFundingAuthorizer",
    "authorization_input_fingerprint",
    "derive_accepted_funding_authorization",
]
