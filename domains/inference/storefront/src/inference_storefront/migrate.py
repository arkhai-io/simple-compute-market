"""The storefront's migration chain and its command, ``inference-storefront-migrate [--check]``.

The chain is the family selling library's under this storefront's table prefix
and baseline identifier, named for this storefront. No release has shipped
the storefront, so its floor is ``0.0.0`` and the chain adopts no database.
The command loads the layered settings alone, so it
runs without the storefront's chains or identity; the image's command runs it
before ``serve``, and ``make migrate`` runs it for local development.
"""

from __future__ import annotations

from collections.abc import Sequence

from arkhai_api_selling.migrate import main as run_migration_command
from arkhai_api_selling.migrations import storefront_chain
from market_schema_migrations import Floor

from inference_storefront.settings_source import settings_source

TABLE_PREFIX = "inference"
"""Names this storefront's family tables; its selling bundle carries the same."""

BASELINE_ID = "v0_3_0_baseline_inference_storefront"
"""Identifies the family baseline in this storefront's databases; permanent."""

CHAIN = storefront_chain(
    TABLE_PREFIX,
    baseline_id=BASELINE_ID,
    service="the inference storefront",
    command="inference-storefront-migrate",
    floor=Floor("0.0.0"),
)


def main(argv: Sequence[str] | None = None) -> None:
    run_migration_command(CHAIN, settings_source, argv)


if __name__ == "__main__":
    main()
