## 1. The engine adopts a database its floor release ran on, and every chain declares its floor

Delivers the engine's side of D1, D6, D7, D10 and D12, and moves every chain and every direct `Chain` constructor onto the required `Floor` in the same slice, since no suite passes while one constructor lacks it. Implements `deployment-state`'s "Every migration chain declares its floor", the ahead rule of "Service-owned migration history", and the adoption and refusal rules of "A chain begins at its supported baseline". Touches `kit/schema-migrations`, the five in-house chains (`provisioning/compute/service`, `domains/vms/storefront`, `domains/bare_metal/storefront`, `domains/apicredits/storefront`, `domains/apicredits/service`), `core/registry`, and the test constructors D6 names.

- [x] 1.1 **`Floor`, and `Chain.floor` required (D6, D12).** In `kit/schema-migrations/src/market_schema_migrations/engine.py` add the frozen `Floor(release: str, recorded: tuple[str, ...] = ())` and replace `Chain.floor_ids` with a required `floor: Floor`; keep `__post_init__`'s refusals of a duplicate floor ID and of a floor ID the chain also lists, now over `floor.recorded`. Export `Floor` from `__init__.py`, and rewrite the module docstrings of `engine.py`, `result.py` and `__init__.py` to describe the floor and adoption as D1 and D12 state them. Verified by 1.5's unit cases: a `Chain` built without `floor` raises, and the existing duplicate and overlap refusals still raise.
      Done. `Floor` and `UnsupportedCause` exported; `Chain.floor` keyword-only and required, a non-`Floor` refused (design.md D6). Unit: `make -C kit/schema-migrations test` — passed.
- [x] 1.2 **Classification (D1, D10).** Rewrite `classify` so that:
      - a database recording any baseline is judged as today (compatible, behind, or ahead with its unknown IDs);
      - a database recording no baseline but every ID of a non-empty `floor.recorded` is *behind* with `adopting` the baselines, `set_aside` every other recorded ID the chain does not list (sorted), and `pending` the later migrations it does not record;
      - a ledger recording some but not all of the floor's IDs, and no baseline, is *unsupported* with `missing` the floor IDs it lacks and the older-or-shared cause;
      - tables with no ledger or an empty ledger, a ledger recording none of the floor's IDs, and any non-empty database under a floor recording nothing are *unsupported* with the not-this-chain cause.

      `CheckResult` (`result.py`) gains `floor: str | None` (filled from `chain.floor.release` on every result), `set_aside: tuple[str, ...] = ()`, and `cause`, set only on an unsupported result, with the two values D10 names. Verified by 1.5's unit cases, one per state and cause.
      Done. `UnsupportedCause` carries D10's two causes; every result, the kit's *absent* result for a missing file included, names the floor release. Unit, one case per state and cause — passed.
- [x] 1.3 **Adoption (D1, D7).** In `migrate`, adoption forgets `floor.recorded` and `set_aside` and records the baselines in the one transaction that read the state; `MigrateReport` gains `set_aside`, and the adoption log line names the floor release and the records set aside. Verified by 1.5's library integration cases.
      Done. Library integration through both adapters (`test_sqlite_engine.py`, `test_sqlalchemy_engine.py`): adoption of a floor database carrying an unknown record and table applies exactly the later migrations, records exactly the chain's IDs, keeps the rows, reports `set_aside`; a rerun changes no byte — passed.
- [x] 1.4 **The words (D7, D10).** In `result.py`:
      - `describe` names the floor release whose records adoption replaces and lists `records set aside: …`;
      - the *behind* refusal says the supported baseline is to be adopted (recording its IDs), replacing the floor release's records and setting aside the listed records earlier releases wrote;
      - the older-or-shared refusal names the floor release and the missing IDs, says the command cannot tell an older database of its own from another service's sharing its history, and directs the upgrade through the floor release only once the operator has confirmed the database, in D10's words;
      - the not-this-chain refusal says the command did not build the database and names no fresh-database remedy and no upgrade;
      - *ahead* keeps its words.

      `refusal_message(result, *, service, command)` keeps its signature. Verified by 1.5's refusal-message cases.
      Done, in the words design.md D10 records. Unit (`test_refusal_message.py`): each refusal's words, D10's sentence asserted whole, no refusal saying "fresh database" — passed.
- [x] 1.5 **The engine's tests.**
      - **Unit** (`tests/unit/test_classification.py`, `tests/unit/test_refusal_message.py`):
        - every classification above, including a floor database carrying unknown records (behind, its `set_aside` sorted, its pending list);
        - a partial floor ledger (older-or-shared, its `missing`);
        - a ledger of none of the floor's IDs, a `Floor("0.0.0")` chain over a non-empty database, and tables with no ledger (each not-this-chain);
        - a database recording a baseline and an unknown ID (ahead);
        - construction without a floor refused;
        - each refusal's words, the floor release named where D10 names it, and no refusal saying "fresh database".
      - **Library integration**, through both adapters (`tests/integration/test_sqlite_engine.py`, `tests/integration/test_sqlalchemy_engine.py`):
        - adoption of a floor database carrying unknown records leaves exactly the chain's IDs recorded and the rows kept, then a rerun changes no byte;
        - a `Floor("0.0.0")` chain builds a fresh database and refuses a foreign one unchanged;
        - a refused database is left byte-identical;
        - a read-only check of a floor database with unknown records creates and changes nothing.
      Done as listed: `make -C kit/schema-migrations test`, 84 passed. Refused databases are compared byte for byte (sqlite: ahead, older-or-shared, not-this-chain; SQLAlchemy: ahead, zero floor); the read-only check leaves the file and directory unchanged through both adapters.
- [x] 1.6 **Every chain declares its floor (D6, D12).**
      - **Compute provisioning, the VM storefront and the bare-metal storefront** declare `Floor("marketplace 0.3.0", FLOOR_IDS)`.
      - **Both API-credit chains** declare `Floor("0.0.0")`, which keeps today's refusal of every database they did not build until section 4 gives them the v0.3.0 floor.
      - **Every other direct constructor** passes an explicit floor, as D6 lists:
        - `core/storefront/tests/core_database.py`;
        - the VM, bare-metal and API-credit storefronts' `tests/integration/test_migrate_command.py`;
        - the API-credit service's `tests/integration/test_migrations.py` (each `Floor("0.0.0")` or `CHAIN.floor`, as the test means);
        - compute provisioning's `tests/integration/test_database.py` (`floor=CHAIN.floor`).
      - **The fixture comparisons.** Each chain test comparing the floor with its fixture compares `CHAIN.floor.recorded`. Each refusal assertion that named the fresh-database remedy asserts the cause and words of 1.4 instead.

      Verified by each service's existing chain, command and startup-check suites passing, with no assertion weakened.
      Done. Five chains declare their floors; each other constructor passes `Floor("0.0.0")` (core's test chain) or `CHAIN.floor`; refusal assertions that named the fresh-database remedy assert cause and words. Library integration: every suite of the five services and `core/storefront`, each through `make test` — passed, no assertion weakened.
- [x] 1.7 **The registry names its floor and its causes (D6, D10).** `core/registry/src/core_registry/db/migrations.py`'s `classify` fills `floor="marketplace 0.3.0"` on every result. It sets the older-or-shared cause on a revision of its history before its floor revision (with `missing` as today), and the not-this-chain cause on every other unsupported result: tables with no `alembic_version`, and more than one recorded revision. `core/registry/src/core_registry/migrate.py` and its `IncompatibleDatabase` keep calling `refusal_message` unchanged. Verified by `core/registry/tests/unit/test_migration_states.py` (each state's cause and floor) and `tests/integration/test_migrations.py` (the command's refusal of a pre-floor revision names marketplace 0.3.0 and the conditional upgrade; tables with no version table are refused as not the registry's).
      Done. `FLOOR_RELEASE = "marketplace 0.3.0"` beside `FLOOR_REVISION`, on every result. The revision count is checked before unknown revisions, so every multi-revision ledger is not-this-chain and a single unknown revision stays *ahead* (18 F1); the shared result's docstrings and the delta name the registry's single-revision *ahead* (25 F1) — design.md D10. Unit (`test_migration_states.py`, `test_several_revisions_with_an_unknown_one_are_not_the_registrys`) and library integration (`test_migrations.py`): `core/registry`'s whole suite, 339 passed; `change-workflow run test-before` at `5590f7914` failed the multi-revision test as expected.
- [x] 1.8 **Versions and locks** (`versioning.md`, `package-versions.md`).
      - `arkhai-kit-schema-migrations` goes to 0.2.0: an incompatible API change before 1.0.0.
      - Each package constructing a `Chain` or reading the new result fields raises its lower bound to `>=0.2.0`: the five service packages and `arkhai-core-registry`, plus `arkhai-core-storefront` only if its source does. Kits exporting only `Migration` keep theirs.
      - Bump each package this section changes once, as `make check-version-bumps` holds against `dev`.
      - Refresh the locks with `make lock` (the workflow's after-functional-change hook).

      Verified by `make check-version-bumps` and `make check-packaging` passing.
      Done. `arkhai-kit-schema-migrations` 0.2.0; one minor bump each, with `>=0.2.0`: compute provisioning service 0.29.0, VM storefront 0.30.0, bare-metal storefront 0.30.0, API-credit storefront 0.24.0, API-credit service 0.9.0, core registry 0.7.0; `arkhai-core-storefront` unchanged. `make lock`; `make check-version-bumps CHANGE_BASE=origin/dev` and `make check-packaging` — passed.
- [x] 1.9 **Verification.**
      - Unit: `make -C kit/schema-migrations test`, the kit's unit tests, and `core/registry`'s `tests/unit/test_migration_states.py`.
      - Library integration: the kit's engine tests through both adapters; each service's `test_migration_chain.py`, `test_migrate_command.py` and startup-check tests; the registry's `test_migrations.py`.
      - Then `change-workflow run pre-commit adopt-databases-upgraded-through-the-floor`, whose functional checks run every suite.

      End-to-end: none exercises adoption, since every lane starts each service through its migration on a fresh database (`migration-chain-tests.md`). Every lane's scenarios therefore exercise the fresh path through the changed engine, and pass only if every chain still builds and checks a fresh database. None is owed: adoption of a release's database is proven only by the chain tests (`migration-tests.md`).
      Done. Unit and library integration as 1.5–1.7; `change-workflow run pre-commit` — passed. End-to-end: none exercises adoption, none owed.


## 2. Each in-house chain adopts a floor database carrying earlier records, and bare metal drops its dead table

Delivers D1's adoption and D10's refusal causes for each chain that already has the v0.3.0 floor, D9's synthetic proof for those chains, and D5. Implements the scenarios "A database that reached v0.3.0 by upgrading is adopted", "Another storefront's database is refused", "A ledger recording none of the floor's migrations is refused", "A table an earlier release created is dropped", and "An operator previews adopting an upgraded database". Touches the chain tests and floor-database helpers of `provisioning/compute/service`, `domains/vms/storefront` and `domains/bare_metal/storefront`, the VM command test, and `domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/migrations.py`.

- [x] 2.1 **A floor database carrying earlier records is adopted, in every chain (D1, D9).** In each of compute provisioning's, the VM storefront's and the bare-metal storefront's `test_migration_chain.py`, build a database from the floor fixture's DDL and IDs (its `floor_database.py`), plus a recorded ID no release of the chain lists, an unknown table, and a planted row. Assert:
      - `check` reports it *behind*, naming the floor release, listing the unknown ID as set aside, and listing the pending later migrations;
      - the command adopts it, applying exactly the later migrations and keeping the row;
      - it ends compatible, recording exactly the chain's IDs.

      Library integration.
      Done. Each `floor_database.py`'s `create_floor_database` takes `earlier_records`; each chain's `test_a_floor_database_carrying_an_earlier_releases_record_and_table_is_adopted` asserts the *behind* check (`floor`, `adopting`, `set_aside`, `pending`), the command's report, both planted rows kept, and exactly the chain's IDs. Library integration: the three projects' `make test` — passed.
- [x] 2.2 **Ledgers the chain cannot vouch for are refused by cause (D10).** In the VM storefront's `test_migration_chain.py`:
      - A database whose ledger records the bare-metal storefront's v0.3.0 floor IDs is refused as *unsupported* with the older-or-shared cause, its `missing` the VM floor IDs it lacks, unchanged byte for byte and not adopted. Read the IDs from `domains/bare_metal/storefront/tests/fixtures/v0_3_0_floor/floor_ids.json`, so no second copy of them exists.
      - A database whose ledger records compute provisioning's v0.3.0 floor IDs, none of which the VM floor shares, is refused with the not-this-chain cause.

      The existing "missing a floor ID" test in each chain asserts the older-or-shared cause and the floor release named. Library integration.
      Done. The bare-metal floor (23 of 37 IDs shared) is refused as older-or-shared, `missing` the 6 VM floor IDs it lacks, unchanged; compute provisioning's floor (none shared) as not built by `market-storefront-migrate`. Both read the other service's `floor_ids.json`. The VM and bare-metal "missing a floor ID" tests assert the cause and the floor release. Library integration — passed.
- [x] 2.3 **Bare metal drops `bare_metal_hosted_lifecycle` (D5).** Append `bare-metal-storefront-0021-drop-hosted-lifecycle` to the bare-metal chain's later migrations: `DROP TABLE IF EXISTS bare_metal_hosted_lifecycle`, with a docstring saying what the table held and that no release has read it since v0.3.0. In `test_migration_chain.py`, test three databases:
      - a floor database planted with that table, a row, and the record `bare-metal-storefront-0008-hosted-physical-lifecycle`: adopted, the record set aside, the table gone;
      - a floor database planted with `bare_metal_accepted_site_generations` and the record `bare-metal-storefront-0011-accepted-site-generations`: adopted, and the table dropped by `0018` (D2);
      - a fresh database: the migration runs and changes nothing.

      Library integration. Bump the bare-metal storefront again only if section 1's bump is smaller than this change needs (`versioning.md`, "One bump per unit of work").
      Done (dropping the table drops its indexes and trigger): `test_the_hosted_lifecycle_an_earlier_release_created_is_dropped`, `test_the_accepted_site_generations_table_is_dropped` (`0011` set aside, `0018` applied), `test_the_hosted_lifecycle_drop_changes_nothing_on_a_fresh_database`. Tests reach a migration by its ID, never its position in `CHAIN.migrations`. No further bump. Test-before at `e863ddf1f`: the fresh-database case fails for the absent `0021`. Library integration — passed.
- [x] 2.4 **The preview through the command (D7).** In `domains/vms/storefront/tests/integration/test_migrate_command.py`, `market-storefront-migrate --check`, driven through its entry point over 2.1's database, prints:
      - the baselines to be adopted;
      - marketplace 0.3.0 as the floor release whose records are replaced;
      - the record set aside;
      - the pending migrations.

      It exits unsuccessfully and changes nothing. The command alone then adopts the database and exits 0, and a second `--check` exits 0. Library integration through the entry point, as the command tests are.
      Done in `test_check_previews_adopting_a_database_an_earlier_release_built`: `--check` prints the baselines, "replacing the records of marketplace 0.3.0", the record set aside and the pending migrations, exits 1 with the bytes unchanged; the command exits 0 and a second `--check` exits 0. Library integration through the entry point — passed.
- [x] 2.5 **Verification.** Library integration: the three chains' `test_migration_chain.py` and the VM storefront's `test_migrate_command.py`. Then `change-workflow run pre-commit adopt-databases-upgraded-through-the-floor`.
      End-to-end: none exercises adoption or the dropped table, since every lane starts on a fresh database, where `0021` changes nothing; none is owed (`migration-tests.md`).
      Done. The three projects' `make test` and `change-workflow run pre-commit` — passed. End-to-end: none exercises adoption or `0021`, none owed.


## 3. The VM storefront adopts a real database that reached v0.3.0 by upgrading

Delivers D9's real upgraded-database proof. Implements "A database that reached v0.3.0 by upgrading is adopted" against the database the observed deployment held. Touches `domains/vms/storefront/tests/fixtures/v0_3_0_floor/upgraded/`, `domains/vms/storefront/tests/floor_database.py`, and `domains/vms/storefront/tests/integration/test_migration_chain.py`.

- [x] 3.1 **Generate the upgraded fixture (D9).** Build the database in two steps, each in an isolated environment and each constrained to the lock of its release's tag, with `kit/schema-migrations` from this repository for the snapshot:
      1. Install `arkhai-vms-storefront==0.3.5` (marketplace-v0.2.29's) from PyPI, constrained to `domains/vms/storefront/uv.lock` at `marketplace-v0.2.29`, and construct that release's database client on a fresh file as its startup did, with no configuration.
      2. Install `arkhai-vms-storefront==0.27.0` (v0.3.0's), constrained to the lock at `9fffe41e9`, and construct its `SQLiteClient` over the same file with the one-registration VM registry, as the floor fixture's README describes. Open no store.

      Then commit `upgraded/` with:
      - `schema.json`, the file's `schema_snapshot`;
      - `recorded_ids.json`, the ledger's IDs in `rowid` order;
      - `ddl.sql`, each `sqlite_master` entry's `sql` in `rowid` order;
      - `README.md`, giving the procedure, the versions, and the count of tables and IDs.

      The ledger is expected to hold the 29 floor IDs and the seven IDs the design's Context lists. If either published package cannot be installed, or the ledger holds other than those 36, stop and report it: the fixture's source is D9's, not this section's to change.
      Done, with step 1's source changed by the owner (2026-11-26) to the `marketplace-v0.2.29` tree, since the published 0.3.5 wheel cannot be installed (design.md D9). The ledger holds the 29 floor IDs and the seven of the Context; the database has 33 tables; `upgraded/README.md` gives the procedure.
- [x] 3.2 **The upgraded database is adopted and ends as a fresh one (D9).** `floor_database.py` gains a builder for the upgraded fixture, as `create_floor_database` builds the fresh one. A test in `test_migration_chain.py` plants a row in a table the release serves, then asserts:
      - `check` lists exactly the seven retired IDs as set aside;
      - the command adopts the database and applies exactly the later migrations;
      - the row is kept;
      - the database ends with the same `schema_snapshot` and ledger as a fresh database.

      Handle any residue as D9 says. A residue the release cannot serve is repaired by a migration appended after the baseline, with its own test, and the task's note names it. A harmless residue SQLite cannot remove safely is named explicitly in the test's comparison, with its reason, and in the note. Library integration.
      Done. `floor_database.py` gains `create_upgraded_database` and `upgraded_recorded_ids`; `test_a_database_an_earlier_release_built_and_v0_3_0_ran_on_ends_as_a_fresh_one` sets aside exactly the seven, adopts, keeps the row, and ends with a fresh database's ledger and schema but for `negotiation_threads`' column order (`_COLUMNS_ADDED_LAST`). The residue `derived_compute_listings` is repaired by `20261126_001_vm_derived_listings_dropped`, with its own tests; the delta's scenario is qualified for the column order (design.md D9). Library integration: `make -C domains/vms/storefront test` (661 integration) — passed.
      - **`derived_compute_listings`**, the listing-to-site mapping `storefront_listing_bindings` replaced, which nothing reads and `20261109_002_vm_frozen_inventory_dropped` does not drop: repaired by a new migration after the baseline, `20261126_001_vm_derived_listings_dropped` (`DROP TABLE IF EXISTS`, discarding its rows), with its own tests (`test_the_derived_listing_mapping_an_earlier_release_created_is_dropped`, `test_the_derived_listing_drop_changes_nothing_on_a_fresh_database`). Section 1's bump to 0.30.0 covers it.
      - **`negotiation_threads`' column order**: `agreement_bytes` and `settlement_data` come last, where v0.3.0 appended them by `ALTER TABLE` to the table v0.2.29 created; a fresh database holds them mid-table. Harmless, since every read and write of the table addresses its columns by name (`cli_logs.py`'s `SELECT *` reads through `sqlite3.Row`). Reordering means rebuilding a table three others reference, which no migration can do safely, since inside the engine's transaction SQLite ignores `PRAGMA foreign_keys`. The delta's scenario "A database that reached v0.3.0 by upgrading is adopted" now says "the same schema, apart from the position of columns the floor release appended to a table an earlier release created" — an edit to the change's spec outside the plan, to agree with D9's harmless-residue rule. Named in the test (`_COLUMNS_ADDED_LAST`, with its reason): the snapshots differ, the two columns are asserted last, and the snapshots are equal with that table's columns compared by name.

      `change-workflow run test-before … --test domains/vms/storefront/tests/integration/test_migration_chain.py --at ebd8621b9` fails at collection, since that commit's helper has no `create_upgraded_database`, which shows only that the test needs it. Library integration: `make -C domains/vms/storefront test` (661 integration) — passed.
- [x] 3.3 **Verification.** Library integration: the VM storefront's `test_migration_chain.py`. Then `change-workflow run pre-commit adopt-databases-upgraded-through-the-floor`.
      End-to-end: none; no lane holds a release's database, and none is owed (`migration-tests.md`).
      Done. `make -C domains/vms/storefront test` and `change-workflow run pre-commit` — passed. End-to-end: none holds a release's database, none owed.


## 4. The API-credit storefront and service adopt their v0.3.0 databases as a pair

Delivers D3. Implements "A v0.3.0 API-credit database is adopted", "An API-credit database is refused", and "The API-credit pair upgrades in order". Touches `domains/apicredits/storefront` (its chain, chain and command tests, and floor fixture README), `domains/apicredits/service` (its chain, a new `tests/fixtures/v0_3_0_floor/`, and its migration tests), and a static configuration test under `scripts/tests/`.

- [x] 4.1 **The API-credit storefront's floor (D3).**
      - **The chain.** `apicredits_storefront/utils/migrations.py` declares `Floor("marketplace 0.3.0", FLOOR_IDS)`, with `FLOOR_IDS` the committed fixture's 20 IDs in order. Rewrite the module docstring, which says the chain names no floor.
      - **The tests.** `tests/integration/test_migration_chain.py` gains a test that the chain's floor is the fixture's. Its tests refusing the release's database become adoption tests: adopted, exactly the later migrations applied, a planted row kept, and the same snapshot and ledger as a fresh database.
      - **The refusals.** A ledger with some but not all of the floor's IDs is refused as older-or-shared. A ledger with none of them is refused as not the storefront's.
      - **The fixture README** (`tests/fixtures/v0_3_0_floor/README.md`) says the chain adopts the release's database rather than that every database is refused.

      Library integration.
      Done. `test_a_database_from_the_release_is_adopted_and_ends_as_a_fresh_one`, `test_the_chain_floor_is_the_fixture_floor`, D9's synthetic case (`test_a_database_from_the_release_carrying_an_earlier_record_and_table_is_adopted`), and the older-or-shared, not-this-chain and no-ledger refusals. `refuse_unbound_listings` no longer names a fresh database (design.md D3). Library integration: `make -C domains/apicredits/storefront test` (302) — passed.
- [x] 4.2 **The API-credit service's floor fixture (D3).** Generate `domains/apicredits/service/tests/fixtures/v0_3_0_floor/` (`README.md`, `schema.json`, `floor_ids.json`, `ddl.sql`) as the other fixtures' READMEs describe. Install `arkhai-apicredits-service==0.7.0` from PyPI, constrained to `domains/apicredits/service/uv.lock` at `9fffe41e9`, and run that release's startup schema path (`apicredits_service.db.database.run_migrations`) over a fresh file with no configuration. The README records the procedure, the release's service code (dev `9fffe41e9`), and the count of tables and IDs; seven IDs are expected, `20260731_001_apicredits_schema_baseline` through `20261106_007_reservation_activated_at`. Verified by 4.3.
      Done as planned: 9 tables and the seven expected IDs; the README records the procedure, the source and the counts.
- [x] 4.3 **The service's baselines reproduce the fixture: decision gate (D3).** Add a test in `tests/integration/test_migrations.py` that the chain's three baselines, applied to an empty database, give exactly the fixture's `schema_snapshot`. Where they do not:
      - If the difference is small and understood, repair it by a migration appended after the baseline, with its own test, and name it in the task's note.
      - If the repair is more than that, stop this section and report it to the owner. D3 then splits the service's floor into its own change: this section's storefront work stays, both API-credit chains keep the floor this section reached, and the split is recorded in `proposal.md` and the change index.
      Done, with a small repair, no split: the baselines give the fixture plus `uq_capacity_buckets_host_id`, created on an adopted database by the site ledger's `20261126_001_capacity_bucket_host_index` (`kit/site` 0.15.0, the service bound `>=0.15.0`); the delta's baseline requirement names the index (design.md D3). `test_the_baselines_reproduce_the_release_schema_but_for_the_named_index`, `test_the_index_repair_changes_nothing_on_a_fresh_database` — passed.
- [x] 4.4 **The service's floor and adoption (D3).**
      - **The chain.** `apicredits_service/db/migrations.py` declares `Floor("marketplace 0.3.0", FLOOR_IDS)` from the fixture, and its module docstring is rewritten.
      - **The tests** (`tests/integration/test_migrations.py`):
        - the chain's floor equals the fixture's;
        - a database built from the fixture's DDL and IDs, with a planted key and grant, is adopted, keeping the rows and ending with the same snapshot and ledger as a fresh database;
        - a partial ledger is refused as older-or-shared, and one of none of the floor's IDs as not the service's;
        - the command, driven through its entry point as the same file's command tests drive it, refuses the partial ledger, naming marketplace 0.3.0.

      Library integration.
      Done. `FLOOR_IDS` holds the fixture's seven IDs. Tests: the floor equals the fixture's; a fixture database with a planted key and grant is adopted, applying the later migrations (the repair among them), keeping both rows, ending as a fresh database; D9's synthetic case; a one-ID ledger refused as older-or-shared by `migrate_database` and the startup check; another service's ID refused as not built by the command; the command through its entry point naming marketplace 0.3.0. Library integration: `make -C domains/apicredits/service test` (98) — passed.
- [x] 4.5 **The pair upgrades in order (D3).** Add a static configuration test, `scripts/tests/test_apicredits_compose.py`, which renders the API-credit stack with `docker compose config` over the files the stack composes. It asserts:
      - the credits storefront `depends_on` the credits service with `condition: service_healthy`;
      - the service's command runs `apicredits-service-migrate && exec …`;
      - the storefront's command runs `apicredits-storefront-migrate && exec …`.

      Together these show a failed service migration leaves the storefront not started and its database untouched. It is a static configuration test (`static-configuration-tests.md`).
      Done. Renders the documented bring-up and the API-credit lane's four files; also asserts the service's healthcheck probes `/health` on the application's port and neither container overrides its entrypoint; skips without Compose except under `COMPOSE_REQUIRED=1`. `make test-release-tooling TESTS=scripts/tests/test_apicredits_compose.py` (2) — passed.
- [x] 4.6 **Versions and locks.** Bump each API-credit package again only if section 1's bump is smaller than this section needs (`versioning.md`, "One bump per unit of work"), and refresh the locks with `make lock`. Verified by `make check-version-bumps` and `make check-packaging`.
      Done. Section 1's bumps cover the floors; `kit/site` 0.15.0 for the repair. `make lock`; `make check-version-bumps CHANGE_BASE=origin/dev` and `check-packaging` — passed.
- [x] 4.7 **Verification.** Library integration: the API-credit storefront's `test_migration_chain.py` and `test_migrate_command.py`, and the API-credit service's `test_migrations.py`. Static configuration: `scripts/tests/test_apicredits_compose.py`. Then `change-workflow run pre-commit adopt-databases-upgraded-through-the-floor`.
      End-to-end: the API-credit lane's scenarios start both services through their migrations on fresh databases, so they show the floor declarations leave a fresh pair working. No scenario exercises adoption, and none is owed (`migration-tests.md`).
      Done. The two API-credit projects' and `kit/site`'s `make test`, the Compose test, and `change-workflow run pre-commit` (every closing check) — passed. End-to-end: the API-credit lane starts both services on fresh databases; none exercises adoption, none owed.


## 5. Closeout

Per `arkhai-change-workflow`'s guidance, "Closeout", with this repository's own parts (`openspec/README.md`, "This repository's closeout parts") after campaign index currency.

- [x] 5.1 **Comment hygiene — confirm.** Run `make check-comment-hygiene`, and read the comments and docstrings this change added: the kit's module docstrings, each chain's, the `0021` migration's, and the fixture READMEs. Each must describe the current system, naming no change, review, task or migration that introduced it. Anything to rewrite returns the change to implementation.
      Done. `make check-comment-hygiene` — passed (no change-ID, task-number or change-name reference). Read the comments and docstrings added: the kit's module docstrings, each chain's, `0021`'s, `20261126_001_vm_derived_listings_dropped`'s, the site ledger repair's, the refusals' words and the fixture READMEs. Each describes the current system and names no change, review, task or introducing migration. Nothing to rewrite.
- [x] 5.2 **Import placement — confirm.** Run `make check-local-imports CHANGE_BASE=origin/dev` over the imports this change added; one that should move returns the change to implementation.
      Done. `make check-local-imports CHANGE_BASE=origin/dev` — passed: every import the change adds inside a function gives its reason. None to move.
- [x] 5.3 **Documentation compliance.** Re-check D1–D12 against `openspec/README.md`, "Documentation placement", and the permanent documents 5.8 writes against the code. Check that:
      - the normative rules are in `deployment-state/spec.md`, by the archive;
      - the rationale is in `deployment-state/architecture.md`;
      - the repository-neutral rule is in `docs/guidance/engineering/migrations.md` and `migration-tests.md`;
      - the repository's description is in `DEPLOYMENT_AND_CONFIG.md` and `ARCHITECTURE.md`;
      - the procedures are in the handbooks.

      Each must describe the current state, with no wording relative to the change.
      Done. D1–D12 were checked against the placement table. The normative rules reach `deployment-state/spec.md` by the archive, and the rationale is in its `architecture.md`. The repository-neutral rule is in `migrations.md` and `migration-tests.md`, and the repository's rules are in `migration-chain-tests.md` and `migrations-at-startup.md`. The description is in `DEPLOYMENT_AND_CONFIG.md` and `ARCHITECTURE.md`, and the procedures are in both handbooks. The API-credit service's baseline exception to `migration-tests.md` is a row in a new guidance file beside the capability, `deployment-state/migration-chains.md`, as `AGENTS.md` places a one-capability exception. Each promoted text was checked against the code (`result.py`'s words, `refuse_unbound_listings`, the migrations' docstrings) and describes the current state, with no wording relative to the change. Two statements this change made false outside the plan's list were corrected: `api-credits/architecture.md`'s "a fresh database is required" for an unbound listing, and its paragraph saying the service migrates in-process.
- [x] 5.4 **Narrative compression.** Compress sections 1–4's task notes to final behaviour, material validation evidence, deferred work (such as a split API-credit service floor), and destinations. First move durable rationale into `design.md`: the residue 3.2 named and the repair it made (`20261126_001_vm_derived_listings_dropped`), the owner's change of D9's v0.2.29 source to the tagged tree (3.1), and any repair 4.3 made.
      Done. Sections 1–4's notes are compressed to final behaviour, evidence and destinations, and the next-session notes are removed. Moved to `design.md` first: under D3, the index repair, its declined tolerance objection, its move to `kit/site`, and the unbound-listing refusal; under D6, the `kw_only` floor, `UnsupportedCause`, and the bumps; under D9, the owner's change of v0.2.29's source to the tagged tree, the regeneration caveat, and the two residues and their handling; under D10, the refusal's service naming, the not-this-chain words, the registry's revision count (18 F1), and the registry's single-revision *ahead* (25 F1). No deferred work: the API-credit service's floor did not split.
- [x] 5.5 **Roadmap currency.** This change serves no roadmap goal and closes no gap row. Record that disposition. Confirm `docs/development/ROADMAP.md`'s Goal 1 sentence on the VM storefront's retired inventory tables ("the storefront's migration after its v0.3.0 baseline drops them from an adopted one") still holds, which D1 makes true of upgraded databases too.
      Done. No roadmap goal is affected, and none is edited. Goal 1's sentence ("the storefront's migration after its v0.3.0 baseline drops them from an adopted one") holds: `20261109_002_vm_frozen_inventory_dropped` runs on every adopted database, upgraded ones included. Recorded in the design-promotion record.
- [x] 5.6 **Campaign index currency.** Update the change's row in `openspec/changes/README.md`, "Independent active changes": its status, and its Notes naming what landed and any split of the API-credit service's floor. It has no campaign graph. Run `make check-change-index`.
      Done. The change's row in "Independent active changes" is `in closeout`, with its Notes naming what landed and no split; it has no campaign graph, and no other row changed. `make check-change-index` — passed (re-run after the archive re-pointed the link, 5.11).
- [x] 5.7 **Packaging, and the end-to-end pipeline** (`openspec/README.md`, "Packaging" and "End-to-end pipeline").
      - **Packaging.** Run `make check-packaging` and resolve every failure, then `make check-architecture-change CHANGE=adopt-databases-upgraded-through-the-floor`. The change touches no `.agents/`, `.claude/` or `.codex/` path.
      - **The pipeline.** Record the end-to-end pipeline run that the latest passing validation gathered, with its result, from that validation's record. Every lane's scenarios exercise each service's migration on a fresh database through the changed engine, and none exercises adoption.
      Done. Packaging: `make check-packaging` — passed; `make check-architecture-change CHANGE=adopt-databases-upgraded-through-the-floor` — passed (owns no architecture row). No `.agents/`, `.claude/` or `.codex/` path touched. Pipeline, from validation 30 (`reviews/30-validation.md`, passed) of `fde26b2f7`, the pre-closeout commit this closeout builds on, no waiver: run 45866020269, success — API-credit lane 4 passed, bare-metal lane 249, VM lane 513; local (`make test`, `check-packaging`) and Helm passed too. Every lane starts each service through its migration on a fresh database through the changed engine and floors; none exercises adoption, which the chain tests in `local`'s `test` step prove. No section owed observations to validation.
- [x] 5.8 **Promotion.** Write the permanent documents and complete the design-promotion record in `design.md`:
      - **`deployment-state`'s spec** (`openspec/specs/deployment-state/spec.md`): by the archive (D1, D3, D5, D7, D10, D12).
      - **Its companion**, `openspec/specs/deployment-state/architecture.md`:
        - "One engine, one contract": the required `Floor`, D6 and D12;
        - "Compatibility is the exact set": ahead only with the baselines recorded, or, for the registry, at one revision neither its chain nor its history up to its floor revision holds, and the two unsupported causes, D10;
        - "The baseline and adoption": adoption whatever else a floor database records, every chain's floor including both API-credit chains, `0.0.0`, the upgrade through the floor, retired tables dropped by later migrations (bare metal's `bare_metal_hosted_lifecycle` and the VM storefront's `derived_compute_listings` among them), the harmless column-order residue of a database that reached the floor by upgrading, the API-credit service's baselines differing from its v0.3.0 schema by one named index the site ledger's repair creates (and, where `migration-tests.md`'s "the baselines alone reproduce the fixture's snapshot exactly" does not hold for that chain, the exception recorded as `rules.md`, "When an exception is expected", admits it), and the API-credit pair's order (D1, D3, D5, D8, D9, D12).
      - **The engineering guidance:**
        - `docs/guidance/engineering/migrations.md`: a new section before "Migrations fail forward" stating, in repository-neutral words, that every chain declares a floor, that a database the floor release ran on is adopted whatever earlier releases recorded, that an older one upgrades through the floor release, and that starting fresh is never the remedy for a database that can upgrade. Amend "A check mode previews" for the records set aside (D1, D7, D10, D12).
        - `docs/guidance/engineering/migration-tests.md`: "The floor fixture" is mandatory for every chain with recorded floor IDs, and "The chain" adds the floor database carrying unknown records and, where a floor release kept records outside its chain, a real upgraded database (D9).
      - **The repository guidance:**
        - `docs/guidance/repository/migration-chain-tests.md`: "The floor fixture" (both API-credit fixtures, and the VM storefront's `upgraded/`) and "The chain" (D9, D12);
        - `docs/guidance/repository/migrations-at-startup.md`: "The application's open and the check mode", the causes and remedies (D10).
      - **The description documents:**
        - `docs/development/DEPLOYMENT_AND_CONFIG.md`, "Migrations at startup": the result table's *ahead* and *unsupported* rows, the adoption paragraph, the API-credit floor, the remedies, and `bare-metal-storefront-0021-drop-hosted-lifecycle`, `20261126_001_vm_derived_listings_dropped` (each with the rows it discards) and the API-credit service's composition of the site ledger's `20261126_001_capacity_bucket_host_index` among the migrations after the baseline (D1, D3, D5, D7, D10);
        - `docs/development/ARCHITECTURE.md`, "Accepted representations and application views": its sentence that any other existing database "is refused, and the service starts from a fresh database instead" restated (D1, D10).
      - **The handbooks:**
        - `docs/release-handbook.md`, "The migration floor": a new floor leaves older deployments to upgrade through the floor release, and the setting-aside has no retirement row (D8);
        - `docs/operator-handbook.md`, "Supported databases" (D1, D3, D10), "The procedure" step 2 (a refused database is confirmed as the service's and upgraded through the floor release; the preview's records set aside), and "What the upgrade from v0.3.0 changes" (the API-credit pair's adoption and rollout, bare metal's dropped table and the VM storefront's `derived_compute_listings`, each with its discarded rows — for the VM table, a database never put through v0.3.0's conversion to the common binding loses its only copy of those mappings, which no release since v0.3.0 has read — D3 and D5).
      Done. Written:
      - `deployment-state/architecture.md`: "One engine, one contract" (the required `Floor`, `0.0.0`); "Compatibility is the exact set" (*ahead* with the baselines, or the registry's single revision; the two unsupported causes); "The baseline and adoption" (adoption whatever else a floor database records, upgrade through the floor, every chain's floor, the dropped tables, the column-order residue, the index repair, the pair's order).
      - `deployment-state/migration-chains.md` (new): the exception to `migration-tests.md`'s exact-reproduction rule for the API-credit service.
      - `migrations.md`: the new section "Every chain declares its floor, and a database upgrades through it" and "A check mode previews".
      - `migration-tests.md`: "The engine", "The floor fixture" (mandatory, the upgraded database), "The chain".
      - `migration-chain-tests.md` and `migrations-at-startup.md`.
      - `DEPLOYMENT_AND_CONFIG.md`, "Migrations at startup": the table, adoption, refusals, the pair, and the three new migrations.
      - `ARCHITECTURE.md`, "Accepted representations and application views".
      - The release handbook's "The migration floor"; the operator handbook's "Supported databases", "The procedure" steps 2–3, and "What the upgrade from v0.3.0 changes".
      - `api-credits/architecture.md` (5.3).

      `deployment-state/spec.md` is written by the archive (5.11). The capability has no `index.md`. The design-promotion record is complete.
- [x] 5.9 **Guidance placement.** Read the sections 5.8 wrote in `docs/guidance/engineering/` against the layer test. The rule must hold in any repository: no marketplace release, service or path named, with a neutral example. Read the repository guidance against its adjacency. Then run `make check-guidance`.
      Done. The sections written in `docs/guidance/engineering/` name no marketplace release, service or path, and use a neutral example (a billing service whose floor is its 2.0 release). The repository guidance sits beside its subject: `migration-chain-tests.md` and `migrations-at-startup.md` span the services, and the one-capability exception sits in `deployment-state/`. One placement for the closeout review to weigh: the exception could instead sit beside `api-credits`, whose service it concerns; it is in `deployment-state`, which owns the chains and whose requirement names the index. `make check-guidance` — passed (98 files, 5 exception rows cite guidance).
- [x] 5.10 **Documentation citations.** Run `make check-doc-citations CHANGE=adopt-databases-upgraded-through-the-floor` and resolve every match, then `change-workflow openspec validate adopt-databases-upgraded-through-the-floor --strict`.
      Done. `make check-doc-citations CHANGE=adopt-databases-upgraded-through-the-floor` — passed. Run unscoped, it found every promoted document's citations resolving; its two misses are pre-existing, in another change's row and another change's `design.md`. `change-workflow run pre-commit adopt-databases-upgraded-through-the-floor` before the archive ran `openspec validate adopt-databases-upgraded-through-the-floor --strict`: "Change 'adopt-databases-upgraded-through-the-floor' is valid", and every closing check of `make check-repository` passed.
- [x] 5.11 **Archival.** Run `change-workflow openspec archive adopt-databases-upgraded-through-the-floor -y`, merging the `deployment-state` delta (two modified requirements, one added) into `openspec/specs/deployment-state/spec.md`. The change's row then links to its archive directory.
      Done. The deltas merge: the permanent spec still directed a fresh database, so they were not synchronized by hand, and no `--skip-specs` was used. `change-workflow openspec archive adopt-databases-upgraded-through-the-floor -y` validated the change, merged `deployment-state` (two modified, one added), and moved the change to `openspec/changes/archive/2026-11-26-adopt-databases-upgraded-through-the-floor/`. Its one warning, about the incomplete task, was this one. The spec's diff shows each modified and added requirement once, as the delta states it, and nothing else changed. The index row links to the archive directory. `make check-change-index` and `change-workflow run pre-commit adopt-databases-upgraded-through-the-floor` (every specification validated strictly) — passed.
