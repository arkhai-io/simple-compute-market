"""API-tokens buyer-plugin common helpers.

Schema-invariant config resolution lives in ``core_buyer``; this module
keeps what is API-tokens vocabulary — the schema id, the registry
filter mapping, and the key-disposition flag parsing.
"""

from __future__ import annotations

import typer

from core_buyer.buyer_config import (  # noqa: F401 — re-exports
    buyer_chains,
    chain_by_name,
    resolve_buyer_wallet,
    resolve_config_value,
    resolve_negotiation_config,
    select_chain_for_listing,
)
from core_buyer.registry_config import (  # noqa: F401 — re-exports
    resolve_discovery_timeout,
    resolve_indexer_auth,
    resolve_indexer_urls,
    resolve_indexer_urls_for_schema,
)

#: The registry schema this plugin implements (mirrors the
#: BuyerSchemaPlugin declaration in `.cli`). Discovery verbs resolve
#: registries through `resolve_indexer_urls_for_schema(APITOKENS_SCHEMA_ID, …)`
#: so registries declaring a different schema are skipped. The
#: api-tokens registry's filter-spec.yaml declares the same id.
APITOKENS_SCHEMA_ID = "api_tokens"


def build_token_filter_params(*, service_name: str | None = None) -> dict[str, str]:
    """Map the plugin's convenience flags to registry filter-spec params."""
    params: dict[str, str] = {}
    if service_name:
        params["service_name"] = service_name
    return params


def resolve_key_disposition(
    *, new_key: bool, key_id: str | None,
) -> tuple[str, str | None]:
    """``(key_mode, key_id)`` from the ``--new-key`` / ``--key-id`` flags.

    Mutually exclusive; with neither given the default is a fresh key
    (auto-bound to the purchasing wallet by the v1 seller default).
    """
    if new_key and key_id:
        typer.secho(
            "--new-key and --key-id are mutually exclusive: a deal either "
            "issues a fresh key or tops up an existing one.",
            err=True, fg=typer.colors.RED,
        )
        raise typer.Exit(2)
    if key_id:
        return "existing", key_id
    return "new", None
