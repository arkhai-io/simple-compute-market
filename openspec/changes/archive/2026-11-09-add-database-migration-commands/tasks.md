# Tasks

Replanned on 2026-11-08 against the reviewed design: sections 1–4 and 6–10 replace the
unchecked tasks of the plan written before the design discussion, whose sections 1–4
covered only the VM storefront and the API-credit services. Section 5 keeps its
completed task; its other tasks moved to section 10 (comment hygiene and import
placement) and section 11 (promotion).

Amended on 2026-11-09 after section 1 returned the change to design and D15a was
narrowed to hosts: section 1's tasks 1.1, 1.2 and 1.4 and closeout parts 11.5 and 11.9
are amended; nothing else moved.

Amended on 2026-11-09 after section 10 returned to planning before any of its tasks
started: section 10 is replanned (its own note says how its tasks map to the old ones);
nothing else moved.

## 1. Stored `ssh` connections are repaired and a connection's version is required

Replanned on 2026-11-09 against the design as settled after section 1's return: D15a's
migration rewrites hosts only, since no job holds a copy of a connection, and a lease
already `release_failed` on a version-1 host is recovered by the operator, not by
retry-release. Tasks 1.1, 1.2 and 1.4 are amended; 1.3 and 1.5 stand. The work in
progress committed before the return was the starting point.

Delivers D15a and `physical-provisioning`'s modified "Host connections are typed by
their implementation's codec" and "Host registry records the connection port".
Touches `provisioning/compute/contracts` (`compute_provisioning_contracts/hosts.py`),
`provisioning/compute/service` (`db/migrations.py` and its tests),
`provisioning/compute/src/compute_provisioning/hosts/` (`definitions.py`, the INI
import, `connection.py`), `provisioning/compute/ansible` (`connection.py`), and every
caller that builds a `ConnectionSubmission`.

- [x] 1.1 Find every stored copy of an `ssh` connection in the provisioning database —
      the `hosts` envelope columns and any job record, envelope, or parameter that
      carries a connection rather than reading its host at dispatch — and record the
      list in the section's notes. Verify by reading the job engine's host lookup
      (`compute_provisioning/jobs/engine.py`, `HostLookup`) and each job table's
      columns. The section notes' "What 1.1 found" records the result — the `hosts`
      row alone — which D15a now states; check this task once the notes are
      compressed to that result. (D15a)
      Done by reading the code: the `hosts` row alone (see the notes).
- [x] 1.2 Add one migration to compute provisioning's chain, after its last entry,
      that rewrites every host's `ssh` connection stored at version 1 to version 2
      with the same public fields and protected values, validating the public fields
      through the version-2 codec and failing, naming every refused host and
      rewriting nothing, when the codec refuses them. It takes only the database and
      touches no job row. Verify with library integration tests in
      `provisioning/compute/service/tests/integration/`: a database with version-1
      hosts (protected key and key file) and a queued create and a queued teardown
      naming them migrates the hosts to version 2 with identical public fields and
      ciphertext, leaves both jobs' rows unchanged, and each job's host parses at
      version 2 at dispatch; a host the version-2 codec refuses fails the migration
      naming it with nothing rewritten and the migration unrecorded; a rerun changes
      nothing. (D15a; `physical-provisioning` "A provisioning database holding
      version-1 connections is migrated", "A version-1 connection's fields are not
      valid at version 2")
      `20261108_001_ssh_connections_version_2` in
      `compute_provisioning_service/db/migrations.py`, last in the chain (section 4
      moved it onto a connection with the rest). Its target version is the literal 2
      (design.md, "Implementation record"). Library integration
      (`tests/integration/test_ssh_connection_version_migration.py`, file-backed
      SQLite, no application): protected-key and key-file hosts with a queued create
      and a queued teardown migrate to version 2, every other column byte for byte,
      the job rows unchanged; each stored job's host is refused by the Ansible
      runner's `inventory_target` before the migration and read at version 2 after it
      through `HostAuthority.lookup`, the job engine's host lookup — dispatch's two
      reads, not a dispatch. A quoted port, or a host naming no key, fails naming the
      host, nothing rewritten, the migration unrecorded; a rerun changes nothing.
      Integration 603 passed.
- [x] 1.3 Make `ConnectionSubmission.version` required (no default), and state the
      version explicitly in every caller that relied on the default — host
      definitions documents' parsing, the INI import, the typed connection factory,
      the provisioning client, fixtures, and e2e helpers — found by searching for
      `ConnectionSubmission(` and connection dictionaries without `version`. Bump the
      contracts distribution's minor version per `docs/development/RELEASING.md`'s
      versioning policy. Verify with a unit test of the contract (an unversioned
      connection is refused naming `version`) and an application-integration test
      through the typed client (an unversioned host submission is refused and nothing
      is stored; a version-1 submission is refused naming version 2). (D15a;
      `physical-provisioning` "A version-1 or unversioned connection is submitted")
      Contracts 0.14.0; the service 0.24.1 requires `>=0.14.0`. No production caller
      relied on the default; four test modules now state it. Unit
      (`contracts/tests/unit/test_contracts.py`): an unversioned connection in
      `HostCreate` and `HostUpdate` is refused as missing `("connection", "version")`
      — 156 passed. Application integration (`test_hosts_api.py::TestConnectionVersions`):
      an unversioned registration, sent raw since the typed client cannot build it,
      answers 422 and stores nothing; versions 1 and 3 are refused through the typed
      client naming version 2 — passed. `make lock` refreshed every lock the bump
      reaches.
- [x] 1.4 Delete `provisioning/compute/service/tests/integration/test_ssh_connection_version_recovery.py`,
      the failing test that showed retry-release cannot recover a teardown whose job
      failed: D15a no longer claims that recovery, and the scenario it proved is
      removed from the delta. A lease already `release_failed` on a version-1 host is
      recovered by the operator's manual teardown and force-release, which closeout
      writes into the operator handbook (11.9), and re-running such a teardown is the
      unowned roadmap gap closeout records (11.5); neither is code in this change.
      Verify with the provisioning service's integration suite passing with no
      failure. (D15a)
      Deleted (`git rm`); nothing else named it. Integration 603 passed, none
      failed.
- [x] 1.5 **Verification.** Run `make -C provisioning/compute/service test`,
      `make -C provisioning/compute/contracts test`, and the provisioning client and
      ansible suites (`make -C provisioning/compute test`), then
      `scripts/change-workflow run pre-commit add-database-migration-commands`.
      End-to-end: `e2e_deal`, `e2e_bare_metal_mock_deal`, and `provisioning` submit
      hosts and run create and teardown against version-2 connections, so the
      pipeline shows the required version reaching every caller; no lane holds
      version-1 data, and no scenario is owed for the migration, which the library
      and application integration tests prove.
      Owed by validation: none.

**Section 1 notes — completed 2026-11-09.**

What 1.1 found. Only the `hosts` row holds a connection (`connection_kind`,
`connection_version`, `connection_public`, `connection_protected`; written in
`compute_provisioning/hosts/db.py`). No job record, envelope, or parameter carries one:
the job engine reads its host at dispatch (`HostLookup`, which `HostAuthority.lookup`
serves from the `hosts` row through `_execution_host`); `ansible_jobs.params`, `result`,
`execution_handle`, the `credentials` envelopes, and the fulfillment aggregate's
prepared operations carry none, and fulfillment requests carried none at the floor. A
job not yet finished at the upgrade reads the rewritten host when it is dispatched.

The return to design (2026-11-08) and its evidence are in design.md's "Implementation
record" and the return's commit `615d071ec`; 1.4 deletes the test that showed it.

End-to-end. `e2e_deal` and `e2e_bare_metal_mock_deal` register their hosts at version 2
and run create and teardown against them. `provisioning` is a read-only smoke marker
and registers no host, so it is not evidence for this section, correcting 1.5. No lane
holds version-1 data.

Suites: service unit 717, integration 603; contracts 156; `make -C provisioning/compute
test` (the kit alone) 531; ansible 187 passed and 4 skipped; client 86 — the last two
run on their own, since `make -C provisioning/compute test` runs only the kit, not as
1.5 said. Pre-commit (`make lock`, the packaging check, every suite, `pre-commit`)
passed, and again after the fresh-context check's fixes (the migration's target
version, the test's overstated dispatch claim, stale wording). Left for closeout:
`physical-provisioning/architecture.md`'s "Nothing rewrites a stored row on its own",
which this migration contradicts (11.9). Why the service bump is a patch: design.md.

## 2. Storefronts retire registry listings they do not hold open

Delivers D15b and `storefront-publication`'s added "A storefront retires registry
listings it does not hold open". Touches `core/storefront`
(`core_storefront/multi_registry_client.py`), `kit/capacity-publication`
(`market_capacity_publication/publication.py`, `capacity.py`, and the hooks each
storefront supplies), and the three storefronts' publication wiring
(`domains/vms/storefront/src/market_storefront/`,
`domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/publication.py`,
`domains/apicredits/storefront/src/apicredits_storefront/`).

- [x] 2.1 Add a per-registry listing read to the cross-registry client, beside
      `publish_listing_per_registry`, `update_listing_per_registry`,
      `delete_listing_per_registry`, and `get_descriptors`: for each configured
      registry it pages `list_listings_for_publisher(principal, status="open")` to
      completion and returns that registry's listings, or an unreachable result when
      any page fails. Verify with unit tests in `core/storefront/tests/unit/`: results
      keep their registry; more than one page is read; a failure on a later page
      yields unreachable for that registry and leaves the others' results intact.
      (D15b)
      `MultiRegistryClient.list_publisher_listings_per_registry` returns one
      `RegistryListings` per configured registry (`listings` `None` when
      unreachable), in pages of `REGISTRY_PAGE_LIMIT` (200, the registry's maximum),
      the per-call deadline bounding each registry's whole read. A
      constructor-injected `client_factory` is the unit tests' seam (design.md). Core
      also gains `SQLiteClient.open_listing_ids` (every locally open listing, paused
      or not), the sweep's held set. Unit
      (`tests/unit/test_multi_registry_publisher_listings.py`, fake clients through
      the factory): per-registry results in order; five listings over three pages; a
      full last page followed by an empty one; a second-page failure makes that
      registry unreachable and keeps the other's listings; a page size below one
      refused — passed. Library integration (`tests/integration/test_open_listing_ids.py`,
      real SQLite) — passed. `make -C core/storefront test`: 240 passed.
      arkhai-core-storefront 0.18.0.
- [x] 2.2 Add the sweep to the publication runtime in `kit/capacity-publication`: after
      a pass's local reconciliation, for each registry the read returns, close through
      the existing per-registry update every open listing under the storefront's own
      principal, of an offering mode it serves, that it does not hold open locally;
      close nothing at an unreachable registry; report each close as `close` with the
      reason that the storefront does not hold it; in a preview pass, report without
      closing. The storefront supplies its principal, its offering modes, and the
      listings it holds open through the runtime's hooks. Verify with unit tests in
      `kit/capacity-publication/tests/unit/` beside `test_registry_convergence.py`:
      an unknown open listing closes; a locally closed listing open at a registry with
      no publication record closes; another offering mode's listing and a listing held
      open during a site-projection outage stay open; a partial read closes nothing;
      a preview closes nothing and reports. (D15b; every scenario of the added
      requirement)
      `PublicationRuntime.retire_unheld(dry_run=...)` returns a `RegistrySweep`
      (each `UnheldListingClose` `planned`, `closed`, or `failed`, and the
      unreachable registries); `retire_unheld_listings(runtime, report)` in
      `cycle.py`, run after `converge_registries`, reports `close`/`not_held` with
      its `registry`, `skip`/`registry_unreachable`, and `fail`/`registry_close_failed`.
      The held set is the repository's `open_listing_ids`; the publisher and offering
      modes are the hooks' new `registry_publisher` and `served_offering_modes`. The
      held set's read order, unrecorded closes, and listings stating no
      `offering_mode` are in design.md's "Implementation record". Unit
      (`tests/unit/test_registry_sweep.py`): an unknown listing closes; a locally
      closed listing with no publication record closes; another mode's and a locally
      open listing stay open (the outage itself is driven in 2.3's VM test); two
      served modes both sweep; an unreachable registry is skipped while the other is
      swept; a preview reports both closes and makes none; a refused close is reported
      and closed next pass; publication turned off sweeps nothing — passed.
      arkhai-kit-capacity-publication 0.12.0 (the hooks and repository protocols each
      gain members).
- [x] 2.3 Wire the sweep into each storefront's publication pass — the VM publication
      cycle, the API-credit capacity reconciliation, and each bare-metal publication
      run — and prove it against a real registry: an application-integration test per
      storefront, or one shared fixture driving each, in which a registry holds an
      open listing under the storefront's principal that the storefront does not
      record, a pass closes it, and a second storefront's offering mode under the same
      principal is left open. Extend `domains/vms/storefront/tests/integration/test_publication_loop.py`,
      `domains/bare_metal/storefront/tests/test_publication_cycle.py`, and
      `domains/apicredits/storefront/tests/unit/test_capacity_reconcile_converges.py`
      or their integration neighbours. (D15b)
      Wired: VM's cycle runs the sweep after convergence in its `converge` stage, its
      hooks naming the signer's principal and `vm` alone (design.md); bare metal's
      cycle the same, naming the publisher `build_publication_runtime` now requires
      and `bare_metal` alone; API credits' capacity reconciliation ends with
      `publication_service.retire_unheld_listings`, which logs.

      Differs from the plan: no test runs a storefront against a real registry; the
      proof is split by level (why: design.md's "Implementation record"). The
      registry's own integration test, through its typed client,
      (`core/registry/tests/integration/test_listings.py::TestListPublisherListings::test_open_listings_page_by_offset_to_the_end`,
      rows inserted directly to fix their creation order) shows a publisher's open
      listings paged by `limit` and `offset` to the end are each returned once, none
      closed and none of another publisher, and that each states its resource's
      `offering_mode`; 2.1's unit tests prove the client's paging and per-registry
      failure; 2.2's the sweep's decisions; each storefront's wiring is proven against
      a double replacing the cross-registry client, so the client's paged read runs
      in no storefront test, and no lane plants an orphaned listing to observe the
      cross-service close. The round's triage (32 F2) took that composition as
      answering 2.3's "against a real registry".

      VM (`test_publication_loop.py`, the storefront app through its typed client,
      the cross-registry client doubled):
      `test_a_cycle_closes_registry_listings_the_storefront_does_not_hold` — read
      under the signer's principal; an unheld `vm` listing closes at both registries;
      the held listing and a `bare_metal` listing under the same principal stay open;
      the preview sends nothing — passed;
      `test_a_listing_held_through_a_site_outage_stays_open_at_the_registry` —
      restarted with its site unreachable, the held listing (`site_projection_unknown`)
      stays open while an unheld one closes — passed. Bare metal
      (`test_publication_cycle.py`, the cycle over a real database with site and
      registry doubles, which its docstring states is not integration evidence):
      unheld closes, held and `vm` stay open, a preview sends nothing, an unreachable
      registry is `skip` and swept next run — passed. API credits
      (`tests/integration/test_publish_reconcile.py::test_the_sweep_closes_registry_listings_the_storefront_does_not_hold`,
      `retire_unheld_listings` over the storefront's real database with
      `_make_registry_client` replaced on its defining module; not application
      integration, design.md): an unheld `api_credits` listing closes, the held one
      and a `vm` listing stay open, the read names the seller's principal — passed;
      `tests/unit/test_capacity_reconcile_converges.py` holds the sweep last, after
      convergence. Versions: bare metal 0.28.0 (its exported `build_publication_runtime`
      and `BareMetalPublicationHooks` gain a required `publisher`), VM 0.28.0 and API
      credits 0.21.0 (new public hook methods), each pinning the kit at 0.12.0 and
      requiring core-storefront `>=0.18.0`; VM's pin on the bare-metal storefront
      moves to 0.28.0, the provisioning service's dev pin on the kit to 0.12.0.
- [x] 2.4 **Verification.** Run `make -C core/storefront test`,
      `make -C kit/capacity-publication test`, and the three storefronts' suites
      (`make -C domains/vms/storefront test`, `make -C domains/bare_metal/storefront test`,
      `make -C domains/apicredits/storefront test`), then
      `scripts/change-workflow run pre-commit add-database-migration-commands`.
      End-to-end: `e2e_bare_metal_publication`, `multi_registry`, `e2e_listing_shapes`,
      and `e2e_credits_deal` run publication passes against live registries, so the
      pipeline shows the sweep closing no listing a storefront holds; no lane plants an
      orphaned listing, and no scenario is owed, since the application integration
      tests prove the close against a real registry.
      Owed by validation: none.
      Correction: no application integration test proves the close against a real
      registry; 2.3's note says how the proof is split by level instead. The
      pipeline has not run on this section: the end-to-end markers above are what
      a passing run would show, read from the scenarios' code. "Owed by
      validation: none" stands, since no push-only workflow is owed.

**Section 2 notes — completed 2026-11-09.**

Suites (final run): core storefront 240; core registry unit 139, integration 129;
capacity publication 135; VM storefront unit 1166 passed and 1 skipped, integration 551;
bare-metal storefront 598; API-credit storefront 256; pre-commit (every suite and the
packaging check) passed.

End-to-end, from the scenarios' code (no pipeline has run on this section): the four
markers run publication passes against live registries, so a passing pipeline is
evidence the sweep closes no listing a storefront holds. No scenario publishes under a
storefront's principal except through the storefront (only `validate_publish_listing`,
a dry run), so none shows a close. The development stack's two VM storefronts, Bob and
Alice, have distinct principals.

Fresh-context checks (two). Fixed: VM swept every mode its domain registry composes
(now `vm` alone, tested); the kit's in-process registry test (removed, the registry's
side proven in its own suite); the missing site-outage test; patch bumps that were
minor changes; the API-credit test replacing `build_capacity_runtime` on an importing
module (now the factory seam); docstrings and notes overstating what tests run; 2.4's
real-registry claim. Kept: the order assertion in `test_capacity_reconcile_converges.py`,
which replaces each step on `publication_service` as it did before; the bare-metal
cycle tests in their non-integration module; `capacity_client.py`'s function-local
import (design.md). Closeout: ARCHITECTURE.md's "Capacity publication and multi-domain
storefront composition", which says the kit owns "the registry convergence every
publication pass ends with" (11.9).

Round 1 triage fix (32 F2). The registry paging test now asserts each listing read
through the typed client carries `listing_resource["offering_mode"] == "vm"`; with the
planted resource emptied it failed on that assertion, and the fixture was restored.
`make -C core/registry test` — unit 139, integration 129. Why, and the declined
alternatives: design.md.

Checks over the round's triage fixes (32 F1, recorded in section 4's notes, and 32 F2):
strict validation valid; pre-commit passed all three hooks. Their fresh-context check
fixed the restated `site-capacity` scenario (now stated by the records
`capacity_reservations` keeps), 11.9's missing `site-capacity/architecture.md`
retired-state paragraph, D12 and the proposal distinguishing the API-credit service's
retired-state conversion from a floor migration (8.1 names the removal), and 2.3's
restored pending note; it declined one change to "Active fulfillment migration"
(design.md).

Handoff. The sweep reads every registry each pass: each VM or bare-metal publication
cycle and each API-credit capacity reconciliation (per capacity event, convergence's
cadence there). `client_factory` is the seam for a test needing its own registry client.

## 3. One migration engine, in a foundation kit

Delivers D2's engine and the engine side of D5 and D14, for `deployment-state`'s added
"One migration mechanism serves every stateful service", "A chain begins at its
supported baseline", and "A migration and its record commit together". Touches a new
`kit/schema-migrations` (distribution `arkhai-kit-schema-migrations`, import package
`market_schema_migrations`), `docs/development/ARCHITECTURE.toml` (`[kit_areas]`
foundation list), and the repository's wheel and lock wiring for a new kit.

- [x] 3.1 Create the kit with the repository's project layout (one flat import package
      under `src/`, `pyproject.toml` declaring only what it imports, the standard
      library for the engine), add it to `[kit_areas].foundation` in
      `docs/development/ARCHITECTURE.toml`, and wire it into `make dist` and the
      locks of its consumers as later sections add them. Verify with
      `make check-architecture` and `make check-packaging`. (D2; repository obligation:
      `AGENTS.md` "Package and dependency discipline")
      `kit/schema-migrations` (`arkhai-kit-schema-migrations` 0.1.0,
      `market_schema_migrations`): no runtime dependency, SQLAlchemy only as the
      `sqlalchemy` extra, a package allowlist naming it alone. Wired into
      `kit/Makefile` (`dist-schema-migrations`, `test-schema-migrations`, both in the
      aggregates) and published (`manifests/published-distributions.json`,
      `publish-pypi.yml`'s filters and package table, RELEASING.md's
      published-packages table; why: design.md). Lock seeded by hand and resolved by
      `make lock PROJECTS=kit/schema-migrations`. `make check-architecture`,
      `make check-packaging` and `make test-release-tooling`
      (`scripts/tests/test_publish_matrix.py`) — passed.
- [x] 3.2 Implement the engine: `Migration` (an ID and an apply callable on a
      connection); `Chain` (its service, command, ordered migrations, the v0.3.0 floor
      IDs, and its baseline IDs); `migrate`, which applies each pending migration and
      records its ID in one transaction, adopts a database recording every floor ID by
      replacing those records with the baseline IDs in one transaction without running
      the baselines, refuses an *ahead* or *unsupported* database applying nothing, and
      refuses any other non-empty database whose chain has no floor; `check`, which
      opens the database read-only and returns *absent*, *behind* (with pending IDs,
      or the adoption pending), *ahead* (unknown IDs taking precedence, pending listed
      too), *unsupported*, or *compatible*, issuing no DDL and creating no file; a
      refusal-message renderer taking a result, a service, and a command, independent
      of the engine so the registry can use it; and `schema_snapshot`, a normalized
      structural view (tables, columns, indexes, triggers) for tests. Provide adapters
      for a `sqlite3` connection and a SQLAlchemy connection; the SQLAlchemy adapter
      imports SQLAlchemy only where a consumer that has it selects it, as its
      `pyproject.toml` records. Verify with unit tests in
      `kit/schema-migrations/tests/unit/` for each result, adoption, refusal of ahead
      and unsupported databases, a failing migration leaving earlier records and no
      trace of itself, the read-only check creating no file, the message for each
      result, and `schema_snapshot` ignoring SQL text differences between an
      `ALTER`-added and a created column. (D2, D5, D14; `deployment-state` "A
      migration and its record commit together", "A migration fails partway through a
      chain")
      `engine.py` (`Migration`, `Chain` of `baselines`, `migrations`, `floor_ids`;
      `classify`, `check`, `migrate`, `MigrationRefused`, `MigrationFailed`),
      `result.py` (`CheckState`, `CheckResult`, `describe`, `refusal_message`; imports
      nothing of the engine), `sqlite.py` (`SqliteMigrationConnection`,
      `connect_read_only`, `check_sqlite_file`), `sqlalchemy_adapter.py`
      (`SqlAlchemyMigrationConnection`, `check_engine`), `snapshot.py`
      (`schema_snapshot`). Differs from the plan: tests that open a real database are
      library integration tests in `tests/integration/`, as TESTING.md's
      library-package rule places them; `tests/unit/` holds the pure classification
      and message tests. Unit (`test_classification.py`, `test_refusal_message.py`):
      every result from tables and recorded IDs (an empty ledger absent; part of the
      floor unsupported naming what it lacks; the floor behind with adoption pending,
      with or without a later migration recorded; leftover floor records ahead), chain
      validation, and each state's message — passed. Library integration
      (`test_sqlite_engine.py`, `test_sqlalchemy_engine.py`, real SQLite files): each
      case the task names, adoption with baselines that raise if called, adoption
      keeping a recorded later migration, tables without a ledger refused with none
      created, a failing migration under default transaction control,
      `isolation_level=None`, `autocommit=True` and SQLAlchemy, a failed adoption
      keeping the floor records, an in-memory engine checked through its own
      connection — passed; `test_schema_snapshot.py`: the `ALTER`-added column, and
      type, nullability, default, keys, unique constraints by columns, foreign keys,
      partial and expression indexes, `CHECK` text, `AUTOINCREMENT`, `STRICT`,
      `WITHOUT ROWID`, triggers and views, the ledger left out — passed.
- [x] 3.3 **Verification.** Run `make -C kit/schema-migrations test`,
      `make check-architecture`, `make check-packaging`, and
      `scripts/change-workflow run pre-commit add-database-migration-commands`.
      End-to-end: none — the kit has no deployed behaviour until section 4 composes it.
      Owed by validation: none.
      `make -C kit/schema-migrations test` — 60 passed; the rest as section 3's notes
      record. End-to-end confirmed: no scenario exercises the kit until section 4.

**Section 3 notes — completed 2026-11-09.**

Suites: `make -C kit/schema-migrations test` — 60 passed; `make check-architecture` —
passed; pre-commit (every suite, `make check-packaging`, the publish-matrix tests) passed
before the fresh-context fixes. Rerun after them, every hook passed but one
change-workflow test this section does not touch and which had passed before
(`scripts/tests/test_change_clone.py::test_the_bootstrap_failed`, `ChildProcessError`
from its own `os.waitpid`); `make test-release-tooling` rerun alone — 2691 passed.

The engine semantics later sections rely on are in design.md's "Implementation record"
and D5's closeout correction. The fresh-context check fixed transaction control under
`autocommit=True`, the snapshot's blindness to `AUTOINCREMENT`, `STRICT`, `WITHOUT
ROWID` and expression indexes, the floor check and adoption running in two transactions
(a test now fails adoption midway and finds the floor records kept), docstrings
describing later consumers or delta-only headings, and one overstated test name; the
suite was not rerun after these confined fixes. Declined: a URI-form SQLite URL
(design.md). Closeout: ARCHITECTURE.md's "Kind", which lists packages with an allowlist,
and the kit-areas diagram (11.9). Outside the repository: the PyPI trusted publisher
(design.md).

## 4. Compute provisioning on the engine, as the reference service

Delivers D2, D3, D4, D5, D8, D11, and D14 for compute provisioning, and the
provisioning half of `deployment-state`'s modified "Service-owned migration history"
and added "A chain begins at its supported baseline". Touches
`provisioning/compute/service` (`db/migrate.py`, `db/database.py`, `db/migrations.py`,
the startup that calls the check, `Makefile`, its tests), the table-owning packages
whose tables provisioning's database holds — `kit/site`, `kit/resource-pools`,
`kit/fulfillment`, `provisioning/compute` (`hosts`, `jobs`, `relays`), and
`domains/vms/provisioning/adapter` — and `helm/charts/provisioning/tests/test_render.py`.

- [x] 4.1 Generate the floor fixture: from a worktree at `9fffe41e9`, start compute
      provisioning's migration on a fresh database and commit its schema, normalized by
      the method `schema_snapshot` uses, under
      `provisioning/compute/service/tests/fixtures/`, with the floor's recorded
      migration IDs beside it; the fixture's README states the command that produced it
      and that the commit is the v0.3.0 release's service code. Verify the fixture
      lists every table the floor code creates, including `kit/site`'s
      `capacity_reservations`. (D3)
      `provisioning/compute/service/tests/fixtures/v0_3_0_floor/`: `schema.json`,
      `floor_ids.json` (43 IDs, ending `20261106_001_reservation_activated_at`),
      `ddl.sql` (each object's stored DDL, the ledger's included), and a README stating
      the procedure. Differs from the plan, on the owner's direction: built from the
      release's published PyPI wheels (`arkhai-compute-provisioning-service[adapters]==0.24.0`,
      every distribution constrained to the release lock, SQLAlchemy 2.0.51 included),
      the release's `compute-provisioning-migrate` run on a fresh file with only
      `PROVISIONING_DATABASE_URL` set; the generator is not committed (both reasons in
      design.md's "Implementation record"). 23 tables, every one the floor's
      `run_migrations` creates through its eight metadata sets and its chain,
      `capacity_reservations` among them (read against `9fffe41e9`'s `db/database.py`).
- [x] 4.2 Write the baselines — one per table-owning package in provisioning's database
      (`kit/site`, `kit/resource-pools`, `kit/fulfillment`, `compute_provisioning`'s
      hosts, jobs and relays, the VM adapter, and the service's own models) — as fixed
      DDL each package exports as engine `Migration`s, composed in provisioning's
      `Chain` in foreign-key order, followed by the migrations merged after the floor
      (`20261106_002_reservation_placement_key` and the section 1 migration) moved
      onto a connection. Delete every pre-floor migration body, the `create_all` calls
      around the chain, and the per-migration test modules they leave without a
      subject. `kit/site` exports its post-floor migration once, for both
      provisioning's and the API-credit service's chains. Verify with a library
      integration test: a fresh chain's `schema_snapshot` equals the floor fixture with
      the post-floor migrations applied; a database built by the floor's chain adopts
      and then applies the post-floor migrations. (D2, D3, D4)
      Each package exports `BASELINE` from a `migrations` module:
      `market_resource_pools`, `market_site` (with `RESERVATION_PLACEMENT_KEY` and
      `MIGRATIONS`), `market_fulfillment`, `compute_provisioning.{hosts,jobs,relays}`,
      `vm_provisioning_adapter`; the service's `db/migrations.py` holds its own
      baseline, the ssh rewrite on a connection, `FLOOR_IDS`, and `CHAIN` (pools,
      relays, VM, hosts, jobs, service, fulfillment, site; then the placement key and
      the ssh rewrite). Baseline IDs are `v0_3_0_baseline_<package>`; the DDL is the
      floor's stored DDL, reformatted. Deleted: the 3,880-line pre-floor chain, the
      `create_all` calls, 25 test modules (16 integration, 9 unit) whose only subject
      was a pre-floor migration or its legacy backfill, and their helper
      `legacy_default_pool.py`; beyond the plan, VM's `legacy_backfill.py`,
      `market_fulfillment.backfill` (with its two exports) and their unit test
      `tests/unit/services/test_legacy_vm_fulfillment_backfill.py`, whose only caller
      was the deleted backfill migration. Library integration
      (`tests/integration/test_migration_chain.py`, file-backed SQLite, no
      application): the baselines alone give the fixture's snapshot; a fresh chain
      equals a database built from `ddl.sql` with the floor IDs, adopted and migrated,
      the engine reporting an adoption applying exactly the two later migrations (that
      adoption calls no baseline is section 3's test); adoption keeps rows; the chain's
      floor IDs are the fixture's; every table and column the eight metadata sets map
      exists — passed. The integration suite's `db_engine` fixture builds its schema
      with the chain; `test_scheduling_composition.py`, `test_ledger_lease_lifecycle.py`
      and `test_fulfillment_convergence.py` still build only the tables they exercise
      with `create_all`. `test_capacity_definitions_startup.py` and
      `test_definition_document_restart_safety.py` moved from `tests/unit/services/`
      to `tests/integration/`, since each runs on a real SQLite file. The API-credit
      service composes `kit/site`'s placement-key migration in 8.1. Versions:
      kit-resource-pools 0.10.0, kit-site 0.14.0, kit-fulfillment 0.8.0,
      compute-provisioning 0.27.0, vms-provisioning-adapter 0.19.0, each depending on
      `arkhai-kit-schema-migrations>=0.1.0`; the service 0.25.0 on its `[sqlalchemy]`
      extra and the new minimums.
- [x] 4.3 Replace `run_migrations` and `check_schema_version` with the engine:
      `compute-provisioning-migrate` applies the chain, reading only the database URL
      and log level, with `--check` reporting the result and exiting successfully only
      when compatible; the service's startup calls `check` and refuses any result but
      *compatible* with the engine's message, which names `compute-provisioning-migrate`
      and no nonexistent file; `make migrate` keeps running the command. Verify with
      library integration tests in `provisioning/compute/service/tests/integration/`
      (extending `test_database.py` and `test_migration_reads_no_configuration.py`):
      fresh, adopted, older-than-floor refused, behind, ahead (including both missing
      and unknown IDs), absent, rerun, `--check` exit codes, and two configurations
      giving one schema and one set of rows. (D4, D5, D8, D11, D14;
      `deployment-state` "Service-owned migration history" scenarios, "An operator
      previews an upgrade", "A v0.3.0 database is adopted", "A database older than
      v0.3.0 is refused")
      `db/database.py`: `migrate_database`, `check_database` (`check_engine`,
      read-only for a file), and `require_compatible_database` raising
      `IncompatibleDatabase` with the engine's message, which
      `app_runtime.initialise_container_resources` calls; `db/migrate.py` parses
      `--check`, prints `describe` and, when not compatible, the refusal, and exits 1
      on a refused database or a failed migration. `make migrate` unchanged. Library
      integration (`test_database.py`, rewritten; no application): each state the
      task names, refused states leaving the database unchanged and absent creating
      no file or directory; a fresh database writes no pool; tables with no ledger are
      unsupported; every startup refusal names `` `compute-provisioning-migrate` ``
      and no `migrate-job.yaml`; the placement key over v0.3.0 reservations — none
      backfilled, uniquely indexed; through `migrate.main` with the service's own
      settings loader, the `--check` and command exit codes — passed.
      `test_migration_reads_no_configuration.py`: two configurations give one schema
      and one set of rows — passed. The startup refusal
      is proven at `require_compatible_database`; no test starts the application on a
      refused database or drives a failing migration through `migrate.main` (the
      engine's failure path is section 3's; section 1's ssh test drives it through
      `migrate_database`).
- [x] 4.4 Add render assertions to `helm/charts/provisioning/tests/test_render.py`: the
      migration init container is present, runs `compute-provisioning-migrate` from the
      application's image, mounts the same data volume at the same database path, and
      precedes the application container. Verify with `make -C helm test-render`. (D8)
      `test_the_migration_runs_first_from_the_application_image_over_its_database`,
      over the defaults and mock mode with a chart-owned volume: exactly one init
      container, `provisioning-migrate`, running `["compute-provisioning-migrate"]`
      from the application's image, both mounting `data` at `/app/data` and
      `config-production.yml`, the render setting `database_url` to
      `sqlite:////app/data/provisioning.db` (anywhere in the render, not within the
      profile's document), the init containers before the containers. Chart render
      test: `make -C helm test-render` — passed; with the init container's data mount
      moved to `/app/elsewhere` it failed on the mount, and the template was restored.
- [x] 4.5 **Verification.** Run `make -C provisioning/compute/service test`,
      `make -C kit/site test`, `make -C kit/resource-pools test`,
      `make -C kit/fulfillment test`, `make -C provisioning/compute test`, the VM
      provisioning adapter's suite, `make -C helm test-render`, `make check-packaging`,
      and `scripts/change-workflow run pre-commit add-database-migration-commands`.
      End-to-end: every lane starts compute provisioning through its migration phase on
      a fresh database (`provisioning`, `provisioning_readonly`, `e2e_deal`,
      `e2e_bare_metal_mock_deal`), so the pipeline is evidence that the baselines build
      a working schema; adoption of a v0.3.0 database is proven by the library
      integration tests, and no scenario is owed for it.
      Owed by validation: none.
      Service unit 622, integration 540; `kit/site` 366; `kit/resource-pools` 141;
      `kit/fulfillment` 211; `provisioning/compute` 531; the VM provisioning adapter
      292; `make -C helm test-render` and `make check-architecture` — passed;
      pre-commit (`make lock`, `make check-packaging` and `make test`, and
      `pre-commit`'s checks) passed, and again over the final tree. End-to-end
      confirmed as the section's notes record; the pipeline has not run on this
      section.

**Section 4 notes — completed 2026-11-09.**

How the floor was produced, and why from published wheels: design.md's "Implementation
record". The release's `compute-provisioning-migrate` applied its 43 migrations; the
ledger's columns are `id` and `applied_at`. The ssh rewrite's test starts from a v0.3.0
database built from `ddl.sql`, the real upgrade path, so the rewrite runs after adoption
and the placement key; its refusal surfaces as the engine's `MigrationFailed` naming the
migration, with the host list as its cause. Tests call `migrate.main([])`.

Left for review and closeout, placed by the round's triage (32 F1): permanent
requirements whose pre-floor migrations this section deleted — `fulfillment` "Existing
lease continuity during fulfillment cutover", `physical-provisioning` "Existing host
identities migrate without loss" and "Active fulfillment migration", `site-capacity` "A
stored reservation in a retired state is converted at upgrade" and "Capacity schema
separation"'s scenario "Existing host migration" — got REMOVED and MODIFIED deltas in
`specs/fulfillment/`, `specs/site-capacity/` and `specs/physical-provisioning/`
(`site-capacity`'s "Capacity schema separation" restated under a new name, since a
MODIFIED requirement cannot drop a scenario), and the two capabilities joined the
proposal and D12. 11.9 names the Evidence lines citing deleted or moved tests
(`fulfillment`, `physical-provisioning`, `site-capacity`, `resource-pool-management`,
`deployment-state`), the architecture text describing what was removed
(`physical-provisioning/architecture.md`'s database modules, `fulfillment/architecture.md`'s
"Atomic legacy-lease cutover"), and `fulfillment`'s "Dependency boundary", which omits
the engine kit; 11.6 recounts `openspec/changes/README.md`'s anchor-form citation row,
stale after `legacy_backfill.py` and `market_fulfillment/backfill.py` were deleted.
11.9's "Migration Tests" states that a service's migration suite with no application is
library integration. A cleaner seam for `migrate.main`'s settings is in design.md.

Fresh-context check, run twice. Fixed: 4.2 and 4.3 duplicated by an edit; notes naming
the stopped session and a scratch path outside the repository; delta-only heading
citations; kit docstrings prescribing `create_all` or describing consumers the branch
lacked; the no-ledger test's missing message check; overstated notes; the orphaned
backfill modules; two real-database tests in `unit/`; RELEASING.md's internal-dependency
table (now listing the engine for the six packages); a stale backfill example in
`job_fulfillment.teardown_operation`'s docstring; Compose in the command's "Used by".
Declined: committing the floor generator, a service-level test of backfilled
fulfillment rows, and kit-level baseline tests (design.md).

End-to-end. `provisioning`, `provisioning_readonly`, `e2e_deal`, and
`e2e_bare_metal_mock_deal` run on lanes whose provisioning service starts through its
migration init container (Helm) or command (Compose) on a fresh database, so a passing
pipeline is evidence the baselines and later migrations build a schema the service runs
on. No lane holds a v0.3.0 database; no scenario is owed.

## 5. Permanent promotion

Replanned against the reviewed design: 5.2's promotion work is section 11's, and 5.3's
comment hygiene and import placement are task 10.7.

- [x] 5.1 **Withdrawn** 2026-10-14: closeout does this — 6.9 writes the architecture companion by hand, and the archive in 6.11 writes the `deployment-state` spec its delta covers. As first planned: Promote explicit command/guard/ordering requirements to `openspec/specs/deployment-state/spec.md` and rationale to `architecture.md`.

## 6. Storefront kit and core baselines, and the store-open migration

Delivers D3 and D9 for the packages beneath the storefront compositions, for
`deployment-state`'s added "A chain begins at its supported baseline" and "Opening a
store changes no schema". Touches `core/storefront` (`sqlite_client.py`,
`sqlite_migrations.py`), `kit/settlement-runtime` (`sqlite_repository.py`),
`kit/contact-exchange` (`migrations.py`), `kit/pool-overrides` (`store.py`), and
`kit/deal-servicing` (`journal.py`, `evidence.py`, `watch.py`, `respondent.py`,
`seller.py`), each moving onto the engine kit.

- [x] 6.1 Generate the storefront floor fixtures: from a worktree at `9fffe41e9`,
      construct each storefront's database client on a fresh database — VM, bare metal,
      and, for its own baseline only, API credits — without opening any store, and
      commit each normalized schema and each chain's recorded floor IDs under the
      owning storefront's `tests/fixtures/`, with a README stating the command. (D3)
      `tests/fixtures/v0_3_0_floor/` under each storefront (`schema.json`,
      `floor_ids.json`, `ddl.sql`, README). Differs from the plan as 4.1 did, on the
      owner's direction and grant: built from the published wheels
      (`arkhai-vms-storefront==0.27.0`, `arkhai-bare-metal-storefront==0.27.0`,
      `arkhai-apicredits-storefront==0.20.0`), each constrained to its lock at
      `9fffe41e9`; generators not committed. VM: 26 tables, 29 IDs; bare metal: 28
      tables, 37 IDs; API credits: 26 tables, 20 IDs. Core's tables, indexes and
      triggers are identical in all three (the `ddl.sql` files differ only in each
      domain's tables and the obligation columns VM and API credits add to
      `escrows`); no fresh floor database holds a frozen table or a store-open table.
- [x] 6.2 Write core storefront's baseline as fixed DDL reproducing the tables and
      indexes the floor constructor creates for core, and each table-owning kit's
      (settlement runtime, contact exchange, pool overrides) as its own exported
      baseline; delete `_ensure_tables_sync`'s unversioned bootstrap, the core chain's
      pre-floor migration bodies, the two-pass application, the `required_tables`
      skip, the identity and legacy context hooks (`LegacyMigrationInputs`,
      `apply_with_identity_context`, `apply_with_legacy_context`), the duck-typed
      `MigrationLike` protocol, and settlement runtime's own runner
      (`apply_migrations`), so constructing `SQLiteClient` issues no DDL. Verify with
      unit tests in each package that its baseline creates exactly its floor tables.
      (D2, D3, D4)
      Amended 2026-11-09 on the owner's direction (option 1 of the section's pause on
      size): this task delivers the baselines; the deletions it lists move to 7.5,
      since removing the constructor's bootstrap switches all three storefronts at
      once and cannot pass the pre-commit suites before section 7 declares the
      chains. Each package exports `BASELINE` (an engine `Migration` over a `sqlite3`
      connection) and `BASELINE_TABLES` from a `migrations` module:
      `core_storefront.migrations`, `market_settlement_runtime.migrations`,
      `market_contact_exchange.migrations`, `market_pool_overrides.migrations`; IDs
      `v0_3_0_baseline_<package>`. The DDL is the floor's, each later `ALTER`-added
      column written into its `CREATE TABLE` in stored order; core's `escrows` leaves
      out `obligation_ref` and `obligation_index`, which VM's and API credits' domain
      baselines add. Library integration (the plan said unit; each opens a real
      database): each package's `tests/integration/test_baseline.py` — exactly
      `BASELINE_TABLES` — passed; beyond the plan,
      `domains/bare_metal/storefront/tests/integration/test_shared_baselines.py` — the
      four baselines in chain order equal the bare-metal floor fixture (whose `escrows`
      is core's alone) restricted to those packages' tables and triggers, column for
      column with indexes, keys and trigger text — passed. Versions: settlement runtime
      0.8.0, contact exchange 0.5.0, pool overrides 0.3.0, each depending on
      `arkhai-kit-schema-migrations>=0.1.0` (in the settlement runtime's and contact
      exchange's allowlists too); core storefront stays 0.18.0. Exact pins moved:
      settlement runtime `==0.8.0` in contact exchange, arkhai-payments (0.6.2), config
      (0.5.2), core buyer (0.6.2), the bare-metal buyer (0.7.3) and the VM buyer
      (0.10.3), each patch-bumped for the pin alone; contact exchange `==0.5.0`, pool
      overrides `==0.3.0`, arkhai-payments `==0.6.2` and core buyer `==0.6.2` where
      pinned. `kit/schema-migrations` now supports Python `>=3.10` (design.md).
      RELEASING.md's internal-dependency table names the engine for the four packages,
      and the API-credit domain's installation test builds its wheel.
- [x] 6.3 Write the store-open migration's contributions: deal-servicing's tables and
      core's post-chain domain-index hook become `IF NOT EXISTS` DDL each package
      exports for composition into the one post-baseline migration each storefront
      chain carries (composed in section 7), and every `create_schema` call at store
      open is removed from `kit/deal-servicing`. Verify with a unit test in
      `kit/deal-servicing` that opening each store on a database already holding its
      tables issues no DDL, and that the migration creates them where absent and leaves
      them unchanged where present. (D3, D9)
      `market_deal_servicing.schema`: `SERVICING_SCHEMA` (every table and index the
      kit uses, the respondent poller's two included) and `create_schema(conn)`, the
      store-open migration's body; no session or poller issues DDL, `SellerSession`
      lost its `initialize` flag, the README's "Schema" section says so;
      arkhai-kit-deal-servicing 0.2.0. Core contributes no DDL: at the floor no
      storefront creates an index after its chain (D3's closeout correction). Library
      integration (`tests/integration/test_servicing_schema.py`; the plan said unit):
      the schema creates exactly its declared objects on an empty database, leaves
      present tables and rows unchanged, and completes a database holding only the
      evidence tables (built from the schema's own statements, which are the 0.1.0
      sessions' text) to a fresh one's schema; constructing each of the four sessions
      traces no DDL, changes no schema, and creates nothing (no session method is
      traced: that they issue none rests on the DDL having been removed from them);
      the poller's `repairs()` reads its table and, without it, fails creating none
      (its poll path is not run). That the schema holds every table the kit uses rests
      on the kit's 70 tests passing over it. Until 7.5, each storefront applied the
      schema when its lifecycle store opened (VM's `deal_lifecycle.py` and
      `delivery_records.py`; bare metal's `BareMetalLifecycle` gained the call, since
      its reads and watch polls would otherwise meet a missing table before the first
      deal, which `test_site_trust.py` showed); tests that plant servicing state
      without a store apply the schema first (the kit's own and
      `domains/compute/delivery/tests/conftest.py`).
- [x] 6.4 **Verification.** Run `make -C core/storefront test`,
      `make -C kit/settlement-runtime test`, `make -C kit/contact-exchange test`,
      `make -C kit/pool-overrides test`, `make -C kit/deal-servicing test`,
      `make check-architecture`, and
      `scripts/change-workflow run pre-commit add-database-migration-commands`; the
      storefront suites run in section 7, which composes these baselines.
      End-to-end: none until section 7 composes the chains.
      Owed by validation: none.
      Correction: 6.3 changes deal servicing's consumers and the bumps move pins in
      eight packages, so the storefront and consumer suites ran here too, as
      TESTING.md's boundary-change validation asks; the section's notes give every
      result. End-to-end: the storefront lanes (`e2e_deal`, `e2e_vm_payment_deal`,
      `e2e_bare_metal_mock_deal`, `e2e_bare_metal_payment_deal`) deliver deals
      through deal servicing's tables, now created at store open by the storefronts
      rather than by the sessions, so a passing pipeline is evidence those tables
      still exist when a deal reaches them; no scenario exercises the baselines.
      Owed by validation: none, confirmed.

**Section 6 notes — completed 2026-11-09.**

The first run stopped at 6.1 until the owner granted the generator one run; the section
then paused on its size, and the owner chose to commit it without the bootstrap
deletion, which moved to 7.5 (why: design.md's "Implementation record"). For 6.3, VM's
`deal_lifecycle.py` and `delivery_records.py` take `create_schema` from
`market_deal_servicing.schema` (the former's alias now `create_servicing_schema`, since
it applies the whole schema), both storefronts' `receipt_claim` call
`SellerSession(conn)`, and the bare-metal storefront requires
`arkhai-kit-settlement-runtime>=0.8.0` and declares the engine as a test dependency. The
API-credit domain's wheel-installation test (`domains/apicredits/tests/conftest_wheels.py`)
builds the engine's wheel, since core storefront and the settlement runtime require it.

Suites (before and after the fresh-context fixes): deal servicing 70; core storefront
242; settlement runtime 187; contact exchange 142; pool overrides 82; bare-metal
storefront 599 (after bare metal's store-open call fixed `test_site_trust.py`); VM
storefront unit and integration (551) passed; compute delivery 126 (after its rig, which
applied no schema, was fixed); API-credit domain 41; pre-commit passed every hook once
the installation test built the engine's wheel, and again over the fixed tree.

Fresh-context check (`make check-architecture`, `make check-comment-hygiene`, `make
check-repository`): no layering or comment-hygiene break. Fixed: VM's misleading
`create_watch_schema` alias; bare metal's settlement-runtime lower bound; baseline-test
and README docstrings claiming more than shown; 6.3's evidence claims; 6.4's consumer
suites. Declined: the bare specification pointers ending the new modules' docstrings,
and the baseline tests' integration placement (design.md).

Handoff for section 7. The chains compose `core_storefront.migrations.BASELINE`, the
settlement runtime's, then contact exchange's and pool overrides' (VM and bare metal;
API credits composes neither), then the domain's baseline, which for VM and API credits
adds `escrows.obligation_ref` and `obligation_index` with that domain's two indexes
(`idx_escrows_*`, `idx_credit_escrows_*`). The store-open migration's body is
`market_deal_servicing.create_schema` plus bare metal's `bare_metal_lifecycle_cursor`,
which a bare-metal floor database holds only if its lifecycle store ever opened. Each
fixture's `ddl.sql`, the ledger's included (`schema_migrations` with `id TEXT` and
`applied_at TEXT`), builds a v0.3.0 database for the adoption tests, as provisioning's
`floor_database.py` does. That no floor storefront creates an index after its chain
(core's `_ensure_domain_indexes` empty, VM and bare metal not overriding it, API
credits' override holding only refusal checks; `git show 9fffe41e9:` of each
`sqlite_client.py`) is D3's closeout correction.

## 7. Storefront chains

Delivers D3 and D9 for the three storefront compositions and `deployment-state`'s
"Composition-owned migration ordering", "A chain begins at its supported baseline",
"Opening a store changes no schema", and the REMOVED "Legacy storefront domain
migration is transactional". Touches `domains/vms/storefront`
(`utils/sqlite_client.py`, `utils/migrations.py`, `payment_repository.py`,
`delivery_records.py`, `domain_migration.py`, `groups/config.py`, `cli.py`),
`domains/bare_metal/storefront` (`sqlite_client.py`, `migrations.py`, `lifecycle.py`,
`lifecycle_records.py`, `runtime.py`), and `domains/apicredits/storefront`
(`utils/sqlite_client.py`, `utils/migrations.py`).

- [x] 7.1 Declare each composition's `Chain`: core's baseline, each composed kit's
      baseline, the domain's baseline (VM's settlement and delivery records; bare
      metal's tables and lifecycle cursor; API credits' `credit_deal_terms` and
      settlement and issuance tables), the store-open migration composed from section
      6's contributions with the domain's own store-open and post-chain index DDL, the
      post-floor migrations (`20261106_001`/`_002` for VM, `-0016-` for bare metal) on
      the engine, and a migration dropping the frozen tables (VM: `compute_allocations`,
      `resources`, `hosts`, `resource_transition_events`, `compute_pool_members`, and
      `compute_capacity_pools` or `compute_inventory_pools`; bare metal:
      `bare_metal_accepted_site_generations`). VM's and bare metal's chains carry their
      floor IDs; API credits' carries none, so any existing database is refused.
      Delete the domains' pre-floor migration bodies, `_ensure_domain_tables`,
      `_ensure_domain_indexes`, `_domain_migrations`, bare metal's required-column
      check, and the store-open `create_schema` calls in `delivery_records.py`,
      `lifecycle_records.py`, and `lifecycle.py`; keep API credits' unbound-listing
      refusal as a startup check run after the migration check. Verify with library
      integration tests per storefront: a fresh chain reproduces its floor fixture plus
      its later migrations; a floor database adopts; a VM floor database without
      deal-servicing tables adopts and gains them; a database missing a floor ID is
      refused; an API-credit database is refused; the frozen tables are gone after
      migration; a failing domain migration leaves startup refused, naming it. (D3, D9;
      `deployment-state` "A v0.3.0 storefront database never opened a store's
      tables", "An API-credit database is refused", "Domain migration fails")
      Each storefront's migrations module (`market_storefront.utils.migrations`,
      `arkhai_bare_metal_storefront.migrations`, `apicredits_storefront.utils.migrations`)
      holds its domain `BASELINE` (`v0_3_0_baseline_<domain>_storefront`; VM's and API
      credits' add `escrows.obligation_ref`/`obligation_index` and their two indexes),
      `CHAIN`, `FLOOR_IDS` (VM 29, bare metal 37; API credits none),
      `MIGRATION_COMMAND`, and `migrate_storefront_database(path)`. Later migrations:
      VM `20261106_001_vm_delivery_activation`, `20261106_002_vm_credentials_cleared`,
      `20261109_001_vm_store_open_tables`, `20261109_002_vm_frozen_inventory_dropped`;
      bare metal `-0016-delivery-activation`, `-0017-store-open-tables` (deal
      servicing's schema and `bare_metal_lifecycle_cursor`),
      `-0018-drop-accepted-site-generations`. The post-floor bodies carry no
      table-existence guards, and API credits has no store-open migration (design.md).
      The pre-floor bodies, the hooks, bare metal's required-column check and the
      store-open `create_schema` calls are deleted; VM's
      `add_vm_settlement_records`/`add_vm_delivery_activation` left `payment_repository`
      (the latter's body is now the chain's). API credits' unbound-listing refusal is
      `refuse_unbound_listings(db_path)`, run by the server composition after the
      migration. Differs from the plan: until section 9, each composition applied its
      chain itself before opening the database (VM's `_build_vm_services`, bare metal's
      `build_runtime_from_configuration`, the API-credit server's composition), so the
      storefronts kept starting on a fresh database in between (design.md). Library
      integration (`tests/integration/test_migration_chain.py` per storefront, no
      application): each case the task names, refusals naming the ID and the command
      with bytes unchanged — the baselines alone give the fixture's `schema.json` (API
      credits: its release fixture); a fresh and an adopted floor database (built from
      `ddl.sql` by `tests/floor_database.py`) give one snapshot and ledger, adoption
      applying exactly the later migrations and keeping rows; a floor database's
      present store-open tables are left as they are (VM: deal servicing's columns and
      indexes; bare metal: its cursor's row); tables without a ledger are refused; a
      rerun changes no byte; a failing appended migration is named by
      `MigrationFailed`, leaves no trace, and `check` reports it pending; the post-floor
      rewrites (VM phase and credentials, bare metal's dispatch marking and access
      stripping) — passed (VM 12, bare metal 11, API credits 5). "Startup
      refused, naming it" is shown at the engine's `check`, the call section 9's
      startup makes.
- [x] 7.2 Add the store-open test to each storefront: on a database its chain migrated,
      constructing the client, starting the application's composition, and opening
      every store it composes leaves `schema_snapshot` unchanged. Verify it fails when
      a `CREATE TABLE IF NOT EXISTS` is reintroduced at a store's open, and passes
      otherwise. (D5, D9; `deployment-state` "A storefront opens its stores on a
      migrated database")
      `tests/integration/test_store_open.py` per storefront, application integration:
      the real app and lifespan composed from configuration over a database the chain
      migrated — VM on `test_degraded_startup`'s configuration and seams, then a stepped
      publication cycle through the typed admin client; API credits on
      `test_alkahest_release_conditions`' fixture, whose startup tasks (the credits
      preflight and the timer loops) are replaced, so a store only a loop's step opens
      is not exercised there; bare metal on `test_app_composition`'s `_started_app`, the
      production app with its site transport replaced and its loops held — each
      reading its health through the typed client, the snapshots before and after
      equal — passed, one test each. Mutation, for VM alone: a `CREATE TABLE IF NOT
      EXISTS` in `VmDealLifecycle`'s constructor failed the test on the snapshot;
      removed, it passed.
- [x] 7.3 Remove `market-storefront migrate-storefront-domains`,
      `market_storefront.domain_migration`, and
      `domains/vms/storefront/tests/unit/test_domain_migration.py`. Verify with
      `market-storefront --help` listing no such command and the VM storefront suite
      passing. (D3; REMOVED "Legacy storefront domain migration is transactional")
      The command was `market-storefront config migrate --scope storefront-domains`
      with its four `--legacy-*` options, not a top-level `migrate-storefront-domains`:
      the scope and options are removed from `groups/config.py`, which now offers
      `settlement` and `publication` alone, and `domain_migration.py` and its test are
      deleted (`git rm`). The VM storefront suite passed (7.4); no CLI help was run.
- [x] 7.4 **Verification.** Run `make -C domains/vms/storefront test`,
      `make -C domains/bare_metal/storefront test`,
      `make -C domains/apicredits/storefront test`, `make -C core/storefront test`,
      `make check-packaging`, and
      `scripts/change-workflow run pre-commit add-database-migration-commands`.
      End-to-end: `e2e_deal`, `e2e_vm_payment_deal`, `e2e_bare_metal_mock_deal`,
      `e2e_bare_metal_payment_deal`, and `e2e_credits_deal` start each storefront on a
      fresh database built by its chain and deliver deals through the store-open
      tables, so the pipeline is evidence that the chains build a working schema;
      adoption is proven by the library integration tests, and no scenario is owed.
      Owed by validation: none.
      Final pre-commit run over the final tree (`make lock`; `make check-packaging` and
      `make test`; `pre-commit`'s checks) passed. From its suites: VM storefront unit
      1137 passed and 1 skipped, integration 550; bare-metal storefront 596; API-credit
      storefront 262; core storefront 222; settlement runtime 182; contact exchange
      141; pool overrides 82; capacity publication 135; deal servicing 70; compute
      delivery 126; API-credit domain 41. `make check-architecture` passed. The first
      run failed only on the local-imports check (nine migrate imports placed inside
      functions, moved to module level).
      End-to-end, corrected: the five lanes start each storefront on a fresh database
      its composition migrates through its chain; the VM and bare-metal lanes deliver
      deals through the store-open migration's deal-servicing tables, and the
      API-credit lane, whose chain has no store-open migration, through its baseline's
      tables. The pipeline has not run on this section: this is what a passing run
      would show. Owed by validation: none, confirmed.
- [x] 7.5 Added 2026-11-09 from 6.2 on the owner's direction, and done with 7.1 in
      one commit, since it switches all three storefronts at once. Delete what 6.2
      lists: `_ensure_tables_sync`'s unversioned bootstrap, the core chain's pre-floor
      migration bodies (`core_storefront/sqlite_migrations.py`), the two-pass
      application, the `required_tables` skip, the identity and legacy context hooks
      (`LegacyMigrationInputs`, `apply_with_identity_context`,
      `apply_with_legacy_context`), the duck-typed `MigrationLike` protocol, the
      settlement runtime's own runner (`SettlementSQLiteRepository`'s
      `apply_migrations` and `settlement_migrations`), and contact exchange's and pool
      overrides' floor-era migrations, so constructing `SQLiteClient` issues no DDL;
      then the interim store-open `create_schema` calls 6.3 left (VM's
      `deal_lifecycle.py` and `delivery_records.py`, bare metal's `BareMetalLifecycle`
      and `lifecycle_records.py`) and bare metal's cursor table creation go with 7.1's
      store-open migration. Every test that constructs a client on a fresh file
      migrates it first through its storefront's chain, or through a core-only chain
      in core's own tests — about 149 constructions in 66 test files (a search for
      `SQLiteClient(` under `tests/`) — and the tests whose subject is a deleted
      pre-floor migration are deleted (core's `test_domain_binding_migrations.py`,
      `test_rate_structure_column.py`, `test_listing_resource_migration.py`,
      `test_identity_migrations.py`; VM's reconciler and freeze tests that import
      core's migrations, judged one by one). Verify with every storefront suite,
      core's, and the kits', and with a test that constructing each storefront's
      client on a migrated database changes no schema. (D2, D3, D4, D9)
      Deleted: `_ensure_tables_sync` and the domain hooks from
      `core_storefront/sqlite_client.py`, whose constructor now takes only `db_path`
      (the principal and legacy-seller arguments served the deleted principal
      migration; the VM and API-credit `get_sqlite_client` no longer resolve the
      signer); `core_storefront/sqlite_migrations.py` whole; the settlement runtime's
      runner, its `apply_migrations`/`extra_migrations` arguments,
      `settlement_migrations`, `SettlementMigration`, the legacy-claim conversion and
      the four `SETTLEMENT_*_MIGRATION_ID` exports; `CONTACT_EXCHANGE_MIGRATIONS` and
      its IDs (the trigger and claim-table rationale moved beside the baseline's DDL);
      `pool_override_migrations`, `PoolOverrideMigration` and their IDs. No further
      bump: each distribution was already bumped on this branch. A test that builds a
      client or store on a fresh file migrates it first — `migrate_storefront_database`
      in each storefront, core's `tests/core_database.py` (core's baseline alone), the
      settlement runtime's `tests/settlement_tables.py` and each kit's `BASELINE` in the
      kits (both suites gain `tests` on their pytest path). Deleted, judged test by
      test, as having a deleted migration or legacy converter for subject: core's
      `test_listing_resource_migration.py` and `test_identity_migrations.py`; of
      `test_domain_binding_migrations.py` and `test_rate_structure_column.py`, which the
      plan named whole, only the migration tests — their live tests (binding
      immutability and conflicts, the `capacity_backing` and `closed_by` triggers, the
      backing labels, the rate-structure write) moved to a new
      `tests/integration/test_domain_bindings.py`; the settlement runtime's six
      migration tests (`test_sqlite_repository.py` keeps its four live tests, plus one
      that a repository issues no DDL); contact exchange's two migration-rerun tests
      (one replaced by a claim-once test); pool overrides' rerun test (renamed to the
      key it still asserts). VM: `test_accepted_escrows_synthesis.py` (its live
      round-trip moved to `test_publication_clause_persistence.py`),
      `test_fulfillment_context_migration.py`, `test_connection_details_migration.py`,
      `test_compute_allocations_freeze.py`, `test_inventory_freeze.py`, and inside kept
      modules the old `test_migrations.py`'s bootstrap, backfill, activation and
      credentials tests (the chain test covers the last two), two legacy-conversion
      tests in `test_negotiation_thread.py`, and the bindings-migration idempotency
      test in `test_reconciler_derivation.py`. Bare metal: `test_migrations.py` (its
      live selected-site test moved to `test_site_clients.py`);
      `test_escrow_identity_backfill.py` kept, its backfill running at startup. API
      credits: none. Moved to `tests/integration/`, since each opens a real database:
      core's `test_identity_authority.py` and `test_identity_lifecycle.py`, the
      settlement runtime's `test_jobs_and_policy.py`, and VM's rewritten
      `unit/test_migrations.py` as `integration/test_restart_persistence.py`. Results
      are 7.4's. The constructing-a-client-changes-no-schema test is 7.2's
      `test_store_open.py`, which constructs each client as its composition does.

**Section 7 notes — completed 2026-11-09.**

Handoff for section 9, done there: each composition's `migrate_storefront_database` call
becomes the startup check (`check_sqlite_file(CHAIN, path)`, refusing any result but
compatible with `refusal_message`, before anything constructs a client); the three
console scripts with `--check`, the init container and the Compose command run the
migration; tests starting an app through a composition migrate first; API credits'
`refuse_unbound_listings` stays a startup refusal after the check (D9).

Seams found while building the chains are in design.md's "Implementation record". The
VM storefront's tests are a package (`from tests.floor_database import ...`); the
bare-metal suite imports helpers by bare module name. No store-open migration creates an
index beyond deal servicing's own (D3's closeout correction).

Left for review and closeout, placed by the pre-closeout triage (56 F1): permanent
requirements that still required the storefront principal migration this section
deleted with core's pre-floor chain. `specs/storefront-publication/spec.md` REMOVES
"Storefront identity state migrates atomically"; `specs/negotiation-protocol/spec.md`
(new) REMOVES "Negotiation identity migration and recovery are deterministic" and ADDS
its recovery rule as "Negotiation recovery is deterministic";
`specs/deployment-state/spec.md` REMOVES "Identity migrations are coordinated and fail
closed" and ADDS it as "Identity cutover is coordinated and fails closed", without the
rule that each service migrates identity rows or its conflicting-owners scenario (a
MODIFIED block cannot drop a scenario, as `site-capacity`'s restatement found).
`proposal.md` lists `negotiation-protocol`, D12 names all three, and 11.9 assigns the
Evidence lines citing deleted modules (in `deployment-state`, `negotiation-protocol`,
`storefront-publication` and `settlement-servicing`), `storefront-publication/architecture.md`'s
conversion paragraph, and TESTING.md's passages on VM's transactional legacy domain
migration tests and the storefront identity-migration tests.
`add-persistent-buyer-profiles` MODIFIES the removed `deployment-state` requirement;
11.10 reconciles the two by which archives first.

Declined from the fresh-context check: moving the VM storefront's other unit modules
that open a real database to `integration/`, and refusals naming console scripts not
yet registered (design.md).

## 8. The API-credit service on the engine

Delivers D3 (swept without adoption), D5, D6, D7's Compose form, D10, D11, and D14 for
the API-credit service, and `deployment-state`'s "The API-credit service starts on a
fresh database" and "A service has no separate deployment step for migrations".
Touches `domains/apicredits/service` (`db/database.py`, `db/migrations.py`,
`container.py`, `pyproject.toml`, `Dockerfile`, `Makefile`, its tests) and
`domains/apicredits/compose.yml`.

- [x] 8.1 Replace `run_migrations` with an engine `Chain`: the service's own baseline,
      `kit/site`'s and `kit/resource-pools`'s baselines and `kit/site`'s post-floor
      migration from section 4, no floor IDs; delete the pre-floor chain, the
      `create_all` calls, `_validate_grant_schema`'s schema half if the baseline makes
      it redundant, and the in-process migration. Add the `apicredits-service-migrate`
      console script with `--check`; the container's startup calls `check`, refuses
      any result but *compatible*, then seeds the `default` pool if absent, then runs
      `_require_valid_pool_declarations`. Verify with library integration tests in
      `domains/apicredits/service/tests/integration/` (extending `test_migrations.py`):
      fresh, rerun, an existing database refused, behind, ahead, absent, the pool
      seeded at startup and never by the migration, and the startup refusal of an
      invalid pool declaration. (D3, D5, D6, D10, D14)
      The pre-floor chain's deletion takes `20261028_006_retired_reservation_states`
      and `tests/integration/test_retired_reservation_states_migration.py` with it,
      which the `site-capacity` REMOVED delta for "A stored reservation in a retired
      state is converted at upgrade" relies on (32 F1).
      `apicredits_service/db/migrations.py` is the chain alone: `CHAIN` (`the
      API-credit service`, `apicredits-service-migrate`) of `market_resource_pools`'
      baseline, the service's own (`v0_3_0_baseline_apicredits_service`: `api_keys`,
      `credit_grants`, `consumption_events`, the DDL `create_all` built for its models)
      and `market_site`'s, then `market_site.MIGRATIONS` (the placement key), no floor
      IDs. Deleted: the pre-floor chain and its runner, `check_schema_version`,
      `SchemaDriftError`, the `create_all` calls, and `_validate_grant_schema` whole —
      it checked schema only, which the exact-set check now holds. `db/database.py`
      gains `migrate_database`, `check_database`, `IncompatibleDatabase`, and
      `initialise_database`, which `container.init()` calls: the check, the `default`
      pool seeded if absent, then `_require_valid_pool_declarations`. `db/migrate.py`
      is the command in provisioning's form, registered as the console script, reading
      `database_url` and `log_level` from `settings_source.load_settings_source()`,
      which `config.py` now builds on (why: design.md). arkhai-apicredits-service
      0.8.0, requiring `arkhai-kit-schema-migrations[sqlalchemy]>=0.1.0`, kit-site
      `>=0.14.0` and kit-resource-pools `>=0.10.0`; RELEASING.md's row names the
      engine. Library integration (`tests/integration/test_migrations.py`, rewritten;
      no application): each state the task names, refused states unchanged and absent
      creating nothing — an existing database (the earlier startup's tables, old ledger
      and a key row) refused as unsupported naming `apicredits-service-migrate` and a
      fresh database; no pool written by the migration, `default` seeded once over two
      startups; the service baseline equals `create_all` of its models and every mapped
      table and column exists; tables without a ledger refused. Through the entry
      point: the `--check` and command exit codes; two configurations (log level, admin
      key, site principal, timestamp skew) give one schema, one ledger and no rows;
      with `storefront_admin_key_file` naming a missing file, which the application
      refuses to load, the command migrates; the console script loads `migrate.main`.
      Application composition
      (`test_signed_authority.py::test_the_service_refuses_to_start_on_a_database_it_has_not_migrated`,
      the real `container.init()`): an unmigrated path raises `IncompatibleDatabase`
      naming the command, builds no service, creates no file. `test_default_pool.py`
      (was `test_pool_declarations_migration.py`): startup seeds a declared `default`
      pool, a stored pool without declarations stops startup, and the projection
      carries its declarations. `test_retired_reservation_states_migration.py` deleted.
      No test starts the ASGI application on a refused database.
      `make -C domains/apicredits/service test` — 80 passed;
      `make -C domains/apicredits test-domain` — 41 passed.
- [x] 8.2 Run the command before the application: the image's command and
      `domains/apicredits/compose.yml`'s `credits-service` become
      `sh -c "apicredits-service-migrate && exec <the service's uvicorn command>"`, and
      the service's `Makefile` gains `migrate`. Verify by starting the Compose stack
      locally (`docker compose -f compose.apicredits.yml -f compose.apicredits-local.yml up -d credits-service`)
      and reading the migration's log line before the server's, and with
      `make -C domains/apicredits/service migrate` on a fresh local database. (D7, D11)
      The image's `CMD` and the Compose `command` are
      `["sh", "-c", "apicredits-service-migrate && exec uvicorn apicredits_service.main:app --host 0.0.0.0 --port 8082"]`;
      `make migrate` runs `uv run ... apicredits-service-migrate`. Differs from the
      plan: the image's builder now installs the project's own wheel
      (`uv_project.py install-wheel`, as the provisioning and storefront images do), so
      the console script exists, and the runtime stage no longer copies `src/` or sets
      `PYTHONPATH`. `make build-apicredits-service` — built. Not run, each denied in the
      session: the Compose bring-up, `make -C domains/apicredits/service migrate`, and a
      `docker run` of the image's command. The entry point and console script are 8.1's
      tests; the e2e-apicredits lane's `credits-service` start through this Compose
      command is this task's pending evidence (design.md).
- [x] 8.3 **Verification.** Run `make -C domains/apicredits/service test` and
      `scripts/change-workflow run pre-commit add-database-migration-commands`.
      End-to-end: `e2e_credits_deal` and `e2e_credits_payment_deal` start the
      API-credit service through its migration command on a fresh database.
      Owed by validation: none.
      End-to-end confirmed from the lane's files: the e2e-apicredits lane brings up
      `domains/apicredits/compose.yml`'s `credits-service`, whose command runs the
      migration on the lane's fresh volume before the server, and `e2e_credits_deal`
      and `e2e_credits_payment_deal` deal against it; the pipeline has not run on this
      section. Owed by validation: none, confirmed.

**Section 8 notes — completed 2026-11-09.**

Suites: service 80; API-credit domain 41 (before the fresh-context fixes, which touch
neither the wheel's contents nor its dependencies); pre-commit passed every hook before
the fixes and again over the final tree. The fresh-context check fixed the command's
import of `apicredits_service.config`, which read the admin-key file at import and so
required the application's secret to migrate, against D4 (now `settings_source.py`,
with a test running the command with that file missing); an overstated docstring; and
the missing `container.init()` refusal test. It declined unchecking 8.2 (design.md).

Handoff. The service's settings load in two steps: `settings_source` (the layers) and
`config` (the admin key, from its file or the storefront TOML fallback). A future command
needing only database settings uses the first.

## 9. Storefront commands, checks, and deployment surfaces

Delivers D5, D6, D7, D11, and D14 for the three storefronts, and `deployment-state`'s
"One mechanism serves every stateful service" and the modified "A deployment does not
wait on a service's dependencies". Touches each storefront's `pyproject.toml`, CLI
`serve` path and `Makefile` (`domains/vms/storefront`, `domains/bare_metal/storefront`,
`domains/apicredits/storefront`), `helm/charts/storefront` and
`helm/charts/bare-metal-storefront` (`templates/deployment.yaml`,
`tests/test_render.py`), and every Compose file that starts a storefront
(`domains/vms/compose.yml`, `domains/bare_metal/compose.yml`,
`domains/apicredits/compose.yml`, and any lane or local overlay that overrides a
storefront's `command`).

- [x] 9.1 Add `market-storefront-migrate`, `bare-metal-storefront-migrate`, and
      `apicredits-storefront-migrate`, each reading only the storefront's database path
      and log level from its configuration and applying its chain, with `--check`;
      each `serve` path calls `check` before constructing anything that opens the
      database and refuses any result but *compatible* with the engine's message.
      Verify with library integration tests per storefront: `--check` on a behind
      database lists pending IDs and exits unsuccessfully; `serve` against a behind,
      ahead, or absent database exits naming the command and creates no file; the
      command reads no configuration beyond the database path and log level (two
      configurations, one schema). (D4, D5, D6, D14)
      Each storefront's migrations module gains `check_storefront_database`
      (`check_sqlite_file`, read-only), `IncompatibleStorefrontDatabase` and
      `require_compatible_storefront_database`, which replaces the interim
      `migrate_storefront_database` call at the same point in each composition, before
      anything opens the database (VM's `_build_vm_services`, bare metal's
      `build_runtime_from_configuration`, the API-credit server's composition, whose
      `refuse_unbound_listings` now runs once the check passes). The commands
      `market_storefront.migrate`, `arkhai_bare_metal_storefront.migrate` and
      `apicredits_storefront.migrate` (`main`, provisioning's form) are console
      scripts; the storefronts' versions already carry this branch's minor bumps
      (0.28.0, 0.28.0, 0.21.0). Each reads `db_path` (VM and API credits `log_level`
      too; bare metal logs at INFO) from the layered settings without resolving them,
      refusing a configuration naming no `db_path`; VM's and API credits' Dynaconf
      construction moved to a new `settings_source.py`, which `utils/config.py` builds
      on (why: design.md). Library integration
      (`tests/integration/test_migrate_command.py` per storefront, the command through
      its entry point with its settings in the loader's environment layer and no
      configuration file, no application): the `--check` and command exit codes on
      behind (API credits, whose chain has no later migration: all but its last
      baseline), missing, migrated and ahead databases, each refusal naming the command
      and differing IDs, bytes unchanged and nothing created; two configurations, the
      second stating settings the application reads (VM and API credits: log level,
      agent name, base URL; bare metal: port and a watchdog interval its configuration
      would refuse), give one schema, ledger and rows; an empty `db_path` exits 1
      naming it; for VM and API credits a fresh interpreter importing the command
      leaves `utils.config` unimported; `require_compatible_storefront_database`
      refuses behind, ahead and missing databases likewise; the console script loads
      `main` — passed. Application integration (`test_store_open.py` per storefront, as 7.2's
      tests start it): on an unmigrated path startup raises
      `IncompatibleStorefrontDatabase` naming the command and creates no file (bare
      metal: no runtime composed) — passed. "serve against a behind or ahead database"
      is shown at the check the composition calls, not through `serve`; the absent case
      through the composition's startup. Tests that start a storefront through its
      composition migrate first: VM's `test_degraded_startup.py`,
      `test_alkahest_address_books.py`, `test_publishable_startup.py`; bare metal's
      `test_app_composition.py` (a `_migrated_configuration` helper behind
      `_configured_runtime` and `_started_app`, `migrated=False` for the refusal test)
      and `test_site_trust.py`; API credits' `test_alkahest_release_conditions.py`
      (`migrated=False` for its five tests of a startup refused before any database
      exists). Suites: VM storefront unit 1137 passed and 1 skipped, integration 562;
      bare-metal storefront 607; API-credit storefront 274.
- [x] 9.2 Add a `migrate` init container to `helm/charts/storefront` (per agent) and
      `helm/charts/bare-metal-storefront`, running the storefront's migration command
      from the application's image without `entrypoint.sh`, with the application's
      environment, configuration mounts, and data volume; change both render tests from
      "no `initContainers`" to "exactly one init container, the migration command, from
      the application's image, over the data volume", keeping the startup-probe
      assertion. Verify with `make -C helm test-render`. (D7; `deployment-state` "A
      storefront chart renders")
      Both Deployments render one `migrate` init container: the application's image and
      pull policy, `command: [market-storefront-migrate]` /
      `[bare-metal-storefront-migrate]`, the application's `env` and configuration
      mounts through the same helpers, the data volume at the persistence mount path;
      VM's carries no ZeroTier device or capabilities, which its render test asserts.
      Chart render tests: each chart's `test_no_release_waits_on_a_dependency_...`
      asserts, over every release it rendered before (VM: defaults, the local release,
      every rendering fixture, a second agent; bare metal: the example, the defaults,
      the umbrella release), exactly one init container, `migrate`, running the command
      alone, no `entrypoint.sh`, image and `env` equal to the application's, mounts
      among the application's (bare metal: equal) with the data volume at
      `/var/lib/arkhai` and `storefront.json`, the init containers first, and the
      application's startup probe. The payments-check pod tests and bare metal's
      environment and command helpers read the application container (design.md).
      `make -C helm test-render` — passed; with the VM init container's data mount
      removed it failed on that assertion, and the template was restored. A template
      comment saying registration needs "no separate init container" was reworded.
      TESTING.md's "Chart Render Tests" still says no VM storefront Deployment renders
      an init container; closeout corrects it (11.9).
- [x] 9.3 Make every Compose storefront start as
      `sh -c "<storefront>-migrate && exec <its serve command>"`, keeping
      `entrypoint.sh` for the VM storefront's serve where it starts ZeroTier, and add a
      `migrate` target to each storefront's `Makefile`. Verify by bringing up each local
      stack's storefront (`compose.vms-local.yml`, `compose.bare-metal-local.yml`,
      `compose.apicredits-local.yml` overlays) and reading the migration's log line
      before the server's. (D7, D11; `deployment-state` "A storefront under Compose has
      pending migrations")
      VM's `bob-storefront` and `alice-storefront` (`domains/vms/compose.yml`) and,
      beyond the plan's list, `compose/seller.yml`'s `seller-storefront`:
      `command: ["./entrypoint.sh", "sh", "-c", "market-storefront-migrate && exec market-storefront serve"]`,
      ZeroTier first through the image's entrypoint script. Bare metal
      (`domains/bare_metal/compose.yml`, which `compose.bare-metal.yml` extends):
      `entrypoint: ["sh", "-c", "bare-metal-storefront-migrate && exec bare-metal-storefront serve"]`
      (why `entrypoint`: design.md). API credits (`domains/apicredits/compose.yml`):
      `command: ["sh", "-c", "apicredits-storefront-migrate && exec apicredits-storefront serve --host 0.0.0.0 --port 8000"]`.
      No lane or local overlay overrides a storefront's command or entrypoint. Each
      storefront `Makefile` gains `migrate` (`uv run ... <storefront>-migrate`). The
      images' own default commands are unchanged (design.md). Not run: the local
      Compose bring-ups, denied as 8.2's was; the lanes start every storefront through
      these commands on fresh volumes (9.4), so their result is this task's pending
      evidence.
- [x] 9.4 **Verification.** Run the three storefronts' suites,
      `make -C helm test-render`, `make check-packaging`, and
      `scripts/change-workflow run pre-commit add-database-migration-commands`.
      End-to-end: every lane deploys its storefronts through the migration phase —
      `e2e_deal`, `e2e_vm_introduction`, `e2e_bare_metal_mock_deal`,
      `e2e_bare_metal_publication`, `e2e_credits_deal`, and the `storefront` smoke
      tests — and validation's Helm checks render and install both charts with their
      init containers.
      Owed by validation: none.
      End-to-end, read from the lanes' files, not yet observed: the VM, bare-metal and
      API-credit lanes start their storefronts from the domain compose files above on
      fresh volumes, so a passing pipeline is evidence the five markers ran on
      databases the storefronts' commands built, and a passing Helm part of validation
      that the installed release's storefront pods started through their init
      containers. Owed by validation: none, confirmed.

**Section 9 notes — completed 2026-11-09.**

Suites: as 9.1 and 9.2 record; pre-commit passed every hook before the fresh-context
fixes and again over the final tree. The fresh-context check fixed a no-configuration
test that ran with `utils.config` already imported (now a fresh interpreter, and the
two-configuration tests name settings the application reads); bare metal's command
reading a `log_level` its configuration does not state; an unset or empty `db_path`,
which would have migrated a file named `None` or a temporary database; stale comments in
`entrypoint.sh` and VM's `settings.toml`; the render note's unsupported ZeroTier claim
(assertion added); 11.9's omission of DEPLOYMENT_AND_CONFIG.md's render-test sentence;
9.4's end-to-end wording. Declined: a `--config` option, unchecking 9.3, and a shared
`main` helper (design.md).

Handoff. Every storefront starts only on a database its migration command built. A test
that starts a storefront through its composition migrates first, as the files 9.1 lists
do. `utils/config.py`'s `_build_settings` (VM, API credits) wraps `settings_source()`,
kept for the tests that call it.

## 10. The registry on the shared contract

Replanned on 2026-11-09 after the section returned before any task was started (its
notes below): the floor fixture's generator and its grant are named, the registry's
packaging — the Alembic scripts inside its wheel, the wheel installed in its image —
becomes its own task, and the squash, the command and check, and the deployment
surfaces are separate tasks. Old 10.1 is now 10.1 (fixture) and 10.3 (squash and
adoption); old 10.2 is 10.2 (packaging) and 10.4 (command and check); old 10.3 is 10.5;
old 10.4–10.6 are 10.6–10.8.

Delivers D1, D3, D4, D5, D6, D7, D11, and D14 for the registry, and `deployment-state`'s
"The registry refuses a database behind its head", "The registry chart renders", and the
registry's part of "A chain begins at its supported baseline". Touches `core/registry`
(`alembic/` moving to `src/core_registry/alembic/` with `env.py` and `versions/`,
`alembic.ini`, `src/core_registry/db/database.py`, `src/core_registry/main.py`, a new
migration command module and configuration-free settings loader, `pyproject.toml`,
`uv.lock`, `Dockerfile`, `Makefile`, `README.md`, its tests and a new
`tests/fixtures/v0_3_0_floor/`); `helm/charts/registry` (`templates/deployment.yaml` and
a new `tests/test_render.py`), which renders both the `registry` instance and its
`api-credits-registry` alias; and every Compose service that starts the registry image —
`registry` and `registry-b` in `domains/vms/compose.yml`, `bare-metal-registry` in
`domains/bare_metal/compose.yml`, `api-credits-registry` in `domains/apicredits/compose.yml`,
`compute-registry` in `compose.apicredits-lane.yml`, `registry` in `compose/registry.yml`
and `compose/registry.dev.yml`, and `core/registry/docker-compose.yml`.

- [x] 10.1 Generate the registry's floor fixture from the v0.3.0 release, as 4.1 and 6.1
      did: install the published `arkhai-core-registry==0.5.0` wheel in an environment
      constrained to `core/registry/uv.lock` at `9fffe41e9` (SQLAlchemy 2.0.44, Alembic
      1.17.2), place that commit's `core/registry/alembic/` where the release's
      `db/database.py` finds it (three directories above the installed package, as the
      release image did), run the release's `init_db()` on a fresh SQLite file — on a
      blank database `Base.metadata.create_all` then `stamp head` — and write
      `core/registry/tests/fixtures/v0_3_0_floor/`: the normalized schema
      (`schema_snapshot`, `schema.json`), the recorded revision (`018_listing_resource_column`),
      the DDL (`ddl.sql`), and a README stating the procedure and that the release's
      `db/`, `alembic/` and `pyproject.toml` are unchanged since `9fffe41e9`. The
      generator is not committed. Running it needs a one-run rule the implementation
      step's table does not hold: the orchestrator grants it on the owner's word before
      the section's session starts, as for 4.1 and 6.1. Verify the fixture holds every
      table the release's models declare, `alembic_version` at `018` included. (D3)
      `core/registry/tests/fixtures/v0_3_0_floor/`: `schema.json`, `floor_revision.json`
      (`"018_listing_resource_column"`), `ddl.sql`, and a README stating the procedure.
      Run once under the owner's grant, on Python 3.13 constrained to the floor lock,
      the generator first checking that the installed `db/database.py`, `db/models.py`
      and `config.py` are byte for byte `9fffe41e9`'s, then placing that commit's
      `alembic/` at the environment's `lib/python3.13/alembic` and running `init_db()`
      with only `DATABASE_URL` set in an empty directory. 7 tables: the six the models
      declare (`publishers`, `publisher_replay_reservations`, `api_keys`, `identities`,
      `publisher_identity_rotations`, `listings`), each asserted present by the
      generator, and `alembic_version` at `018`. Not committed.
- [x] 10.2 Package the Alembic scripts in the registry's wheel and install the wheel in
      its image, so the migration command 10.4 adds exists in the image (D6; the
      API-credit service's image is the precedent, 8.2): move `core/registry/alembic/`
      to `src/core_registry/alembic/` with `script_location = core_registry:alembic`
      in `alembic.ini` and in `db/database.py`'s configuration; remove `env.py`'s
      `sys.path` insertion, which assumes the source layout; make the image install the
      project's own wheel through `scripts/uv_project.py install-wheel`, stop copying
      `src/` and `alembic/` into it, keep copying the two filter specifications, and
      start `uvicorn core_registry.main:app` without `--app-dir`; bump
      `arkhai-core-registry`'s version per `docs/development/RELEASING.md`'s versioning
      policy and refresh the locks it reaches (`make lock`). Verify with a unit test
      that the installed package's `core_registry/alembic/env.py` and `versions/`
      resolve through `importlib.resources`, with `make dist` building a wheel that
      carries them, and with `make check-packaging`; the image itself is built by the
      e2e lanes. (D6, D7)
      Moved (`git mv`) to `src/core_registry/alembic/`; `alembic.ini` names
      `core_registry:alembic` and no URL; `env.py` lost its `sys.path` insertion and
      runs `fileConfig` only under the Alembic command line. The image installs the
      project's wheel (`uv_project.py install-wheel`), copies no `src/` or `alembic/`,
      and starts uvicorn without `--app-dir`. arkhai-core-registry 0.6.0 (the wheel's
      contents, a console script, and the removal of `core_registry.db`'s re-exports
      and `init_db`), requiring `arkhai-kit-schema-migrations>=0.1.0`; RELEASING.md's
      row names it; `make lock PROJECTS=core/registry` refreshed the lock (no other
      project pins the registry). Outside the plan: `filter-spec.yaml` moved into the
      package (`src/core_registry/filter-spec.yaml`, resolved beside the code; why:
      design.md), the image still copying it to `/app/filter-spec.yaml`, which the
      chart names, and the paths citing it moved with it (`helm/scripts/test-render.sh`,
      two registry tests, and the active changes `discover-open-ended-compute-listings`
      and `store-registry-listings-as-published`). Unit
      (`tests/unit/test_migration_states.py::test_the_packaged_script_holds_the_environment_and_the_baseline`):
      `files("core_registry") / "alembic"` holds `env.py`, `script.py.mako` and the
      baseline, the script's revisions the baseline alone — passed. The wheel `make
      dist` built (`.dist/arkhai_core_registry-0.6.0-py3-none-any.whl`, listed with
      `unzip -l`) carries `core_registry/alembic/{env.py,script.py.mako,versions/v0_3_0_baseline.py}`,
      `core_registry/filter-spec.yaml`, and an `entry_points.txt`; the console-script
      entry point resolves to `migrate.main` (10.4's test). `make check-packaging`: in
      the section's pre-commit run.
- [x] 10.3 Squash the eighteen revisions into one baseline revision, written in Alembic
      operations, whose ID fits `alembic_version`'s 32 characters, reproducing 10.1's
      fixture; adopt a database whose `alembic_version` is `018_listing_resource_column`
      by rewriting it to the baseline in one transaction before upgrading, since
      Alembic cannot locate the deleted revision; refuse a database at any other
      unknown revision as ahead and one with tables but no `alembic_version` as
      unsupported. Delete the old revisions, the blank-database `create_all` +
      `stamp head`, the legacy-revision detection (`_legacy_revision`), and the tests
      of what they did (`tests/unit/test_principal_migrations.py`, and
      `tests/unit/test_database.py`'s mocked stamp-and-upgrade cases). Verify with
      library integration tests in `core/registry/tests/integration/`: a blank
      database migrated through the chain has a `schema_snapshot` equal to the fixture;
      a database built as 10.1 built the floor adopts, records the baseline, and keeps
      its rows; a database at an earlier pre-floor revision, or with tables and no
      `alembic_version`, is refused as unsupported and left unchanged. (D3;
      `deployment-state` "A v0.3.0 database is adopted", "A database older than v0.3.0
      is refused")
      `versions/v0_3_0_baseline.py`, revision `v0_3_0_baseline`: fixed Alembic
      operations in the floor's table and index order, `DateTime(timezone=True)` and the
      `liststatusenum` enum as the models declare them (on SQLite, `DATETIME` and
      `VARCHAR(7)`), the partial unique index for both dialects; its downgrade raises.
      Deleted (`git rm`): the eighteen revisions, `_legacy_revision`, the blank-database
      `create_all` + `stamp head`, `init_db`, `tests/unit/test_principal_migrations.py`
      and `tests/unit/test_database.py`, whose one test of a live rule, a second
      primary identity refused, moved to `test_migrations.py` (10.4). Adoption and
      `PRE_FLOOR_REVISIONS` (the seventeen squashed revisions) are in
      `core_registry.db.migrations` (10.4; how and why: design.md). Library integration
      (`tests/integration/test_migrations.py`, file-backed SQLite through
      `migrate_database`, no application): a blank database's `schema_snapshot` equals
      `schema.json` and records the baseline; a database built from `ddl.sql` at `018`
      holding a publisher and a listing is behind with adoption pending, then adopted
      with nothing run, records the baseline, keeps both rows, and has the fixture's
      snapshot; `014_…` and `017_…` refused as unsupported, an unknown revision as ahead
      naming it, tables with no `alembic_version` as unsupported — each through
      `MigrationRefused`, bytes unchanged; `016_…` refused naming `017_…`, the floor
      and a fresh database; a rerun applies nothing, bytes unchanged — passed.
- [x] 10.4 Add the `registry-migrate` console script with `--check`, and replace
      `init_db()`'s in-process migration at startup with a read-only check. Both map the
      registry's Alembic state onto the engine kit's `CheckResult` — at the script head
      *compatible*, at a known earlier revision or the floor *behind* with the pending
      revisions or the adoption, at an unknown revision *ahead*, tables without
      `alembic_version` *unsupported*, no file or no tables *absent* — and render
      refusals with its `refusal_message` naming `registry-migrate`; the check opens
      the database read-only and creates no file. The command and `env.py` resolve only
      the database URL and log level, through a loader that reads those two settings
      from the resolved profile files and nothing else, as the storefronts'
      `settings_source.py` do (D4). `make migrate` runs the command. Test fixtures that
      start the application migrate their database through the command's function
      first; fixtures that build ORM tables for route tests without the application's
      lifespan are left as they are. Verify with library integration tests: startup
      refuses each of behind, ahead, absent and unsupported in the shared message
      form, mutating nothing and creating no file; `--check` exits successfully only
      when compatible and lists the differing revisions; a rerun changes nothing; the
      command runs with no credential file and no keys in its profile. (D4, D5, D6, D11,
      D14; `deployment-state` "The registry refuses a database behind its head", "An
      operator previews an upgrade")
      `core_registry/db/migrations.py`: `classify` (tables and recorded revision onto
      `CheckResult`), `check_database` (a SQLite file through `connect_read_only`, any
      other URL through a SQLAlchemy connection that only reads),
      `require_compatible_database` raising `IncompatibleDatabase` with
      `refusal_message`, and `migrate_database` (refuses ahead and unsupported, adopts,
      upgrades through Alembic one revision at a time on the command's own connection,
      which `env.py` takes from the configuration's `connection` attribute).
      `core_registry/migrate.py` is `registry-migrate` (provisioning's form; the URL is
      logged with its password hidden), registered as the console script.
      `core_registry/settings_source.py` holds the default dotenv files and profile
      resolution, which `config.py` builds on, and `DatabaseSettings`/`load_database_settings`
      (`DATABASE_URL` and `LOG_LEVEL` alone), which `env.py` uses when no connection is
      handed in; `core_registry.db`'s `__init__` no longer imports `db.database`
      (design.md). The lifespan calls `require_compatible_database` first. `make migrate`
      runs the command. No test fixture starts the lifespan — the integration tests
      drive routes over `ASGITransport` and `TestClient` without it — so none needed
      migrating. Unit (`test_migration_states.py`: every state, each refusal naming
      `` `registry-migrate` ``, a behind refusal naming its revision and the head it
      lacks; `test_database_settings.py`: the two settings follow the profiles, even
      under a profile the application's loader refuses) — passed. Library integration
      (`test_migrations.py`): the startup check refuses each state the task names (behind
      being the floor), naming the command, unchanged, absent creating nothing; through
      `migrate.main` with `DATABASE_URL` alone and no files, the `--check` and command
      exit codes on floor, missing, migrated and ahead databases; a profile naming a
      missing credential file and an invalid boolean migrates; a fresh
      interpreter importing the command loads neither `core_registry.config` nor
      `core_registry.db.database`; the console-script entry point resolves to
      `migrate.main`; a migrated database refuses a second primary identity for one
      publisher (the test `tests/unit/test_database.py` held) — passed.
      `test_migrations.py::test_the_application_refuses_to_start_on_an_unmigrated_database`
      (the lifespan entered directly, its settings object's URL replaced, no request
      served; not application integration): an absent database raises
      `IncompatibleDatabase` naming the command and creates nothing — passed. Behind at
      a known earlier revision is shown only by the unit test, since the script holds
      the baseline alone; the floor's refusal named the floor and the adoption, not the
      head, as the in-house engine's adoption refusal did.
      Correction (49 F2): both refusals now name the baseline adoption records as well
      as the floor (the section's round-2 notes).
- [x] 10.5 Add the registry chart's `migrate` init container — the application's image,
      `registry-migrate`, the configuration profile mounts, the resolver variables, and
      the data volume at the database path — and `helm/charts/registry/tests/test_render.py`
      asserting, for both the `registry` instance and its `api-credits-registry` alias,
      exactly one init container, the migration command, from the application's image,
      over the data volume, and nothing rendered for a disabled instance. Make every
      Compose registry service named above start as
      `sh -c "registry-migrate && exec uvicorn core_registry.main:app --host 0.0.0.0 --port 8080"`,
      and the image's own command the same. Verify with `make -C helm test-render`,
      including one assertion seen failing with the init container's data mount
      removed; the Compose start is evidenced by the e2e lanes, which start every
      registry through it on fresh volumes. (D7; `deployment-state` "The registry chart
      renders", "A service has no separate deployment step for migrations")
      The Deployment renders one init container, `migrate`: the application's image and
      pull policy, `command: ["registry-migrate"]`, the resolver variables and profile
      mounts through two new helpers the application container uses too
      (`registry.resolverEnv`, `registry.profileMounts`, the secret profile included,
      since it may state the URL), and the data volume at the persistence mount path; it
      mounts no signer credential. The application container states its own command,
      `uvicorn core_registry.main:app --host 0.0.0.0 --port <service.port>` (design.md).
      Chart render test (`helm/charts/registry/tests/test_render.py`, run by
      `test-render.sh`'s chart loop): over the defaults, with persistence disabled, and
      with another mount path, exactly one init container before the containers,
      running `registry-migrate` alone, image, pull policy and `env` equal to the
      application's, its mounts the application's but the credential, the data volume
      at the application's path, and the application's command naming no migration;
      with a secret profile, the init container mounts it and lists it; in the umbrella
      with the alias enabled, `registry` and `api-credits-registry` render the same, and
      with it disabled nothing of the alias renders — passed (`make -C helm
      test-render`). With the init container's data mount removed it failed on that
      assertion, and the template was restored. `helm/tests/test_release_topology.py`'s
      `_resolver_environment` reads the application container's `env`. Compose: every
      service named above, and the image's `CMD`, state
      `["sh", "-c", "registry-migrate && exec uvicorn core_registry.main:app --host 0.0.0.0 --port 8080"]`.
      No Compose bring-up was run; the lanes' result was this task's pending evidence,
      which validation 37 supplied (the section's round-2 notes).
- [x] 10.6 Find every file the change added or touched that names a removed command,
      module, migration ID, or frozen table — tests, fixtures, scripts, Makefiles,
      e2e helpers, documentation outside the closeout's promotion list — and update or
      remove each reference. Verify with a repository search for
      `migrate-storefront-domains`, `run_migrations`, `check_schema_version`,
      `apply_schema_migrations`, `_ensure_tables_sync`, and `required_tables` returning
      only what the change intends to keep. (D3; repository obligation:
      `AGENTS.md` "Cross-references must resolve")
      Searched (`git grep`; archive, this change and locks excluded) for those six
      names, the registry's removed `init_db`, `_legacy_revision`, `core/registry/alembic`
      and `--app-dir`, the names sections 6–9 removed (the context hooks,
      `MigrationLike`, the kits' migration lists and IDs, `SchemaDriftError`,
      `_validate_grant_schema`, the domain hooks, `domain_migration`, the backfill
      modules, `migrate-job.yaml`, `sqlite_migrations`), and `alembic` outside the
      registry. Kept: Alembic's own `run_migrations` in `env.py`; the
      `settlement_migrations` and `pool_override_migrations` import aliases of the live
      `migrations` modules; provisioning's test asserting `migrate-job.yaml` is absent;
      `docs/attachments/`, which record past runs; DEPLOYMENT_AND_CONFIG.md's
      `migrate-storefront-domains` paragraph and the permanent `Evidence` lines 11.9
      names, plus `settlement-servicing/spec.md`'s `sqlite_migrations` citation;
      `openspec/changes/README.md`'s anchor-form row (11.6); and other active changes'
      own documents (`hollow-pre-floor-provisioning-migrations`, which closeout removes,
      `multi-domain-storefront-composition`, which D13 reconciles,
      `relay-vm-access-without-a-dashboard`, `kit-owned-storefront-auth-and-persistence`,
      `storefront-domain-parameterization`). No test, fixture, script, Makefile or e2e
      helper names a removed command, module, migration ID or frozen table. The deleted
      registry tests are cited by `deployment-state/spec.md`'s "registry Alembic tests"
      (11.9) and `registry-discovery/spec.md`'s `test_principal_migrations.py` (placed
      by 49 F1).
- [x] 10.7 **Comment hygiene and import placement, before the pre-closeout review.** Run
      `make check-comment-hygiene` and read the comments this change added for any that
      narrate the review or migration that introduced them; move each import the change
      added to module level unless a verified circular import or a recorded lazy-load
      reason keeps it local. Closeout only confirms both. (Repository obligation:
      `openspec/README.md#plan-closeout-requirements`, parts 1–2)
      `make check-comment-hygiene` — passed; `make check-repository` (history wording and
      local imports among its checks) — passed once one docstring saying the script "no
      longer" holds the floor was restated. Read the comment and docstring lines the
      change adds since `7091c186c`, filtered for history words (now, no longer, moved,
      formerly, previously, replaced, legacy, interim, review, section); the hits
      describe current behaviour. Section 10 adds no function-local import; the one kept
      local in the change is `capacity_client.py`'s, for a circular import.
- [x] 10.8 **Verification.** Run `make -C core/registry test` (unit and library
      integration), `make -C helm test-render`, `make check-packaging`, and
      `scripts/change-workflow run pre-commit add-database-migration-commands`.
      End-to-end: `registry`, `multi_registry`, `e2e_deal`, `e2e_bare_metal_mock_deal`,
      and `e2e_credits_deal` build the registry image from its wheel and start every
      registry through `registry-migrate` on a fresh volume, so a passing pipeline is
      evidence for 10.2's packaging and 10.5's Compose form; validation's Helm checks
      install the registry chart with its init container. Adoption is proven by 10.3's
      library integration tests, and no scenario is owed.
      Owed by validation: none.
      `make -C core/registry test` — unit 137 passed, integration 148 passed;
      `make -C helm test-render` — passed; pre-commit in the section's notes.
      End-to-end, read from the markers and the lanes' files, not observed at the time:
      the five markers run on lanes whose registries start from this image through the
      Compose commands above (or, under Helm, the init container) on fresh volumes, so
      a passing pipeline is evidence the image carries `registry-migrate` and the
      packaged scripts, and that a fresh registry migrates and starts. Owed by
      validation: none, confirmed.

**Section 10 notes — completed 2026-11-09.**

Suites: the final pre-commit run, over the tree with the fresh-context fixes, passed
every hook (`make lock`; `make check-packaging` and `make test`, the registry chart's
render checks and the topology test's registry loader probe among them; `pre-commit`'s
checks); the first run failed `pre-commit` on history wording alone.

Fresh-context check. Fixed: the one-primary-identity test lost with
`tests/unit/test_database.py`, restored on a migrated database; a comment overstating
the floor's refusal; a failed upgrade naming every pending revision (now one revision
at a time, naming the one that failed); the adoption race's bare `RuntimeError` (now
`MigrationFailed`); the README's standalone run and `make serve` starting on an
unmigrated database (the README runs `registry-migrate` first); test docstrings and a
name claiming an installed wheel and executable they do not exercise (the wheel's
contents rest on 10.2's `unzip -l`); the rendered profile read only by the application's
loader (`test_release_topology.py`'s registry probe, run where `REGISTRY_PYTHON` is set,
now reads it with `load_database_settings` and asserts the migration finds the
application's database); 10.6's search of deleted test names; 11.9's TESTING.md and
`deployment-state` Evidence lines. Declined: an injected seam for the lifespan test, and
a heading anchor in the baseline's docstring pointer (design.md).

Left for review and closeout: `registry-discovery` still stated the deleted
`016_marketplace_principal_auth`'s migration (`spec.md`'s "Publisher identity migration
preserves ownership", the legacy clause of "Stable publisher-chosen listing identity",
an Evidence line citing `core/registry/tests/unit/test_principal_migrations.py`, and
`architecture.md`'s "Atomic legacy identity migration"); placed by 49 F1 below.

Handoff. A later registry change adds a revision with `down_revision = "v0_3_0_baseline"`,
which `classify` then reports pending on an older database; the script must keep one
head. SQLite DDL under Alembic is not transactional (design.md).

**Round-2 triage fixes, 2026-11-09** (reviews 49, validation 37 at `6ec41c9fc`, which
passed, its lanes the pending evidence 10.2 and 10.5 named: every lane built the
registry image from its wheel and started each Compose registry through
`registry-migrate`).

- 49 F1, placed as 32 F1 placed section 4's: `specs/registry-discovery/spec.md` (new)
  REMOVES "Publisher identity migration preserves ownership" and MODIFIES "Stable
  publisher-chosen listing identity" to keep only rotation's preservation of
  identifiers; `proposal.md` lists `registry-discovery`, D12 names the removal, and 11.9
  assigns the Evidence line and the architecture section. Strict validation passes.
- 49 F2: the floor's refusal and `--check` now name both revisions. The engine kit's
  `CheckResult` carries `adopting`, the baseline IDs adoption records unrun, in place of
  its `adoption_pending` flag, which is now derived from it; `describe` and the behind
  refusal name them ("its supported baseline is to be adopted (recording
  v0_3_0_baseline)"; `--check`: "supported baseline to be adopted: v0_3_0_baseline").
  The registry's `classify` sets its baseline, the in-house engine its chain's
  baselines. This corrects 10.4's note that the floor's refusal does not name the head.
  Unit (`kit/schema-migrations/tests/unit/test_refusal_message.py`: the baselines named,
  and an adoption with nothing after it naming both revisions and nothing pending;
  `test_classification.py`; `core/registry/tests/unit/test_migration_states.py`:
  `adopting == ("v0_3_0_baseline",)`); library integration
  (`kit/schema-migrations/tests/integration/test_sqlite_engine.py`;
  `core/registry/tests/integration/test_migrations.py`: the startup refusal names
  `018_listing_resource_column` and `v0_3_0_baseline`, `--check` prints the baseline);
  service integration (`provisioning/compute/service/tests/integration/test_database.py`:
  the refusal names every baseline ID). `make -C kit/schema-migrations test` — 61 passed;
  pre-commit passed every hook (registry unit 137, integration 148); no lock changed.
  Fresh-context check: no defect; two wordings it declined are in design.md. Left to 11.3:
  `registry-discovery/architecture.md`'s line that credential independence lets "key
  rotation and schema migration" preserve discovery URLs, which still reads true of any
  migration.

**The return to planning, 2026-11-09, on the owner's direction.** Nothing of section 10
was implemented and no task was checked. What was found before starting — the published
registry wheel carries no Alembic scripts, the image serves copied source, and the floor
generator needs the owner's grant — and how the replan answered it are in design.md's
"Implementation record".

## 11. Closeout

Per `openspec/README.md#plan-closeout-requirements`.

- [x] 11.1 **Comment hygiene — confirm.** Run `make check-comment-hygiene`, read the
      comments this change added for any that narrate the review or migration that
      introduced them, and confirm no production source references
      `openspec/changes/add-database-migration-commands` or the floor commit as
      provenance rather than as the fixtures' stated source. Do not edit code here:
      anything to rewrite returns the change to implementation.
      Confirmed: `make check-comment-hygiene` — both scans OK. The added lines of
      `git diff origin/dev HEAD` over `.py`, `.toml`, `.yml`, `.yaml`, shell and
      Dockerfiles, searched for `openspec/changes`, `9fffe41e9` and history wording
      (no longer, formerly, previously, interim, triage, review round, now): no
      reference to the change or the floor commit; the "now" hits are SQL `'now'`
      defaults and settings "read now" docstrings describing current behaviour.
      The pre-closeout review found no comment finding either.
- [x] 11.2 **Import placement — confirm.** Check the imports this change added for any
      still local without a recorded reason. One that should move returns the change to
      implementation.
      Confirmed: `make check-local-imports CHANGE_BASE=origin/dev` — every import the
      change adds inside a function gives its reason; the one kept local,
      `apicredits_storefront/services/capacity_client.py`'s import of the
      publication service, names the circular import that keeps it there.
- [x] 11.3 **Documentation compliance.** Re-check D1–D16 against `openspec/README.md`'s
      placement rules and the permanent documents against the code they describe: the
      mechanism's normative rules in `deployment-state/spec.md`, its rationale in
      `deployment-state/architecture.md`, its operator guidance in
      `DEPLOYMENT_AND_CONFIG.md` and `docs/operator-handbook.md`, and no repository-wide
      principle claimed in `ARCHITECTURE.md` beyond the Terms entry and the kit's place.
      In progress. D1–D16 sit where `openspec/README.md#documentation-placement` puts
      them (the proposal's "Knowledge to promote"), and `ARCHITECTURE.md` gains only the
      Terms entries, the kit's place, and the sweep after convergence. Corrected in
      `design.md` ("Correction at closeout"): D3's post-chain domain indexes, which the
      floor never built, and D5's *absent*, which the engine draws narrower.
      `registry-discovery/architecture.md`'s "key rotation and schema migration preserve
      discovery URLs" is kept, true of any migration. Found and put to the owner:
      fifteen places in seven capabilities' permanent requirements still described a
      pre-floor migration this change deleted, with no delta covering them. The owner
      chose to carry the twelve clear ones as deltas under D12's rule and leave the
      borderline four (vm-storefront-fulfillment's and api-credits' fresh-schema
      scenarios, test-compatibility's word "migration", fulfillment's "Begin
      fulfillment" rationale), whose rules still hold. Placed: `resource-pool-management`
      (new delta: four requirements restated under new names, the old removed),
      `site-capacity` (three restated), `physical-provisioning` (three restated; "A
      bare-metal storefront refuses state written under a retired listing kind"
      removed), `storefront-publication` ("Storefront holds no physical-resource
      authority" restated as "… or inventory", the retired tables dropped by the VM
      chain); no open change's delta names any of the twelve; `proposal.md` and D12
      record them. Strict validation passes.
- [x] 11.4 **Narrative compression.** Compress completed-task notes to final behavior,
      material validation evidence, unresolved or deferred work, and
      permanent-documentation destinations, moving durable rationale into `design.md`
      first.
      Sections 1–10's notes compressed (the file from 2284 to 1788 lines); task
      statements, `Owed by validation:` lines and corrections kept. Alternatives,
      debugging findings, declined review items and known limits moved first into
      `design.md`'s new "Implementation record", by topic: the floor fixtures, the
      engine, chains and adoption, the `ssh` repair, retiring registry listings, the
      storefront cutover's sequencing, the migration commands, the deployment
      surfaces, the registry on Alembic, and test placement. Two correction notes
      were added where later notes corrected a task (10.4 for 49 F2; 10.5 for the
      lane evidence validation 37 supplied).
- [x] 11.5 **Roadmap currency.** In `docs/development/ROADMAP.md`, close the deferral
      "Dropping the frozen tables … belongs to a later follow-up" (it is done); add to
      Goal 1's open-gap table the unowned row D15a records — a teardown that failed
      before its executor ran (as on a version-1 host) is resolved only by an
      operator's manual teardown and force-release, since its job identity is fixed per
      reservation and retry-release re-observes the failed job; re-running such a
      teardown under a new job identity would change the one-teardown-one-job rule —
      owned "Unowned — needs a new change", with background in
      `openspec/specs/physical-provisioning/architecture.md`, "Proof-driven release";
      and record that no other gap row is affected: the change sits under the
      "Registry productionization" lesser goal, which has no roadmap goal. (D15a)
      Done: Goal 1's frozen-table deferral paragraph removed and its current state
      restated (the VM storefront's database holds neither `compute_allocations` nor
      the retired inventory tables, dropped from an adopted one by the migration
      after the baseline); the unowned failed-teardown row added to Goal 1's gaps,
      linking the operator handbook's procedure and "Proof-driven release". No other
      goal or gap row is affected: the change sits under the "Registry
      productionization" lesser goal, which has no roadmap goal.
- [x] 11.6 **Campaign index currency.** In `openspec/changes/README.md`: update this
      change's row; remove `hollow-pre-floor-provisioning-migrations`'s directory and
      row, since this change supersedes it, and reconcile the campaign graph line that
      names it; note in `migrate-registry-to-postgres`'s row that its command, guard and
      blank-database baseline landed here; leave other rows' `Depends on` alone. Amend
      `openspec/changes/migrate-registry-to-postgres/proposal.md` to drop "Repair
      Alembic so blank … databases reach the complete current registry schema" and "Add
      a packaged registry migration command and read-only runtime schema guard", stating
      that both landed here. Recount the unowned row on anchor-form spec citations
      that omit the `requirement-` prefix: section 4 deleted
      `vm_provisioning_adapter/legacy_backfill.py` and `market_fulfillment/backfill.py`,
      so its count of thirteen and its list of files are stale (32 F1). Run
      `make check-change-index`.
      Done: this row `in closeout`, its notes rewritten for closeout. The superseded
      change's row and graph line removed; its directory could not be deleted (no
      rule allows `git rm` or `rm` in the closeout step), so it was archived as
      superseded through `scripts/change-workflow openspec archive
      hollow-pre-floor-provisioning-migrations --skip-specs -y`, to
      `archive/2026-11-09-hollow-pre-floor-provisioning-migrations/`, the index's
      precedent for superseded proposals, and "Archived and superseded" says so.
      `migrate-registry-to-postgres`'s row notes what landed here, and its proposal
      drops the two items and says what it builds on. The anchor-form citation row
      recounted: ten citations, in `market_core/envelopes.py`, `kit/site`'s ledger, and
      seven `kit/fulfillment` modules. 11.10's reconciliations recorded in
      `multi-domain-storefront-composition`'s and `add-persistent-buyer-profiles`'
      rows, and the D16 sweep's two overlapping MODIFIED requirements in
      `add-persistent-buyer-profiles`' and `bare-metal-and-credits-domain-stacks`'
      rows. No other row's `Depends on` or status changed; the campaign graph is
      unchanged. `scripts/change-workflow check index` — OK.
- [x] 11.7 **Packaging.** Run `make check-packaging` and resolve every failure it
      reports (a failure needing a code or lock change returns the change to
      implementation), then `make check-architecture-change CHANGE=add-database-migration-commands`.
      `scripts/change-workflow run pre-archive add-database-migration-commands` at
      `0b93401a4` — `make check-packaging` (installs derived from locks, locks
      current, one Python version, one project layout, the layer, scope,
      dependency and kind rules) and `make check-architecture-change` ("owns no
      architecture row") — "passed, exit 0". The skills check runs in `run
      pre-commit`'s defaults.
- [x] 11.8 **End-to-end pipeline.** Record the passing run the latest validation names,
      its result, and the scenarios that exercise this change — every lane's services
      starting through their migration phase (`e2e_deal`, `e2e_vm_payment_deal`,
      `e2e_bare_metal_mock_deal`, `e2e_bare_metal_publication`, `e2e_credits_deal`,
      `multi_registry`, `registry`, `provisioning`, `storefront`) — or an explicit
      blocker naming its cause and the change that owns it, with the validations it
      gates treated as unrun.
      Validation 57 passed at `0b93401a4`, the merge of `origin/dev` after the
      pre-closeout triage, which is the commit closeout's documentation commit
      builds on: pipeline run 42693134626 (e2e.yml at HEAD) succeeded — e2e-bare-metal
      98 passed, e2e-vm 185 passed and 2 skipped, e2e-apicredits 4 passed, the native
      Ansible gate passed; local (`check-packaging`, `test`) passed; Helm passed
      (build, render, deploy, five rollouts, `helm test`, the payments check). Every
      lane starts each service through its migration phase on a fresh database —
      Compose's `<service>-migrate && exec …` commands, the charts' init containers
      under Helm — so the scenarios above passing show each chain builds a schema its
      service runs on and each image carries its command; no scenario exercises a
      migration command directly or holds a v0.3.0 database, so adoption rests on the
      library integration suites. CI: none owed; no section owed validation
      ("Owed by validation: none" throughout). Closeout changes no code, so the run
      describes the code the closeout commit carries.
- [x] 11.9 **Promotion.** Write the permanent documents this change owes and complete
      the design-promotion record in `design.md`, mapping every decision to its exact
      heading:
      - `openspec/specs/deployment-state/architecture.md`: "Migration and
        initialization boundary" rewritten for one mechanism, the baseline and
        adoption, the exact-set check, and the store-open migration (D1–D5, D9, D14);
        "Bare-metal seller artifact" and "Multi-domain storefront activation" corrected
        where they describe migrating at construction or the legacy domain migration
        (D3); "Current limits" without the "not yet uniform" caveat (D1).
      - `docs/development/DEPLOYMENT_AND_CONFIG.md`: "Migrations at startup" rewritten
        as the mechanism's guidance — commands, `--check`, the init container and
        Compose form, the floor and adoption, configuration-free migration, and the
        upgrade notes for individual old migrations and frozen tables removed (D2–D8,
        D14, D16); "Kubernetes: ConfigMap and Secret mounting" — the init-container
        sentence, and the sentence that render tests assert no init container
        renders for a storefront (D7; the second added 2026-11-09 by section 9); "Combined compute-family storefront" — the
        `migrate-storefront-domains` paragraph removed (D3); "Current limits" (D1).
      - `docs/operator-handbook.md`: a new "## Upgrading a deployment" — backup,
        `--check`, deploy, the refusal of a pre-v0.3.0 or any existing API-credit
        database, rollback by backup, the `ssh` connection repair and required version,
        the recovery of a lease already `release_failed` on a version-1 host (find it
        through release-oversight, read its teardown job's error, remove from the host
        what the domain's teardown would have removed, then force-release with a reason
        and evidence; a failed create's lease after the host check alone), and option
        IDs not stable across an envelope change (D3, D14, D15).
      - `docs/seller-quickstart.md`: "Upgrading from CSV inventory" removed (D3).
      - `docs/development/ARCHITECTURE.md`: "Terms" gains *role* and *service* (D16);
        "Build, packaging, and initialization" restates its fresh-database sentence
        against the baseline (D3); "Kit areas" names the migration kit among the
        foundation capabilities (D2); "Capacity publication and multi-domain
        storefront composition", which says every publication pass ends with
        registry convergence, gains the sweep that follows it (D15b; added
        2026-11-09 by section 2); "Kind" lists the migration kit among the packages
        with a package allowlist, and `docs/development/diagrams/kit-areas.drawio` and
        its `.svg` draw it in the foundation band (D2; added 2026-11-09 by section 3).
      - `docs/development/TESTING.md`: a "## Migration Tests" section — the floor
        fixture, adoption, the store-open test, and the per-service integration suite
        (D5, D9); "Chart Render Tests" stating that each storefront chart renders one
        init container, its migration, where it now says the VM chart renders none
        (D7; added 2026-11-09 by section 9), and listing the registry chart's render
        test, `helm/charts/registry/tests/test_render.py`, its init container over both
        instances (D7; added 2026-11-09 by section 10).
      - `openspec/specs/deployment-state/spec.md`'s "Evidence", which the archive does
        not write: "registry Alembic tests" becomes
        `core/registry/tests/integration/test_migrations.py` and
        `core/registry/tests/unit/test_migration_states.py`, and the registry chart's
        render test joins the chart evidence (added 2026-11-09 by section 10).
      - `docs/development/RELEASING.md`: "Cutting a release" gains the step of weighing
        a new migration floor when an official release is promoted (D16).
      - `openspec/specs/physical-provisioning/architecture.md`: "The host registry owns
        the connection" — rewriting a host's connection by a recorded exact migration,
        jobs reading their host's at dispatch, and the required version (D15a);
        "Proof-driven release" is unchanged, already stating that a failed teardown
        waits for an operator's verification and force-release.
      - `openspec/specs/storefront-publication/architecture.md`: "Registry convergence"
        — the sweep beside the convergence repair (D15b); and
        `openspec/specs/storefront-publication/spec.md`'s "Evidence", which the
        archive does not write, gains the sweep's tests section 2 names (added
        2026-11-09 by section 2).
      - The specifications whose pre-floor migrations section 4 deleted (32 F1): the
        "Evidence" lists, which the archive does not write, lose or correct every
        line citing a test section 4 deleted or moved — `fulfillment/spec.md`'s three
        legacy-backfill lines; `physical-provisioning/spec.md`'s, among them
        `tests/unit/services/test_definition_document_restart_safety.py`, now under
        `tests/integration/`; `site-capacity/spec.md`'s offering-mode backfill and
        reservation release-mirror lines; `resource-pool-management/spec.md`'s,
        including its citation of `test_database.py` for a legacy host backfill that
        file no longer tests; and `deployment-state/spec.md`'s
        `test_job_envelope_migration.py`. `openspec/specs/fulfillment/architecture.md`'s
        "Atomic legacy-lease cutover" is removed, and
        `openspec/specs/physical-provisioning/architecture.md`'s paragraph on the
        service's database modules no longer names VM's legacy lease conversion or a
        history recording how VM's tables evolved, the chain now beginning at
        baselines; `openspec/specs/site-capacity/architecture.md`'s paragraph saying a
        retired-state row is converted by each ledger-holding service's chain
        (`20261028_001` and the API-credit service's `20261028_006`) is removed or
        restated, no supported database holding such a row. The requirements themselves are this change's deltas: REMOVED in
        `fulfillment`, `physical-provisioning`, and `site-capacity`, `site-capacity`'s
        "Capacity schema separation" restated as "A capacity reservation is stored
        apart from its host, pool, and assignment", and `fulfillment`'s "Dependency
        boundary" MODIFIED to admit the migration kit.
      - The registry specification whose pre-floor migration section 10 deleted (49 F1):
        `registry-discovery/spec.md`'s "Evidence", which the archive does not write,
        loses the line "Atomic canonical-principal migration and rollback", which cites
        the deleted `core/registry/tests/unit/test_principal_migrations.py`; and
        `openspec/specs/registry-discovery/architecture.md`'s "Atomic legacy identity
        migration" is removed. The requirements are this change's `registry-discovery`
        delta: "Publisher identity migration preserves ownership" REMOVED and "Stable
        publisher-chosen listing identity" MODIFIED.
      - The storefront specifications whose pre-floor identity conversion section 7
        deleted (56 F1): the "Evidence" lists, which the archive does not write —
        `storefront-publication/spec.md`'s canonical-principals line drops
        `core/storefront/tests/unit/test_identity_migrations.py`, its "Transactional
        storefront principal migration" line is removed, and its multi-domain listing
        bindings line cites `core/storefront/tests/integration/test_domain_bindings.py`
        for `test_domain_binding_migrations.py`; `negotiation-protocol/spec.md`'s
        "Transactional principal migration and fail-closed recovery ownership" line
        becomes recovery ownership alone, citing
        `core/buyer/tests/unit/test_identity_recovery.py`; `deployment-state/spec.md`'s
        line citing `domains/vms/storefront/tests/unit/test_domain_migration.py` is
        removed with its REMOVED requirement; `settlement-servicing/spec.md`'s citation
        drops `sqlite_migrations`. `openspec/specs/storefront-publication/architecture.md`'s
        paragraph on the one-transaction identity conversion is removed.
        `docs/development/TESTING.md`'s VM storefront bullet loses "transactional legacy
        migration" and the paragraph after the list its sentence on migration tests
        comparing source bytes; "Marketplace Identity Verification"'s migration bullet
        keeps explicit buyer run-log migration and startup/readiness rejection of drift
        or mixed signature versions, without populated legacy service state. The
        requirements are this change's deltas: `storefront-publication`'s "Storefront
        identity state migrates atomically" REMOVED; `negotiation-protocol`'s
        "Negotiation identity migration and recovery are deterministic" REMOVED and
        "Negotiation recovery is deterministic" ADDED; `deployment-state`'s "Identity
        migrations are coordinated and fail closed" REMOVED and "Identity cutover is
        coordinated and fails closed" ADDED.
      - The vocabulary sweep (D16): every permanent document's use of *role* for a
        service becomes *service*; a requirement whose name or text changes is carried
        as a delta in this change's `specs/` before 11.10, and
        `openspec/specs/README.md` is updated where a capability's description uses the
        word.
      - The `deployment-state`, `storefront-publication`, `physical-provisioning`,
        `fulfillment`, `site-capacity`, `registry-discovery`, and
        `negotiation-protocol` `spec.md` files are
        written by the archive in 11.11; the record names them. None of these
        capabilities has an `index.md`.
      Done, the record being `design.md`'s "Design promotion record". Every document
      above written, with these differences from the list: `seller-quickstart.md`'s
      "Upgrading from CSV inventory" is restated rather than removed, since
      `market_storefront/retired_settings.py`'s refusal of the retired inventory
      settings cites it and closeout edits no code — it now says only which settings
      are retired and how to declare inventory at provisioning; `deployment-state/
      architecture.md`'s "Transactional identity cutover" and the Evidence lines of
      `resource-pool-management` were also corrected, and `ARCHITECTURE.md`'s "Atomic
      workload-lifecycle cutovers" no longer names the deleted lease conversion;
      `deployment-state/spec.md`'s Evidence gains the engine, chain, command and
      render-test suites and drops its sentence calling the migration entrypoints
      proposed. D16's sweep renamed no requirement heading (open changes modify them
      by name) and carried seven `deployment-state` requirements as MODIFIED deltas;
      `openspec/specs/README.md` needed no change. `resource-pool-management` joins the
      capabilities the archive writes (11.3).
      Corrected at the closeout triage, passages the promotion missed:
      `openspec/specs/storefront-publication/architecture.md`'s opening paragraph and
      its override-status paragraph, and `docs/development/ARCHITECTURE.md`'s host-naming
      passage, which kept the VM inventory tables and bare metal's accepted generations
      frozen, now say the chains drop them (63 F1); and
      `openspec/specs/negotiation-protocol/architecture.md`'s "Principal-bound history"
      no longer describes the deleted identity conversion, stating instead that a
      supported database already holds canonical principals and the recovery rule
      (63 F2). Documentation only. `scripts/change-workflow run pre-commit
      add-database-migration-commands` — `validate --specs --strict` 27 passed, every
      repository check passed, "passed, exit 0". The fresh-context check of the diff
      found the negotiation passage placing the conversion before the floor rather
      than in it, as `deployment-state/architecture.md` and the floor's IDs have it;
      corrected. It found no other passage still keeping the tables or describing the
      conversion.
- [x] 11.10 **Documentation citations.** Run
      `make check-doc-citations CHANGE=add-database-migration-commands` and resolve every
      match, then `scripts/change-workflow openspec validate add-database-migration-commands --strict`.
      Before archiving, check whether `multi-domain-storefront-composition` has archived:
      if it has, extend this change's REMOVED delta to its "Storefront domain-binding
      migration is transactional and explicit"; if not, record in its row that its delta
      must drop that requirement. Likewise check whether `add-persistent-buyer-profiles`
      has archived, since its delta MODIFIES `deployment-state`'s "Identity migrations
      are coordinated and fail closed", which this change removes and restates (56 F1):
      if it has, this change's "Identity cutover is coordinated and fails closed"
      carries its archived text without the rule that each service migrates its
      identity-bearing rows and without "Migration encounters conflicting owners",
      keeping its buyer profile store migration and buyer scenarios; if not, record in
      its row that its delta must modify "Identity cutover is coordinated and fails
      closed" instead, without that rule or that scenario.
      `make check-doc-citations CHANGE=add-database-migration-commands` — every cited
      path resolves, none a tombstone; `scripts/change-workflow run pre-commit
      add-database-migration-commands` — strict validation "valid", the index, tasks
      and skills checks, and `make check-repository` (comment hygiene, citations,
      specification index, decision destinations, history wording, version bumps, local
      imports, capability index) — "passed, exit 0". Neither
      `multi-domain-storefront-composition` nor `add-persistent-buyer-profiles` has
      archived, so each row records what its delta owes (11.6).
- [x] 11.11 **Archival.** Last, once every other part is checked:
      `scripts/change-workflow openspec archive add-database-migration-commands -y`
      merges the deltas into `openspec/specs/` and moves the change under
      `openspec/changes/archive/`; point the index row at the archived directory, and
      run `scripts/change-workflow openspec validate --specs --strict`.
      Archived without `--skip-specs`: no delta had been synchronized into the
      permanent specs by hand. The merged specs and the index row are checked after
      the move, and `run pre-commit` validates every specification strictly.
