"""The storefront's migration chain and its command, ``apicredits-storefront-migrate [--check]``.

The chain is the family selling library's under this storefront's table prefix
and baseline identifier, named for this storefront, with this storefront's
floor: marketplace 0.3.0, whose chain recorded :data:`FLOOR_IDS`. A database
recording all of them is one that release ran on and is adopted at the
baseline, whatever earlier releases recorded beside them; one recording only
some is older than the floor, or another storefront's, which shares core
storefront's history. The storefront's database is upgraded together with the
API-credit service's, the service first. The command loads the layered settings alone, so it
runs without the storefront's chains or identity; Compose runs it before
``serve`` in the storefront's container, and ``make migrate`` runs it for local
development.
"""

from __future__ import annotations

from collections.abc import Sequence

from arkhai_api_selling.migrate import main as run_migration_command
from arkhai_api_selling.migrations import storefront_chain
from market_schema_migrations import Floor

from apicredits_storefront.settings_source import settings_source

TABLE_PREFIX = "api_credit"
"""Names this storefront's family tables; its selling bundle carries the same."""

BASELINE_ID = "v0_3_0_baseline_apicredits_storefront"
"""Identifies the family baseline in this storefront's databases; permanent."""

FLOOR_IDS: tuple[str, ...] = (
    "20260604_000_listing_resource_timestamps",
    "20260604_004_negotiation_amount_text_columns",
    "20260604_005_escrows_and_listings",
    "20260722_001_capacity_holds_reservation_id",
    "20260810_003_negotiation_provision_terms",
    "20260811_001_marketplace_principals_v2",
    "20260811_002_replay_attempt_leases",
    "20260815_001_storefront_domain_bindings",
    "20260911_001_listing_resource_column",
    "20260923_001_listing_binding_capacity_backing",
    "20260923_002_listing_binding_capacity_backing_required",
    "20260923_003_listing_closed_by",
    "20261001_001_listing_rate_structure",
    "20260810_001_settlement_obligation_lifecycle",
    "20260810_002_settlement_servicing_runtime",
    "20260811_003_settlement_principal_authorization",
    "20260815_004_settlement_mechanism_materialization_params",
    "20261028_005_settlement_operation_awaiting_delivery",
    "20260810_001_escrow_settlement_identity",
    "20260815_002_issuance_evidence",
)
"""Every ID the v0.3.0 release's API-credit storefront chain recorded."""

CHAIN = storefront_chain(
    TABLE_PREFIX,
    baseline_id=BASELINE_ID,
    service="the API-credit storefront",
    command="apicredits-storefront-migrate",
    floor=Floor("marketplace 0.3.0", FLOOR_IDS),
)


def main(argv: Sequence[str] | None = None) -> None:
    run_migration_command(CHAIN, settings_source, argv)


if __name__ == "__main__":
    main()
