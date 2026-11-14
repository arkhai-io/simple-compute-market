---
tags: [engineering, persistence, deployment]
---

# Migrations

How a stateful service's schema migrations run in a deployment, and what its
application does with the database they leave. Stored representations and schema
changes are [Persistence](persistence.md); how a migration chain is proven is
[Migration tests](migration-tests.md).

## Migrations run in a deployment phase, through the service's own command

A stateful service applies its migrations in a deployment phase before its
application starts, through its own packaged migration command, and its application
only checks the database. The application starts only once the migration succeeds.

## The command reads only the database location and log level

A migration command reads only its database location and log level from the
service's layered settings, without resolving anything else, so it needs no secret
mounted, and one database migrates to the same schema and rows under any profile.
What a deployment configures is applied by the service's startup after its check
passes, never by a migration.

## The application opens its database read-only

The application's startup opens its database read-only, issues no DDL, and refuses
any database but a compatible one, naming the migration command and every migration
ID that differs.

## A check mode previews

The migration command's check mode prints the same result as the startup check and
changes nothing: it succeeds only for a compatible database, and otherwise lists the
pending IDs, the unknown IDs, or the baseline to be adopted, so an operator can
preview an upgrade or verify a restored backup.

## Migrations fail forward

An older image cannot serve a migrated schema and refuses it as ahead, so rolling
back means restoring the backup taken before the upgrade, and a backup is taken
before every upgrade.

## No two versions share a database

No two versions of a service share its database: a deployment stops the old version
before the new one opens it. The Kubernetes form is in [Kubernetes](kubernetes.md).
