"""The ``market`` buyer executable: core verb skeleton + plugin assembly.

Core owns the console script and the cross-schema verb shape (``listing``,
``buy``, ``negotiate``, ``settle``); installed schema plugins supply the
concrete command behavior. Verbs a plugin registers replace the core
fallbacks for those names. Without plugins:

* ``market listing list/show`` work generically through one typed
  ``--resource`` query compiled against each selected registry's filter spec,
  with raw JSON output and no schema-specific rendering;
* ``market buy``/``negotiate``/``settle`` are stubs that explain a schema
  plugin is required — core never fakes a concrete buy experience.
"""

from __future__ import annotations

import json
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

import typer

from core_buyer.orchestrator import (
    fetch_listing_dict_multi,
    query_registry_for_matches_multi,
)
from core_buyer.buyer_config import resolve_fresh_buyer_identity
from core_buyer.profile_service import BuyerProfileService
from core_buyer.plugins import discover_domains
from core_buyer.registry_config import (
    resolve_discovery_timeout,
    resolve_indexer_urls,
    resolve_registry_api_keys,
    resolve_registry_authorities,
)
from market_core import MarketDomainContract, validate_domain_contracts
from market_identity import (
    CredentialProviderKind,
    CredentialReference,
    Identity,
    IdentityScheme,
)

if TYPE_CHECKING:
    from market_policy.buyer_policy import BuyerPolicy


def _registry_identity_context(registry_urls: list[str]):
    resolved = resolve_fresh_buyer_identity()
    return (
        resolved.signer,
        resolve_registry_authorities(registry_urls),
        resolve_registry_api_keys(),
    )


def parse_key_value_options(
    raw_values: list[str] | None,
    *,
    option_name: str,
) -> dict[str, str]:
    """Parse repeatable key=value options without echoing supplied values."""

    parsed: dict[str, str] = {}
    for index, raw in enumerate(raw_values or []):
        if "=" not in raw:
            typer.secho(
                f"Invalid {option_name} at index {index}; expected key=value.",
                err=True,
                fg=typer.colors.RED,
            )
            raise typer.Exit(2)
        name, value = raw.split("=", 1)
        name = name.strip()
        value = value.strip()
        if not name or not value:
            typer.secho(
                f"Invalid {option_name} at index {index}; "
                "key and value must be non-empty.",
                err=True,
                fg=typer.colors.RED,
            )
            raise typer.Exit(2)
        parsed[name] = value
    return parsed


def _dist_version(distribution: str) -> str:
    try:
        return version(distribution)
    except PackageNotFoundError:
        return "unknown (not installed)"


def _config_path_callback(value: str | None) -> str | None:
    """Set an explicit buyer config path before command bodies run."""
    if value:
        from market_config.config_loader import set_user_config_path

        set_user_config_path(Path(value))
    return value


def interactive_disposition(assume_yes: bool) -> bool:
    """Canonical answer to "may this run prompt the user?".

    True only when the user did not pass ``--yes`` AND stdin is a TTY —
    the same disposition every prompt in the pipeline must follow, and
    the form policy hooks receive (``derive_prices(interactive=...)``)
    so a policy never re-derives it from the environment.
    """
    import sys

    try:
        is_tty = sys.stdin.isatty()
    except Exception:
        is_tty = False
    return (not assume_yes) and is_tty


def assume_yes_option(help: str) -> Any:
    """The shared ``--yes/-y`` flag every policy verb declares.

    Core owns the flag spelling and short option so ``buy``/``negotiate``
    across schema plugins stay in lockstep; the help text remains
    per-verb (``buy`` skips *all* prompts, ``negotiate`` only the
    auto-derived-price confirmation). Feed the collected value to
    :func:`interactive_disposition`.
    """
    return typer.Option(False, "--yes", "-y", help=help)


def register_policy_verb(
    app: typer.Typer,
    name: str,
    fn: Any,
    policy: "BuyerPolicy",
) -> None:
    """Bind a policy-bearing verb (``buy``/``negotiate``) onto the app.

    Materializes the configured negotiation policy's CLI flags onto the
    verb (ARCHITECTURE.md, "Buyer negotiation policy surface") and
    registers it under ``name``. Core owns the inject-then-register
    pairing so every schema plugin's buy/negotiate surfaces the policy
    flags identically — the plugin only supplies the verb function and
    the policy it fetched.
    """
    from market_policy.buyer_policy import inject_policy_cli_params

    app.command(name)(inject_policy_cli_params(fn, policy))


def _credential_reference(provider: str, locator: str) -> CredentialReference:
    try:
        return CredentialReference(
            provider=CredentialProviderKind(provider),
            locator=locator,
        )
    except (TypeError, ValueError) as exc:
        raise typer.BadParameter(
            "provider/reference must identify keyring.v1, secret_file.v1, "
            "or environment.v1 exactly"
        ) from exc


def _canonical_principal(value: str) -> Identity:
    scheme, separator, identifier = value.partition(":")
    if not separator or not identifier:
        raise typer.BadParameter("principal must be scheme:identifier")
    try:
        return Identity(scheme=IdentityScheme(scheme), identifier=identifier)
    except (TypeError, ValueError) as exc:
        raise typer.BadParameter("principal is not canonical") from exc


def _emit_profile(value: Any, *, json_output: bool) -> None:
    if json_output:
        typer.echo(json.dumps(value, sort_keys=True, separators=(",", ":")))
        return
    typer.echo(json.dumps(value, indent=2, sort_keys=True))


def _profile_service() -> BuyerProfileService:
    return BuyerProfileService()


def _build_profile_app() -> typer.Typer:
    profile_app = typer.Typer(no_args_is_help=True)

    @profile_app.command("create")
    def profile_create(
        name: str = typer.Argument(..., help="Unique local profile name."),
        provider: str = typer.Option(..., "--provider", help="Exact provider kind."),
        reference: str = typer.Option(
            ...,
            "--reference",
            help="Provider-owned locator; never the secret value.",
        ),
        scheme: str = typer.Option("ed25519", "--scheme"),
        generate: bool = typer.Option(
            False,
            "--generate",
            help="Generate a new Ed25519 seed through the selected provider.",
        ),
        select: bool = typer.Option(
            False,
            "--select",
            help="Select this profile for fresh runs (the first is selected automatically).",
        ),
        json_output: bool = typer.Option(False, "--json"),
    ) -> None:
        """Create a durable profile from one exact credential reference."""

        try:
            result = _profile_service().create(
                name=name,
                credential_reference=_credential_reference(provider, reference),
                scheme=IdentityScheme(scheme),
                generate=generate,
                select=True if select else None,
            )
        except Exception as exc:
            typer.secho(str(exc), err=True, fg=typer.colors.RED)
            raise typer.Exit(2) from exc
        _emit_profile(result.redacted(), json_output=json_output)

    @profile_app.command("import")
    def profile_import(
        source: Path = typer.Argument(
            ...,
            exists=True,
            dir_okay=False,
            readable=True,
            resolve_path=True,
            help="Legacy buyer TOML containing exactly [Identity].",
        ),
        name: str = typer.Option(..., "--name"),
        provider: str = typer.Option(..., "--provider"),
        reference: str = typer.Option(..., "--reference"),
        check: bool = typer.Option(
            False,
            "--check",
            help="Validate and preview without writing profile metadata.",
        ),
        select: bool = typer.Option(False, "--select"),
        json_output: bool = typer.Option(False, "--json"),
    ) -> None:
        """Explicitly preview or import one legacy public buyer identity."""

        try:
            result = _profile_service().import_legacy(
                source=source,
                name=name,
                credential_reference=_credential_reference(provider, reference),
                check=check,
                select=True if select else None,
            )
        except Exception as exc:
            typer.secho(str(exc), err=True, fg=typer.colors.RED)
            raise typer.Exit(2) from exc
        _emit_profile(result.redacted(), json_output=json_output)

    @profile_app.command("list")
    def profile_list(
        json_output: bool = typer.Option(False, "--json"),
    ) -> None:
        """List public profile metadata and redacted credential references."""

        try:
            profiles = _profile_service().list_profiles()
        except Exception as exc:
            typer.secho(str(exc), err=True, fg=typer.colors.RED)
            raise typer.Exit(2) from exc
        _emit_profile(list(profiles), json_output=json_output)

    @profile_app.command("show")
    def profile_show(
        profile: str = typer.Argument(..., help="Profile UUID or name."),
        json_output: bool = typer.Option(False, "--json"),
    ) -> None:
        """Show one profile without resolving or displaying its credential."""

        try:
            value = _profile_service().show(profile)
        except Exception as exc:
            typer.secho(str(exc), err=True, fg=typer.colors.RED)
            raise typer.Exit(2) from exc
        _emit_profile(value, json_output=json_output)

    @profile_app.command("select")
    def profile_select(
        profile: str = typer.Argument(..., help="Profile UUID or name."),
        json_output: bool = typer.Option(False, "--json"),
    ) -> None:
        """Select one active profile for subsequent fresh runs."""

        try:
            value = _profile_service().select(profile)
        except Exception as exc:
            typer.secho(str(exc), err=True, fg=typer.colors.RED)
            raise typer.Exit(2) from exc
        _emit_profile(value, json_output=json_output)

    @profile_app.command("rotate")
    def profile_rotate(
        profile: str = typer.Argument(..., help="Profile UUID or name."),
        provider: str = typer.Option(..., "--provider"),
        reference: str = typer.Option(..., "--reference"),
        scheme: str = typer.Option("ed25519", "--scheme"),
        generate: bool = typer.Option(False, "--generate"),
        overlap_seconds: int = typer.Option(0, "--overlap-seconds", min=0),
        json_output: bool = typer.Option(False, "--json"),
    ) -> None:
        """Prove both signers and promote a replacement for fresh runs."""

        try:
            result = _profile_service().rotate(
                profile,
                replacement_reference=_credential_reference(provider, reference),
                replacement_scheme=IdentityScheme(scheme),
                generate=generate,
                overlap_seconds=overlap_seconds,
            )
        except Exception as exc:
            typer.secho(str(exc), err=True, fg=typer.colors.RED)
            raise typer.Exit(2) from exc
        _emit_profile(result.redacted(), json_output=json_output)

    @profile_app.command("retire")
    def profile_retire(
        profile: str = typer.Argument(..., help="Profile UUID or name."),
        principal: Optional[str] = typer.Option(
            None,
            "--principal",
            help="Retire one eligible non-primary scheme:identifier predecessor.",
        ),
        json_output: bool = typer.Option(False, "--json"),
    ) -> None:
        """Retire one predecessor or the whole eligible profile."""

        try:
            service = _profile_service()
            value = (
                service.retire_principal(profile, _canonical_principal(principal))
                if principal is not None
                else service.retire(profile)
            )
        except Exception as exc:
            typer.secho(str(exc), err=True, fg=typer.colors.RED)
            raise typer.Exit(2) from exc
        _emit_profile(value, json_output=json_output)

    @profile_app.command("delete")
    def profile_delete(
        profile: str = typer.Argument(..., help="Retired profile UUID or name."),
        confirm_history_release: bool = typer.Option(
            False,
            "--confirm-history-release",
            help="Confirm that retained public history may be removed.",
        ),
        delete_credentials: bool = typer.Option(
            False,
            "--delete-credentials",
            help="Separately delete each now-unshared provider entry.",
        ),
        json_output: bool = typer.Option(False, "--json"),
    ) -> None:
        """Delete eligible metadata and, only when confirmed, provider entries."""

        try:
            result = _profile_service().delete(
                profile,
                confirm_history_release=confirm_history_release,
                delete_credentials=delete_credentials,
            )
        except Exception as exc:
            typer.secho(str(exc), err=True, fg=typer.colors.RED)
            raise typer.Exit(2) from exc
        _emit_profile(result.redacted(), json_output=json_output)

    return profile_app


# ---------------------------------------------------------------------------
# Generic (no-plugin) fallback commands
# ---------------------------------------------------------------------------


def _build_generic_listing_app() -> typer.Typer:
    listing_app = typer.Typer(no_args_is_help=True)

    @listing_app.command("list")
    def listing_list(
        registry_urls: Optional[str] = typer.Option(
            None,
            "--registry-urls",
            "-r",
            help="Comma-separated listing registry base URLs "
            "(config.toml: registry.urls).",
        ),
        discovery_timeout: Optional[float] = typer.Option(
            None,
            "--discovery-timeout",
            help="Per-registry deadline in seconds.",
        ),
        resource_query: Optional[str] = typer.Option(
            None,
            "--resource",
            help="Typed resource constraints, for example "
            "'gpu_model in [H200,A100] ram_gb>=64'.",
        ),
        limit: int = typer.Option(
            50, "--limit", "-l", help="Maximum listings to fetch (1-200)."
        ),
        offset: int = typer.Option(0, "--offset", "-o", help="Pagination offset."),
    ) -> None:
        """List open listings from the configured registries as raw JSON."""
        if limit < 1 or limit > 200:
            raise typer.BadParameter("limit must be between 1 and 200")
        if offset < 0:
            raise typer.BadParameter("offset must be >= 0")
        urls = resolve_indexer_urls(override=registry_urls)
        signer, authorities, api_keys = _registry_identity_context(urls)
        try:
            items = query_registry_for_matches_multi(
                urls,
                timeout=resolve_discovery_timeout(override=discovery_timeout),
                signer=signer,
                registry_authorities=authorities,
                resource_query=resource_query,
                limit=limit,
                offset=offset,
                api_keys=api_keys,
            )
        except RuntimeError as exc:
            typer.secho(str(exc), err=True, fg=typer.colors.RED)
            raise typer.Exit(code=2) from exc
        typer.echo(json.dumps(items, indent=2, default=str))

    @listing_app.command("show")
    def listing_show(
        listing_id: str = typer.Argument(..., help="Listing ID"),
        registry_urls: Optional[str] = typer.Option(
            None,
            "--registry-urls",
            "-r",
            help="Comma-separated listing registry base URLs "
            "(config.toml: registry.urls).",
        ),
        discovery_timeout: Optional[float] = typer.Option(
            None,
            "--discovery-timeout",
            help="Per-registry deadline in seconds.",
        ),
    ) -> None:
        """Show one listing as raw JSON — first configured registry that knows it wins."""
        urls = resolve_indexer_urls(override=registry_urls)
        signer, authorities, api_keys = _registry_identity_context(urls)
        try:
            found = fetch_listing_dict_multi(
                urls,
                listing_id,
                timeout=resolve_discovery_timeout(override=discovery_timeout),
                signer=signer,
                registry_authorities=authorities,
                api_keys=api_keys,
            )
        except RuntimeError as exc:
            typer.secho(str(exc), err=True, fg=typer.colors.RED)
            raise typer.Exit(code=1)
        if found is None:
            typer.secho(
                f"Listing {listing_id!r} not found in any of {len(urls)} registries.",
                err=True,
                fg=typer.colors.RED,
            )
            raise typer.Exit(code=1)
        typer.echo(json.dumps(found, indent=2, default=str))

    return listing_app


def _make_plugin_required_stub(verb: str):
    def stub(ctx: typer.Context) -> None:
        typer.secho(
            f"`market {verb}` needs a buyer market domain and none is "
            f"installed. Install your market domain's buyer package; core "
            f"only provides generic listing browsing via "
            f"`market listing list --resource '<query>'`.",
            err=True,
            fg=typer.colors.RED,
        )
        raise typer.Exit(2)

    stub.__name__ = verb
    stub.__doc__ = f"Unavailable: `{verb}` requires a buyer market domain."
    return stub


# ---------------------------------------------------------------------------
# App assembly
# ---------------------------------------------------------------------------


def _registered_names(app: typer.Typer) -> set[str]:
    names: set[str] = set()
    for group in app.registered_groups:
        if group.name:
            names.add(group.name)
        elif group.typer_instance is not None and group.typer_instance.info.name:
            names.add(str(group.typer_instance.info.name))
    for command in app.registered_commands:
        if command.name:
            names.add(command.name)
        elif command.callback is not None:
            names.add(command.callback.__name__.replace("_", "-"))
    return names


def build_app(domains: list[MarketDomainContract] | None = None) -> typer.Typer:
    """Assemble the ``market`` app from core verbs + installed domains.

    ``domains=None`` discovers installed contracts through the
    ``market.buyer_domains`` entry-point group; tests pass an explicit list.
    """
    if domains is None:
        domains = discover_domains()
    else:
        domains = list(validate_domain_contracts(domains))

    app = typer.Typer(no_args_is_help=True)

    def version_callback(value: bool) -> None:
        if value:
            typer.echo(
                f"market (arkhai-core-buyer) version {_dist_version('arkhai-core-buyer')}"
            )
            for domain in domains:
                typer.echo(
                    f"  market domain: {domain.identity} "
                    f"(contract {domain.contract_version})"
                )
            raise typer.Exit()

    @app.callback()
    def main(
        version_flag: bool = typer.Option(
            None,
            "--version",
            "-v",
            callback=version_callback,
            is_eager=True,
            help="Show version and exit.",
        ),
        config_file: Optional[str] = typer.Option(
            None,
            "--config",
            callback=_config_path_callback,
            is_eager=True,
            help="Path to an explicit buyer.toml. Defaults to "
            "$XDG_CONFIG_HOME/arkhai/buyer.toml.",
        ),
    ) -> None:
        """Buyer CLI for Arkhai market operations."""

    @app.command("plugins")
    def list_plugins() -> None:
        """List installed registry schema plugins."""
        if not domains:
            typer.echo(
                "No buyer market domains installed. Only generic typed "
                "resource-query listing is available."
            )
            return
        for domain in domains:
            typer.echo(f"{domain.identity}  [contract {domain.contract_version}]")

    app.add_typer(
        _build_profile_app(),
        name="profile",
        help="Manage durable local buyer profiles and retained signer history.",
    )

    for domain in domains:
        if domain.buyer is not None:
            domain.buyer.register_commands(app)

    claimed = _registered_names(app)
    if "listing" not in claimed:
        app.add_typer(
            _build_generic_listing_app(),
            name="listing",
            help="Browse registry listings generically (raw JSON, typed --resource).",
        )
    for verb in ("buy", "negotiate", "settle"):
        if verb not in claimed:
            app.command(
                verb,
                context_settings={
                    "allow_extra_args": True,
                    "ignore_unknown_options": True,
                },
            )(_make_plugin_required_stub(verb))

    return app


def main() -> None:
    """Console-script entry point for ``market``."""
    build_app()()


if __name__ == "__main__":
    main()
