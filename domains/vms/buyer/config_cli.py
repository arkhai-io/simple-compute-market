from __future__ import annotations

import json
import os
from collections.abc import Mapping
from typing import Any

import typer
from market_config.config_loader import (
    get_dotted,
    load_user_config,
    set_dotted,
    user_config_dir,
    user_config_file,
    write_user_config,
)
from market_config.settlement_migration import (
    BUYER_MIGRATION_COMMAND,
    SettlementMigrationError,
    format_migration_result,
    migrate_settlement_config,
    reject_legacy_settlement_path,
)
from market_settlement_runtime import SettlementRole

config_app = typer.Typer(no_args_is_help=True)


def _validate_settlement_candidate(
    document: Mapping[str, Any], role: SettlementRole
) -> None:
    from market_alkahest import create_alkahest_registration
    from market_hosted_settlement import create_stripe_registration
    from market_settlement_runtime import SettlementConfigurationRegistry

    registry = SettlementConfigurationRegistry(
        [create_alkahest_registration(), create_stripe_registration()]
    )
    registry.resolve(document.get("Settlement", {}), role=role)


_REMOVED_IDENTITY_ROOTS = {
    "identity",
    "identity_credential",
    "buyer_private_key",
    "marketplace_private_key",
    "marketplace_seed",
    "marketplace_mnemonic",
}


def _reject_removed_identity_document(document: Mapping[str, Any]) -> None:
    present = sorted(
        str(key)
        for key in document
        if str(key).casefold() in _REMOVED_IDENTITY_ROOTS
    )
    if present:
        raise typer.BadParameter(
            "direct buyer identity fields are import-only: "
            + ", ".join(present)
            + "; run `market profile import --check`, import explicitly, "
            "then remove them"
        )


def _reject_removed_identity_path(path: str) -> None:
    root = path.partition(".")[0].casefold()
    if root in _REMOVED_IDENTITY_ROOTS:
        raise typer.BadParameter(
            f"{path!r} is import-only; run `market profile import --check` "
            "and remove the legacy field"
        )


@config_app.command("path")
def config_path() -> None:
    """Print the path of the buyer.toml (whether or not it exists)."""
    p = user_config_file()
    typer.echo(str(p))
    if not p.exists():
        typer.secho(
            "(not present — run `market config init-user` to scaffold it)",
            fg=typer.colors.YELLOW,
        )


@config_app.command("show")
def config_show(
    raw: bool = typer.Option(
        False,
        "--raw",
        help="Print the TOML file verbatim instead of the loaded mapping.",
    ),
) -> None:
    """Show the current user config."""
    p = user_config_file()
    if not p.exists():
        typer.secho(f"No user config at {p}.", fg=typer.colors.YELLOW)
        raise typer.Exit(1)
    document = load_user_config(p)
    _reject_removed_identity_document(document)
    if raw:
        typer.echo(p.read_text())
        return
    typer.echo(json.dumps(document, indent=2, sort_keys=True))


@config_app.command("set")
def config_set(
    key: str = typer.Argument(..., help="Dotted config key, e.g. 'chain.rpc_url'."),
    value: str = typer.Argument(
        ..., help="Value to assign (coerced to int/float/bool when possible)."
    ),
) -> None:
    """Set a single value in the buyer.toml.

    Values are coerced: 'true' / 'false' → bool, integer-looking strings → int,
    float-looking strings → float, otherwise left as strings. Use quotes around
    strings that look numeric if you want to keep them as text.
    """
    _reject_removed_identity_path(key)
    try:
        reject_legacy_settlement_path(key, command=BUYER_MIGRATION_COMMAND)
    except SettlementMigrationError as exc:
        typer.secho(str(exc), err=True, fg=typer.colors.RED)
        raise typer.Exit(2) from exc
    coerced: object = value
    low = value.strip().lower()
    if low in ("true", "false"):
        coerced = low == "true"
    else:
        try:
            coerced = int(value)
        except ValueError:
            try:
                coerced = float(value)
            except ValueError:
                coerced = value

    path = user_config_file()
    doc = load_user_config(path)
    set_dotted(doc, key, coerced)
    written = write_user_config(doc, path)
    typer.echo(f"Set {key} = {coerced!r} in {written}")


@config_app.command("get")
def config_get(
    key: str = typer.Argument(..., help="Dotted config key, e.g. 'chain.rpc_url'."),
) -> None:
    """Print the value of a single config key from the buyer.toml."""
    doc = load_user_config()
    val = get_dotted(doc, key)
    if val is None:
        typer.secho(
            f"Key {key!r} not set in {user_config_file()}.",
            fg=typer.colors.YELLOW,
        )
        raise typer.Exit(1)
    if isinstance(val, (dict, list)):
        typer.echo(json.dumps(val, indent=2, sort_keys=True))
    else:
        typer.echo(str(val))


@config_app.command("migrate")
def config_migrate(
    scope: str = typer.Option(..., "--scope", help="Configuration scope to migrate."),
    check: bool = typer.Option(
        False,
        "--check",
        help="Preview redacted settlement changes without writing.",
    ),
    write: bool = typer.Option(
        False,
        "--write",
        help="Validate, back up, and atomically write the migrated file.",
    ),
    backup: bool = typer.Option(
        False,
        "--backup",
        help="Create the required same-directory backup in write mode.",
    ),
) -> None:
    """Migrate settlement config; buyer identity uses explicit profile import."""

    if scope == "identity":
        typer.secho(
            "Identity migration is explicit: run `market profile import --check "
            "<buyer.toml> --name <name> --provider <kind> --reference <locator>`, "
            "then repeat without --check and remove [Identity].",
            err=True,
            fg=typer.colors.YELLOW,
        )
        raise typer.Exit(2)
    if scope != "settlement":
        typer.secho(
            "Only --scope settlement or identity is supported.",
            err=True,
            fg=typer.colors.RED,
        )
        raise typer.Exit(2)
    try:
        result = migrate_settlement_config(
            user_config_file(),
            role="buyer",
            check=check,
            write=write,
            backup=backup,
            environ=os.environ,
            validator=_validate_settlement_candidate,
        )
    except SettlementMigrationError as exc:
        typer.secho(str(exc), err=True, fg=typer.colors.RED)
        raise typer.Exit(1) from exc
    for line in format_migration_result(result):
        typer.echo(line)


_INIT_USER_TEMPLATE = """\
# arkhai buyer config — see `market config path` for this file's location
# Marketplace signing identity comes only from the selected durable buyer
# profile. Metadata defaults to $XDG_DATA_HOME/arkhai/buyer/profiles.json;
# credentials remain in the exact keyring.v1, secret_file.v1, or
# environment.v1 provider recorded by `market profile create|import`.
# Run `market profile --help`; direct [Identity], raw seed, mnemonic, and
# ARKHAI_IDENTITY_CREDENTIAL inputs are rejected rather than used as fallback.
#
# [BuyerProfile]
# store_path = "/absolute/override/profiles.json"  # optional; XDG is preferred


[provisioning]
# ssh_public_key = "ssh-ed25519 AAAA... user@host"


[registry]
# urls = ["http://localhost:8080"]             # one or more indexer URLs to discover listings from.
# [registry.authorities."http://localhost:8080"]
# authority = "registry"
# identities = [
#   { scheme = "ed25519", identifier = "<registry-public-key>" },
# ]


[registry.auth]
# Free-form table of {url = "bearer-token"}. Keys must match `urls` above
# verbatim (scheme, host, port, no trailing slash). Empty = public.

[aggregation]
# policy = "best_price"                        # across-seller match policy. Alkahest installs
                                                # best_price, cheapest_first, and priceless_last.
                                                # Core installs fastest_agreed | registry_order |
                                                # random_shuffle | any custom name registered
                                                # via domains.vms.buyer.aggregation.register_aggregation_policy,
                                                # or a folder name under
                                                # $XDG_CONFIG_HOME/arkhai/aggregation_policies/.
# extra_policy_paths = []                      # additional directories to scan for file-based policies.
                                                # Each immediate subdirectory is treated as a policy named
                                                # after the folder; the subdir must contain a policy.py
                                                # exposing `factory(cfg) -> AggregationPolicy`.
# best_price_timeout = 30.0                    # optional wall-clock cap (seconds) for the `best_price`
                                                # policy. When set, candidates still negotiating at the
                                                # deadline are cancelled and the lowest agreed price among
                                                # those that completed wins. Unset = wait for all.

[Settlement]
schema_version = 1
priority = []

[Settlement.stripe]
enabled = false
# base_url = "https://settlement.example"
# authority_id = "hosted-authority"
# environment = "production"
# expected_manifest_digest = "sha256:<released-manifest-digest>"
# expected_api_version = "0.2.1"
# expected_schema_version = 5
# required_capabilities = [
#   "scheme-tagged-identities.v1",
#   "account-owner-admission.v1",
#   "account-owner-rotation.v1",
#   "account-owner-retirement.v1",
#   "signer-injected-client.v1",
#   "provider-neutral-seller-onboarding.v1",
#   "conditional-escrow.v2",
#   "stripe-connect-separate-charges-transfers.v2",
#   "portable-attestation.v1",
#   "eas-arbiter.v1",
#   "payer-profile.v1",
#   "funding-authorization.v1",
#   "funding-profile.card.v1",
#   "funding-profile.us_bank_transfer.v1",
#   "funding-profile.us_ach_debit.v1",
#   "normalized-funding-reversal.v1",
#   "operator-recovery-redaction.v1",
# ]
# request_timeout_seconds = 10.0
# preflight_timeout_seconds = 5.0
# allow_insecure_loopback = false
# authorization_journal_path = "/var/lib/arkhai/buyer/funding-authorizations.jsonl"
# [Settlement.stripe.off_session_policy]
# enabled = false
# mode = "saved_instrument"
# authority_id = "hosted-authority"
# environment = "production"
# funding_profile = "card.v1" # card.v1 or us_ach_debit.v1
# currency = "usd"
# max_purchase_minor_units = 10000
# max_aggregate_minor_units = 50000
# window_kind = "rolling" # rolling or fixed
# window_seconds = 86400
# fixed_window_anchor_unix = 0 # required only for fixed windows
# seller_principals = [
#   { scheme = "ed25519", identifier = "<seller-public-key>" },
# ]
# [Settlement.stripe.authority]
# principals = [
#   { scheme = "ed25519", identifier = "<authority-public-key>" },
# ]

[Settlement.alkahest]
enabled = false
# address_config_path = "/path/to/alkahest.json"
# oracle_gated = false
# trusted_oracle_addresses = []
# interruptible = false
# interruptible_oracle_addresses = []

[negotiation]
# policies = ["buyer_escrow_shape_guard", "bisection"]
#                                              # ordered policy chain; terminal policy is
#                                              # `bisection` (default; no ML deps), `rl` (torch + checkpoint),
#                                              # `erc20_bisection`, `native_token_bisection`, or
#                                              # `erc1155_bisection`, `erc20_rl`, `native_token_rl`, or
#                                              # `erc1155_rl`
#                                              # For per-kind dispatch, replace the list with:
#                                              # [negotiation.policies]
#                                              # erc20 = "erc20_bisection"
#                                              # native_token = "native_token_bisection"
#                                              # erc1155 = "erc1155_bisection"
#                                              # [negotiation.policies.erc721]
#                                              # chain = ["accept_exact_listing"]
# policy_mode = "bisection"                    # legacy single-terminal key (synthesizes the default chain
#                                              # when `policies` is absent)
"""

_EVM_RESOURCE_TEMPLATE = """\

# Shared EVM resources are separate from mechanism policy and are omitted
# unless `market config init-user --include-evm-resources` is requested.
[Wallet]
# address = "0x..."
# private_key = "0x..."

[Chains.ethereum_sepolia]
# rpc_url = "https://sepolia.infura.io/v3/<project_id>"
# chain_id = 11155111
"""


@config_app.command("init-user")
def config_init_user(
    overwrite: bool = typer.Option(
        False,
        "--overwrite",
        help="Replace an existing buyer.toml instead of refusing.",
    ),
    include_evm_resources: bool = typer.Option(
        False,
        "--include-evm-resources",
        help="Include optional [Wallet] and [Chains] placeholders for EVM mechanisms.",
    ),
) -> None:
    """Scaffold the buyer.toml with placeholders for every known key.

    Writes only the commented-out skeleton so nothing breaks on first
    load. Fill in the values you need; the resolver treats missing keys
    as 'fall back to default', so a partial file is fine.
    """
    path = user_config_file()
    if path.exists() and not overwrite:
        typer.secho(
            f"{path} already exists. Pass --overwrite to replace it.",
            err=True,
            fg=typer.colors.RED,
        )
        raise typer.Exit(1)

    user_config_dir().mkdir(parents=True, exist_ok=True)
    template = _INIT_USER_TEMPLATE
    if include_evm_resources:
        template += _EVM_RESOURCE_TEMPLATE
    path.write_text(template)
    typer.echo(f"Wrote {path}")
    typer.echo("Edit it, or use `market config set <key> <value>` to populate.")
