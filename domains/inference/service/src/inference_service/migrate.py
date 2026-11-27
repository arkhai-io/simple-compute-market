"""The service's migration chain and its command, ``inference-service-migrate [--check]``.

The chain is the family authority's, named for this service. No release has
shipped the service, so its floor is ``0.0.0`` and the chain adopts no
database: it refuses every non-empty one it did not build. The command loads
the layered settings alone; the image's command runs it before the application, and
``make migrate`` runs it for local development outside Docker.
"""

from __future__ import annotations

from collections.abc import Sequence

from arkhai_api_authority import authority_chain
from arkhai_api_authority.migrate import main as run_migration_command
from market_schema_migrations import Floor

from inference_service.settings_source import load_settings_source

CHAIN = authority_chain(
    service="the inference service",
    command="inference-service-migrate",
    floor=Floor("0.0.0"),
)


def main(argv: Sequence[str] | None = None) -> None:
    run_migration_command(CHAIN, load_settings_source, argv)


if __name__ == "__main__":
    main()
