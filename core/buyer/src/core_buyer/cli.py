"""The ``market`` buyer executable: core verb skeleton + plugin assembly.

Core owns the console script and the cross-schema verb shape (``listing``,
``buy``, ``negotiate``, ``settle``); installed schema plugins supply the
concrete command behavior. Verbs a plugin registers replace the core
fallbacks for those names. Without plugins:

* ``market listing list/show`` work generically — repeatable
  ``--filter name=value`` passthrough straight to the registry filter-spec
  API, raw JSON output, no schema-specific flags or rendering;
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
from core_buyer.plugins import BuyerSchemaPlugin, discover_plugins
from core_buyer.registry_config import (
    resolve_discovery_timeout,
    resolve_indexer_auth,
    resolve_indexer_urls,
)

if TYPE_CHECKING:
    from market_policy.buyer_policy import BuyerPolicy


def parse_filter_options(raw_filters: list[str] | None) -> dict[str, str]:
    """Parse repeatable ``--filter name=value`` CLI options."""
    parsed: dict[str, str] = {}
    for raw in raw_filters or []:
        if "=" not in raw:
            typer.secho(
                f"Invalid --filter {raw!r}; expected name=value.",
                err=True, fg=typer.colors.RED,
            )
            raise typer.Exit(2)
        name, value = raw.split("=", 1)
        name = name.strip()
        value = value.strip()
        if not name or not value:
            typer.secho(
                f"Invalid --filter {raw!r}; name and value must be non-empty.",
                err=True, fg=typer.colors.RED,
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
    import os
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
    app: typer.Typer, name: str, fn: Any, policy: "BuyerPolicy",
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


# ---------------------------------------------------------------------------
# Generic (no-plugin) fallback commands
# ---------------------------------------------------------------------------


def _build_generic_listing_app() -> typer.Typer:
    listing_app = typer.Typer(no_args_is_help=True)

    @listing_app.command("list")
    def listing_list(
        registry_urls: Optional[str] = typer.Option(
            None, "--registry-urls", "-r",
            help="Comma-separated listing registry base URLs "
                 "(config.toml: registry.urls).",
        ),
        discovery_timeout: Optional[float] = typer.Option(
            None, "--discovery-timeout",
            help="Per-registry deadline in seconds.",
        ),
        raw_filters: Optional[list[str]] = typer.Option(
            None, "--filter", "-f",
            help="Registry filter-spec parameter as name=value. Repeatable. "
                 "This is the only filter surface without a schema plugin; "
                 "install one for named flags and rendered output.",
        ),
        limit: int = typer.Option(50, "--limit", "-l", help="Maximum listings to fetch (1-200)."),
        offset: int = typer.Option(0, "--offset", "-o", help="Pagination offset."),
    ) -> None:
        """List open listings from the configured registries as raw JSON."""
        if limit < 1 or limit > 200:
            raise typer.BadParameter("limit must be between 1 and 200")
        if offset < 0:
            raise typer.BadParameter("offset must be >= 0")
        urls = [u.rstrip("/") for u in resolve_indexer_urls(override=registry_urls)]
        filters: dict[str, object] = {"limit": limit, "offset": offset}
        filters.update(parse_filter_options(raw_filters))
        items = query_registry_for_matches_multi(
            urls,
            timeout=resolve_discovery_timeout(override=discovery_timeout),
            filters=filters,
            auth=resolve_indexer_auth(),
        )
        typer.echo(json.dumps(items, indent=2, default=str))

    @listing_app.command("show")
    def listing_show(
        listing_id: str = typer.Argument(..., help="Listing ID"),
        registry_urls: Optional[str] = typer.Option(
            None, "--registry-urls", "-r",
            help="Comma-separated listing registry base URLs "
                 "(config.toml: registry.urls).",
        ),
        discovery_timeout: Optional[float] = typer.Option(
            None, "--discovery-timeout",
            help="Per-registry deadline in seconds.",
        ),
    ) -> None:
        """Show one listing as raw JSON — first configured registry that knows it wins."""
        urls = [u.rstrip("/") for u in resolve_indexer_urls(override=registry_urls)]
        try:
            found = fetch_listing_dict_multi(
                urls, listing_id,
                timeout=resolve_discovery_timeout(override=discovery_timeout),
                auth=resolve_indexer_auth(),
            )
        except RuntimeError as exc:
            typer.secho(str(exc), err=True, fg=typer.colors.RED)
            raise typer.Exit(code=1)
        if found is None:
            typer.secho(
                f"Listing {listing_id!r} not found in any of {len(urls)} registries.",
                err=True, fg=typer.colors.RED,
            )
            raise typer.Exit(code=1)
        typer.echo(json.dumps(found, indent=2, default=str))

    return listing_app


def _make_plugin_required_stub(verb: str):
    def stub(ctx: typer.Context) -> None:
        typer.secho(
            f"`market {verb}` needs a registry schema plugin and none is "
            f"installed. Install your registry's buyer schema package "
            f"(e.g. market-buyer for the VM compute schema); core only "
            f"provides generic listing browsing via "
            f"`market listing list --filter name=value`.",
            err=True, fg=typer.colors.RED,
        )
        raise typer.Exit(2)

    stub.__name__ = verb
    stub.__doc__ = f"Unavailable: `{verb}` requires a registry schema plugin."
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


def build_app(plugins: list[BuyerSchemaPlugin] | None = None) -> typer.Typer:
    """Assemble the ``market`` app from core verbs + installed schema plugins.

    ``plugins=None`` discovers installed plugins through the
    ``market.buyer_plugins`` entry-point group; tests pass an explicit list.
    """
    if plugins is None:
        plugins = discover_plugins()

    app = typer.Typer(no_args_is_help=True)

    def version_callback(value: bool) -> None:
        if value:
            typer.echo(f"market (arkhai-core-buyer) version {_dist_version('arkhai-core-buyer')}")
            for plugin in plugins:
                suffix = (
                    f" ({plugin.distribution} {_dist_version(plugin.distribution)})"
                    if plugin.distribution else ""
                )
                typer.echo(f"  schema plugin: {plugin.schema_id}{suffix}")
            raise typer.Exit()

    @app.callback()
    def main(
        version_flag: bool = typer.Option(
            None, "--version", "-v",
            callback=version_callback, is_eager=True,
            help="Show version and exit.",
        ),
        config_file: Optional[str] = typer.Option(
            None, "--config",
            callback=_config_path_callback, is_eager=True,
            help="Path to an explicit buyer.toml. Defaults to "
                 "$XDG_CONFIG_HOME/arkhai/buyer.toml.",
        ),
    ) -> None:
        """Buyer CLI for Arkhai market operations."""

    @app.command("plugins")
    def list_plugins() -> None:
        """List installed registry schema plugins."""
        if not plugins:
            typer.echo(
                "No buyer schema plugins installed. Only generic listing "
                "browsing (--filter passthrough) is available."
            )
            return
        for plugin in plugins:
            suffix = (
                f"  [{plugin.distribution} {_dist_version(plugin.distribution)}]"
                if plugin.distribution else ""
            )
            typer.echo(f"{plugin.schema_id}{suffix}")

    for plugin in plugins:
        plugin.register(app)

    claimed = _registered_names(app)
    if "listing" not in claimed:
        app.add_typer(
            _build_generic_listing_app(), name="listing",
            help="Browse registry listings generically (raw JSON, --filter passthrough).",
        )
    for verb in ("buy", "negotiate", "settle"):
        if verb not in claimed:
            app.command(
                verb,
                context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
            )(_make_plugin_required_stub(verb))

    return app


def main() -> None:
    """Console-script entry point for ``market``."""
    build_app()()


if __name__ == "__main__":
    main()
