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
preview an upgrade or verify a restored backup. For a database awaiting adoption it
names the floor release whose records adoption replaces and lists every other record
adoption sets aside, so the IDs that differ between databases are visible before a
deployment.

## Every chain declares its floor, and a database upgrades through it

Every migration chain declares its floor: the release it is supported from, by name,
and the migration IDs that release's chain recorded. A chain with no earlier history
declares a floor recording nothing, and adopts no database. The engine refuses to
construct a chain that declares no floor.

A database the floor release ran on is adopted, whatever earlier releases recorded
in it. Such a database records every ID the floor release's chain recorded and none
of the chain's baselines. In one transaction, the command forgets every recorded ID
the chain does not list, records the baselines without running them, and then
applies the later migrations. An earlier runner may have ignored records it no
longer listed, so a database that reached the floor by upgrading can carry records a
fresh one lacks. Every image of the chain records the baselines, so a record on a
database recording no baseline was written in the floor release's era or before it,
never by a newer image.

A database recording some of the floor's IDs but not all is older than the floor, or
it is another service's database sharing its history, and the ledger cannot tell
the two apart. The command refuses it, naming the floor release and the IDs the
database lacks. Once the operator has confirmed the database is the service's own,
the refusal directs them to upgrade it through the floor release first. A database
recording none of the floor's IDs is not the service's, and its refusal names no
remedy. Starting fresh is never the remedy for a database that can upgrade, since it
discards the deployment's state.

For example, a billing service whose floor is its 2.0 release adopts a database 2.0
ran on, even one carrying records its 1.x releases wrote. It tells the operator of a
1.x database to run 2.0 on it first.

## Migrations fail forward

An older image cannot serve a migrated schema and refuses it as ahead, so rolling
back means restoring the backup taken before the upgrade, and a backup is taken
before every upgrade.

## No two versions share a database

No two versions of a service share its database: a deployment stops the old version
before the new one opens it. The Kubernetes form is in [Kubernetes](kubernetes.md).
