"""Typer contribution for direct hosted payer lifecycle commands."""

from __future__ import annotations

import asyncio
import inspect
import json
from collections.abc import Callable
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any

import typer
from hosted_settlement_client import FundingProfile
from market_identity import (
    AuthorityBindingState,
    AuthorityPayerBinding,
    BuyerProfile,
    Identity,
    IdentityScheme,
    Signer,
)

from .payer import (
    HostedPayerError,
    PayerCommandContext,
    instrument_list_projection,
    instrument_projection,
    payer_profile_projection,
    payer_setup_projection,
)


class PayerCommandError(RuntimeError):
    """A safe local payer command precondition failure."""


def _binding(
    context: PayerCommandContext,
    profile: BuyerProfile,
) -> AuthorityPayerBinding:
    matches = tuple(
        binding
        for binding in profile.authority_payer_bindings
        if binding.authority_id == context.authority_id
        and binding.environment == context.environment
    )
    if len(matches) != 1:
        raise PayerCommandError("selected profile has no exact hosted payer binding")
    return matches[0]


def _selected_owner(
    context: PayerCommandContext,
) -> tuple[BuyerProfile, Signer, AuthorityPayerBinding]:
    profile, signer = context.profiles.resolve_fresh_signer()
    binding = _binding(context, profile)
    if (
        binding.state is not AuthorityBindingState.ACTIVE
        or binding.bound_principal != signer.identity
        or profile.primary_principal != signer.identity
    ):
        raise PayerCommandError("selected hosted payer ownership is not active")
    return profile, signer, binding


def _principal(value: str) -> Identity:
    scheme, separator, identifier = value.partition(":")
    if not separator or not identifier:
        raise PayerCommandError("principal must be one canonical scheme:identifier")
    try:
        return Identity(scheme=IdentityScheme(scheme), identifier=identifier)
    except (TypeError, ValueError):
        raise PayerCommandError("principal must be one canonical scheme:identifier") from None


def _epoch(value: str | None) -> int:
    if value is None:
        raise PayerCommandError("local owner rotation metadata is incomplete")
    try:
        return int(datetime.fromisoformat(value).timestamp())
    except ValueError:
        raise PayerCommandError("local owner rotation metadata is invalid") from None


def _action(value: str | None) -> str | None:
    if value is not None and value not in {"open", "print", "fail"}:
        raise PayerCommandError("action must be open, print, or fail")
    return value


async def _dispatch_action(
    context: PayerCommandContext,
    result: Any,
    requested: str | None,
) -> None:
    action = getattr(result, "action", None)
    if action is None:
        return
    dispatched = context.dispatch_action(action, _action(requested))
    if inspect.isawaitable(dispatched):
        await dispatched


def _emit(value: dict[str, Any], *, json_output: bool) -> None:
    typer.echo(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":") if json_output else None,
            indent=None if json_output else 2,
        )
    )


def _invoke(operation: Callable[[], Any]) -> Any:
    try:
        return asyncio.run(operation())
    except (HostedPayerError, PayerCommandError) as exc:
        typer.secho(str(exc), err=True, fg=typer.colors.RED)
        raise typer.Exit(2) from None
    except Exception:
        typer.secho("hosted payer command failed", err=True, fg=typer.colors.RED)
        raise typer.Exit(2) from None


@asynccontextmanager
async def _facade(context: PayerCommandContext, signer: Signer):
    facade = context.facade(signer)
    try:
        yield facade
    finally:
        await facade.aclose()


def create_stripe_command_group(
    context_factory: Callable[[], PayerCommandContext],
) -> typer.Typer:
    """Create the mechanism-owned ``stripe payer`` command contribution."""

    stripe_app = typer.Typer(
        no_args_is_help=True,
        help="Direct hosted payer lifecycle utilities.",
    )
    payer_app = typer.Typer(no_args_is_help=True, help="Manage the selected payer.")
    owner_app = typer.Typer(no_args_is_help=True, help="Manage payer owners.")
    setup_app = typer.Typer(no_args_is_help=True, help="Manage saved-method setup.")
    instrument_app = typer.Typer(
        no_args_is_help=True,
        help="Inspect and revoke opaque saved instruments.",
    )

    @payer_app.command("create")
    def create(
        country: str = typer.Option("US", "--country"),
        json_output: bool = typer.Option(False, "--json"),
    ) -> None:
        """Create one payer binding owned by the selected marketplace signer."""

        async def operation() -> dict[str, Any]:
            if country != "US":
                raise PayerCommandError("hosted payer country must be US")
            context = context_factory()
            profile, signer = context.profiles.resolve_fresh_signer()
            if any(
                binding.authority_id == context.authority_id
                and binding.environment == context.environment
                and binding.state is not AuthorityBindingState.RETIRED
                for binding in profile.authority_payer_bindings
            ):
                raise PayerCommandError(
                    "selected profile already has an active hosted payer binding"
                )
            async with _facade(context, signer) as facade:
                result = await facade.create(country=country)
            if result.primary_principal.model_dump(mode="json") != signer.identity.model_dump(
                mode="json"
            ):
                raise PayerCommandError("hosted payer owner does not match selected signer")
            context.profiles.set_authority_payer_binding(
                str(profile.profile_id),
                AuthorityPayerBinding(
                    authority_id=context.authority_id,
                    environment=context.environment,
                    binding_ref=result.payer_profile_ref,
                    bound_principal=signer.identity,
                    state=AuthorityBindingState.ACTIVE,
                ),
            )
            return payer_profile_projection(result)

        _emit(_invoke(operation), json_output=json_output)

    @payer_app.command("show")
    def show(json_output: bool = typer.Option(False, "--json")) -> None:
        """Retrieve the current safe payer lifecycle projection."""

        async def operation() -> dict[str, Any]:
            context = context_factory()
            _profile, signer, binding = _selected_owner(context)
            async with _facade(context, signer) as facade:
                result = await facade.show(binding.binding_ref)
            return payer_profile_projection(result)

        _emit(_invoke(operation), json_output=json_output)

    @payer_app.command("delete")
    def delete(json_output: bool = typer.Option(False, "--json")) -> None:
        """Delete the hosted payer and retire only its local opaque binding."""

        async def operation() -> dict[str, Any]:
            context = context_factory()
            profile, signer, binding = _selected_owner(context)
            async with _facade(context, signer) as facade:
                result = await facade.delete(binding.binding_ref)
            context.profiles.set_authority_payer_binding(
                str(profile.profile_id),
                binding.model_copy(update={"state": AuthorityBindingState.RETIRED}),
            )
            return payer_profile_projection(result)

        _emit(_invoke(operation), json_output=json_output)

    @owner_app.command("rotate")
    def rotate(json_output: bool = typer.Option(False, "--json")) -> None:
        """Prove the retained and selected signers and rotate hosted ownership."""

        async def operation() -> dict[str, Any]:
            context = context_factory()
            profile, new_signer = context.profiles.resolve_fresh_signer()
            binding = _binding(context, profile)
            if binding.bound_principal == new_signer.identity:
                raise PayerCommandError("hosted payer already uses the selected signer")
            predecessor = profile.history_entry(binding.bound_principal)
            if predecessor.rotation_nonce is None:
                raise PayerCommandError("local owner rotation metadata is incomplete")
            _old_profile, old_signer = context.profiles.resolve_recovery_signer(
                profile_id=str(profile.profile_id),
                principal=binding.bound_principal,
            )
            overlap_until = _epoch(predecessor.overlap_until)
            async with _facade(context, old_signer) as facade:
                result = await facade.rotate_owner(
                    payer_profile_ref=binding.binding_ref,
                    new_signer=new_signer,
                    nonce=predecessor.rotation_nonce,
                    overlap_until_unix=overlap_until,
                    valid_until_unix=overlap_until + 300,
                )
            context.profiles.set_authority_payer_binding(
                str(profile.profile_id),
                binding.model_copy(
                    update={
                        "bound_principal": new_signer.identity,
                        "state": AuthorityBindingState.ACTIVE,
                    }
                ),
            )
            return payer_profile_projection(result)

        _emit(_invoke(operation), json_output=json_output)

    @owner_app.command("retire")
    def retire(
        principal: str = typer.Option(..., "--principal"),
        json_output: bool = typer.Option(False, "--json"),
    ) -> None:
        """Retire one hosted predecessor after local recovery retention allows it."""

        target = _principal(principal)

        async def operation() -> dict[str, Any]:
            context = context_factory()
            profile, signer, binding = _selected_owner(context)
            context.profiles.ensure_principal_retirable(
                str(profile.profile_id),
                target,
            )
            async with _facade(context, signer) as facade:
                result = await facade.retire_owner(
                    payer_profile_ref=binding.binding_ref,
                    principal=target,
                )
            context.profiles.retire_principal(str(profile.profile_id), target)
            return payer_profile_projection(result)

        _emit(_invoke(operation), json_output=json_output)

    @setup_app.command("start")
    def setup_start(
        funding_profile: str = typer.Option(..., "--funding-profile"),
        label: str = typer.Option(..., "--label"),
        action: str | None = typer.Option(None, "--action"),
        json_output: bool = typer.Option(False, "--json"),
    ) -> None:
        """Start card or ACH setup and dispatch any action transiently."""

        async def operation() -> dict[str, Any]:
            context = context_factory()
            _profile, signer, binding = _selected_owner(context)
            try:
                profile_value = FundingProfile(funding_profile)
            except ValueError:
                raise PayerCommandError("unsupported exact funding profile") from None
            if profile_value not in {
                FundingProfile.CARD,
                FundingProfile.US_ACH_DEBIT,
            }:
                raise PayerCommandError(
                    "saved setup supports only card.v1 or us_ach_debit.v1"
                )
            async with _facade(context, signer) as facade:
                result = await facade.start_setup(
                    payer_profile_ref=binding.binding_ref,
                    funding_profile=profile_value,
                    label=label,
                )
            await _dispatch_action(context, result, action)
            return payer_setup_projection(result)

        _emit(_invoke(operation), json_output=json_output)

    @setup_app.command("status")
    def setup_status(
        setup_ref: str = typer.Argument(...),
        action: str | None = typer.Option(None, "--action"),
        json_output: bool = typer.Option(False, "--json"),
    ) -> None:
        """Re-fetch setup and dispatch only its current transient action."""

        async def operation() -> dict[str, Any]:
            context = context_factory()
            _profile, signer, binding = _selected_owner(context)
            async with _facade(context, signer) as facade:
                result = await facade.setup_status(
                    payer_profile_ref=binding.binding_ref,
                    setup_ref=setup_ref,
                )
            await _dispatch_action(context, result, action)
            return payer_setup_projection(result)

        _emit(_invoke(operation), json_output=json_output)

    @setup_app.command("verify")
    def setup_verify(
        setup_ref: str = typer.Argument(...),
        amounts: str | None = typer.Option(
            None,
            "--amounts",
            help="The two deposited minor-unit amounts, comma separated.",
        ),
        descriptor_code: str | None = typer.Option(None, "--descriptor-code"),
        json_output: bool = typer.Option(False, "--json"),
    ) -> None:
        """Submit the payer's own verification evidence for a pending setup."""

        async def operation() -> dict[str, Any]:
            context = context_factory()
            _profile, signer, binding = _selected_owner(context)
            deposited: tuple[int, ...] | None = None
            if amounts is not None:
                try:
                    deposited = tuple(
                        int(part) for part in amounts.split(",") if part.strip()
                    )
                except ValueError:
                    raise PayerCommandError(
                        "deposited amounts must be whole minor units"
                    ) from None
            async with _facade(context, signer) as facade:
                result = await facade.verify_setup(
                    payer_profile_ref=binding.binding_ref,
                    setup_ref=setup_ref,
                    amounts=deposited,
                    descriptor_code=descriptor_code,
                )
            # No action dispatch: verification is the payer answering an action
            # they already took, not the authority handing them a new one.
            return payer_setup_projection(result)

        _emit(_invoke(operation), json_output=json_output)

    @instrument_app.command("list")
    def instrument_list(json_output: bool = typer.Option(False, "--json")) -> None:
        """List only opaque and provider-neutral instrument lifecycle fields."""

        async def operation() -> dict[str, Any]:
            context = context_factory()
            _profile, signer, binding = _selected_owner(context)
            async with _facade(context, signer) as facade:
                result = await facade.list_instruments(binding.binding_ref)
            return instrument_list_projection(result)

        _emit(_invoke(operation), json_output=json_output)

    def add_instrument_mutation(name: str) -> None:
        def command(
            instrument_ref: str = typer.Argument(...),
            json_output: bool = typer.Option(False, "--json"),
        ) -> None:
            async def operation() -> dict[str, Any]:
                context = context_factory()
                _profile, signer, binding = _selected_owner(context)
                async with _facade(context, signer) as facade:
                    result = await facade.mutate_instrument(
                        name,
                        payer_profile_ref=binding.binding_ref,
                        instrument_ref=instrument_ref,
                    )
                return instrument_projection(result)

            _emit(_invoke(operation), json_output=json_output)

        command.__name__ = f"instrument_{name}"
        instrument_app.command(name)(command)

    for operation_name in ("default", "revoke", "delete"):
        add_instrument_mutation(operation_name)

    payer_app.add_typer(owner_app, name="owner")
    payer_app.add_typer(setup_app, name="setup")
    payer_app.add_typer(instrument_app, name="instrument")
    stripe_app.add_typer(payer_app, name="payer")
    return stripe_app


__all__ = ["PayerCommandError", "create_stripe_command_group"]
