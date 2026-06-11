"""VM compute schema plugin for the core `market` buyer CLI.

The `market` console script is core-owned (``core_buyer.cli:main``); this
package contributes the VM compute schema's commands through the
``market.buyer_plugins`` entry-point group. The plugin claims the
``buy``/``negotiate``/``settle`` verbs and the ``listing`` group (named
compute filter flags + rendered output), plus the buyer-operator groups
(``config``, ``logs``, ``escrow``, ``network``, ``chain``).
"""

from __future__ import annotations

import typer

from core_buyer.cli import build_app
from core_buyer.plugins import BuyerSchemaPlugin

from . import buy_cli as buy_module
from .chain_cli import chain_app
from .config_cli import config_app
from .logs_cli import logs_app
from .network_cli import network_app
from . import negotiate_cli as negotiate_module
from . import settle_cli as settle_module
from . import service_cli as service_module
from .escrow_cli import escrow_app
from .listing_cli import listing_app


def register(app: typer.Typer) -> None:
    """Register the VM compute schema's buyer commands on the core app."""
    app.add_typer(listing_app, name="listing", help="Browse marketplace listings (list/show).")
    app.add_typer(
        config_app,
        name="config",
        help="Inspect or edit the buyer.toml (path/show/get/set/init-user).",
    )
    app.add_typer(logs_app, name="logs", help="Inspect past buy/negotiate runs (run-log JSONL files).")
    app.add_typer(escrow_app, name="escrow", help="Buyer-side escrow lifecycle (create, reclaim).")
    app.add_typer(network_app, name="network", help="Join the operator's ZeroTier network and list peers.")
    app.add_typer(chain_app, name="chain", help="Sanity-check chain config (eth_getCode against configured addresses).")

    buy_module.register(app)
    negotiate_module.register(app)
    settle_module.register(app)
    service_module.register(app)


#: Loaded by the core CLI via
#: [project.entry-points."market.buyer_plugins"] vms = "domains.vms.buyer.cli:plugin"
plugin = BuyerSchemaPlugin(
    schema_id="vms.compute",
    register=register,
    distribution="arkhai-vms-buyer",
)

#: Pre-assembled app for the PyInstaller binary (main.py), which can't rely
#: on entry-point metadata inside the frozen bundle. The installed `market`
#: console script reaches the same assembly through plugin discovery.
app = build_app(plugins=[plugin])


if __name__ == "__main__":
    app()
