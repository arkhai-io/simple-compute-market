"""
Database migration: Add process_id column and cancelled status.

This migration adds:
1. process_id column to track running Ansible processes for cancellation
2. 'cancelled' status to JobStatus enum

Run this migration before deploying the updated provisioning service.
"""

import logging
from sqlalchemy import text

from async_provisioning_service.db.database import SessionLocal, engine

logger = logging.getLogger(__name__)


def migrate():
    """Apply migration to add process_id column."""
    logger.info("Running migration: add process_id and cancelled status")

    with engine.begin() as connection:
        # Check if process_id column already exists
        result = connection.execute(
            text(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = 'provisioning_jobs'
                AND column_name = 'process_id'
                """
            )
        )
        column_exists = result.fetchone() is not None

        if not column_exists:
            logger.info("Adding process_id column to provisioning_jobs table")
            connection.execute(
                text(
                    """
                    ALTER TABLE provisioning_jobs
                    ADD COLUMN process_id VARCHAR NULL
                    """
                )
            )
            logger.info("Migration complete: process_id column added")
        else:
            logger.info("Migration skipped: process_id column already exists")


def rollback():
    """Rollback migration (remove process_id column)."""
    logger.info("Rolling back migration: remove process_id")

    with engine.begin() as connection:
        logger.info("Removing process_id column from provisioning_jobs table")
        connection.execute(
            text(
                """
                ALTER TABLE provisioning_jobs
                DROP COLUMN IF EXISTS process_id
                """
            )
        )
        logger.info("Rollback complete: process_id column removed")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    migrate()
