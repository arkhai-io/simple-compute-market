"""API-tokens schema plugin for the core `market` buyer CLI.

The `market` console script is core-owned (``core_buyer.cli:main``);
this package contributes the API-tokens schema's commands through the
``market.buyer_plugins`` entry-point group. Unlike the first (VM)
plugin, which claims the bare ``buy``/``negotiate``/``settle`` verbs,
this plugin namespaces its verbs under one ``tokens`` group —
``market tokens buy``, ``market tokens listing list``, … — so the two
plugins compose in one binary without shadowing each other ("one
binary, many registry schemas"). Dispatching the bare verbs by listing
schema is item-7 territory; until then the first-installed plugin's
claim on them stands.
"""

from __future__ import annotations

import typer

from core_buyer.cli import build_app
from core_buyer.plugins import BuyerSchemaPlugin

from . import buy_cli as buy_module
from . import negotiate_cli as negotiate_module
from . import settle_cli as settle_module
from .common import APITOKENS_SCHEMA_ID
from .listing_cli import listing_app


tokens_app = typer.Typer(no_args_is_help=True)
tokens_app.add_typer(
    listing_app, name="listing",
    help="Browse API-token listings (list/show).",
)
buy_module.register(tokens_app)
negotiate_module.register(tokens_app)
settle_module.register(tokens_app)


def register(app: typer.Typer) -> None:
    """Register the API-tokens schema's buyer commands on the core app."""
    app.add_typer(
        tokens_app, name="tokens",
        help="API-token (prepaid credits) market: discover, buy, top up keys.",
    )


#: Loaded by the core CLI via
#: [project.entry-points."market.buyer_plugins"] apitokens = "domains.apitokens.buyer.cli:plugin"
plugin = BuyerSchemaPlugin(
    schema_id=APITOKENS_SCHEMA_ID,
    register=register,
    distribution="arkhai-apitokens-buyer",
)

#: Pre-assembled app for direct module execution; the installed `market`
#: console script reaches the same assembly through plugin discovery.
app = build_app(plugins=[plugin])


if __name__ == "__main__":
    app()
