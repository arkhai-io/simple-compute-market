## Why

Six services own SQLite state, and only compute provisioning separates migration from startup — imperfectly: its guard checks only the last migration ID and `create_all` runs around its chain. The three storefronts build their schema whenever a database client is constructed, through an unversioned bootstrap interleaved with two passes of their chains, and kits create tables whenever a store opens; the API-credit service and the registry migrate in-process. A failed migration therefore appears as an application crash loop, no tool can say a database is behind without changing it, and every in-flight change adding a migration lands in an ad hoc path. Four migration engines exist and disagree on whether a migration commits with its record. An upgrade of a long-lived deployment to the marketplace v0.3.0 release also found stored data the release cannot serve and a superseded listing left open at the registry.

## What Changes

- One migration mechanism for every stateful service — compute provisioning, the VM storefront, the bare-metal storefront, the API-credit storefront, the API-credit service, and the registry: a packaged `<service command>-migrate` console script reading only its database location and log level, with a `--check` preview; a startup check that issues no DDL and accepts only the exact set of its chain's migrations; and a deployment phase before the application — a Helm init container in the storefront, bare-metal storefront, and registry charts, and the command before the application under Compose.
- A new foundation kit holds one in-house migration engine, used by every in-house service and every kit that owns tables, applying each migration and its record in one transaction; the registry keeps Alembic behind the same command, check result, and refusal message.
- A clean sweep: each chain begins at baselines of fixed DDL — for compute provisioning, both compute storefronts, and the registry, reproducing the schema the v0.3.0 release builds at startup; v0.3.0 databases of compute provisioning, both compute storefronts, and the registry are adopted, and older ones are refused as unsupported; the API-credit services are swept without an adoption path. The storefronts' unversioned bootstrap, every pre-v0.3.0 migration, the registry's eighteen revisions (squashed into one baseline revision), the frozen tables, and `market-storefront migrate-storefront-domains` are removed.
- No schema change outside a migration chain: kits' and domains' table creation at store open, and the storefront's index creation after its chain, move into one migration after the baseline, which creates on an adopted v0.3.0 database whatever v0.3.0 had not yet created; the API-credit service's `default` pool is seeded at startup instead of by migration.
- A migration after the baseline rewrites every compute provisioning host's stored `ssh` version-1 connection to version 2, so no job dispatched after the upgrade fails on one; the host contract's connection `version` becomes required. A reservation whose teardown already failed on a version-1 host is recovered by the operator's manual teardown and force-release, as the operator handbook's upgrade procedure states.
- Each storefront's publication pass closes, at each registry, open listings under its own principal and offering modes that it does not hold open.
- Permanent documents use *role* for an actor and *service* for a stateful process, throughout.
- Breaking for operators: pre-v0.3.0 databases and every existing API-credit database must start fresh; an image rolled back over a migrated database is refused; a host submission must state its connection version; a lease left `release_failed` on a version-1 host before the upgrade needs a manual teardown before force-release.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `deployment-state`: every stateful service migrates through its packaged command before startup, checks the exact set of its chain without DDL, begins its chain at the v0.3.0 baseline, records each migration atomically, and changes no schema outside its chain; a chart's only init container is the service's own migration; the legacy storefront domain migration is removed; "Identity migrations are coordinated and fail closed" is restated as "Identity cutover is coordinated and fails closed", without its rule that each service migrates address-only identity rows, a conversion part of the v0.3.0 floor.
- `storefront-publication`: a storefront retires registry listings it does not hold open; the requirement for the storefront identity conversion, part of the v0.3.0 floor, is removed; and "Storefront holds no physical-resource authority" is restated as "Storefront holds no physical-resource authority or inventory", without the retained inventory rows the VM storefront's migration now drops.
- `negotiation-protocol`: the requirement for the negotiation identity conversion, part of the storefronts' v0.3.0 floor, is removed, and its recovery rule is kept as "Negotiation recovery is deterministic".
- `physical-provisioning`: hosts' stored `ssh` version-1 connections are rewritten to version 2 by migration, and a connection submission must state its version; the requirements for the host-identity and active-fulfillment migrations, part of the v0.3.0 floor, are removed, as is the bare-metal storefront's refusal of state written under a retired listing kind, part of its v0.3.0 floor; and the host requirements describing the floor's capacity-declaration derivation and GPU-column drop are restated without them.
- `fulfillment`: the requirement for the legacy-lease cutover, part of the v0.3.0 floor, is removed, and the kit's dependency boundary admits the migration kit.
- `registry-discovery`: the requirement for the legacy publisher-identity migration, part of the registry's v0.3.0 floor, is removed, and "Stable publisher-chosen listing identity" no longer requires that migration to preserve identifiers.
- `site-capacity`: the requirement for converting reservations in retired states — part of compute provisioning's v0.3.0 floor, and of the API-credit service's chain, which no longer migrates an existing database — is removed, and "Capacity schema separation" is restated without its pre-floor migration scenario, as are the requirements for the requested offering mode, the release handle, and lease activation, without their offering-mode backfill, release-mirror drop, and activation-column migrations.
- `resource-pool-management`: the requirements describing its pool-membership, offering-mode, advertisement-and-backing, and VM-provider-identity migrations, part of compute provisioning's v0.3.0 floor, are removed, and their rules are restated without them.

## Dependencies and Related Changes

- Heads the "Registry productionization" campaign. Takes the registry's migration command, startup check, and blank-database baseline from `migrate-registry-to-postgres`, which keeps PostgreSQL, the cutover, the rollout Job and the Secrets; this change's closeout amends its proposal.
- `store-registry-listings-as-published` adds its registry migration after the baseline revision.
- `separate-marketplace-registry` expects a registry migration resource that a disabled registry must not render; this change creates it, so the dependency its index note questions is real, for its design review to record.
- Supersedes `hollow-pre-floor-provisioning-migrations`, whose upgrade floor and hollowed migrations the baseline replaces; closeout removes its directory and reconciles its row.
- `multi-domain-storefront-composition` (in closeout) adds a requirement for the domain migration command this change removes; whichever archives second reconciles the two.
- Changes in flight that add migrations, `relay-vm-access-without-a-dashboard` among them, place them after the baseline.

## Non-Goals

- No business-schema redesign beyond dropping the frozen tables.
- No automatic downgrade.
- No PostgreSQL cutover, rollout Job, or external database provisioning for the registry.
- No Alembic for the in-house services (deferred; see `design.md`'s Open Questions).
- No option-ID stability across a release that changes the option envelope.

## Impact

Touches every stateful service's database construction, migration modules and startup; a new foundation kit and its packaging and architecture entries; every kit that owns tables (core storefront, settlement runtime, contact exchange, pool overrides, deal-servicing, site, resource pools, fulfillment); console entry points for six services; the storefront, bare-metal storefront, and registry charts and their render tests; every Compose stack and service Makefile; the compute provisioning host contract; `kit/capacity-publication`; migration tests across the repository; and the permanent documents' vocabulary. Runtime APIs are unchanged except the host contract's required connection version.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md`
- [x] Existing subsystem specification
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

- D1 — every stateful service migrates through the one mechanism: `openspec/specs/deployment-state/spec.md` (archive) and `openspec/specs/deployment-state/architecture.md`, "Migration and initialization boundary".
- D2 — one in-house engine in a foundation kit, the registry on Alembic behind the same contract: `openspec/specs/deployment-state/architecture.md`; `docs/development/ARCHITECTURE.md`, the kit areas (where the foundation kit sits); `docs/development/DEPLOYMENT_AND_CONFIG.md`, "Migrations at startup".
- D3 — the v0.3.0 baseline, adoption, and refusal; the frozen tables dropped; the legacy domain migration removed: `openspec/specs/deployment-state/spec.md` (archive) and its architecture companion; `docs/development/DEPLOYMENT_AND_CONFIG.md`, "Migrations at startup", pruned; `docs/operator-handbook.md`, the upgrade procedure; `docs/development/ARCHITECTURE.md`, "Build, packaging, and initialization", its fresh-database rule restated; `docs/development/ROADMAP.md`, the frozen-table follow-up closed.
- D4 — no migration reads operational configuration: `openspec/specs/deployment-state/spec.md` (archive).
- D5 — compatibility is the exact set of recorded migrations: `openspec/specs/deployment-state/spec.md` (archive) and its architecture companion; `docs/development/TESTING.md`, the floor-fixture and store-open tests.
- D6 — one console script per service: `openspec/specs/deployment-state/spec.md` (archive); `docs/development/DEPLOYMENT_AND_CONFIG.md`, "Migrations at startup".
- D7 — the init container and the Compose form: `openspec/specs/deployment-state/spec.md` (archive); `docs/development/DEPLOYMENT_AND_CONFIG.md`, "Kubernetes: ConfigMap and Secret mounting" and "Migrations at startup".
- D8 — provisioning on the standard: `openspec/specs/deployment-state/spec.md` (archive); `docs/development/DEPLOYMENT_AND_CONFIG.md`, "Migrations at startup".
- D9 — no schema change outside a chain: `openspec/specs/deployment-state/spec.md` (archive); `docs/development/TESTING.md`.
- D10 — the API-credit service seeds its pool at startup: `openspec/specs/deployment-state/spec.md` (archive).
- D11: no permanent destination — a Make target per service is a development convenience the Makefiles document themselves.
- D12: no permanent destination — it records how the requirements change, which the archived specifications then state.
- D13: no permanent destination — effects on other changes are recorded in those changes and the change index at closeout.
- D14 — the check mode: `openspec/specs/deployment-state/spec.md` (archive); `docs/operator-handbook.md`, the upgrade procedure.
- D15 — `ssh` connection repair and required version: `openspec/specs/physical-provisioning/spec.md` (archive) and `openspec/specs/physical-provisioning/architecture.md`, "The host registry owns the connection"; recovering a lease left `release_failed` on a version-1 host by manual teardown and force-release: `docs/operator-handbook.md`, the upgrade procedure; re-running a teardown that failed before its executor ran, unowned: `docs/development/ROADMAP.md`, Goal 1's open gaps; registry-listing retirement: `openspec/specs/storefront-publication/spec.md` (archive) and `openspec/specs/storefront-publication/architecture.md`; option-ID policy at upgrade: `docs/operator-handbook.md`.
- D16 — role and service: `docs/development/ARCHITECTURE.md`, "Terms"; the permanent documents' uses made consistent; the mechanism's guidance in `docs/development/DEPLOYMENT_AND_CONFIG.md` and the release-time floor decision in `docs/development/RELEASING.md`.
