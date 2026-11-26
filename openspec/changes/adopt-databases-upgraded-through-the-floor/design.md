## Context

Each in-house stateful service's chain (`kit/schema-migrations`, `market_schema_migrations`) begins at baselines reproducing the schema the marketplace v0.3.0 release built, and adopts a database recording every ID that release's chain recorded. `engine.classify` takes a database recording no baseline but every floor ID down its adoption branch, where any other recorded ID makes it *ahead* (`unknown = known - floor - ids`); `engine.migrate` forgets only the floor IDs at adoption, so an extra record would survive adoption and make the database ahead at the next check anyway. A chain with no floor — both API-credit chains — refuses every non-empty database it did not build, and every *unsupported* refusal tells the operator to start on a fresh database.

v0.3.0's runner (`core_storefront.sqlite_migrations` at `marketplace-v0.3.0`) applied its own list by ID and ignored every other record, so a database could reach the floor carrying records the floor release does not list. On 2026-11-25 a VM storefront database built under v0.2.x and run by v0.3.0 since was refused by 0.4.0 as ahead for seven such records. Marketplace 0.4.0's release notes tell such a deployment to keep that service on v0.3.0 until a later release adopts its database. Since 0.4.0 the engine records exactly its chain and refuses anything else, so a database any later release ran on records exactly that release's IDs: the stray records are particular to the v0.3.0 floor.

What release history holds, from the non-test source at every tag `marketplace-v0.2.0` through `v0.2.29` against `v0.3.0` (IDs written as string literals):

- **The VM storefront** recorded seven IDs v0.3.0 retired. Six are v0.2.29 `VM_MIGRATIONS` touching only the inventory tables (`compute_allocations`, `compute_inventory_pools` or `compute_capacity_pools`, `compute_pool_members`, `resources`), every one of which the chain's `20261109_002_vm_frozen_inventory_dropped` already drops `IF EXISTS`; the seventh, `20260815_005_hosted_settlement_funding_profile`, from `kit/hosted-settlement`, rewrote `settlement_obligations` rows and created no table.
- **The bare-metal storefront** recorded `bare-metal-storefront-0008-hosted-physical-lifecycle` in every v0.2.x tag; v0.3.0 reused the number for `0008-settlement-records`. It created `bare_metal_hosted_lifecycle`, which nothing has read since v0.3.0. Builds between v0.2.29 and v0.3.0 also recorded `bare-metal-storefront-0011-accepted-site-generations`, which v0.3.0 deliberately kept and 0.4.0 refuses.
- **Compute provisioning, the API-credit storefront and the API-credit service** recorded nothing v0.3.0 retired. **The registry**'s Alembic history is linear, so any registry database v0.3.0 ran on is at its floor revision, `018_listing_resource_column`.
- At the v0.2.x tags the release workflow built only the VM storefront image; the other services were published to PyPI as wheels from `main`.

The API-credit storefront commits a v0.3.0 floor fixture (20 IDs) and a test that its baselines reproduce it; its chain names no floor. The API-credit service has no fixture: at v0.3.0 (`arkhai-apicredits-service` 0.7.0) it built its schema with `create_all` over its own, the resource pools' and the site ledger's models, then recorded seven in-process IDs, `20260731_001_apicredits_schema_baseline` through `20261106_007_reservation_activated_at`. The release record (`package-versions.md`: the release tags; the newest, `marketplace-v0.4.0`) carries both as library wheels, with no image or chart.

## Goals / Non-Goals

**Goals:** a database the floor release ran on is adopted whatever earlier releases recorded; a database older than the floor is told to upgrade through the floor release, and starting fresh is never the remedy for one that can upgrade; *ahead* means only that an image newer than this one migrated the database; every chain declares a floor; both API-credit chains gain the v0.3.0 floor; the upgrade path is proven against a real upgraded database; the rule is written in the engineering guidance, and the repository guidance, handbooks and specification describe it.

**Non-Goals:** moving the floor; supporting a database that skips the floor release; carrying a database that records no migrations; per-package floors within one chain.

## Decisions

### D1 — A database the floor release ran on is adopted, whatever else it records

A database recording every ID the floor release's chain recorded and none of the chain's baselines is one the floor release ran on: v0.3.0 added IDs after v0.2.29, so a v0.2.x database it never ran on lacks some and stays unsupported. Such a database is *behind* with its adoption pending, whatever else it records. Adoption, in one transaction and without running the baselines, forgets every recorded ID the chain does not list — the floor's and any others — records the baselines, and then the later migrations apply. A recorded ID the chain lists as a later migration is treated as applied, as today.

The rule is sound by construction: since 0.4.0 no image leaves a ledger without the baselines — a fresh database runs them, an adopted one records them — so an extra record on a database recording no baseline was written by the floor release's era or before it, never by a newer image. It is a permanent rule of every floor, not a path for v0.3.0 alone.

Rejected:

- **The chain declares the retired records it sets aside** (`retired_ids`). Precise, but it is release history kept by hand: an inventory miss — an ID built at runtime, a release nobody searched — strands a deployment exactly as the observed one was stranded, and it would need decisions on how far back the list reaches and what an undeclared record is called. Too brittle to maintain.
- **A declaration plus a schema check at adoption.** It contradicts adoption resting on recorded IDs alone, and v0.3.0 databases legitimately differ (store-open tables present or absent, frozen inventory tables), so it would need allowances of its own.
- **No engine change, and an operator procedure deleting the records with `sqlite3`.** Manual ledger surgery on production data, contrary to the floor being an upgrade path.
- **Deferring.** The 0.4.0 release notes promise that a later release adopts these databases.

The cost is that the image vouches for records it cannot name: where a forgotten migration created what a later migration also creates, that later migration fails in its own transaction, named, with nothing of it applied. The preview lists every record set aside (D7) before an operator deploys.

### D2 — How far back the recognised records reach

Resolved by D1: nothing is declared, so there is no reach to choose. Every record an earlier release wrote on a database the floor release ran on is set aside, whichever release wrote it, untagged builds' included — the bare-metal `0011-accepted-site-generations` database among them, whose table 0.4.0's `bare-metal-storefront-0018-drop-accepted-site-generations` drops once it is adopted.

### D3 — Both API-credit chains gain the v0.3.0 floor

The API-credit storefront declares the IDs its committed fixture holds, and its tests refusing every existing database become adoption tests. The API-credit service gains a floor fixture generated from `arkhai-apicredits-service` 0.7.0's published wheels, as the other fixtures' READMEs describe; a test that its three baselines reproduce that fixture's schema; a repair migration after the baseline wherever they do not; and its floor IDs. The two databases are a pair — the service holds the keys, request-digested grants and balances the storefront's issued credentials refer to — so this change gives both chains the floor: an existing pair upgrades in place together, and neither is started fresh beside the other. Every in-house chain then shares the v0.3.0 floor, and no API-credit database is told to start fresh.

The pair is upgraded in the order its deployment already enforces, with no coordination of its own (07 F1). The operator backs up both databases and previews both with `--check` before deploying, and deploys neither if either is refused. Under Compose, the only deployment the two have, the credits storefront `depends_on` the credits service being healthy, and each container runs `<service>-migrate && exec <application>`: the service migrates first, and the storefront's migration runs only once the service has migrated and started. A failed service migration therefore leaves the storefront's database untouched and the storefront not started. A failed storefront migration after the service adopted leaves the storefront not started, so no credential is issued against a mixed pair; the remedy is the earlier release over both backups, as for any failed upgrade.

Should the service's fixture show a difference whose repair is more than a small, understood migration, the service's floor splits into its own change, as the workflow's guidance on defects found during a change frames it.

Rejected: no floor for either, recorded as current behaviour on the ground that they run only under Compose — the bill of materials carries their wheels, and it would keep a permanent exception to the rule this change establishes; the storefront alone — an adopted storefront beside a fresh service is broken state, not an upgrade; a follow-up change for both — the guidance would keep the API-credit exception in words until it landed.

### D4 — What a database recording no baseline but records nobody declared is called

Resolved by D1: with nothing declared, no record on a database the floor release ran on is undeclared. *Ahead* arises only on a database recording a baseline, which an image newer than this one migrated, and keeps its remedy: restore the backup taken before the upgrade, or run the image that wrote it.

### D5 — Tables an earlier release's retired migration created are dropped by an ordinary later migration

Following `20261109_002_vm_frozen_inventory_dropped`, which already drops every table the VM's retired migrations created, the bare-metal storefront's chain gains `bare-metal-storefront-0021-drop-hosted-lifecycle`, dropping `bare_metal_hosted_lifecycle` `IF EXISTS` and discarding its rows, which no release has read since v0.3.0 removed `kit/hosted-settlement` and its hosted-card mechanism. On a fresh database it does nothing. The operator handbook's "What the upgrade from v0.3.0 changes" names the discarded rows, as it does the VM's inventory.

Rejected: adoption dropping tables — the engine would issue DDL at adoption, and adoption would no longer rest on recorded IDs alone; leaving the table — a dead table with unreadable rows kept forever.

### D6 — The chain's floor is one required value naming its release

```python
@dataclass(frozen=True)
class Floor:
    release: str                    # what refusals name: "marketplace 0.3.0", or "0.0.0"
    recorded: tuple[str, ...] = ()  # the IDs that release's chain recorded; () adopts nothing

Chain(service="the VM storefront", command="market-storefront-migrate",
      floor=Floor("marketplace 0.3.0", FLOOR_IDS),
      baselines=(...), migrations=(...))
```

`Chain.floor_ids` becomes `Chain.floor`, a required `Floor`. The kit is market-neutral, so each service states the whole release name and the kit never says "marketplace". `Chain.__post_init__` keeps its refusals of a duplicate floor ID and of a floor ID the chain also lists. `CheckResult` gains `floor: str | None`, the floor release, which `classify` fills from `chain.floor.release` and the registry's own `classify` fills with its floor's release, so `refusal_message(result, *, service, command)` keeps its signature.

Every caller: the five in-house chains (compute provisioning, the VM, bare-metal and API-credit storefronts, the API-credit service) construct a `Floor`; the `refusal_message` callers — the engine's `MigrationRefused`, each service's incompatible-database error, and the registry's command and error — are unchanged; the chain tests comparing the floor with their fixture compare `CHAIN.floor.recorded`; compute provisioning's integration test building a chain from `CHAIN.floor_ids` passes `CHAIN.floor`. Every other direct constructor passes an explicit `Floor` too (07 F4): core storefront's reusable test chain (`core/storefront/tests/core_database.py`); each command or migration test that copies a service's baselines into a chain of its own — the VM and bare-metal storefronts' and the API-credit storefront's `test_migrate_command.py`, the API-credit service's `test_migrations.py` — passing `Floor("0.0.0")` or the chain's own `CHAIN.floor`, as each test means; and the kit's own unit and integration tests (`test_classification.py`, `test_sqlite_engine.py`, `test_sqlalchemy_engine.py`). None interprets the engine's internals. A default floor for tests was rejected: it reopens the way around the required floor D12 closes.

Rejected: keeping `floor_ids` beside a separate `floor_release`, two fields that must agree; passing the release to `refusal_message` at every call site, which changes every caller and leaves the registry to remember it.

### D7 — The check and the preview name every record adoption sets aside

`CheckResult` gains `set_aside`: the recorded IDs adoption forgets beyond the floor's own, sorted. `describe` adds `records set aside: …`; the *behind* refusal reads that the supported baseline is to be adopted (recording its IDs), setting aside the listed records earlier releases wrote; `MigrateReport` gains `set_aside`, and `migrate` logs them. A preview therefore names the baselines adoption records, the floor release whose records it replaces — by name, from `CheckResult.floor` — every record it sets aside beyond the floor's, and the pending migrations, as `migrations.md`'s "A check mode previews" asks. A count alone was rejected: an operator verifying a backup wants the IDs that differ between databases.

The floor's own records are named by their release, not listed (07 F3): they are fixed for each release, committed in each chain's floor fixture, and the same on every database the floor release built, so listing them would lengthen every preview by twenty to forty-odd IDs and tell the operator nothing about the database in hand. Listing them as a result field was rejected for that reason.

### D8 — A floor move carries nothing forward, and the rule retires with no floor

D1 is the permanent rule of every floor, so it has no row in the release handbook's "Compatibility to retire" (`package-versions.md`: a migration is not a row; the floor absorbs migrations). A new floor replaces each chain's baselines and `Floor`, deletes the migrations it absorbs, and regenerates each fresh floor fixture. The upgraded-database proof of D9 is owed only where a floor release kept records outside its chain, which v0.3.0's runner alone did. Deployments older than a new floor upgrade through the floor release first; none is left to start fresh. A row retiring the setting-aside at the next floor was rejected: it would retire a permanent rule.

### D9 — The upgrade path is proven synthetically for every chain and against one real upgraded VM database

- **The engine.** `kit/schema-migrations`' unit tests classify a floor database carrying unknown records as behind with them set aside and render the refusals of D10; its library integration tests prove, through both adapters, that adoption forgets every unlisted record and records the baselines in one transaction, that a `Floor("0.0.0")` chain adopts nothing, and that a chain cannot be built without a floor.
- **Every chain.** Each service's chain test adds a database built from its floor fixture's DDL and IDs plus an unknown record and an unknown table, adopted and ending compatible.
- **The VM storefront.** One real upgraded database is committed beside its floor fixture, `tests/fixtures/v0_3_0_floor/upgraded/` — its `README.md` (built by v0.2.29's published storefront on a fresh file, then by v0.3.0's, `arkhai-vms-storefront` 0.27.0, over it), `schema.json`, `recorded_ids.json` and `ddl.sql`. v0.2.29's chains carry every ID any v0.2.x release recorded that v0.3.0 does not, so this one database covers the retired set. Its chain test asserts it is adopted, applies exactly the later migrations, keeps a planted row, and ends with the same `schema_snapshot` and ledger as a fresh database. A residue it reveals that the release cannot serve is repaired by a migration after the baseline; a harmless one SQLite cannot remove safely, such as a leftover column, is named explicitly in the test.

The level is library integration, as `migration-tests.md` places a chain's tests. Rejected: synthetic proof alone, which never meets a real upgraded schema; real upgraded fixtures for every service that published a v0.2.x wheel, three of which retired nothing, which is release history to generate and keep for little proof; a second real fixture for bare metal, whose retired record the synthetic case covers.

### D10 — The refusals say what happened, and the documents say a database upgrades through the floor

*Unsupported* splits by cause, each refusal saying only what the ledger shows (07 F2):

- **Older than the floor, or another service's sharing its history** — a ledger recording some of the floor's IDs but not all, none of the chain's baselines, or a registry revision of its own history before its floor. Every chain shares one ledger table, and the three storefronts share the core storefront's migrations — their v0.3.0 floors overlap by 18 to 23 IDs — so a bare-metal storefront's database under the VM storefront's command records most of the VM floor and is indistinguishable by its ledger from an older VM storefront database. The refusal names the floor release and the IDs the database lacks, says the command cannot tell an older database of its own from another service's sharing its history, and directs the upgrade only once the operator has confirmed the database: "the VM storefront's database lacks migrations … that marketplace 0.3.0's VM storefront recorded. If it is the VM storefront's database, it predates marketplace 0.3.0, the release it is supported from: upgrade it through marketplace 0.3.0 first — run marketplace 0.3.0's VM storefront on it — then run `market-storefront-migrate`. Confirm it is first: `market-storefront-migrate` cannot tell another service's database from an older one of its own."
- **Not this chain's database** — tables but no ledger, or a ledger recording none of the floor's IDs; a non-empty database under a chain whose floor recorded nothing falls here, since it records none of an empty floor. It holds what the command did not build and records none of the floor's migrations, so it is not a database the service can migrate. No fresh-database remedy is named, and no upgrade path.

`CheckResult` gains `cause`, which `classify` sets on an unsupported result, and the registry's own `classify` sets to older-or-shared for a revision of its history before its floor — older-or-shared, or not this chain's — so `refusal_message` words each without knowing the chain. The engine's unit tests and the delta hold each separately: a ledger recording none of the floor's IDs is refused as not the chain's; another storefront's floor database under the VM storefront's chain is refused with the conditional upgrade instruction and not adopted.

Rejected: identifying each chain's known pre-floor IDs and reserving the upgrade instruction for them — D1's rejected `retired_ids` again, release history kept by hand, and defeated anyway by the IDs the storefronts share; one neutral refusal for every unsupported ledger, naming no upgrade — safe, but it withholds the remedy from the older database this change exists for.

*Ahead* keeps its words and arises only on a database recording a baseline.

The documents: `docs/guidance/engineering/migrations.md` states the rule in repository-neutral words — every chain declares a floor, a database the floor release ran on is adopted whatever earlier releases recorded, an older one upgrades through the floor release, and starting fresh is never the remedy for a database that can upgrade; `docs/guidance/engineering/migration-tests.md` makes the floor fixture mandatory and adds the upgraded-database proof where a floor release kept records outside its chain; the repository's `migration-chain-tests.md` and `migrations-at-startup.md`; `DEPLOYMENT_AND_CONFIG.md`'s "Migrations at startup" (its result table, the API-credit floor, the remedy); the release handbook's "The migration floor"; the operator handbook's "Supported databases", its procedure's preview step (a refused database is confirmed as the service's and upgraded through the floor release first, not started fresh), and "What the upgrade from v0.3.0 changes" (the API-credit adoption and the pair's rollout of D3, bare metal's dropped table); and `deployment-state`'s specification and companion.

### D11 — Implementation cadence

One round, one session: the engine (`Floor`, adoption setting records aside, the result's fields and words, its unit and library integration tests), every chain's floor and its tests (the VM's upgraded fixture, bare metal's drop migration, the API-credit storefront's floor, the API-credit service's fixture, reproduction test and any repair), and the guidance, handbook and specification text, reviewed once before closeout. Should the API-credit service's repair prove large, its split (D3) leaves the round without it.

### D12 — Every chain declares a floor

A chain cannot be constructed without a `Floor` (D6): every import of a chain missing one fails, so every test of its service fails, and a kit unit test proves the refusal. Floors may differ between chains; each is the release that chain is supported from. A chain that truly needs no minimum declares `Floor("0.0.0")`, recording nothing: it adopts no database, and refuses a non-empty database it did not build as not its own (D10). The constructor holds that a floor is declared; that it is the right one is held by each service's chain test comparing it with its floor fixture, which `migration-chain-tests.md` requires of every chain with recorded floor IDs, and by the engineering guidance and code review for a new chain. The registry keeps its floor in Alembic and names the same release through `CheckResult.floor`.

Rejected: a non-empty floor only, which leaves a chain with no earlier history unable to declare one; a repository test deriving every service's chain from its `-migrate` entry point and checking its floor and fixture, which reaches into each service's layout from outside across the package layers; per-service tests required only by guidance, which nothing enforces.

## Risks / Trade-offs

- **[A forgotten pre-floor migration created what a later migration creates]** → The later migration fails in its own transaction, named, applying nothing of itself; the preview listed the record set aside beforehand.
- **[A record set aside was written by a hand edit or a foreign build]** → It is listed by the preview and the log; the rule adopts it, since only a database the floor release ran on reaches adoption.
- **[The real upgraded VM database reveals a residue]** → Repaired by a migration after the baseline where the release cannot serve it, or named in the test where harmless and not removable safely.
- **[The API-credit service's v0.3.0 schema differs from its baselines]** → A repair migration after the baseline; a large or poorly understood one splits the service's floor into its own change (D3).
- **[A new chain declares `0.0.0` where it owes a real floor]** → Guidance and code review; the constructor cannot judge correctness.

## Migration Plan

An operator whose 0.4.0 refused a database as ahead for records v0.3.0 retired, and who kept that service on v0.3.0 as the 0.4.0 release notes advised, takes a backup and runs the new image's `<service>-migrate --check`, which reports the baseline to be adopted, the records set aside and the pending migrations, then deploys; the database is adopted in place. An existing v0.3.0 API-credit storefront and service database are adopted the same way, as a pair: both backed up and previewed before either is deployed, the service migrating first and the storefront once the service is healthy, and both restored from their backups under the earlier release should the storefront's migration fail (D3). A database older than v0.3.0 is upgraded through marketplace 0.3.0 first, then to the new release. Rollback is the pre-upgrade backup, as for every migration.

## Open Questions

None.
