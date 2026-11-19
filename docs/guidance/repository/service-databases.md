---
tags: [repository, persistence, deployment, kubernetes]
---

# Service databases

Who owns each service's state here, and how a stateful service is deployed over it.
What the images and charts do with the services' volumes is
[`DEPLOYMENT_AND_CONFIG.md`, "Stateful service persistence"](../../development/DEPLOYMENT_AND_CONFIG.md#stateful-service-persistence).

## Each service owns its database

Each service owns its own database; there is no shared database between
services (see `openspec/specs/deployment-state/spec.md`'s "Explicit
persistence ownership").

The API-credit storefront and the credits service each own their own state: the
credits service owns keys, request-digested grants, balances, quota, credentials,
and its migration history. Restart either against its own volume. Never
source-share a sibling package or mount one service's database into the other.

## A single-writer store deploys with `Recreate`

Each SQLite-backed service's chart deploys it with
the `Recreate` strategy over one `ReadWriteOnce` volume
([`kubernetes.md`, "A single-writer store deploys with `Recreate`"](../engineering/kubernetes.md#a-single-writer-store-deploys-with-recreate)),
so no two versions of a service share a database
([`migrations.md`](../engineering/migrations.md#no-two-versions-share-a-database)).
