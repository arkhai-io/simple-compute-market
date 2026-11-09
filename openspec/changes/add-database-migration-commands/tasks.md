# Tasks

Replanned on 2026-11-08 against the reviewed design: sections 1–4 and 6–10 replace the
unchecked tasks of the plan written before the design discussion, whose sections 1–4
covered only the VM storefront and the API-credit services. Section 5 keeps its
completed task; its other tasks moved to section 10 (comment hygiene and import
placement) and section 11 (promotion).

Amended on 2026-11-09 after section 1 returned the change to design and D15a was
narrowed to hosts: section 1's tasks 1.1, 1.2 and 1.4 and closeout parts 11.5 and 11.9
are amended; nothing else moved.

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
      `compute_provisioning_service/db/migrations.py`, last in the chain. It runs on
      the chain's `Engine` today, as every provisioning migration does; section 4
      moves it onto a connection with the rest. Library integration
      (`tests/integration/test_ssh_connection_version_migration.py`, file-backed
      SQLite, no application): protected-key and key-file hosts with a queued create
      and a queued teardown migrate to version 2 with every other column byte for
      byte and the job rows unchanged; the host each stored job names is refused
      by the Ansible runner's `inventory_target` before the migration and read at
      version 2 after it, through `HostAuthority.lookup`, the host lookup the job
      engine is given for dispatch. No job engine dispatches in the test: it shows
      the two reads dispatch makes, not a dispatch. A quoted port fails naming the
      host, nothing rewritten, the migration unrecorded; a host naming no key
      fails naming it; a rerun changes nothing. The target version is the literal
      2, not the codec's served version, so a later codec version makes the
      migration fail rather than stamp a version it never mapped. Passed (part of
      `make -C provisioning/compute/service test`: integration 603 passed).
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
      Contracts 0.14.0; the provisioning service requires `>=0.14.0` (service
      0.24.1). No production caller relied on the default — host definitions, the
      INI import, the typed factory, the clients, and every e2e helper already
      state version 2; four test modules that relied on it now state it. Unit
      (`contracts/tests/unit/test_contracts.py`): an unversioned connection in
      `HostCreate` and `HostUpdate` is refused as missing `("connection", "version")`
      — passed, 156. Application integration (`test_hosts_api.py::TestConnectionVersions`,
      in-process app): an unversioned registration answers 422 and stores nothing —
      sent raw as a rejection-path test, since the typed client cannot build it —
      and versions 1 and 3 are refused through the typed client naming version 2 —
      passed. `make lock` refreshed every lock the bump reaches.
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
the job engine reads its host at dispatch (`compute_provisioning/jobs/engine.py`,
`HostLookup`, which `HostAuthority.lookup` serves from the `hosts` row through
`_execution_host`). `ansible_jobs.params`, `result`, `execution_handle`, the
`credentials` envelopes, and the fulfillment aggregate's prepared operations carry no
connection, and fulfillment requests carried none at the floor. A job not yet finished
at the upgrade therefore reads the rewritten host when it is dispatched.

The return to design (2026-11-08). Retry-release cannot re-run a teardown whose job
failed on a version-1 host: a fulfillment's teardown is one job under
`<reservation>:teardown` (`compute_provisioning/job_fulfillment.py`), and the engine
answers a repeated identity with the existing job whatever its status (`jobs/engine.py`,
`_repeat`). The design took option (b), D15a narrowed to the hosts, and the test that
showed it (`test_ssh_connection_version_recovery.py`) is deleted by 1.4; the evidence,
the options weighed, and the work then in progress are in the return's commit
`615d071ec` and in D15a.

End-to-end. `e2e_deal` (the VM lane's conftest) and `e2e_bare_metal_mock_deal` (the
bare-metal deal driver) register their hosts at version 2 and run create and teardown
against them, so the pipeline is evidence the required version reaches those callers.
`provisioning` is a read-only smoke marker and registers no host, so it is not evidence
for this section, correcting 1.5. No lane holds version-1 data.

Suites at completion: `make -C provisioning/compute/service test` — unit 717 passed,
integration 603 passed; `make -C provisioning/compute/contracts test` — 156 passed;
`make -C provisioning/compute test` (the kit alone) — 531 passed;
`make -C provisioning/compute/ansible test` — 187 passed, 4 skipped;
`make -C provisioning/compute/client test` — 86 passed. 1.5 named the ansible and
client suites as part of `make -C provisioning/compute test`, which runs only the kit,
so each ran on its own. `scripts/change-workflow run pre-commit add-database-migration-commands`
— `after-functional-change` (`make lock`), `pre-commit-functional` (the packaging
check and every suite), and `pre-commit` all passed; it ran again after the
fresh-context check's fixes, before the commit.

Fresh-context check. Fixed: the migration stamped the codec's served version, which a
later codec version would have changed under a recorded migration — now the literal 2;
the test's dispatch claim overstated it — it now reads the stored job rows, adds the
before-migration refusal, and the note says it shows dispatch's two reads, not a
dispatch; stale wording in the section's intro and the fixture docstring. Noted, not
changed here: `openspec/specs/physical-provisioning/architecture.md`'s "Nothing
rewrites a stored row on its own" is contradicted by this migration and is rewritten at
closeout (11.9, "The host registry owns the connection"); service 0.24.1 is a patch
though an unversioned submission's refusal moved from 400 to 422 — the contract change
is the contracts distribution's minor bump, and the service's wire routes are unchanged.

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
      unreachable), pages of `REGISTRY_PAGE_LIMIT` (200, the registry's maximum),
      the per-call deadline bounding each registry's whole read. The client gains a
      constructor-injected `client_factory` (unset: `RegistryClient`, resolved when
      the clients are built, so existing tests patching the module's name still
      apply) — the seam the unit tests use. Unit
      (`tests/unit/test_multi_registry_publisher_listings.py`, fake registry clients
      through the factory): per-registry results in order; five listings over three
      pages; a full last page followed by an empty one; a failure on the second page
      makes that registry unreachable and keeps the other's three listings; a page
      size below one refused — passed. Core also gains `SQLiteClient.open_listing_ids`
      (every locally open listing, paused or not), the sweep's held set: library
      integration (`tests/integration/test_open_listing_ids.py`, real SQLite) —
      passed. `make -C core/storefront test`: 240 passed. arkhai-core-storefront
      0.18.0 (new public API).
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
      `cycle.py`, run after `converge_registries`, reports each close as `close`
      with reason `NOT_HELD` (`not_held`) and its `registry`, an unreachable
      registry as `skip`/`registry_unreachable`, and a refused close as
      `fail`/`registry_close_failed`. The held set is the repository's
      `open_listing_ids` (every storefront's repository is core's SQLite client);
      the publisher and offering modes are the domain hooks' new
      `registry_publisher` and `served_offering_modes`. The held set is read after
      the registries, since a listing is recorded locally before any registry is
      told of it. Closes are not recorded as publications: a failed one is found
      again by the next sweep. A registry listing whose resource states no
      `offering_mode` is never swept, since nothing says which storefront under
      the principal it belongs to. Unit (`tests/unit/test_registry_sweep.py`): an
      unknown listing closes; a locally closed listing with no publication record
      closes; another mode's and a locally open listing stay open (the outage
      itself is driven in 2.3's VM test); two served modes both sweep; an unreachable
      registry is skipped while the other is swept; a preview reports both closes
      and makes none; a refused close is reported and closed next pass; publication
      turned off sweeps nothing — passed. arkhai-kit-capacity-publication 0.12.0
      (new API; the hooks protocol and repository protocol each gain members).
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
      Wired: VM's cycle runs the sweep after convergence in its `converge` stage,
      its hooks naming the signer's principal and `vm` alone — the only mode its
      loop publishes, so a bare-metal listing under a shared principal is the
      bare-metal storefront's even where VM composes that domain; bare metal's
      cycle the same, its hooks naming the publisher `build_publication_runtime`
      now requires and `bare_metal` alone; API credits' capacity reconciliation
      ends with `publication_service.retire_unheld_listings`, which logs, since
      that pass keeps no report and its capacity-events preview does not
      reconcile.

      Differs from the plan: no test runs a storefront against a real registry.
      A first version ran the registry application in process in a kit test,
      which `docs/development/TESTING.md`'s library integration (the library's own
      database, collaborators injected) does not cover and which made a kit
      depend on a deployed service (`ARCHITECTURE.md`, "Kit areas"); it was
      removed. The proof is split by level instead, and no test runs the
      cross-registry client's read against a real registry: the registry's own
      integration test, through its typed client, shows it honours `limit` and
      `offset` with the publisher and status filters, which that read relies on
      — a publisher's open listings paged to the end are each of them once, none
      closed and none of another publisher (`core/registry/tests/integration/test_listings.py::TestListPublisherListings::test_open_listings_page_by_offset_to_the_end`;
      its rows are inserted directly, as the file's fixtures do, to fix their
      creation order), beside its existing owner-signed close tests; the
      cross-registry client's paging and per-registry failure are 2.1's unit
      tests; the sweep's decisions are 2.2's; each storefront's wiring is proven
      against its own double, which replaces the cross-registry client itself,
      serves planted listings, and drops one it is sent a close for — so the
      client's paged read runs in no storefront test. The triage should weigh
      whether that composition answers 2.3's "against a real registry"; the
      cross-service close itself is a system-level observation no lane makes,
      since no lane plants an orphaned listing.

      VM (`test_publication_loop.py`, the storefront app through its typed
      client's lifecycle controls, the cross-registry client doubled):
      `test_a_cycle_closes_registry_listings_the_storefront_does_not_hold` — read
      under the signer's principal; an unheld `vm` listing closes at both
      registries; the held listing, and a `bare_metal` listing under the same
      principal, stay open; the preview sends nothing — passed;
      `test_a_listing_held_through_a_site_outage_stays_open_at_the_registry` —
      restarted with its site unreachable, the storefront holds the site's
      listing (`site_projection_unknown`) and the sweep leaves it open at the
      registry while closing an unheld one — passed. Bare metal
      (`test_publication_cycle.py`, the cycle over a real database with site and
      registry doubles, which its module docstring states is not integration
      evidence): an unheld `bare_metal` listing closes, a held one and a `vm`
      listing under the same principal stay open, a preview sends nothing; an
      unreachable registry is reported `skip` and swept by the next run — passed.
      API credits (`tests/integration/test_publish_reconcile.py::test_the_sweep_closes_registry_listings_the_storefront_does_not_hold`,
      the publication service's `retire_unheld_listings` called over the
      storefront's real database, its registry-client factory `_make_registry_client`
      replaced on the module that defines it, as TESTING.md's factory-seam
      convention allows — not application integration, since the API-credit
      storefront has no injected registry client to override): an unheld
      `api_credits` listing closes, the held one and a `vm` listing stay open, the
      read names the seller's principal — passed; and
      `tests/unit/test_capacity_reconcile_converges.py`, which already replaced
      each step of the reconciliation on `publication_service`, now holds the
      sweep last, after convergence. Versions: the three storefronts take minor bumps — bare
      metal 0.28.0, since its exported `build_publication_runtime` and
      `BareMetalPublicationHooks` gain a required `publisher`; VM 0.28.0 and API
      credits 0.21.0 for their new public hook methods and API credits'
      `retire_unheld_listings` — pin the kit at 0.12.0, and require core-storefront
      `>=0.18.0`; VM's exact pin on the bare-metal storefront moves to 0.28.0, and
      the provisioning service's dev pin on the kit to 0.12.0.
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

Suites (final run, before the commit): `make -C core/storefront test` — 240 passed;
`make -C core/registry test` — unit 139 passed, integration 129 passed;
`make -C kit/capacity-publication test` — 135 passed; `make -C domains/vms/storefront test`
— unit 1166 passed and 1 skipped, integration 551 passed;
`make -C domains/bare_metal/storefront test` — 598 passed;
`make -C domains/apicredits/storefront test` — 256 passed; and
`scripts/change-workflow run pre-commit add-database-migration-commands`, whose
`pre-commit-functional` runs every suite and the packaging check, passed.

End-to-end, confirmed from the scenarios' code (no pipeline has run on this section):
`e2e_bare_metal_publication`, `multi_registry`, `e2e_listing_shapes`, and
`e2e_credits_deal` run publication passes against live registries, so a passing
pipeline is evidence the sweep closes no listing a storefront holds. No e2e scenario
publishes to a registry under a storefront's principal except through the storefront
(only `validate_publish_listing`, a dry run), so none plants a listing to be swept and
none shows a close. The sweep is scoped by principal and by the mode a storefront
publishes, so storefronts of different modes may share a principal; the two VM
storefronts of the development stack, Bob and Alice, have distinct principals.

Fresh-context check. Fixed: VM swept every mode its domain registry composes, so with
bare metal composed it would close the dedicated bare-metal storefront's listings under
a shared principal, against the delta's scenario — VM now serves `vm` alone and its
test asserts the bare-metal listing stays open; the kit's in-process registry test
broke TESTING.md's library-integration definition and made a kit depend on a deployed
service — removed, the registry's side now proven in the registry's own suite;
the site-outage scenario had no test — the VM restart test drives it; the storefronts'
patch bumps were minor changes; an import added inside a function in `capacity_client.py`
was moved to module level, failed collection with the circular import
(`publication_service` imports `build_capacity_runtime` from it), and was restored with
the reason beside it; the API-credit sweep's docstring misdescribed the preview; the
kit test's docstring claimed an outage it does not set up; 2.4's claim of a real-registry
application test is corrected. A second check found the API-credit test replacing
`build_capacity_runtime` on a module that imports it, against TESTING.md's mocking
rules: it now calls the sweep function directly and replaces only the publication
service's own registry-client factory; the cross-registry client's docstring named the
removed in-process test; and these notes overstated what the storefront and registry
tests run, now corrected. Kept: `test_capacity_reconcile_converges.py` asserts the
reconciliation's order by replacing each step on `publication_service`, as it did
before this section, and the sweep joins it; the bare-metal cycle tests stay in a module
whose docstring says they are not integration evidence. Noted for closeout: `ARCHITECTURE.md`'s "Capacity publication and
multi-domain storefront composition" says the kit owns "the registry convergence every
publication pass ends with"; 11.9 now names it.

Known limit, for the triage. A registry listing whose resource states no
`offering_mode` is not swept: under a principal two storefronts of different modes may
share, nothing says whose it is. Listings published before the offering mode was
written into the resource would be such listings; the upgrade defect D15b fixes was a
bare-metal listing, which states its mode.

Handoff. The sweep reads every registry each pass: a VM or bare-metal publication
cycle, and an API-credit capacity reconciliation, which runs per capacity event — the
cadence convergence already has there. The cross-registry client's `client_factory` is
the seam for a test that needs a registry client of its own.

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
      `sqlalchemy` extra, and a package allowlist naming it alone. Wired into
      `kit/Makefile` (`dist-schema-migrations`, `test-schema-migrations`, both in
      the aggregates) and published beside its future consumers, since `kit/site` and
      the provisioning service are published and section 4 makes them depend on it:
      first in `manifests/published-distributions.json`, in `publish-pypi.yml`'s
      filters and package table, and in `RELEASING.md`'s published-packages table.
      Its lock was seeded by hand and resolved by `make lock PROJECTS=kit/schema-migrations`
      (a direct `uv lock` was not permitted in the session). `make check-architecture`
      — passed; `make check-packaging` (in `pre-commit-functional`) — passed;
      `make test-release-tooling` (in `make test`, `scripts/tests/test_publish_matrix.py`
      over the three publication files) — passed.
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
      (`schema_snapshot`). Differs from the plan: the tests that open a real database
      are library integration tests in `tests/integration/`, as `TESTING.md`'s
      library-package rule places them, not unit tests; `tests/unit/` holds the pure
      classification and message tests. Unit (`test_classification.py`,
      `test_refusal_message.py`): every result from tables and recorded IDs — absent
      (no file; an empty ledger), unsupported (tables without records, part of the
      floor naming what it lacks, a floorless chain's foreign records), behind (on the
      chain, in chain order; the floor with adoption pending, with or without a later
      migration already recorded), ahead (unknown beside the floor; unknown taking
      precedence over pending; leftover floor records), compatible; chain validation;
      each state's message naming the service, the command, and each differing ID,
      and a revision-based result naming both revisions — passed. Library integration
      over real SQLite files (`test_sqlite_engine.py`, `test_sqlalchemy_engine.py`):
      fresh, rerun, adoption without running the baselines (baselines that raise if
      called), adoption keeping an already-recorded later migration, ahead and
      unsupported refused with schema and ledger unchanged, tables without a ledger
      refused with no ledger created, a migration failing after DDL leaving earlier
      ones recorded and no trace of itself under default transaction control,
      `isolation_level=None`, `autocommit=True`, and through SQLAlchemy, a failed
      adoption keeping the floor records, the check of a missing file creating no file
      or directory, the check leaving a behind database's bytes unchanged, an
      in-memory engine checked through its own connection — passed;
      `test_schema_snapshot.py`: an `ALTER`-added column equal to a created one, column
      type, nullability, default, extra column and primary key seen, unique
      constraints by columns not generated names, foreign keys, partial and expression
      indexes, `CHECK` text without whitespace, `AUTOINCREMENT`, `STRICT`,
      `WITHOUT ROWID`, triggers and views, the ledger left out — passed.
- [x] 3.3 **Verification.** Run `make -C kit/schema-migrations test`,
      `make check-architecture`, `make check-packaging`, and
      `scripts/change-workflow run pre-commit add-database-migration-commands`.
      End-to-end: none — the kit has no deployed behaviour until section 4 composes it.
      Owed by validation: none.
      `make -C kit/schema-migrations test` — 60 passed; the rest as section 3's notes
      record. End-to-end confirmed: no scenario exercises the kit until section 4.

**Section 3 notes — completed 2026-11-09.**

Suites: `make -C kit/schema-migrations test` — unit and integration, 60 passed;
`make check-architecture` — passed; `scripts/change-workflow run pre-commit
add-database-migration-commands` — `after-functional-change`, `pre-commit-functional`
(every suite, `make check-packaging`, the release tooling's publish-matrix tests) and
`pre-commit` passed before the fresh-context check's fixes. Run again after them, every
hook passed but for one test of the change workflow's clone tooling,
`scripts/tests/test_change_clone.py::test_the_bootstrap_failed` (`ChildProcessError:
No child processes` from its own `os.waitpid`), which this section does not touch and
which had passed in the first run; `make test-release-tooling` rerun alone — 2691
passed.

Engine semantics the next sections rely on. A database records the chain once it
records any baseline ID; an ID the chain does not list then makes it *ahead*. A database
recording no baseline but every floor ID is *behind* with `adoption_pending`, and any
other ID it records beside the floor makes it *ahead*. Anything else holding tables or
records is *unsupported*, including tables with no ledger: design D5's "no file or no
records is *absent*" holds only for a database with no tables, which the delta's
"refuse any other non-empty database" already says — D5's sentence is looser than the
code, for closeout's documentation compliance. `migrate` reads the state, refuses, and
adopts in one transaction; every migration then runs in its own transaction with its
record. The ledger is `schema_migrations`; the engine reads and writes only `id`, so the
provisioning and storefront ledgers an earlier engine created serve as they are, and
`schema_snapshot` leaves the ledger out. A migration cannot turn `PRAGMA foreign_keys`
off, since it runs inside the engine's transaction; a later table rebuild must work with
enforcement as the connection has it. `check_engine` reads a file-backed SQLite URL
through a read-only `sqlite3` connection of its own, and any other engine, in-memory
included, through the engine.

Fresh-context check. Fixed: under `autocommit=True` the driver's `commit()` does
nothing, so the adapter now ends its transactions with `COMMIT`/`ROLLBACK` statements
and the failure test runs under all three transaction controls; the snapshot could not
see `AUTOINCREMENT`, which v0.3.0 storefront tables use, nor `STRICT`, `WITHOUT ROWID`
or an expression index's definition — now it does (a column's `COLLATE` is still not
seen, as its docstring says); an untested guard re-checked the floor in a second
transaction — the read, the refusal, and the adoption are now one transaction, and a
test fails adoption midway and finds the floor records kept; docstrings that described
consumers sections 6–10 add, and a citation of requirement headings that exist only in
the delta, reworded; a test name that overstated what it exercised renamed. Not run
again after these fixes, which were confined to the findings. Declined: a URI-form
SQLite URL (`sqlite:///file:...?uri=true`) is checked as a plain path — no service
configures one. Noted for closeout: `ARCHITECTURE.md`'s "Kind" lists the packages with
a package allowlist, and the kit-areas diagram draws the foundation kits; 11.9 now names
both. Outside the repository: publishing needs a PyPI trusted publisher and the
`pypi-arkhai-kit-schema-migrations` environment (`RELEASING.md`, "One-time setup"),
until which this package's publish job fails on `main`.

## 4. Compute provisioning on the engine, as the reference service

Delivers D2, D3, D4, D5, D8, D11, and D14 for compute provisioning, and the
provisioning half of `deployment-state`'s modified "Service-owned migration history"
and added "A chain begins at its supported baseline". Touches
`provisioning/compute/service` (`db/migrate.py`, `db/database.py`, `db/migrations.py`,
the startup that calls the check, `Makefile`, its tests), the table-owning packages
whose tables provisioning's database holds — `kit/site`, `kit/resource-pools`,
`kit/fulfillment`, `provisioning/compute` (`hosts`, `jobs`, `relays`), and
`domains/vms/provisioning/adapter` — and `helm/charts/provisioning/tests/test_render.py`.

- [ ] 4.1 Generate the floor fixture: from a worktree at `9fffe41e9`, start compute
      provisioning's migration on a fresh database and commit its schema, normalized by
      the method `schema_snapshot` uses, under
      `provisioning/compute/service/tests/fixtures/`, with the floor's recorded
      migration IDs beside it; the fixture's README states the command that produced it
      and that the commit is the v0.3.0 release's service code. Verify the fixture
      lists every table the floor code creates, including `kit/site`'s
      `capacity_reservations`. (D3)
- [ ] 4.2 Write the baselines — one per table-owning package in provisioning's database
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
- [ ] 4.3 Replace `run_migrations` and `check_schema_version` with the engine:
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
- [ ] 4.4 Add render assertions to `helm/charts/provisioning/tests/test_render.py`: the
      migration init container is present, runs `compute-provisioning-migrate` from the
      application's image, mounts the same data volume at the same database path, and
      precedes the application container. Verify with `make -C helm test-render`. (D8)
- [ ] 4.5 **Verification.** Run `make -C provisioning/compute/service test`,
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

## 5. Permanent promotion

Replanned against the reviewed design: 5.2's promotion work is section 11's, and 5.3's
comment hygiene and import placement are task 10.5.

- [x] 5.1 **Withdrawn** 2026-10-14: closeout does this — 6.9 writes the architecture companion by hand, and the archive in 6.11 writes the `deployment-state` spec its delta covers. As first planned: Promote explicit command/guard/ordering requirements to `openspec/specs/deployment-state/spec.md` and rationale to `architecture.md`.

## 6. Storefront kit and core baselines, and the store-open migration

Delivers D3 and D9 for the packages beneath the storefront compositions, for
`deployment-state`'s added "A chain begins at its supported baseline" and "Opening a
store changes no schema". Touches `core/storefront` (`sqlite_client.py`,
`sqlite_migrations.py`), `kit/settlement-runtime` (`sqlite_repository.py`),
`kit/contact-exchange` (`migrations.py`), `kit/pool-overrides` (`store.py`), and
`kit/deal-servicing` (`journal.py`, `evidence.py`, `watch.py`, `respondent.py`,
`seller.py`), each moving onto the engine kit.

- [ ] 6.1 Generate the storefront floor fixtures: from a worktree at `9fffe41e9`,
      construct each storefront's database client on a fresh database — VM, bare metal,
      and, for its own baseline only, API credits — without opening any store, and
      commit each normalized schema and each chain's recorded floor IDs under the
      owning storefront's `tests/fixtures/`, with a README stating the command. (D3)
- [ ] 6.2 Write core storefront's baseline as fixed DDL reproducing the tables and
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
- [ ] 6.3 Write the store-open migration's contributions: deal-servicing's tables and
      core's post-chain domain-index hook become `IF NOT EXISTS` DDL each package
      exports for composition into the one post-baseline migration each storefront
      chain carries (composed in section 7), and every `create_schema` call at store
      open is removed from `kit/deal-servicing`. Verify with a unit test in
      `kit/deal-servicing` that opening each store on a database already holding its
      tables issues no DDL, and that the migration creates them where absent and leaves
      them unchanged where present. (D3, D9)
- [ ] 6.4 **Verification.** Run `make -C core/storefront test`,
      `make -C kit/settlement-runtime test`, `make -C kit/contact-exchange test`,
      `make -C kit/pool-overrides test`, `make -C kit/deal-servicing test`,
      `make check-architecture`, and
      `scripts/change-workflow run pre-commit add-database-migration-commands`; the
      storefront suites run in section 7, which composes these baselines.
      End-to-end: none until section 7 composes the chains.
      Owed by validation: none.

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

- [ ] 7.1 Declare each composition's `Chain`: core's baseline, each composed kit's
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
- [ ] 7.2 Add the store-open test to each storefront: on a database its chain migrated,
      constructing the client, starting the application's composition, and opening
      every store it composes leaves `schema_snapshot` unchanged. Verify it fails when
      a `CREATE TABLE IF NOT EXISTS` is reintroduced at a store's open, and passes
      otherwise. (D5, D9; `deployment-state` "A storefront opens its stores on a
      migrated database")
- [ ] 7.3 Remove `market-storefront migrate-storefront-domains`,
      `market_storefront.domain_migration`, and
      `domains/vms/storefront/tests/unit/test_domain_migration.py`. Verify with
      `market-storefront --help` listing no such command and the VM storefront suite
      passing. (D3; REMOVED "Legacy storefront domain migration is transactional")
- [ ] 7.4 **Verification.** Run `make -C domains/vms/storefront test`,
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

## 8. The API-credit service on the engine

Delivers D3 (swept without adoption), D5, D6, D7's Compose form, D10, D11, and D14 for
the API-credit service, and `deployment-state`'s "The API-credit service starts on a
fresh database" and "A service has no separate deployment step for migrations".
Touches `domains/apicredits/service` (`db/database.py`, `db/migrations.py`,
`container.py`, `pyproject.toml`, `Dockerfile`, `Makefile`, its tests) and
`domains/apicredits/compose.yml`.

- [ ] 8.1 Replace `run_migrations` with an engine `Chain`: the service's own baseline,
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
- [ ] 8.2 Run the command before the application: the image's command and
      `domains/apicredits/compose.yml`'s `credits-service` become
      `sh -c "apicredits-service-migrate && exec <the service's uvicorn command>"`, and
      the service's `Makefile` gains `migrate`. Verify by starting the Compose stack
      locally (`docker compose -f compose.apicredits.yml -f compose.apicredits-local.yml up -d credits-service`)
      and reading the migration's log line before the server's, and with
      `make -C domains/apicredits/service migrate` on a fresh local database. (D7, D11)
- [ ] 8.3 **Verification.** Run `make -C domains/apicredits/service test` and
      `scripts/change-workflow run pre-commit add-database-migration-commands`.
      End-to-end: `e2e_credits_deal` and `e2e_credits_payment_deal` start the
      API-credit service through its migration command on a fresh database.
      Owed by validation: none.

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

- [ ] 9.1 Add `market-storefront-migrate`, `bare-metal-storefront-migrate`, and
      `apicredits-storefront-migrate`, each reading only the storefront's database path
      and log level from its configuration and applying its chain, with `--check`;
      each `serve` path calls `check` before constructing anything that opens the
      database and refuses any result but *compatible* with the engine's message.
      Verify with library integration tests per storefront: `--check` on a behind
      database lists pending IDs and exits unsuccessfully; `serve` against a behind,
      ahead, or absent database exits naming the command and creates no file; the
      command reads no configuration beyond the database path and log level (two
      configurations, one schema). (D4, D5, D6, D14)
- [ ] 9.2 Add a `migrate` init container to `helm/charts/storefront` (per agent) and
      `helm/charts/bare-metal-storefront`, running the storefront's migration command
      from the application's image without `entrypoint.sh`, with the application's
      environment, configuration mounts, and data volume; change both render tests from
      "no `initContainers`" to "exactly one init container, the migration command, from
      the application's image, over the data volume", keeping the startup-probe
      assertion. Verify with `make -C helm test-render`. (D7; `deployment-state` "A
      storefront chart renders")
- [ ] 9.3 Make every Compose storefront start as
      `sh -c "<storefront>-migrate && exec <its serve command>"`, keeping
      `entrypoint.sh` for the VM storefront's serve where it starts ZeroTier, and add a
      `migrate` target to each storefront's `Makefile`. Verify by bringing up each local
      stack's storefront (`compose.vms-local.yml`, `compose.bare-metal-local.yml`,
      `compose.apicredits-local.yml` overlays) and reading the migration's log line
      before the server's. (D7, D11; `deployment-state` "A storefront under Compose has
      pending migrations")
- [ ] 9.4 **Verification.** Run the three storefronts' suites,
      `make -C helm test-render`, `make check-packaging`, and
      `scripts/change-workflow run pre-commit add-database-migration-commands`.
      End-to-end: every lane deploys its storefronts through the migration phase —
      `e2e_deal`, `e2e_vm_introduction`, `e2e_bare_metal_mock_deal`,
      `e2e_bare_metal_publication`, `e2e_credits_deal`, and the `storefront` smoke
      tests — and validation's Helm checks render and install both charts with their
      init containers.
      Owed by validation: none.

## 10. The registry on the shared contract

Delivers D1, D3, D5, D6, D7, D11, and D14 for the registry, and `deployment-state`'s
"The registry refuses a database behind its head" and "The registry chart renders".
Touches `core/registry` (`alembic/versions/`, `alembic/env.py`,
`src/core_registry/db/database.py`, `src/core_registry/main.py`, `pyproject.toml`,
`Dockerfile`, `Makefile`, its tests), `helm/charts/registry` (`templates/deployment.yaml`
and a new `tests/test_render.py`), and every Compose file that starts a registry.

- [ ] 10.1 Generate the registry's floor fixture from `9fffe41e9` (a blank database
      migrated to `018_listing_resource_column`), then squash the eighteen revisions
      into one baseline revision written in Alembic operations that reproduces it, and
      adopt a database at `018` by rewriting `alembic_version` to the baseline in one
      transaction; delete the old revisions, the blank-database `create_all` +
      `stamp head`, and the legacy-revision detection. Verify with library integration
      tests in `core/registry/tests/`: a blank database's `schema_snapshot` equals the
      fixture; a database at `018` adopts; a database at an earlier revision or with no
      `alembic_version` but tables is refused as unsupported. (D3)
- [ ] 10.2 Add `registry-migrate` with `--check`, reporting through the engine kit's
      result type and message renderer; replace `init_db()`'s in-process upgrade at
      startup with a read-only check that refuses a database not at the script head
      (behind, ahead, absent, unsupported), naming the command and both revisions; add
      `make migrate`. Verify with library integration tests: startup refuses each
      result in the shared message form; `--check` exit codes; rerun changes nothing.
      (D5, D6, D11, D14; `deployment-state` "The registry refuses a database behind
      its head")
- [ ] 10.3 Add the registry chart's `migrate` init container (the application's image,
      `registry-migrate`, the configuration profile and data volume) and a render test
      in `helm/charts/registry/tests/test_render.py` asserting exactly one init
      container, the migration, over the data volume, and none for a disabled registry
      instance; make every Compose registry start as
      `sh -c "registry-migrate && exec <its uvicorn command>"`. Verify with
      `make -C helm test-render` and a local Compose bring-up reading the migration's
      log line first. (D7; `deployment-state` "The registry chart renders")
- [ ] 10.4 Find every file the change added or touched that names a removed command,
      module, migration ID, or frozen table — tests, fixtures, scripts, Makefiles,
      e2e helpers, documentation outside the closeout's promotion list — and update or
      remove each reference. Verify with a repository search for
      `migrate-storefront-domains`, `run_migrations`, `check_schema_version`,
      `apply_schema_migrations`, `_ensure_tables_sync`, and `required_tables` returning
      only what the change intends to keep. (D3; repository obligation:
      `AGENTS.md` "Cross-references must resolve")
- [ ] 10.5 **Comment hygiene and import placement, before the pre-closeout review.** Run
      `make check-comment-hygiene` and read the comments this change added for any that
      narrate the review or migration that introduced them; move each import the change
      added to module level unless a verified circular import or a recorded lazy-load
      reason keeps it local. Closeout only confirms both. (Repository obligation:
      `openspec/README.md#plan-closeout-requirements`, parts 1–2)
- [ ] 10.6 **Verification.** Run `make -C core/registry test`,
      `make -C helm test-render`, `make check-packaging`, and
      `scripts/change-workflow run pre-commit add-database-migration-commands`.
      End-to-end: `registry`, `multi_registry`, `e2e_deal`, `e2e_bare_metal_mock_deal`,
      and `e2e_credits_deal` start every registry through `registry-migrate`; validation's
      Helm checks install the registry chart with its init container.
      Owed by validation: none.

## 11. Closeout

Per `openspec/README.md#plan-closeout-requirements`.

- [ ] 11.1 **Comment hygiene — confirm.** Run `make check-comment-hygiene`, read the
      comments this change added for any that narrate the review or migration that
      introduced them, and confirm no production source references
      `openspec/changes/add-database-migration-commands` or the floor commit as
      provenance rather than as the fixtures' stated source. Do not edit code here:
      anything to rewrite returns the change to implementation.
- [ ] 11.2 **Import placement — confirm.** Check the imports this change added for any
      still local without a recorded reason. One that should move returns the change to
      implementation.
- [ ] 11.3 **Documentation compliance.** Re-check D1–D16 against `openspec/README.md`'s
      placement rules and the permanent documents against the code they describe: the
      mechanism's normative rules in `deployment-state/spec.md`, its rationale in
      `deployment-state/architecture.md`, its operator guidance in
      `DEPLOYMENT_AND_CONFIG.md` and `docs/operator-handbook.md`, and no repository-wide
      principle claimed in `ARCHITECTURE.md` beyond the Terms entry and the kit's place.
- [ ] 11.4 **Narrative compression.** Compress completed-task notes to final behavior,
      material validation evidence, unresolved or deferred work, and
      permanent-documentation destinations, moving durable rationale into `design.md`
      first.
- [ ] 11.5 **Roadmap currency.** In `docs/development/ROADMAP.md`, close the deferral
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
- [ ] 11.6 **Campaign index currency.** In `openspec/changes/README.md`: update this
      change's row; remove `hollow-pre-floor-provisioning-migrations`'s directory and
      row, since this change supersedes it, and reconcile the campaign graph line that
      names it; note in `migrate-registry-to-postgres`'s row that its command, guard and
      blank-database baseline landed here; leave other rows' `Depends on` alone. Amend
      `openspec/changes/migrate-registry-to-postgres/proposal.md` to drop "Repair
      Alembic so blank … databases reach the complete current registry schema" and "Add
      a packaged registry migration command and read-only runtime schema guard", stating
      that both landed here. Run `make check-change-index`.
- [ ] 11.7 **Packaging.** Run `make check-packaging` and resolve every failure it
      reports (a failure needing a code or lock change returns the change to
      implementation), then `make check-architecture-change CHANGE=add-database-migration-commands`.
- [ ] 11.8 **End-to-end pipeline.** Record the passing run the latest validation names,
      its result, and the scenarios that exercise this change — every lane's services
      starting through their migration phase (`e2e_deal`, `e2e_vm_payment_deal`,
      `e2e_bare_metal_mock_deal`, `e2e_bare_metal_publication`, `e2e_credits_deal`,
      `multi_registry`, `registry`, `provisioning`, `storefront`) — or an explicit
      blocker naming its cause and the change that owns it, with the validations it
      gates treated as unrun.
- [ ] 11.9 **Promotion.** Write the permanent documents this change owes and complete
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
        sentence (D7); "Combined compute-family storefront" — the
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
        (D5, D9).
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
      - The vocabulary sweep (D16): every permanent document's use of *role* for a
        service becomes *service*; a requirement whose name or text changes is carried
        as a delta in this change's `specs/` before 11.10, and
        `openspec/specs/README.md` is updated where a capability's description uses the
        word.
      - The `deployment-state`, `storefront-publication`, and `physical-provisioning`
        `spec.md` files are written by the archive in 11.11; the record names them. None
        of these capabilities has an `index.md`.
- [ ] 11.10 **Documentation citations.** Run
      `make check-doc-citations CHANGE=add-database-migration-commands` and resolve every
      match, then `scripts/change-workflow openspec validate add-database-migration-commands --strict`.
      Before archiving, check whether `multi-domain-storefront-composition` has archived:
      if it has, extend this change's REMOVED delta to its "Storefront domain-binding
      migration is transactional and explicit"; if not, record in its row that its delta
      must drop that requirement.
- [ ] 11.11 **Archival.** Last, once every other part is checked:
      `scripts/change-workflow openspec archive add-database-migration-commands -y`
      merges the deltas into `openspec/specs/` and moves the change under
      `openspec/changes/archive/`; point the index row at the archived directory, and
      run `scripts/change-workflow openspec validate --specs --strict`.
