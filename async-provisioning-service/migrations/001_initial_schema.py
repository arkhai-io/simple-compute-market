"""
Database migration: Initial schema with all required columns.

This migration creates the provisioning_jobs table with all columns including:
1. Core job fields (id, status, params, result, logs, error)
2. Timestamps (created_at, updated_at)
3. Cancellation support (process_id)
4. Retry support (retry_count, max_retries, next_retry_at)

Run this migration before starting the provisioning service.
"""

import logging
from sqlalchemy import text

from async_provisioning_service.config import settings
from async_provisioning_service.db.database import SessionLocal, engine

logger = logging.getLogger(__name__)


def _table_exists(connection, table_name: str) -> bool:
    """Check if a table exists (works with both PostgreSQL and SQLite)."""
    if settings.is_sqlite:
        # SQLite uses sqlite_master
        result = connection.execute(
            text(
                """
                SELECT name FROM sqlite_master
                WHERE type='table' AND name=:table_name
                """
            ),
            {"table_name": table_name}
        )
    else:
        # PostgreSQL uses information_schema
        result = connection.execute(
            text(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_name = :table_name
                """
            ),
            {"table_name": table_name}
        )
    return result.fetchone() is not None


def _column_exists(connection, table_name: str, column_name: str) -> bool:
    """Check if a column exists (works with both PostgreSQL and SQLite)."""
    if settings.is_sqlite:
        # SQLite uses PRAGMA table_info
        result = connection.execute(
            text(f"PRAGMA table_info({table_name})")
        )
        columns = {row[1] for row in result.fetchall()}  # row[1] is column name
        return column_name in columns
    else:
        # PostgreSQL uses information_schema
        result = connection.execute(
            text(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = :table_name
                AND column_name = :column_name
                """
            ),
            {"table_name": table_name, "column_name": column_name}
        )
        return result.fetchone() is not None


def migrate():
    """Apply migration to create or update provisioning_jobs table."""
    logger.info("Running migration: initial schema")

    with engine.begin() as connection:
        # Check if table exists
        table_exists = _table_exists(connection, "provisioning_jobs")

        if not table_exists:
            logger.info("Creating provisioning_jobs table with full schema")

            # Use appropriate syntax for SQLite vs PostgreSQL
            if settings.is_sqlite:
                # SQLite doesn't support TIMESTAMP WITH TIME ZONE, use TEXT
                connection.execute(
                    text(
                        """
                        CREATE TABLE provisioning_jobs (
                            id VARCHAR PRIMARY KEY,
                            status VARCHAR NOT NULL,
                            params JSON NOT NULL,
                            result JSON,
                            logs TEXT,
                            error TEXT,
                            process_id VARCHAR,
                            retry_count INTEGER NOT NULL DEFAULT 0,
                            max_retries INTEGER NOT NULL DEFAULT 3,
                            next_retry_at TEXT,
                            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                        )
                        """
                    )
                )
            else:
                # PostgreSQL with proper timestamp types
                connection.execute(
                    text(
                        """
                        CREATE TABLE provisioning_jobs (
                            id VARCHAR PRIMARY KEY,
                            status VARCHAR NOT NULL,
                            params JSON NOT NULL,
                            result JSON,
                            logs TEXT,
                            error TEXT,
                            process_id VARCHAR,
                            retry_count INTEGER NOT NULL DEFAULT 0,
                            max_retries INTEGER NOT NULL DEFAULT 3,
                            next_retry_at TIMESTAMP WITH TIME ZONE,
                            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
                            updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
                        )
                        """
                    )
                )
            logger.info("Migration complete: provisioning_jobs table created")
        else:
            logger.info("Table provisioning_jobs already exists, checking for missing columns")

            # Add process_id if missing
            if not _column_exists(connection, "provisioning_jobs", "process_id"):
                logger.info("Adding process_id column")
                connection.execute(
                    text("ALTER TABLE provisioning_jobs ADD COLUMN process_id VARCHAR")
                )

            # Add retry_count if missing
            if not _column_exists(connection, "provisioning_jobs", "retry_count"):
                logger.info("Adding retry tracking columns")
                connection.execute(
                    text("ALTER TABLE provisioning_jobs ADD COLUMN retry_count INTEGER NOT NULL DEFAULT 0")
                )
                connection.execute(
                    text("ALTER TABLE provisioning_jobs ADD COLUMN max_retries INTEGER NOT NULL DEFAULT 3")
                )

                # Use appropriate timestamp type
                if settings.is_sqlite:
                    connection.execute(
                        text("ALTER TABLE provisioning_jobs ADD COLUMN next_retry_at TEXT")
                    )
                else:
                    connection.execute(
                        text("ALTER TABLE provisioning_jobs ADD COLUMN next_retry_at TIMESTAMP WITH TIME ZONE")
                    )

            logger.info("Migration complete: all columns verified")


def rollback():
    """Rollback migration (drop provisioning_jobs table)."""
    logger.info("Rolling back migration: drop provisioning_jobs table")

    with engine.begin() as connection:
        logger.info("Dropping provisioning_jobs table")
        connection.execute(text("DROP TABLE IF EXISTS provisioning_jobs"))
        logger.info("Rollback complete: provisioning_jobs table dropped")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    migrate()
