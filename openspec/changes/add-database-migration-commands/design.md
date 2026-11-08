## Context

Six services own SQLite state: compute provisioning, the VM storefront (`market-storefront`), the bare-metal storefront, the API-credit storefront, the API-credit service, and the registry. Only compute provisioning separates migration from startup: `compute-provisioning-migrate` runs as a Helm init container, and the application refuses a database behind its chain. Even it is a hybrid — `create_all` over seven metadata sets runs around its versioned chain, its guard checks only that the last listed ID is recorded (so a table added without a migration, or an ID the code does not know, passes), its refusal names a `migrate-job.yaml` that does not exist, and no render test covers the init container.

The three storefronts build their schema whenever `core_storefront.SQLiteClient` is constructed. `_ensure_tables_sync` interleaves an unversioned bootstrap (legacy renames and drops, about thirty `try/except` column additions, backfill-then-drop sequences — still extended as recently as 2026-10-08), `CREATE TABLE IF NOT EXISTS`, two passes of the core chain (the first silently skipping, without recording, any migration whose `required_tables` are absent), the kit and domain chains, domain indexes, and domain refusal checks. `kit/deal-servicing`, VM's delivery records, and bare metal's lifecycle cursor create tables whenever a store opens. One core migration (`20260811_001_marketplace_principals_v2`) needs the configured principal and storefront URL, so the storefront chain is not configuration-free.

The API-credit service runs `create_all`, seeds a `default` pool, and applies a versioned chain in-process; its `check_schema_version` exists and nothing calls it. The permanent spec names it as allowed to migrate in-process. The registry runs Alembic in-process (`create_all` + `stamp head` on a blank database, legacy-revision detection otherwise). Both storefront charts' render tests assert that no init container renders.

Four engines exist: provisioning's (SQLAlchemy `Engine`, records each ID in a separate transaction after the migration), the API-credit service's copy of it, core storefront's (`sqlite3`, one savepoint per migration with its record inside), and the registry's Alembic.

The marketplace v0.3.0 release (`main` at `d595f0c2`) carries exactly dev `9fffe41e9`'s service code. An upgrade of a long-lived deployment to v0.3.0 found that the v0.3.0 provisioning chain itself writes legacy hosts as `ssh` connection version 1, which v0.3.0 refuses, leaving jobs that captured those connections unable to tear down; and that the bare-metal storefront left a superseded listing open at the registry, unknown to it.

## Goals / Non-Goals

**Goals:** one migration mechanism for every stateful service — a packaged command, a startup check that issues no DDL, a deployment phase before the application, and a `--check` preview; a chain that begins at the v0.3.0 schema, so pre-release history and its bootstrap are deleted rather than carried; atomic per-migration recording; supported v0.3.0 databases adopted and repaired where their data is something the release cannot serve; storefronts that retire registry listings they no longer hold; one vocabulary — a role is an actor, a stateful process is a service.

**Non-Goals:** business-schema redesign; automatic downgrade; the registry's PostgreSQL cutover and its rollout Job; adopting Alembic for the in-house services; option-ID stability across a release that changes the option envelope.

## Decisions

### D1 — Every stateful service is in scope

The VM storefront, the bare-metal storefront, the API-credit storefront, the API-credit service, and the registry converge on one mechanism, with compute provisioning brought onto it as well. The three storefronts share one construction path, so bare metal cannot be left out; the API-credit service's guard already exists, and its in-process exception is removed; the registry's command, guard and deployment phase over its existing Alembic machinery are small and make this change the real head of the registry campaign.

Rejected: the proposal's VM-and-API-credit scope (bare metal would need a second, opt-in migrating path in core); storefronts only (keeps a named exception and a crash-loop failure mode); leaving the registry with `migrate-registry-to-postgres` (its dependents would conform to conventions never set for it).

### D2 — One in-house migration engine in a foundation kit; the registry stays on Alembic behind the same contract

A new market-neutral foundation kit holds the engine: the `Migration` type, a `Chain` (its service, command, migrations, v0.3.0 floor IDs and baseline IDs), `migrate` (which adopts at the floor), `check` (returning *absent*, *behind*, *ahead*, *unsupported*, or *compatible* with the differing IDs), a refusal-message renderer that does not depend on the engine, and `schema_snapshot` for tests. It runs over a small adapter per connection type (`sqlite3` and SQLAlchemy). Provisioning, the API-credit service, the three storefronts, and every kit that owns tables use it; `kit/site`, present in both the provisioning and API-credit databases, contributes its migrations once to both chains. Provisioning's migrations take a connection rather than an `Engine`, so every migration commits with its record. The registry keeps Alembic — its PostgreSQL path — and returns the same result and message.

The operator-facing contract — command name, check results, message, deployment phase — does not depend on the engine, so a later adoption of Alembic replaces only the kit's engine.

Rejected: standardizing the contract only (engines already disagree on atomic recording and nothing would make them converge); Alembic everywhere (three to four times the engine work from a baseline, Alembic and SQLAlchemy in every storefront-side kit, and its decisive advantage — portability between databases — unused while these services stay single-writer SQLite; see Open Questions); copying provisioning's engine per service.

### D3 — A clean sweep to a v0.3.0 baseline

Every in-house chain's history is replaced by baseline migrations, one per package whose tables the database's startup builds (core storefront, each such kit, each domain storefront, provisioning, the API-credit service), whose bodies are fixed DDL reproducing the schema dev `9fffe41e9` — the v0.3.0 release's service code — builds when it starts on a fresh database, without opening its stores. They are not `create_all` from current models, which would change silently with every model edit. A committed fixture generated by starting that code proves the baselines reproduce it. The registry's eighteen revisions squash into one Alembic baseline revision, written in Alembic operations, adopted at revision `018_listing_resource_column`.

A database whose `schema_migrations` records every ID the v0.3.0 chain recorded is adopted: in one transaction the command checks the floor IDs, deletes them, and records the baseline IDs, without running the baselines. Recorded IDs prove the storefront constructor's chain ran, and with it the bootstrap that precedes the chain; they do not prove what v0.3.0 created outside the chain — the domain indexes the constructor creates after it, which a crash between the two leaves missing, and the tables stores create when they open, some only lazily (`kit/deal-servicing`'s journal tables first appear when a deal's delivery is registered, so a storefront that never delivered one lacks them). That DDL is therefore not in the baselines: one ordinary migration after the baseline creates every store-open table (D9) and those domain indexes with `IF NOT EXISTS`, the only migration that tolerates objects already present, since a v0.3.0 database may or may not hold them; on a fresh database it simply creates them. Adoption stays on IDs alone, with no schema inspection (13 F4). Migrations merged after `9fffe41e9` — the `20261106` storefront and provisioning migrations among them — stay as ordinary entries after the baseline, and so do migrations later changes add. Any other non-empty database is refused as unsupported, directing the operator to a fresh database.

Supported from the floor: the VM storefront, the bare-metal storefront, compute provisioning, and the registry. The API-credit storefront and service are swept without an adoption path: their baselines are their schema when this lands, and any existing API-credit database is refused.

Deleted with the sweep: core's unversioned bootstrap, every pre-floor migration body, the two-pass application and the `required_tables` skip, the identity and legacy context hooks, the per-migration tests, and DEPLOYMENT_AND_CONFIG's notes on individual old migrations. One ordinary migration after the baseline drops the frozen tables (VM's `compute_allocations`, `resources`, `hosts`, `resource_transition_events`, `compute_pool_members`, and `compute_capacity_pools` or `compute_inventory_pools`; bare metal's `bare_metal_accepted_site_generations`), whose extraction purpose applied only to pre-floor databases; the rule that the engine skips recorded IDs it no longer lists is retired with them. `market-storefront migrate-storefront-domains`, its tests, and the requirement "Legacy storefront domain migration is transactional" are removed: their only input is a pre-floor database.

Planning must confirm that no schema change since the floor reached a database through the unversioned path (`_ensure_domain_tables`, `create_all`); any that did becomes a migration after the baseline, or a v0.3.0 database would adopt without it. The same audit covers the window before the floor: a bootstrap change made after the last migration ID the v0.3.0 chain added, with no ID of its own, would leave a database recording every floor ID without it — a column missing from a table that exists, which the store-open migration's `IF NOT EXISTS` cannot repair — and any such change also becomes a migration after the baseline.

Planning ran that audit at `7091c186c` and found nothing to add. Since the floor, the one commit changing schema code (`7091c186c`) adds only versioned migrations: VM's `20261106_001`/`_002`, bare metal's `-0016-`, provisioning's `20261106_002_reservation_placement_key`, the API-credit service's `20261106_008`, and `kit/site`'s placement-key columns, which those migrations add to existing databases. Before the floor, all three storefront chains last gained an ID in `3c0edcc40` (2026-10-28, settlement-runtime and contact-exchange migrations every storefront composes), and the only schema code changed after it, in `38a5fec12`, creates new tables at store open — deal-servicing's and bare metal's lifecycle cursor — which the store-open migration covers; provisioning last gained an ID in `9623f99e9` (2026-11-06), and the one later commit to its schema files, `5839fb201`, changes job parameters, which are stored as JSON, not schema. The registry has no unversioned path beyond its blank-database bootstrap. An implementer who finds otherwise adds the migration and records it in the section's notes.

Rejected for 13 F4: an adoption-time structural comparison with the floor fixture that creates absent store-open tables and refuses any other difference (inspection machinery and a declared store-open set for what a recorded repair migration does through D3's own rule); making the store-open baselines idempotent and running them at adoption (misses the constructor's indexes); refusing any database whose schema differs from the floor (strands every quiet storefront that never delivered a deal).

The floor is a one-time decision for v0.3.0. Whether a later release becomes a new floor is weighed each time an official release is promoted (D16's RELEASING.md step).

Rejected: ordered bootstrap steps carrying the history verbatim (keeps every older database upgradeable, which the owner does not need); one entry per ad hoc step (more names, same behaviour); leaving the bootstrap outside the chain (invisible to the check).

### D4 — No migration reads operational configuration

Every migration takes only its database. The one migration that needed configuration — the principal migration — is pre-floor and deleted by D3, so the rule compute provisioning already kept now holds for every service, and each migration command reads only its database location and log level.

Rejected: passing configuration to the storefront migration command, or the principal and storefront URL as arguments — both moot once the migration is gone.

### D5 — Compatibility is the exact set of recorded migrations

The startup check compares the recorded IDs with the chain. Fewer is *behind* (listing what is pending), extras are *ahead* (listing the unknown IDs, and any pending ones too: an unknown ID takes precedence, since this image cannot vouch for the database and the remedy is the backup or the image that wrote it, not a fresh database — 13 F5), a database recording some but not all floor IDs is *unsupported*, a v0.3.0 database not yet adopted is *behind* with the adoption pending, no file or no records is *absent*, and only equality is *compatible*. The migration command refuses an ahead database and applies nothing, since applying pending migrations over unknown ones deepens the divergence. The registry's equivalent compares `alembic_version` with the script head. The check opens the database read-only, so it never creates an empty file. An image rolled back over a migrated database is refused; recovery is restoring the pre-upgrade backup or rolling forward, as DEPLOYMENT_AND_CONFIG already prescribes. Shape is enforced by tests, not at startup: a fresh chain must reproduce the floor fixture plus the later migrations, and opening every store on a migrated database must leave the schema unchanged.

Rejected: provisioning's last-ID check (an older image silently serves a database a newer release changed); tolerating declared-additive unknown migrations (needs a ledger column and a flag every author must get right); a runtime shape check (SQLite-specific, and nothing runs DDL outside a chain after D3 and D9); classifying a database both missing and carrying unknown IDs as *unsupported* (its remedy, a fresh database, would point the operator at discarding data they may keep) or as a separate *diverged* result (a sixth public state with ahead's remedy).

### D6 — One console script per service

`market-storefront-migrate`, `bare-metal-storefront-migrate`, `apicredits-storefront-migrate`, `apicredits-service-migrate`, `registry-migrate`, and the existing `compute-provisioning-migrate`. The API-credit service and the registry gain their first console scripts. This follows provisioning's form; a verb on each CLI was rejected because the API-credit service and the registry have no CLI.

### D7 — The deployment phase is an init container under Helm and the command before the application under Compose

The `storefront` chart (per agent), the `bare-metal-storefront` chart, and the `registry` chart gain a `migrate` init container from the application's image with the application's environment, configuration mounts and data volume; the storefront's runs without `entrypoint.sh`, which only starts ZeroTier. Both storefront render tests change from "no init container" to "exactly one, the migration", and DEPLOYMENT_AND_CONFIG's statement that provisioning's migration is the only init container a chart runs changes with them. Under Compose every service, the API-credit services included, runs `sh -c "<service>-migrate && exec <service command>"`, provisioning's existing form. A separate one-shot Compose service was rejected to keep the one form that already exists.

### D8 — Provisioning's own gaps are fixed where the standard is defined

Provisioning moves onto the kit engine with atomic recording (D2), loses its `create_all` calls to its baseline (D3), gains the exact-set check (D5), names its real command in its refusal, and gains the render test its init container lacks: present, from the application's image, with the same database path, ahead of the application.

### D9 — DDL outside a chain moves into the baselines

`kit/deal-servicing`'s tables, VM's delivery records, and bare metal's lifecycle cursor are created by the store-open migration after the baseline (D3), and the `create_schema` calls at store open are removed. A test asserts that opening every store leaves the schema unchanged, which catches the next one.

The refusal checks the storefront constructor runs after its chain go the same way as the rest of its DDL. Bare metal's check that `bare_metal_settlement_records.evidence_json` and `bare_metal_fulfillment_lifecycle.settlement_ref` exist is removed: its baseline creates those columns, and the exact-set check refuses any database that did not run it. API credits' refusal of a listing with no durable binding concerns data, not schema, and stays as a startup refusal, run after the check passes.

### D10 — The API-credit service seeds its `default` pool at startup

ARCHITECTURE.md lets a migration seed only rows a schema constraint requires, and provisioning's migration creates no pool. The service's startup inserts the `default` pool if absent, after the check passes; `_require_valid_pool_declarations` stays as a startup refusal. Keeping the row in the baseline was rejected: no constraint requires it.

### D11 — Each service's Makefile has a `migrate` target

It runs the service's command, as provisioning's does. The proposal's "reinit targets" are dropped: `reinit` refreshes environments in this repository.

### D12 — The requirements change shape

`deployment-state`'s "Service-owned migration history" is modified to cover every stateful service, the exact-set check, and configuration-free migration, and loses its API-credit in-process exception. Added beside it: one mechanism with its command, `--check`, and phase; the baseline and adoption; atomic recording; no schema change outside a chain; composition-owned ordering. "A deployment does not wait on a service's dependencies" is modified so a chart's only init container is the service's own migration. "Legacy storefront domain migration is transactional" is removed. `storefront-publication` and `physical-provisioning` change as D15 records.

### D13 — Effects on other changes

This change supersedes `hollow-pre-floor-provisioning-migrations`: its floor and hollowing are replaced by D3, and the "long-term policy for retiring applied migrations" it deferred is D3 together with the release-time weighing. Closeout removes its directory and reconciles its row. `migrate-registry-to-postgres` no longer owns the registry's command, guard, or blank-database baseline; it keeps PostgreSQL, the cutover, the rollout Job and the Secrets, and closeout amends its proposal. `store-registry-listings-as-published` adds its registry migration after the baseline revision. `separate-marketplace-registry`'s tasks expect a registry migration resource a disabled registry must not render, which D7 creates — the dependency its index note questions is real, for its design review to record. `multi-domain-storefront-composition` (in closeout) adds "Storefront domain-binding migration is transactional and explicit" for the command D3 removes; whichever change archives second reconciles — this change's REMOVED delta then also covers that requirement, or that change's delta drops it. Changes still in flight that add migrations, `relay-vm-access-without-a-dashboard` among them, place them after the baseline.

### D14 — Every migration command has a check mode

`<service>-migrate --check` reports the check's result and the pending and unknown IDs, changes nothing, and exits successfully only for a compatible database, so an operator sees what an upgrade will apply and can verify a restored backup.

### D15 — Supported databases are repaired, and storefronts retire listings they do not hold

**15a — `ssh` connections.** `physical-provisioning` refuses a stored connection at a version no codec serves and forbade any rewrite but a submission. The v0.3.0 chain wrote legacy hosts at version 1, which v0.3.0 refuses, and jobs captured before an operator resubmitted the host keep the version-1 copy, so their teardown fails and `retry-release` cannot recover the reservation. A migration after the baseline rewrites every `ssh` version-1 connection, on hosts and on jobs not yet finished, to version 2 with the same public fields and protected values — an exact mapping, since version 2 is version 1 with an optional `public_port` that falls back to the connection port. A connection whose fields the version-2 codec refuses fails the migration naming its host or job. The requirement is modified: no reader upgrades a stored connection, and only a submission stating the version or a recorded migration with an exact mapping rewrites one. `ConnectionSubmission.version` loses its default of 1 and becomes required, so an unversioned submission is refused as missing the field; this changes the host contract, a minor version under the pre-1.0 policy. Rejected: keeping the rule and re-reading the host's current connection for stuck jobs only (operators still resubmit every host by hand, and job envelopes are frozen); handbook text alone (force-release for every stuck reservation).

**15b — retiring registry listings.** `storefront-publication`'s convergence requirement already resends what a registry missed for every listing with a publication record at a configured registry. It cannot see a listing without one: a lost record, one from before publication records, or one at a registry whose URL is no longer configured. Each publication pass of all three storefronts therefore lists, at each reachable configured registry, the open listings under the storefront's own publisher principal for the offering modes it serves, and closes each one it does not hold open. Scoping by offering mode lets the VM and bare-metal storefronts share a principal. A preview pass reports without closing; an unreachable registry is swept later. It lives in `kit/capacity-publication`'s runtime, so all three storefronts share it. No wire changes: the list-by-publisher and status-update routes exist. The cross-registry client's `list_listings` merges every registry's results by listing ID and the single-registry query returns one page, so the sweep reads through a new per-registry operation on the cross-registry client, beside its per-registry writes and `get_descriptors`: for each configured registry it pages the publisher's open listings to completion and returns them, or an unreachable result when the registry fails on any page. The sweep reads every page of a registry before closing anything there — closing while paging by offset would shift later pages — and closes through the existing per-registry update; a listing held open locally, including one held while its site's projection is unavailable, is never closed (13 F2). Rejected for 13 F2: each composition building individual registry clients (duplicates fan-out and failure handling above the shared runtime). Rejected: a bare-metal-only fix (the other storefronts close through the same runtime); recording it as an unowned gap (it would leave unfixed a defect a real upgrade hit, while its fix is understood and small beside this change).

**15c — option IDs and shapes.** The option envelope is a forward-only wire boundary (`deployment-state/architecture.md`): an option's ID is not stable across a release that changes the envelope, buyers re-read listings after such an upgrade, and a closed historical registry listing in an older shape stays as history. The operator handbook's upgrade procedure says so; no migration rewrites them.

### D16 — A role is an actor; a stateful process is a service

The permanent documents use *role* for actors — buyer, seller, operator — and *service* for a deployable process with its own state. This change writes its own text that way and updates the permanent documents' uses of "role" for a service for consistency, recording the term in ARCHITECTURE.md's Terms. Where a requirement's name or text changes, the change carries it as a delta.

The selected migration mechanism is guidance for operators and maintainers, not a cross-system principle: DEPLOYMENT_AND_CONFIG.md describes it, RELEASING.md gains the step of weighing a new floor when an official release is promoted, and the `deployment-state` specification and its architecture companion describe it normatively and conceptually.

### Implementation cadence

Two rounds, each reviewed before the next, then closeout.

- **Round 1 — upgrade repairs, the engine, and the reference service.** Two sessions: (a) the `ssh` connection migration and the required `version` (D15a), and the registry-listing sweep with the cross-registry client's per-registry read (D15b); (b) the engine kit and compute provisioning on it — its baseline and adoption, exact-set check, atomic recording, `--check`, corrected message, init-container render test, and `make migrate` (D2, D3, D5, D8, D11, D14).
- **Round 2 — the storefronts, the API-credit service, and the registry.** Two sessions: (a) the chains — baselines in core, the kits and the domains, each composition's chain, the store-open migration, the frozen-table drop, removing `migrate-storefront-domains`, and the store-open tests (D3, D9); (b) commands, checks and deployment surfaces for the three storefronts and the API-credit service — the `default` pool seeded at startup, both storefront charts' init containers and render tests, Compose, Make — and the registry's Alembic squash and adoption, `registry-migrate`, check, chart init container, Compose and Make (D6, D7, D10, D11, D14). The vocabulary sweep (D16) is written with the documentation each session touches and completed at closeout.

## Risks / Trade-offs

- **[A baseline differs from what v0.3.0 builds]** → The committed fixture generated from `9fffe41e9`'s code and the `schema_snapshot` comparison fail the build on any difference.
- **[A post-floor schema change arrived through the unversioned path]** → Planning audits the commits since the floor; any such change becomes a migration after the baseline.
- **[Adoption by recorded IDs admits data the release cannot serve]** → Known defects are repaired by migrations after the baseline (D15a); the floor's own chain is the one place such data is known to originate.
- **[Adoption by recorded IDs admits a schema missing what v0.3.0 created outside its chain]** → The store-open migration after the baseline creates those tables and indexes where absent (D3); a column missing from an existing table is ruled out by planning's audit of the window before the floor.
- **[The engine is retired when services move to PostgreSQL]** → The contract is engine-independent; only the kit's engine is replaced.
- **[An image rollback is refused]** → Intended: recovery is the pre-upgrade backup or rolling forward, which the operator handbook states with `--check` before migrating.
- **[Two storefronts under one principal serving one offering mode would close each other's listings]** → Already an unsupported topology; the sweep's scope is principal and offering mode.

## Migration Plan

An operator upgrading a supported deployment takes a database backup, runs `<service>-migrate --check` from the new image to see what will apply, then deploys; the init container (or Compose's command) adopts the v0.3.0 database and applies the later migrations, including the store-open tables and indexes, the `ssh` connection repair, and the frozen-table drop, before the application starts. A database from before v0.3.0, or any existing API-credit database, is refused as unsupported and the service starts from a fresh database. Rollback past a migration restores the backup.

## Open Questions

- **Adopting Alembic for the in-house services.** Deferred: provisioning, the storefronts, and the API-credit service are expected to move to PostgreSQL eventually, where Alembic's portability matters, but not for a month or two. Revisit when any of them is planned onto PostgreSQL or onto more than one writer; the move then adopts Alembic from a baseline and replaces only the engine.
