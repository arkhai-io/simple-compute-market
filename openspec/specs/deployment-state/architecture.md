# Deployment and State Architecture

The [normative contract](spec.md) defines established deployment, persistence, migration, and package behavior. This document explains the operational boundaries those rules protect.

## Role-separated topology

Registry, seller stack, and buyer are independently operable roles. A buyer is normally a one-shot CLI or long-running agent, not a service required to keep the seller stack healthy. A seller composition owns its storefront and physical or quota authorities; a registry may be operated separately.

Local development composes domain stacks with development-only dependencies such as the local chain. Deployment charts compose the same roles conditionally without making test fixtures part of the production authority model.

## State ownership

Each stateful service owns its database and migration history. Cross-service relationships use public identifiers and APIs rather than foreign keys into another service's database. This keeps backup, rollout, failure, and authority boundaries aligned.

SQLite-backed deployed services use one writer with ReadWriteOnce storage and `Recreate` rollout semantics. Retained, existing, and ephemeral volumes have different durability consequences and must remain explicit deployment choices rather than hidden application behavior.

## Migration and initialization boundary

Schema migration and runtime initialization solve different problems:

- migration deterministically transforms the data model and may seed only rows required by a schema invariant;
- runtime initialization reconciles operator configuration and inventory idempotently without overwriting later operator changes.

Where a service has an explicit migration phase, deployment runs it before application startup and startup verifies schema compatibility rather than mutating the schema. This makes a migration failure diagnosable as deployment preparation instead of an application crash loop. That separation is not yet uniform across every service.

## Artifact and package boundary

Internal Python boundaries are exercised as distributions. Prerequisite packages are built into `.dist`, consumers install from that wheelhouse, and reinitialization explicitly upgrades or reinstalls changed distributions. Images include `.dist` in every stage that resolves internal packages.

The architectural purpose is reproducibility: package metadata and wheel contents, not checkout-relative imports, determine what a consumer receives. Pure-Python wheel checks prevent a host-built native artifact from being mistaken for a target-platform image dependency.

## Compatibility posture

Schema evolution is additive by default. A non-additive change needs an explicit expand/contract plan that identifies the period in which old and new readers or writers coexist. Public package and wire compatibility similarly belong to the owning capability rather than being inferred from a shared repository version.

## Current limits

The repository does not yet have one universal configuration-delivery mechanism or migration phase for every service. Publication authority between private artifact registries and public package releases, removal of all local source overrides, and a repository-wide typed-client versioning policy remain separate decisions.

## Related contracts

- [Market composition](../market-composition/spec.md)
- [Physical provisioning](../physical-provisioning/spec.md)
- [Testing and compatibility](../test-compatibility/spec.md)
