"""Standalone migration CLI entrypoint.

    python -m db.migrate

Invokes the same migration logic the application used to run in-process at
startup (see ARCHITECTURE.md § Schema Migration Execution). Used by:

  - The Helm init container (same image as the main Deployment container,
    different command) — ``Init:Error`` is an unambiguous signal in
    Kubernetes pod status that migration failed, distinct from an
    application crash.
  - ``make migrate`` for local development outside Docker.

Idempotent: applied migrations are tracked in ``schema_migrations`` and
skipped on repeat runs. Logs each migration applied and exits 0 on success;
exits non-zero (via the raised exception's default traceback) on failure.
"""

from __future__ import annotations

import logging

from compute_provisioning_service.config import settings
from compute_provisioning_service.db.database import create_db_engine, run_migrations

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def main() -> None:
    engine = create_db_engine(settings.database_url, settings.is_sqlite)
    logger.info("Applying migrations to %s ...", settings.database_url)
    run_migrations(
        engine,
        default_playbook_path=str(settings.resolved_playbook_path),
        default_inventory_group=str(settings.default_pool_inventory_group),
    )
    logger.info("Migrations applied successfully.")


if __name__ == "__main__":
    main()
