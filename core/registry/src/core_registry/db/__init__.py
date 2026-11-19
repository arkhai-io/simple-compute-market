"""The registry's persistence: its models, sessions, and migrations.

Importing this package loads nothing else: the migration command and the
Alembic environment import ``core_registry.db.models`` and
``core_registry.db.migrations`` without the application's settings, which
``core_registry.db.database`` reads to build its engine.
"""
