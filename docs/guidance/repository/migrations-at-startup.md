---
tags: [repository, persistence, deployment]
---

# Migrations at startup

How each stateful service here migrates its database before it starts, as
[`migrations.md`](../engineering/migrations.md) describes. For this repository the
rules are `deployment-state`'s
["Service-owned migration history"](../../../openspec/specs/deployment-state/spec.md#requirement-service-owned-migration-history)
and the requirements beside it, and the design is its companion's
["Migration and initialization boundary"](../../../openspec/specs/deployment-state/architecture.md#migration-and-initialization-boundary).
What the check mode reports, which databases each chain adopts, and the migrations
after the baseline are
[`DEPLOYMENT_AND_CONFIG.md`, "Migrations at startup"](../../development/DEPLOYMENT_AND_CONFIG.md#migrations-at-startup);
how the chains are proven is [`migration-chain-tests.md`](migration-chain-tests.md).

## The command and its phase

Every stateful service migrates through the command and in the phase below.

| Service | Command | Deployment phase |
|---|---|---|
| Compute provisioning | `compute-provisioning-migrate` | init container in `helm/charts/provisioning`; before the service under Compose |
| VM storefront | `market-storefront-migrate` | init container per agent in `helm/charts/storefront`; before the storefront under Compose |
| Bare-metal storefront | `bare-metal-storefront-migrate` | init container in `helm/charts/bare-metal-storefront`; before the storefront under Compose |
| API-credit storefront | `apicredits-storefront-migrate` | before the storefront under Compose |
| API-credit service | `apicredits-service-migrate` | before the service under Compose, and in its image's command |
| Registry | `registry-migrate` | init container in `helm/charts/registry`, for each instance; before the registry under Compose, and in its image's command |

Each service's `Makefile` has a `migrate` target running its command. Under
Helm the init container runs from the application's image with the
application's environment, configuration mounts and data volume — the VM
storefront's without `entrypoint.sh`, which only starts ZeroTier — and is the
only init container a chart renders for a service
([`helm-charts.md`](helm-charts.md#a-deployment-does-not-wait-on-a-services-dependencies)).
Under Compose the service's command is
`sh -c "<service>-migrate && exec <service command>"`, so the application starts
only once the migration succeeds; the VM storefront runs it through
`./entrypoint.sh`, and the bare-metal storefront, whose image's entrypoint is its
CLI, states it as its `entrypoint`. The registry chart's application container
states its own `uvicorn` command, since the image's command migrates first for
Compose.

## The command's configuration

Each migration command is configured as
[`migrations.md`](../engineering/migrations.md#the-command-reads-only-the-database-location-and-log-level)
says; the bare-metal storefront's reads only its `db_path`, logging at INFO. What a
deployment configures — a site's pools, their seed, its playbooks, the
API-credit service's `default` pool — is applied by the service's startup
after its check passes. Migration creates no pool.

## The application's open and the check mode

Each application opens its database as
[`migrations.md`](../engineering/migrations.md#the-application-opens-its-database-read-only)
says, and `<service>-migrate --check` is the check mode
([`migrations.md`](../engineering/migrations.md#a-check-mode-previews)):
it exits 0 only for a compatible database.

## Migrations fail forward

The migrations after a chain's baseline are fail-forward
([`migrations.md`](../engineering/migrations.md#migrations-fail-forward)). No two
versions of a service share a database, as
[`service-databases.md`](service-databases.md#a-single-writer-store-deploys-with-recreate)
deploys each.
