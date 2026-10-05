"""Inspect the credits authority's disposable fresh grant schema."""

from pathlib import Path
from tempfile import TemporaryDirectory

from sqlalchemy import text
from db.database import create_db_engine, run_migrations
from db.migrations import check_schema_version

with TemporaryDirectory(prefix="closeout-credits-schema-") as directory:
    path = Path(directory) / "db.sqlite"
    engine = create_db_engine("sqlite:///" + str(path), True)
    run_migrations(engine)
    run_migrations(engine)
    check_schema_version(engine)
    with engine.connect() as conn:
        print("credit_grants", [row[1] for row in conn.execute(text("PRAGMA table_info(credit_grants)"))])
        print(conn.execute(text("SELECT sql FROM sqlite_master WHERE name='credit_grants'")).scalar())
    engine.dispose()
print("temporary_database_removed=", not path.exists())
