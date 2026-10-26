"""The buyer's settlement composition over the stage entries its plugin injects."""

from __future__ import annotations

import inspect
from collections.abc import Callable, Mapping
from typing import Any

import typer
from core_buyer.buyer_config import ResolvedBuyerIdentity
from core_buyer.settlement import BuyerSettlementPolicy
from market_config.config_loader import load_user_config
from market_core import SettlementStageTable
from market_core.schemas import Agreement
from market_settlement_runtime import (
    MechanismReadiness,
    SettlementConfig,
    SettlementConfigurationRegistry,
)

from arkhai_api_buying.common import resolve_fresh_buyer_identity
from arkhai_api_buying.contributions import BuyingContributions
from arkhai_api_buying.credentials import CredentialStore, FileCredentialStore
from arkhai_api_buying.stages import BuyerStage, BuySession, EscrowCodec, StageOption, StageOptions


class _NoEscrow:
    """The codec of a table with no stage that negotiates an escrow proposal."""

    def encode_proposal(self, proposal: Any) -> dict[str, Any]:
        raise ValueError("no installed settlement stage negotiates an escrow proposal")

    def decode_proposal(self, value: Any) -> Any:
        raise ValueError("no installed settlement stage decodes an escrow proposal")

    def decode_terms(self, value: Any) -> Any:
        raise ValueError("no installed settlement stage decodes escrow terms")


class BuyerSettlementComposition:
    """One plugin's stage table, the selection, acceptance, and readiness read through it.

    ``credential_store`` keeps the keys its runs deliver.
    """

    def __init__(
        self,
        contributions: BuyingContributions,
        stages: SettlementStageTable[BuyerStage],
        *,
        credential_store: CredentialStore | None = None,
    ) -> None:
        for mechanism, stage in stages.items():
            if stage.mechanism_id != mechanism:
                raise ValueError(f"stage table entry {mechanism!r} holds the {stage.mechanism_id!r} stage")
        self.contributions = contributions
        self.stages = stages
        self.credential_store: CredentialStore = credential_store or FileCredentialStore()
        self._options: dict[str, dict[str, StageOption]] = {}
        for stage in stages.values():
            for option in stage.options:
                command = self._options.setdefault(option.command, {})
                if option.name in command:
                    raise ValueError(
                        f"two buyer stages contribute the {option.command} option {option.name!r}"
                    )
                command[option.name] = option
        codecs = [stage.escrow_codec for stage in stages.values() if stage.escrow_codec is not None]
        if len(codecs) > 1:
            raise ValueError("at most one buyer stage may negotiate an escrow proposal")
        self.escrow_codec: EscrowCodec = codecs[0] if codecs else _NoEscrow()

    def stage(self, agreement: Any) -> BuyerStage:
        accepted = Agreement.model_validate(agreement)
        if accepted.settlement is None:
            raise ValueError("accepted Agreement has no settlement option")
        try:
            return self.stages[accepted.settlement.mechanism]
        except KeyError as exc:
            raise ValueError(
                f"unsupported accepted {self.contributions.noun} settlement mechanism"
            ) from exc

    def options(self, command: str) -> tuple[StageOption, ...]:
        return tuple(self._options.get(command, {}).values())

    def add_options(self, fn: Callable[..., Any], command: str) -> Callable[..., Any]:
        """Add every stage's options for ``command`` to ``fn``'s signature; their values reach its ``**kwargs``."""
        signature = inspect.signature(fn)
        parameters = [
            parameter
            for parameter in signature.parameters.values()
            if parameter.kind is not inspect.Parameter.VAR_KEYWORD
        ]
        taken = {parameter.name for parameter in parameters}
        for option in self.options(command):
            if option.name in taken:
                raise ValueError(f"a stage's {command} option {option.name!r} names one of the command's own")
            parameters.append(
                inspect.Parameter(
                    option.name,
                    inspect.Parameter.KEYWORD_ONLY,
                    default=typer.Option(option.default, *option.flags, help=option.help),
                    annotation=option.annotation,
                )
            )
        fn.__signature__ = signature.replace(parameters=parameters)
        return fn

    def split_options(
        self, values: Mapping[str, Any], command: str,
    ) -> tuple[StageOptions, dict[str, Any]]:
        """Separate the stages' option values from the rest of a command's keyword values."""
        names = self._options.get(command, {})
        return (
            {name: values.get(name, option.default) for name, option in names.items()},
            {key: value for key, value in values.items() if key not in names},
        )

    def chain_config_paths(self) -> dict[str, str | None]:
        paths: dict[str, str | None] = {}
        for stage in self.stages.values():
            paths.update(stage.chain_config_paths())
        return paths

    def validate_acceptance(self, outcome: Any) -> None:
        self.stage(outcome.agreement).validate_acceptance(outcome)

    def registry(self) -> SettlementConfigurationRegistry:
        return SettlementConfigurationRegistry(
            tuple(stage.registration() for stage in self.stages.values())
        )

    def select_proposal(
        self,
        policy: BuyerSettlementPolicy,
        listing: Mapping[str, Any],
        sessions: Mapping[str, BuySession],
        *,
        expiration_unix: int,
    ) -> Any:
        """The first enabled mechanism's proposal for a listing, in the buyer's priority order."""
        for registration in policy.registry.ordered_registrations(policy.config, role="buyer"):
            section = policy.config.mechanism_config(registration.config_key)
            if section is None or not getattr(section, "enabled", False):
                continue
            session = sessions.get(registration.mechanism_id)
            if session is not None:
                selected = session.propose(listing, expiration_unix=expiration_unix)
                if selected is not None:
                    return selected
        return None

    def resolve_policy(
        self,
        config: Mapping[str, Any] | None = None,
        *,
        identity: ResolvedBuyerIdentity | None = None,
    ) -> BuyerSettlementPolicy:
        """Resolve the shared hierarchy without constructing unused mechanisms."""
        document = dict(load_user_config() if config is None else config)
        if "settlement" in document:
            raise ValueError(
                "legacy [settlement] configuration is not supported; run "
                "`market config migrate --scope settlement --write --backup`"
            )
        raw = document.get("Settlement", {})
        if not isinstance(raw, Mapping):
            raise ValueError("[Settlement] must be a table")
        registry = self.registry()
        return BuyerSettlementPolicy(
            config=registry.resolve(raw, role="buyer"),
            registry=registry,
            stages=self.stages,
            public_context={},
        )

    async def readiness(self) -> tuple[SettlementConfig, tuple[MechanismReadiness, ...]]:
        """Observe only enabled mechanism prerequisites."""
        policy = self.resolve_policy(identity=resolve_fresh_buyer_identity())
        resources: dict[str, Any] = {}
        for registration in policy.registry.ordered_registrations(policy.config, role="buyer"):
            stage = self.stages.get(registration.mechanism_id)
            section = policy.config.mechanism_config(registration.config_key)
            if stage is not None and section is not None and getattr(section, "enabled", False):
                resources.update(stage.resources())
        statuses = await policy.registry.ordered_readiness(
            policy.config,
            role="buyer",
            resources=resources,
        )
        return policy.config, statuses
