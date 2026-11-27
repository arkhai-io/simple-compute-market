"""The service's migration chain and its command, ``apicredits-service-migrate [--check]``.

The chain is the family authority's, named for this service, with this
service's floor: marketplace 0.3.0, whose service recorded :data:`FLOOR_IDS`
on every database it built. A database recording all of them is one that
release ran on and is adopted at the baseline, whatever earlier releases
recorded beside them; one recording only some is older than the floor, or
another service's. The service's database is upgraded together with the
API-credit storefront's, the service first. The command loads
the layered settings without the application's secrets, so it runs before they
are mounted; Compose runs it before the application, and ``make migrate`` runs
it for local development outside Docker.
"""

from __future__ import annotations

from collections.abc import Sequence

from arkhai_api_authority import authority_chain
from arkhai_api_authority.migrate import main as run_migration_command
from market_schema_migrations import Floor

from apicredits_service.settings_source import load_settings_source

FLOOR_IDS: tuple[str, ...] = (
    "20260731_001_apicredits_schema_baseline",
    "20260811_002_canonical_owner_principals",
    "20260815_003_fulfillment_grants",
    "20260922_004_pool_advertisement_and_backing",
    "20261005_005_reservation_release_requested_at",
    "20261028_006_retired_reservation_states",
    "20261106_007_reservation_activated_at",
)
"""Every ID the v0.3.0 release's API-credit service recorded on a database it built."""

CHAIN = authority_chain(
    service="the API-credit service",
    command="apicredits-service-migrate",
    floor=Floor("marketplace 0.3.0", FLOOR_IDS),
)


def main(argv: Sequence[str] | None = None) -> None:
    run_migration_command(CHAIN, load_settings_source, argv)


if __name__ == "__main__":
    main()
