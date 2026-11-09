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
      The round's triage (32 F2) took that composition as answering 2.3's
      "against a real registry", once the
      registry's paging test also asserts the one wire fact the sweep keys on and
      no other test carried: each listing read through the typed client states its
      resource's `offering_mode` (see the section's notes).

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

Round 1 triage fix (32 F2). The sweep closes only listings whose
`listing_resource.offering_mode` it serves, and never one stating none, so a registry
list response that dropped or renamed that field would make it close nothing while every
test passed. The registry's paging test
(`core/registry/tests/integration/test_listings.py::TestListPublisherListings::test_open_listings_page_by_offset_to_the_end`)
now asserts each listing read through the typed client carries
`listing_resource["offering_mode"] == "vm"`. Library integration of the registry
through its typed client: `make -C core/registry test` — unit 139 passed, integration
129 passed; with the planted resource emptied, the test failed on that assertion, and the
fixture was restored. The triage declined, as disproportionate, a system scenario that
plants an orphan and observes a storefront close it, and an in-process test booting the
registry app beside the cross-registry client, which would make a core or storefront
package depend on a deployed service.

Checks over the round's triage fixes (32 F1's deltas and notes, recorded in section 4's
notes, and this one): `scripts/change-workflow openspec validate
add-database-migration-commands --strict` — valid; `scripts/change-workflow run pre-commit
add-database-migration-commands` — "after-functional-change … passed, exit 0",
"pre-commit-functional … passed, exit 0" (`make check-packaging` and every suite), and
"pre-commit … passed, exit 0". Fresh-context check: fixed — the restated `site-capacity`
scenario said a reservation names its site, which `capacity_reservations` does not store,
now stated by the records the schema keeps; 11.9 lacked `site-capacity/architecture.md`'s
retired-state paragraph, now named; D12 and the proposal called the API-credit service's
retired-state conversion a floor migration, now distinguished, and 8.1 names the removal
its deletion makes true; 2.3's pending note had been replaced, now restored with the
outcome after it. Declined — the "Active fulfillment migration" Reason cites
`20260713_002`, which by the floor no longer placed hosts in a pool; the Reason says
"among them" of the migrations that did so historically, and every ID it names is a
floor ID.

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

- [x] 4.1 Generate the floor fixture: from a worktree at `9fffe41e9`, start compute
      provisioning's migration on a fresh database and commit its schema, normalized by
      the method `schema_snapshot` uses, under
      `provisioning/compute/service/tests/fixtures/`, with the floor's recorded
      migration IDs beside it; the fixture's README states the command that produced it
      and that the commit is the v0.3.0 release's service code. Verify the fixture
      lists every table the floor code creates, including `kit/site`'s
      `capacity_reservations`. (D3)
      `provisioning/compute/service/tests/fixtures/v0_3_0_floor/`: `schema.json`
      (the snapshot), `floor_ids.json` (43 IDs, ending
      `20261106_001_reservation_activated_at`), `ddl.sql` (each object's stored
      DDL, the ledger's included), and a README stating the procedure. Differs from
      the plan, on the owner's direction: built from the release's published PyPI
      wheels (`arkhai-compute-provisioning-service[adapters]==0.24.0`, every
      distribution constrained to the release lock's version, SQLAlchemy 2.0.51
      included), not from a worktree build of `9fffe41e9`, whose dependencies a
      rebuild may resolve differently; the release's own
      `compute-provisioning-migrate` ran on a fresh file with only
      `PROVISIONING_DATABASE_URL` set. The generator and its environment's
      `pyproject.toml` (a hundred-odd version constraints) are not committed: the
      README states the procedure, and the fixture is regenerated only to correct it
      against that release. The fixture holds 23 tables, every one the
      floor's `run_migrations` creates through its eight metadata sets and its
      chain, `capacity_reservations` among them (read against `9fffe41e9`'s
      `db/database.py`).
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
      the ssh rewrite). Baseline IDs are `v0_3_0_baseline_<package>`. The DDL is the
      floor's stored DDL, reformatted. Deleted: the 3,880-line pre-floor chain, the
      `create_all` calls, and 25 test modules (16 integration, 9 unit) whose only
      subject was a pre-floor migration or the legacy backfill it ran, with their
      helper `legacy_default_pool.py`. Library integration
      (`tests/integration/test_migration_chain.py`, file-backed SQLite through the
      engine, no application): the baselines alone give the fixture's snapshot; a
      fresh chain's snapshot equals a database built from `ddl.sql` with the floor IDs,
      adopted and migrated, whose run the engine reports as an adoption applying
      exactly the two later migrations (that adoption calls no baseline is section 3's
      engine test, with baselines that raise); adoption keeps rows; the chain's floor IDs are the fixture's; every
      table and column the eight metadata sets map exists in the migrated schema —
      passed. The integration suite's `db_engine` fixture now builds its schema with
      the chain instead of `create_all`, so every integration test using that fixture
      runs on the chain's schema; three modules that build only the tables they
      exercise (`test_scheduling_composition.py`, `test_ledger_lease_lifecycle.py`,
      `test_fulfillment_convergence.py`) still do so with `create_all`, unchanged.
      Also deleted, beyond the plan's list: VM's `legacy_backfill.py` and
      `market_fulfillment.backfill` (with its two exports), whose only caller was the
      deleted backfill migration, and their unit test
      `tests/unit/services/test_legacy_vm_fulfillment_backfill.py`. Two tests this
      section touched that run on a real SQLite file moved from `tests/unit/services/`
      to `tests/integration/`, as TESTING.md asks of a test exercising a real
      database: `test_capacity_definitions_startup.py` and
      `test_definition_document_restart_safety.py`. `kit/site`
      exports the placement-key migration for every chain holding the ledger; the
      API-credit service composes it in section 8 (8.1), and until then keeps its own
      `20261106_008`.
      Versions: kit-resource-pools 0.10.0, kit-site 0.14.0, kit-fulfillment 0.8.0,
      compute-provisioning 0.27.0, vms-provisioning-adapter 0.19.0, each depending
      on `arkhai-kit-schema-migrations>=0.1.0`; the service 0.25.0 on its
      `[sqlalchemy]` extra and the new minimums.
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
      `db/database.py`: `migrate_database`, `check_database` (the engine's
      `check_engine`, read-only for a file), `require_compatible_database` raising
      `IncompatibleDatabase` with the engine's refusal message, which
      `app_runtime.initialise_container_resources` calls; `db/migrate.py` parses
      `--check`, prints `describe` and, when not compatible, the refusal, and exits
      1 on a refused database or a failed migration. `make migrate` unchanged.
      Library integration (`test_database.py`, rewritten; SQLite file or shared
      in-memory, no application): fresh — compatible, no pool; rerun — nothing
      applied, schema unchanged; a v0.3.0 database — behind with adoption pending,
      refused by the startup check naming the later IDs, then adopted; one floor ID missing —
      unsupported naming it, the command refuses and changes nothing; tables with no
      ledger — unsupported, both the check's and the command's refusals naming the
      command; behind — the refusal names the pending ID; ahead,
      unknown alone and unknown with one missing — both named, the command refuses,
      nothing changes; absent — the check creates neither file nor directory; every
      startup refusal these tests provoke names `` `compute-provisioning-migrate` ``
      and no `migrate-job.yaml`;
      the placement key over v0.3.0 reservations — none backfilled, uniquely
      indexed; through `migrate.main` with the service's own settings loader:
      `--check` exits 1 on a behind database listing its pending IDs and leaves its
      bytes unchanged, exits 1 on a missing one creating none, exits 0 after the
      command migrated; the command exits 1 on an ahead database, bytes unchanged —
      passed. `test_migration_reads_no_configuration.py`: two copies of a v0.3.0
      database migrated under two configurations give one schema and one set of
      rows — passed. The startup refusal is proven at `require_compatible_database`,
      the function `app_runtime.initialise_container_resources` calls; no test starts
      the application on a refused database, and no test drives a failing migration
      through `migrate.main` to its exit status (the engine's failure path is
      section 3's, and section 1's ssh test drives it through `migrate_database`).
- [x] 4.4 Add render assertions to `helm/charts/provisioning/tests/test_render.py`: the
      migration init container is present, runs `compute-provisioning-migrate` from the
      application's image, mounts the same data volume at the same database path, and
      precedes the application container. Verify with `make -C helm test-render`. (D8)
      `test_the_migration_runs_first_from_the_application_image_over_its_database`,
      over the defaults and over mock mode with a chart-owned volume: exactly one init
      container, `provisioning-migrate`, running `["compute-provisioning-migrate"]`
      from the application container's image, both mounting the `data` volume at
      `/app/data` and the profile `config-production.yml`, the rendered manifest
      setting `database_url` to `sqlite:////app/data/provisioning.db` (asserted
      anywhere in the render, not within the profile's document), the init
      containers rendered before the containers. Chart render test (static configuration, no cluster):
      `make -C helm test-render` — passed; with the init container's data mount moved
      to `/app/elsewhere` it failed on the mount, and the template was restored. Done
      first, while 4.1–4.3 waited on the floor fixture.
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
      `make -C provisioning/compute/service test` — unit 622 passed, integration 540
      passed; `make -C kit/site test` — 366 passed; `make -C kit/resource-pools test`
      — 141 passed; `make -C kit/fulfillment test` — 211 passed;
      `make -C provisioning/compute test` — 531 passed;
      `make -C domains/vms/provisioning/adapter test` — 292 passed;
      `make -C helm test-render` — passed; `make check-architecture` — passed;
      `scripts/change-workflow run pre-commit add-database-migration-commands` —
      `after-functional-change` (`make lock`), `pre-commit-functional`
      (`make check-packaging` and `make test`, every suite) and `pre-commit` (the
      change index, tasks, skills, strict validation, and the repository's eight
      checks) passed, and passed again over the final tree after the second
      fresh-context check's docstring and note fixes. End-to-end confirmed as the
      section's notes record; the pipeline has not run on this section.

**Section 4 notes — completed 2026-11-09.**

How the floor was produced. The first session stopped at 4.1: the implementation step
runs Python only as `uv run pytest`, and running the fixture generator was denied. The
owner directed that the floor come from the v0.3.0 release's published PyPI wheels, not
a build of `9fffe41e9`, and granted the resumed session a one-run rule for the
generator, which the session then ran: the release's `compute-provisioning-migrate`
applied its 43 migrations to a fresh file and the generator wrote the fixture (23
tables, ledger columns `id` and `applied_at`). `main` has not moved past the release,
and `d595f0c2e`'s tree equals `9fffe41e9`'s, so PyPI's wheels are the release's code.
Constraining third-party distributions mattered: unconstrained, the environment resolved
SQLAlchemy 2.1.8, against the 2.0.51 the release shipped. A later floor (D16's release
step) is produced the same way; the fixture README gives the procedure.

Seams and surprises. Adoption keeps a deployment that already ran this branch's chain
working: it records every floor ID plus `20261106_002` and `20261108_001`, so it is
adopted with nothing pending. The ssh rewrite's test now starts from a v0.3.0 database
built from `ddl.sql`, the real upgrade path, so the rewrite runs after adoption and the
placement key; its refusal surfaces as the engine's `MigrationFailed` naming the
migration, with the host list as its cause. `migrate.main` takes `argv`, since pytest's
own arguments would otherwise reach its parser; tests call `migrate.main([])`. The
service's chain needs no `_table_exists` guards: every migration after the baseline runs
on a database the baselines built or an adopted floor.

Left for review and closeout, outside this section's plan:
- Permanent specifications still state requirements whose pre-floor migrations this
  section deleted: `openspec/specs/fulfillment/spec.md` "Existing lease continuity
  during fulfillment cutover"; `physical-provisioning/spec.md` "Existing host
  identities migrate without loss" and "Active fulfillment migration";
  `site-capacity/spec.md` "A stored reservation in a retired state is converted at
  upgrade" (whose rule still holds for the API-credit service until section 8) and
  "Capacity schema separation"'s scenario "Existing host migration". No delta of the
  change covers these requirements, though it has deltas for `physical-provisioning`
  and `deployment-state`, and 11.9 names none of them.
- Permanent Evidence lines cite test modules this section deleted or moved:
  `fulfillment/spec.md` (~664–665), `physical-provisioning/spec.md` (~3446–3451, one of
  them `tests/unit/services/test_definition_document_restart_safety.py`, now under
  `tests/integration/`), `site-capacity/spec.md` (~305, offering-mode backfill; ~314,
  reservation release mirror), `resource-pool-management/spec.md` (~1020–1029, which
  also cites `test_database.py` for a legacy host backfill it no longer tests), and
  `deployment-state/spec.md` (~1240, `test_job_envelope_migration.py`).
- Permanent architecture text describes what this section removed:
  `openspec/specs/physical-provisioning/architecture.md` (~line 21: the service's
  database modules naming VM's tables and VM's legacy lease conversion) and
  `openspec/specs/fulfillment/architecture.md` "Atomic legacy-lease cutover" (~66–70).
  `fulfillment/spec.md` "Dependency boundary" (~40) lists what `market_fulfillment` may
  depend on and omits the migration engine kit it now imports.
- `openspec/changes/README.md`'s unowned row on anchor-form citations counts thirteen
  citations in files including `legacy_backfill.py` and seven `kit/fulfillment` modules;
  this section deleted `legacy_backfill.py` and `market_fulfillment/backfill.py`, so the
  row's counts are stale.
- The triage should place each of these: REMOVED or MODIFIED deltas, Evidence and
  architecture corrections, and the proposal's capability list, most likely as
  amendments to 11.9 and 11.10. Placed by the round's triage (32 F1): REMOVED and
  MODIFIED deltas in new `specs/fulfillment/` and `specs/site-capacity/` and in
  `specs/physical-provisioning/` (`site-capacity`'s "Capacity schema separation"
  restated under a new name, since a MODIFIED requirement cannot drop a scenario),
  the two capabilities added to the proposal and to D12, the Evidence and architecture
  corrections named in 11.9, and the citation row's recount in 11.6.
- TESTING.md defines library integration for kit libraries; this section, like section
  1, names a service's migration tests with no application "library integration" (a
  real component against real storage, no application). 11.9's planned "Migration
  Tests" section should say so for a service's migration suite.
- The command's tests set the settings object's source through the service's own
  loader, as the existing configuration test did; giving `migrate.main` its settings as
  a parameter would be the cleaner seam.

Fresh-context check, run twice. Fixed after the first: 4.2 and 4.3 had been duplicated
in an edit, unchecked copies left beside the checked ones; the notes described the
stopped session and named a scratch path outside the repository; the service chain's
docstring cited a requirement heading that exists only in the delta; the kits' `db.py`
docstrings still prescribed `create_all`; `kit/site`'s migrations docstring described a
consumer section 8 adds; the no-ledger test checked no refusal message; overstated notes
(every integration test on the chain, every refusal checked, a refusal "at startup");
the orphaned backfill modules and their test, deleted; two real-database tests moved
out of `unit/`. The first pre-commit run failed on RELEASING.md's internal-dependency
table (now listing `arkhai-kit-schema-migrations` for the six packages), the duplicated
tasks, and one history-wording hit, all fixed. Fixed after the second: kit docstrings
reworded to the rule rather than a consumer the branch lacks; a stale backfill example
in `job_fulfillment.teardown_operation`'s docstring; Compose added to the command's
"Used by"; the fulfillment boundary test's docstring; four overstated or wrong notes
(eight metadata sets, the adoption claim, 4.4's `database_url` assertion, the spec
list). Declined: committing the floor generator (the README states the procedure; its
environment is a hundred-odd constraints, regenerated only to correct the fixture);
keeping a service-level test of backfilled fulfillment rows (the rows the deleted
backfill wrote are ordinary fulfillment states, which `test_fulfillment_convergence.py`
covers with natively created rows; the deleted tests' subject was the backfill that
produced them); kit-level tests of each exported baseline (only the provisioning
service holds the floor fixture they reproduce, and its chain test proves them against
it, with every mapped column).

End-to-end. `provisioning`, `provisioning_readonly`, `e2e_deal`, and
`e2e_bare_metal_mock_deal` (markers in `e2e-tests/pyproject.toml`) run on lanes whose
provisioning service starts through its migration init container (Helm) or its
migration command before the application (Compose) on a fresh database, so a passing
pipeline is evidence the baselines and later migrations build a schema the service runs
on. No lane holds a v0.3.0 database; adoption is proven by the library integration
tests, and no scenario is owed.

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

- [x] 6.1 Generate the storefront floor fixtures: from a worktree at `9fffe41e9`,
      construct each storefront's database client on a fresh database — VM, bare metal,
      and, for its own baseline only, API credits — without opening any store, and
      commit each normalized schema and each chain's recorded floor IDs under the
      owning storefront's `tests/fixtures/`, with a README stating the command. (D3)
      `tests/fixtures/v0_3_0_floor/` under each storefront (`schema.json`,
      `floor_ids.json`, `ddl.sql`, README). Differs from the plan as 4.1 did, on the
      owner's direction and grant: built from the release's published PyPI wheels
      (`arkhai-vms-storefront==0.27.0`, `arkhai-bare-metal-storefront==0.27.0`,
      `arkhai-apicredits-storefront==0.20.0`), each environment constrained to its
      lock at `9fffe41e9`, not from a worktree. VM: 26 tables, 29 IDs; bare metal: 28
      tables, 37 IDs; API credits: 26 tables, 20 IDs. Core's tables, indexes and
      triggers are identical in all three (the `ddl.sql` files differ only in each
      domain's tables and the obligation columns VM and API credits add to
      `escrows`); no fresh floor database holds a frozen table or a store-open
      table. The generator is not committed, as 4.1's was not; each README states
      the procedure.
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
      `market_contact_exchange.migrations` (beside the floor-era migrations 7.5
      deletes), `market_pool_overrides.migrations`; IDs `v0_3_0_baseline_<package>`.
      The DDL is the floor's, with each column a later `ALTER` added written into its
      `CREATE TABLE` in stored order. Core's `escrows` leaves out `obligation_ref`
      and `obligation_index`, which VM's and API credits' domain baselines add.
      Library integration (real SQLite, no application; the plan said unit, but each
      opens a real database, which TESTING.md places in `tests/integration/`):
      each package's `tests/integration/test_baseline.py` — the baseline creates
      exactly `BASELINE_TABLES` — passed; and
      `domains/bare_metal/storefront/tests/integration/test_shared_baselines.py`,
      beyond the plan — the four baselines applied in chain order give a
      `schema_snapshot` equal to the bare-metal floor fixture's restricted to those
      packages' tables and their triggers (column for column, with indexes, keys and
      trigger text), the bare-metal floor being the one whose `escrows` is core's
      alone — passed. Versions: settlement runtime 0.8.0, contact exchange 0.5.0,
      pool overrides 0.3.0, each depending on `arkhai-kit-schema-migrations>=0.1.0`
      (in the settlement runtime's and contact exchange's package allowlists too);
      core storefront stays 0.18.0, already bumped on this branch. The exact pins
      moved: settlement runtime `==0.8.0` in contact exchange, arkhai-payments
      (0.6.2), config (0.5.2), core buyer (0.6.2), the bare-metal buyer (0.7.3) and
      the VM buyer (0.10.3), each patch-bumped for the pin alone; contact exchange
      `==0.5.0` and pool overrides `==0.3.0` in both storefronts and buyers that pin
      them; arkhai-payments `==0.6.2` and core buyer `==0.6.2` where pinned.
      `kit/schema-migrations` now supports Python `>=3.10`, as wide as the
      settlement runtime, whose lock could not otherwise resolve; it uses nothing
      newer. RELEASING.md's internal-dependency table names the engine for the four
      packages, and the API-credit domain's installation test builds its wheel.
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
      storefront creates an index after its chain (see the notes). Library
      integration (`tests/integration/test_servicing_schema.py`, real SQLite files,
      no application; the plan said unit): the schema creates exactly the objects
      its own statements declare on an empty database, leaves present tables and
      rows unchanged, and completes a database holding only the evidence tables
      (built from the schema's own evidence statements, not from the DDL the 0.1.0
      sessions issued, though the statements are those sessions' text) to a fresh
      one's schema; constructing each of the four sessions traces no DDL and changes
      no schema, and creates nothing on an empty database (no session method is
      traced: that they issue none rests on the DDL having been removed from them);
      the poller's `repairs()` reads its table on a schema'd database and, without
      the tables, fails on the missing table and creates none (its poll path is not
      run). That the schema holds every table the kit uses rests on the kit's 70
      tests passing over it — `make -C kit/deal-servicing test`, 70 passed. Until section
      7's migration replaces them, each storefront applies the schema when its
      lifecycle store opens: VM's `deal_lifecycle.py` and `delivery_records.py`
      already did (now through `market_deal_servicing.schema`), and bare metal's
      `BareMetalLifecycle` gains the call beside its cursor table, since its reads
      and watch polls would otherwise meet a missing table before the first deal
      registers; bare metal's `test_site_trust.py`, which plants a delivery after the
      app's lifespan opened that store, failed without it. Tests that plant
      servicing state without a store apply the schema first: the kit's own and
      `domains/compute/delivery/tests/conftest.py`.
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

How the section ran. The first run stopped at 6.1, since running the fixture generator
was denied; the owner granted one run on resumption. The section then paused on its
size, and the owner chose to commit section 6 without the bootstrap deletion, which
moves to 7.5 (6.2's amendment).

Why the deletion moved. Removing the constructor's bootstrap (6.2's deletion half) changes
every storefront at once, since all three construct core's `SQLiteClient`: from then on
constructing a client issues no DDL, and every test that builds a client on a fresh
file must migrate it first. That is about 149 constructions in 66 test files across
core and the three storefronts (a search for `SQLiteClient(` under `tests/`), beside
core's four migration-test modules (`test_domain_binding_migrations.py`,
`test_rate_structure_column.py`, `test_listing_resource_migration.py`,
`test_identity_migrations.py`) and VM's reconciler and freeze tests that import core's
pre-floor migrations. A section 6 commit with the bootstrap gone cannot pass the
pre-commit hooks, which run every suite, until section 7 declares the chains, so 6.2's
deletion and section 7 land together or not at all. Adding the baselines also gives
each table-owning package new public API and a dependency on the engine kit, and
`arkhai-kit-settlement-runtime` is pinned exactly (`==0.7.0`) by `kit/contact-exchange`,
`kit/arkhai-payments`, `kit/config`, `core/buyer`, and the VM and bare-metal buyers,
so its minor bump reaches each of those; the storefronts pin `arkhai-kit-pool-overrides`
and `arkhai-kit-contact-exchange` exactly too. 6.2's note records the bumps and pins.

Outside the plan. `kit/schema-migrations`' `requires-python` widened to `>=3.10`: the
settlement runtime supports 3.10 and its lock could not resolve the engine otherwise;
the engine's code uses no feature newer than 3.10, though its suite runs only on 3.13,
and `schema_snapshot` reads `PRAGMA table_list` (SQLite 3.37 or later). The API-credit
domain's wheel-installation test (`domains/apicredits/tests/conftest_wheels.py`) builds
the engine's wheel, since core storefront and the settlement runtime now require it;
the first pre-commit run failed on that alone. The VM and bare-metal callers changed
for 6.3: VM's `deal_lifecycle.py` and `delivery_records.py` take `create_schema` from
`market_deal_servicing.schema` (the former's alias now `create_servicing_schema`, since
it applies the whole schema, not the watch tables alone), both storefronts'
`receipt_claim` call `SellerSession(conn)`, and bare metal's `BareMetalLifecycle` gains
a store-open `create_schema` (6.3's note says why). The bare-metal storefront requires
`arkhai-kit-settlement-runtime>=0.8.0` and declares the engine as a test dependency.

Suites (before the fresh-context fixes, then again after them; see below):
`make -C kit/deal-servicing test` — 70 passed; `make -C core/storefront test` — 242;
`make -C kit/settlement-runtime test` — 187; `make -C kit/contact-exchange test` — 142;
`make -C kit/pool-overrides test` — 82; `make -C domains/bare_metal/storefront test` —
599 (one failure first, `test_site_trust.py`, fixed by bare metal's store-open call);
`make -C domains/vms/storefront test` — unit and integration (551) passed;
`make -C domains/compute/delivery test` — 126 (92 errors first, its rig applying no
schema, fixed); `make -C domains/apicredits test-domain` — 41;
`scripts/change-workflow run pre-commit add-database-migration-commands` — the first run
failed only on the API-credit installation test; the second passed every hook
(`make lock`, `make check-packaging`, `make test`, and `pre-commit`'s checks), and a
third, over the tree with the fresh-context fixes, passed every hook again.

Fresh-context check. No layering or comment-hygiene break (it ran `make
check-architecture`, `make check-comment-hygiene` and `make check-repository`). Fixed:
VM's misleading `create_watch_schema` alias; the bare-metal storefront's settlement
runtime lower bound, which its new test needs at 0.8.0; the kit baseline tests'
docstrings, which claimed proof against the storefronts' fixtures where only the
bare-metal one is compared; the deal-servicing README and the fixture READMEs, which
described behaviour section 7 brings; 6.3's evidence claims (constructors traced, not
methods; `repairs()` alone; the partial database built from the schema's own
statements; completeness resting on the kit suite); 6.4, amended for the consumer
suites; these notes, which still described the paused state. Declined: the bare
`See openspec/specs/deployment-state/spec.md.` pointers ending the new modules'
docstrings, the form sections 3 and 4 used (the requirements they mean exist only in
the change's delta until archive; 11.1 confirms comments at closeout); the four
packages' baseline tests in `tests/integration/` where 6.2 said unit, since each opens a
real database (6.2's note records it).

Handoff for section 7. The chains compose, in order, `core_storefront.migrations.BASELINE`,
the settlement runtime's, then contact exchange's and pool overrides' where composed
(VM and bare metal; API credits composes neither), then the domain's baseline, which
for VM and API credits adds `escrows.obligation_ref` and `obligation_index` with that
domain's two indexes (`idx_escrows_*` for VM, `idx_credit_escrows_*` for API credits).
The store-open migration's body is `market_deal_servicing.create_schema` plus bare
metal's `bare_metal_lifecycle_cursor`, which a bare-metal floor database holds only if
its lifecycle store ever opened.
Each floor fixture's `ddl.sql` builds a v0.3.0 database for the adoption tests, the
ledger's DDL included (`schema_migrations` with `id TEXT` and `applied_at TEXT`), as
provisioning's `floor_database.py` does. 7.5 does the deletion with 7.1, as one commit.

Found for 6.3 and 7.1. At the floor no storefront creates indexes after its chain:
core's `_ensure_domain_indexes` is empty, VM and bare metal do not override it, and API
credits' override holds only its refusal checks (`git show 9fffe41e9:` of each
`sqlite_client.py`). So core contributes no DDL to the store-open migration, which
holds deal servicing's tables and the domains' own store-open tables (bare metal's
lifecycle cursor); D3's "domain indexes the constructor creates after it" names
nothing the floor builds, for closeout's documentation compliance.

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
      holds its domain `BASELINE` (`v0_3_0_baseline_<domain>_storefront`, the floor's
      DDL with each `ALTER`-added column written in place; VM's and API credits' add
      `escrows.obligation_ref`/`obligation_index` and their two indexes), `CHAIN`,
      `FLOOR_IDS` (VM 29, bare metal 37; API credits none), `MIGRATION_COMMAND`, and
      `migrate_storefront_database(path)`, the function section 9's command calls.
      Later migrations: VM `20261106_001_vm_delivery_activation`,
      `20261106_002_vm_credentials_cleared`, `20261109_001_vm_store_open_tables`,
      `20261109_002_vm_frozen_inventory_dropped`; bare metal `-0016-delivery-activation`,
      `-0017-store-open-tables` (deal servicing's schema and `bare_metal_lifecycle_cursor`),
      `-0018-drop-accepted-site-generations`. The post-floor bodies lost their
      table-existence guards, since every table they touch exists once the baselines
      ran. API credits has no store-open migration: it composes no deal servicing and
      adopts no database. The pre-floor bodies, the hooks, bare metal's required-column
      check and the store-open `create_schema` calls are deleted; VM's
      `add_vm_settlement_records`/`add_vm_delivery_activation` left `payment_repository`
      (the latter's body is now the chain's). API credits' unbound-listing refusal is
      `refuse_unbound_listings(db_path)`, run by the server composition after the
      migration. Differs from the plan: until section 9 adds the startup check and the
      commands, each composition applies its chain itself before it opens the
      database — VM's `_build_vm_services`, bare metal's `build_runtime_from_configuration`,
      the API-credit server's service composition — so the storefronts keep starting on
      a fresh database (the lanes) in between; section 9 replaces each call with the
      check (see the notes). Library integration (`tests/integration/test_migration_chain.py`
      per storefront, real SQLite files through the engine, no application): the
      baselines alone give the floor fixture's `schema.json` exactly (API credits: its
      release fixture); the chain's floor IDs are the fixture's; a fresh database and an
      adopted floor database (built from `ddl.sql` by `tests/floor_database.py`) give
      one snapshot and one ledger, the adoption applying exactly the later migrations
      and keeping rows; a rerun changes no byte; a floor database without the
      store-open tables gains them, and present ones are left as they are (VM: deal
      servicing's tables keep their columns and indexes; bare metal: its cursor keeps
      its row); the frozen tables are dropped; a
      database missing a floor ID is refused as unsupported naming it and the command,
      bytes unchanged; an API-credit release database and tables without a ledger are
      refused unchanged; a failing appended migration is named by `MigrationFailed`,
      leaves no trace, and `check` reports it pending; the post-floor migrations'
      rewrites (VM phase and credentials, bare metal's dispatch marking and access
      stripping) — passed (VM 12, bare metal 11, API credits 5). "Startup refused,
      naming it" is shown at the engine's `check`, the call section 9's startup makes;
      no startup check exists before section 9.
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
      `test_alkahest_release_conditions`' fixture, whose startup tasks are replaced;
      bare metal on `test_app_composition`'s `_started_app`, the production app over a
      runtime built from the configuration files with its site transport replaced and
      its loops held — each reading its health through the typed client, and the
      `schema_snapshot` before and after are equal — passed, one test each. Mutation: with a
      `CREATE TABLE IF NOT EXISTS` added to `VmDealLifecycle`'s constructor, the VM test
      failed on the snapshot, and passed once it was removed; the mutation was run
      for VM alone. The API-credit fixture replaces the startup tasks (the credits
      preflight and the timer loops), so a store only a loop's step opens is not
      exercised there; VM's runs a publication cycle, and bare metal's holds its loops.
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
      Final run, `scripts/change-workflow run pre-commit add-database-migration-commands`
      over the final tree (only these notes changed after it) — `after-functional-change` (`make lock`),
      `pre-commit-functional` (`make check-packaging` and `make test`, every suite) and
      `pre-commit` (the index, tasks, skills, strict validation, and the repository's
      eight checks) all "passed, exit 0". From its suites: VM storefront unit 1137
      passed and 1 skipped, integration 550; bare-metal storefront 596; API-credit
      storefront 262; core storefront 222; settlement runtime 182; contact exchange
      141; pool overrides 82; capacity publication 135; deal servicing 70; compute
      delivery 126; API-credit domain 41. `make check-architecture` passed. The first
      run failed only on the local-imports check (nine migrate imports the test sweep
      placed inside functions, moved to module level).
      End-to-end, corrected: `e2e_deal`, `e2e_vm_payment_deal`, `e2e_bare_metal_mock_deal`,
      `e2e_bare_metal_payment_deal`, and `e2e_credits_deal` start each storefront on a
      fresh database its composition migrates through its chain; the VM and bare-metal
      lanes deliver deals through the store-open migration's deal-servicing tables, and
      the API-credit lane, whose chain has no store-open migration, through its
      baseline's tables. The pipeline has not run on this section: this is what a
      passing run would show. Owed by validation: none, confirmed.
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
      Deleted: `_ensure_tables_sync` and the domain hooks from `core_storefront/sqlite_client.py`,
      whose constructor now takes only `db_path` (the principal and legacy-seller
      arguments existed for the deleted principal migration);
      `core_storefront/sqlite_migrations.py` whole; `SettlementSQLiteRepository`'s runner,
      its `apply_migrations`/`extra_migrations` arguments, `settlement_migrations`,
      `SettlementMigration`, the legacy-claim conversion and the four
      `SETTLEMENT_*_MIGRATION_ID` exports; `CONTACT_EXCHANGE_MIGRATIONS` and its IDs (the
      trigger and claim-table rationale moved beside the baseline's DDL);
      `pool_override_migrations`, `PoolOverrideMigration` and their IDs. These are
      removals from public API in distributions this change already bumped (settlement
      runtime 0.8.0, contact exchange 0.5.0, pool overrides 0.3.0, core storefront
      0.18.0), so no further bump. Tests: a test that builds a client or store on a
      fresh file migrates it first — `migrate_storefront_database` in each storefront,
      core's `tests/core_database.py` (a chain of core's baseline alone) in core, the
      settlement runtime's `tests/settlement_tables.py` and each kit's `BASELINE` in
      the kits (both suites gain `tests` on their pytest path for the helper).
      Deleted, judged test by test, as having a deleted migration or legacy converter
      for subject: core's `test_listing_resource_migration.py` and
      `test_identity_migrations.py` whole; of core's `test_domain_binding_migrations.py`
      and `test_rate_structure_column.py`, which the plan named whole, only the
      migration tests — their live tests (binding immutability and conflicts, the
      baseline's `capacity_backing` and `closed_by` triggers, the backing labels, the
      rate-structure write) are kept in a new `tests/integration/test_domain_bindings.py`
      on a migrated database; the settlement runtime's six migration tests
      (`test_sqlite_repository.py` keeps its four live tests, plus one that a
      repository issues no DDL); contact exchange's two migration-rerun tests (one
      replaced by a claim-once test); pool overrides' rerun test (renamed to the key it
      still asserts). VM: `test_accepted_escrows_synthesis.py` (its live round-trip
      test moved to `test_publication_clause_persistence.py`),
      `test_fulfillment_context_migration.py`, `test_connection_details_migration.py`,
      `test_compute_allocations_freeze.py`, `test_inventory_freeze.py`; inside kept
      modules, the old `test_migrations.py`'s bootstrap, backfill, activation and
      credentials tests (the chain test covers the last two), two legacy-conversion
      tests in `test_negotiation_thread.py`, and the bindings-migration idempotency
      test in `test_reconciler_derivation.py`. Bare metal: `test_migrations.py` (its
      one live test, the selected-site table's constraints and trigger, moved to
      `test_site_clients.py`); `test_escrow_identity_backfill.py` is kept, its
      backfill running at startup. API credits: none. Moved to `tests/integration/`,
      since each opens a real database: core's `test_identity_authority.py` and
      `test_identity_lifecycle.py`, the settlement runtime's `test_jobs_and_policy.py`,
      and VM's rewritten `unit/test_migrations.py` as
      `integration/test_restart_persistence.py`. Results are 7.4's.
      The constructing-a-client-changes-no-schema test is 7.2's `test_store_open.py`,
      which constructs each client as its composition does.

**Section 7 notes — completed 2026-11-09.**

Handoff for section 9. Each composition calls its storefront's
`migrate_storefront_database` before it opens the database — `server._build_vm_services`,
`runtime.build_runtime_from_configuration`, and the API-credit server's composition
(which then calls `refuse_unbound_listings`) — so a storefront still starts on a fresh
database with no deployment step. Section 9 replaces each call with the startup check
(`market_schema_migrations.check_sqlite_file(CHAIN, path)`, refusing any result but
compatible with `refusal_message`, before anything constructs a client), adds the three
console scripts over `migrate_storefront_database` with `--check`, and moves the
migration into the init container and the Compose command. Every storefront test that
starts an app through those compositions then needs its database migrated first, as the
tests that construct a client directly already do; the store-open tests already migrate
before starting. API credits' `refuse_unbound_listings` stays a startup refusal after the
check (D9).

Seams and surprises. `executescript` cannot replay a fixture's `ddl.sql` as stored:
SQLite records `CREATE TABLE sqlite_sequence(name,seq)` for an `AUTOINCREMENT` key and
refuses to create it by name, so `tests/floor_database.py` (VM, bare metal) strips that
line. A trigger's text is compared after whitespace normalisation, so a baseline may
reflow a floor trigger but not change a token. Bare metal's floor fulfillment-lifecycle
columns added by `ALTER` are written in place in its baseline, matching column order.
The VM storefront's tests are a package (`from tests.floor_database import ...`); the
bare-metal suite imports helpers by bare module name. Core's client constructor lost its
principal and legacy-seller arguments with the principal migration, which reached every
construction; the VM and API-credit `get_sqlite_client` no longer resolve the signer.
Running suites while another session reinstalls the same package's `.venv` (each
`test` target's `reinit`) gives spurious import errors; the shared `.dist` wheels are
rebuilt only by `make lock`/`make dist`.

D3's sentence on "the domain indexes the constructor creates after it" names nothing
the floor builds (section 6's notes), so no store-open migration creates an index beyond
deal servicing's own; closeout's documentation compliance corrects D3.

Left for review and closeout, outside this section's plan (as section 4's were):
- Permanent requirements still require the storefront principal migration this section
  deleted with core's pre-floor chain: `storefront-publication/spec.md` "Storefront
  identity state migrates atomically" (~535), and the requirements at
  `negotiation-protocol/spec.md` ~153 and `deployment-state/spec.md` ~226 that describe
  it. No delta of the change covers them; they want REMOVED or MODIFIED deltas, and
  the proposal's capability list and D12 would gain `negotiation-protocol`.
- Evidence lines cite deleted modules: `deployment-state/spec.md` ~1250
  (`test_domain_migration.py`, whose requirement the REMOVED delta covers);
  `negotiation-protocol/spec.md` ~461 and `storefront-publication/spec.md` ~3247, ~3250
  (`core/storefront/tests/unit/test_identity_migrations.py`); `storefront-publication/spec.md`
  ~3278 (`test_domain_binding_migrations.py`, whose live tests are now
  `test_domain_bindings.py`); `settlement-servicing/spec.md` ~651
  (`core_storefront/sqlite_migrations.py`).
- `docs/development/TESTING.md` ~1167–1168 and ~1182–1183 describe VM's transactional
  legacy domain migration tests, and ~1221–1225 the storefront identity-migration
  tests; 11.9's "Migration Tests" section is the natural place to replace them.
- The triage should place each, most likely as deltas and as 11.9 and 11.10 amendments.

Declined from the fresh-context check: moving the VM storefront's other unit modules
that open a real database (e.g. `test_publications.py`, `test_negotiation_thread.py`,
`test_settlement_composition.py`) to `integration/` — TESTING.md's move-when-touched
rule is written for library packages, those modules opened real databases before this
section, and the touch here is one migrate call each; the rewritten
`test_migrations.py` did move. The `MIGRATION_COMMAND` names refer to console scripts
section 9 registers: a refusal raised by the in-process migration in between names a
command that does not exist yet, within one round.

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
      `apicredits_service/db/migrations.py` is now the chain alone: `CHAIN`
      (`the API-credit service`, `apicredits-service-migrate`) of
      `market_resource_pools`' baseline, the service's own
      (`v0_3_0_baseline_apicredits_service`: `api_keys`, `credit_grants`,
      `consumption_events`, the DDL `create_all` built for its models) and
      `market_site`'s, then `market_site.MIGRATIONS` (the placement key), no floor
      IDs. Deleted: the whole pre-floor chain and its runner, `check_schema_version`,
      `SchemaDriftError`, the `create_all` calls, and `_validate_grant_schema` whole —
      it checked schema only, which the exact-set check now holds, since a database
      the chain did not build is refused. `db/database.py` gains `migrate_database`,
      `check_database` (the engine's `check_engine`, read-only for a file),
      `IncompatibleDatabase` (the engine's refusal message), and
      `initialise_database`, which `container.init()` calls: the check, then the
      `default` pool seeded if absent, then `_require_valid_pool_declarations`.
      `db/migrate.py` is the command, provisioning's form (`--check` prints `describe`
      and the refusal, exits 1 unless compatible; a refusal or failed migration exits
      1), registered as the console script. It reads `database_url` and `log_level`
      from `settings_source.load_settings_source()`, the layered settings before any
      secret is read, which `config.py` now builds on: `config.py` resolves the admin
      key from its file at import and refuses an unreadable one, so a command
      importing it would have needed the application's secret mounted (see the
      section's notes). arkhai-apicredits-service 0.8.0, requiring
      `arkhai-kit-schema-migrations[sqlalchemy]>=0.1.0`, kit-site `>=0.14.0` and
      kit-resource-pools `>=0.10.0` (the versions exporting their baselines);
      RELEASING.md's internal-dependency row names the engine. Library integration
      (`tests/integration/test_migrations.py`, rewritten; file-backed SQLite through
      the engine, no application): fresh — every chain ID recorded, compatible, no
      pool written; the service baseline's snapshot equals `create_all` of its models
      for its three tables; every table and column the three metadata sets map exists;
      rerun — nothing applied, bytes unchanged; an existing database (the earlier
      startup's tables with its old ledger and a key row) — unsupported, the command
      refuses naming `apicredits-service-migrate` and a fresh database, the startup
      refuses, bytes unchanged; tables without a ledger — refused, no ledger created;
      behind (baselines only) — the startup refuses naming the command and the pending
      placement key, bytes unchanged; ahead — the startup and the command refuse naming
      the unknown ID, bytes unchanged; absent — refused naming the command, neither
      file nor directory created; startup seeds `default` once over two runs. Through
      the entry point, its configuration loaded fresh by the service's own loader:
      `--check` exits 1 on a behind database listing the pending ID, bytes unchanged,
      and on a missing one creating none; exits 0 once the command has migrated, run
      twice; the command exits 1 on an ahead database naming the unknown ID, bytes
      unchanged; two configurations differing in log level, admin key, site principal
      and timestamp skew give one schema, one ledger and no rows; with
      `storefront_admin_key_file` naming a missing file, which the application refuses
      to load, the command migrates; the installed console script
      `apicredits-service-migrate` loads `migrate.main`. Application composition
      (`test_signed_authority.py::test_the_service_refuses_to_start_on_a_database_it_has_not_migrated`,
      the real `container.init()` under configuration loaded fresh): on an unmigrated
      path it raises `IncompatibleDatabase` naming the command, builds no service, and
      creates no file. `test_default_pool.py`
      (was `test_pool_declarations_migration.py`; same level): startup seeds a
      declared `default` pool, a stored pool without declarations stops startup, and
      the pool projection carries its declarations — the test of the deleted
      advertisement migration went with it. `test_signed_authority.py` migrates its
      database before `container.init()`. Deleted
      `test_retired_reservation_states_migration.py` (`git rm`). The refusals of each
      state are shown at `initialise_database`, the call `container.init()` makes in
      the lifespan, and the absent one through `container.init()` itself; no test
      starts the ASGI application on a refused database.
      `make -C domains/apicredits/service test` — 80 passed;
      `make -C domains/apicredits test-domain` (the wheel-installation tests) — 41
      passed.
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
      plan: the image installed only the project's dependencies and ran the service
      from copied source on `PYTHONPATH`, which installs no console script, so its
      builder now installs the project's own wheel (`uv_project.py install-wheel`, as
      the provisioning and storefront images do) and the runtime stage no longer
      copies `src/` or sets `PYTHONPATH`. `make build-apicredits-service` — built.
      Not run: the Compose bring-up, `make -C domains/apicredits/service migrate`, and
      a `docker run` of the image's command were each denied in this session (no rule
      allows them). What stands for them: the command's entry point and console-script
      registration are 8.1's tests, and the e2e-apicredits lane starts
      `credits-service` from this image through this Compose command (8.3). Checked on
      that understanding: the lane's result is this task's pending evidence, for
      validation to judge — a failing `credits-service` start there means this task's
      form is wrong.
- [x] 8.3 **Verification.** Run `make -C domains/apicredits/service test` and
      `scripts/change-workflow run pre-commit add-database-migration-commands`.
      End-to-end: `e2e_credits_deal` and `e2e_credits_payment_deal` start the
      API-credit service through its migration command on a fresh database.
      Owed by validation: none.
      End-to-end confirmed from the lane's files: the e2e-apicredits lane brings up
      `domains/apicredits/compose.yml`'s `credits-service`, whose command now runs the
      migration on the lane's fresh volume before the server, and `e2e_credits_deal`
      and `e2e_credits_payment_deal` deal against it; the pipeline has not run on this
      section. Owed by validation: none, confirmed. Results in the section's notes.

**Section 8 notes — completed 2026-11-09.**

Suites: `make -C domains/apicredits/service test` — 80 passed;
`make -C domains/apicredits test-domain` — 41 passed (before the fresh-context fixes,
which touch neither the wheel's contents nor its dependencies);
`scripts/change-workflow run pre-commit add-database-migration-commands` —
`after-functional-change` (`make lock`), `pre-commit-functional` (`make check-packaging`
and `make test`, every suite) and `pre-commit` (the index, tasks, skills, strict
validation, and the repository's checks: comment hygiene, documentation citations,
history wording, version bumps, local imports among them) each "passed, exit 0" before
the fresh-context fixes, and again over the final tree.

Fresh-context check. Fixed: the command imported `apicredits_service.config`, which
reads `storefront_admin_key_file` at import and raises when it is unreadable, so the
command could not run — `--check` on a restored backup included — without the
application's admin-key secret mounted, against D4 and the delta's "MUST NOT read
operational configuration"; the layered loading moved to `settings_source.py`, which
reads no file a setting names, and a test runs the command with that file missing; the
two-configurations test's docstring claimed more than it showed; no test reached the
startup refusal through `container.init()` — one now does, for an absent database.
Declined: unchecking 8.2, whose local Compose bring-up was denied — its note names the
e2e-apicredits lane's result as its pending evidence.

Handoff. The API-credit service's settings now load in two steps: `settings_source`
(the layers) and `config` (the admin key resolved from its file or the storefront TOML
fallback). A future command needing only database settings uses the first. Provisioning's
`compute-provisioning-migrate` still imports its full settings; its loader reads no
secret file at import, so it has no such failure.

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
      Each storefront's migrations module gains `check_storefront_database` (the
      engine's `check_sqlite_file`, read-only), `IncompatibleStorefrontDatabase` (the
      engine's refusal message) and `require_compatible_storefront_database`, which
      replaces the interim `migrate_storefront_database` call in each composition, at
      the same point, before anything opens the database: VM's `_build_vm_services`,
      bare metal's `build_runtime_from_configuration`, and the API-credit server's
      composition, whose `refuse_unbound_listings` now runs once the check passes.
      The commands are `market_storefront.migrate`, `arkhai_bare_metal_storefront.migrate`
      and `apicredits_storefront.migrate` (`main`, provisioning's form), registered as
      console scripts; the storefronts' versions already carry this branch's minor
      bumps (0.28.0, 0.28.0, 0.21.0), so none moves. Each reads `db_path` (VM and API
      credits `log_level` too; bare metal's configuration states none, so its command
      logs at INFO), refusing a configuration naming no `db_path`, from the
      storefront's layered settings without resolving them:
      VM's and API credits' `utils/config.py` resolve chains, the agent id, and VM's
      base URL (through ZeroTier) at import, so their Dynaconf construction moved to a
      new `settings_source.py` in each package, which `utils/config.py` builds on;
      bare metal's `config.settings_source()` already only reads. Library integration
      (`tests/integration/test_migrate_command.py` per storefront, real SQLite files,
      the command through its entry point with its settings in the loader's
      environment layer and no configuration file, no application): `--check` on a
      behind database (baselines only; API credits, whose chain has no later
      migration, all but its last baseline) exits 1 listing the pending IDs and naming
      the command, bytes unchanged; `--check` on a missing database exits 1 creating
      neither file nor directory; the command twice then `--check` exit 0; the command
      on an ahead database exits 1 naming the unknown ID, bytes unchanged; two
      configurations give one schema, one ledger, and the same rows — the second
      stating settings the application reads (VM and API credits: log level, agent
      name, base URL; bare metal: port and a watchdog interval its configuration
      would refuse); a configuration whose `db_path` is empty exits 1 naming it; for
      VM and API credits, importing the command in a fresh interpreter leaves
      `utils.config`, which resolves configuration at import, unimported;
      `require_compatible_storefront_database`
      refuses behind and ahead databases naming the command and each differing ID,
      bytes unchanged, and a missing one creating nothing; the console script loads
      `main` — passed. Application integration (`test_store_open.py` per storefront,
      the real app and lifespan composed from configuration, as 7.2's tests start it):
      on an unmigrated path startup raises `IncompatibleStorefrontDatabase` naming the
      command and creates no file (bare metal: no runtime composed) — passed. "serve
      against a behind or ahead database" is shown at the check the composition calls,
      not through `serve`; the absent case through the composition's startup.
      Tests that start a storefront through its composition now migrate its database
      first: VM's `test_degraded_startup.py`, `test_alkahest_address_books.py`,
      `test_publishable_startup.py`; bare metal's `test_app_composition.py` (a
      `_migrated_configuration` helper behind `_configured_runtime` and `_started_app`,
      which takes `migrated=False` for the refusal test) and `test_site_trust.py`; API
      credits' `test_alkahest_release_conditions.py`, whose `_started` migrates unless
      `migrated=False`, which the five tests asserting a startup refused before any
      database exists pass. Suites: `make -C domains/vms/storefront test` — unit 1137
      passed and 1 skipped, integration 562 passed; `make -C domains/bare_metal/storefront test`
      — 607 passed; `make -C domains/apicredits/storefront test` — 274 passed.
- [x] 9.2 Add a `migrate` init container to `helm/charts/storefront` (per agent) and
      `helm/charts/bare-metal-storefront`, running the storefront's migration command
      from the application's image without `entrypoint.sh`, with the application's
      environment, configuration mounts, and data volume; change both render tests from
      "no `initContainers`" to "exactly one init container, the migration command, from
      the application's image, over the data volume", keeping the startup-probe
      assertion. Verify with `make -C helm test-render`. (D7; `deployment-state` "A
      storefront chart renders")
      Both Deployments render `initContainers` with one `migrate` container: the
      application's image and pull policy, `command: [market-storefront-migrate]` /
      `[bare-metal-storefront-migrate]`, the application's `env` and configuration
      mounts through the same helpers, and the data volume at the persistence mount
      path; VM's carries no ZeroTier device or capabilities, which its render test
      asserts. Chart render tests (static
      configuration, no cluster): each chart's
      `test_no_release_waits_on_a_dependency_...` now asserts, over every release it
      rendered before (VM: defaults, the local release, every rendering fixture, a
      second agent; bare metal: the example, the defaults, the umbrella release),
      exactly one init container, `migrate`, running the command alone, no
      `entrypoint.sh`, image and `env` equal to the application container's, its
      mounts among the application's (bare metal: equal to them) with the data volume
      at `/var/lib/arkhai` and `storefront.json`, the init containers before the
      containers, and the application's startup probe. The payments-check pod tests
      and bare metal's environment and command helpers read the application container
      now, since the first `env` and `volumeMounts` in the Deployment are the init
      container's. `make -C helm test-render` — passed; with the VM init container's
      data mount removed it failed on that assertion, and the template was restored.
      A Helm template comment saying registration needs "no separate init container"
      was reworded. `TESTING.md`'s "Chart Render Tests" still says no VM storefront
      Deployment renders an init container; closeout corrects it (11.9).
- [x] 9.3 Make every Compose storefront start as
      `sh -c "<storefront>-migrate && exec <its serve command>"`, keeping
      `entrypoint.sh` for the VM storefront's serve where it starts ZeroTier, and add a
      `migrate` target to each storefront's `Makefile`. Verify by bringing up each local
      stack's storefront (`compose.vms-local.yml`, `compose.bare-metal-local.yml`,
      `compose.apicredits-local.yml` overlays) and reading the migration's log line
      before the server's. (D7, D11; `deployment-state` "A storefront under Compose has
      pending migrations")
      VM's `bob-storefront` and `alice-storefront` (`domains/vms/compose.yml`) and
      `compose/seller.yml`'s `seller-storefront`, found beyond the plan's list:
      `command: ["./entrypoint.sh", "sh", "-c", "market-storefront-migrate && exec market-storefront serve"]`,
      ZeroTier first through the image's entrypoint script. Bare metal
      (`domains/bare_metal/compose.yml`, which `compose.bare-metal.yml` extends):
      `entrypoint: ["sh", "-c", "bare-metal-storefront-migrate && exec bare-metal-storefront serve"]`,
      since its image's entrypoint is the CLI; setting it drops the image's `serve`
      command, which the line restates. API credits (`domains/apicredits/compose.yml`):
      `command: ["sh", "-c", "apicredits-storefront-migrate && exec apicredits-storefront serve --host 0.0.0.0 --port 8000"]`.
      No lane or local overlay overrides a storefront's command or entrypoint. Each
      storefront `Makefile` gains `migrate` (`uv run ... <storefront>-migrate`). The
      images' own default commands are unchanged: Helm runs the migration as an init
      container, and Compose states its command. Not run: the local Compose bring-ups,
      denied in this session as 8.2's was; the lanes start every storefront through
      these commands on fresh volumes (9.4), so the pipeline's result is this task's
      pending evidence, for validation to judge.
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
      fresh volumes, so a passing pipeline is evidence `e2e_deal`,
      `e2e_vm_introduction`, `e2e_bare_metal_mock_deal`, `e2e_bare_metal_publication`
      and `e2e_credits_deal` ran on databases the storefronts' commands built; a
      passing Helm part of validation is evidence the installed release's storefront
      pods started through their init containers. Owed by validation: none,
      confirmed. Results in the section's notes.

**Section 9 notes — completed 2026-11-09.**

Suites: as 9.1 and 9.2 record; `scripts/change-workflow run pre-commit
add-database-migration-commands` — `after-functional-change`, `pre-commit-functional`
(`make check-packaging` and `make test`, every suite) and `pre-commit` each "passed,
exit 0" before the fresh-context fixes, and again over the final tree.

Fresh-context check. Fixed: a test showed only that in-process settings left no trace,
with `utils.config` already imported by the suite — VM and API credits now prove in a
fresh interpreter that the command never imports it, and the two-configuration tests
name settings the application reads; bare metal's command read a `log_level` its
configuration does not state — it logs at INFO; an unset or empty `db_path` would have
migrated a file named `None` or a temporary database — refused, tested; `entrypoint.sh`'s
comment described a Helm init container running `register` and Compose passing no
arguments; VM's `settings.toml` said serve creates the database's directory; a missing
blank line; the render note claimed a ZeroTier assertion the test lacked — added;
11.9 now names `DEPLOYMENT_AND_CONFIG.md`'s render-test sentence too; 9.4's end-to-end
lines read as observed. Declined: a `--config` option on the VM and API-credit commands
— `--config` reaches `storefront_config_file()` alone, and the settings serve reads its
`db_path` from come from `storefront_config_files()`, which ignores it, so serve and the
command read the same database; unchecking 9.3, whose Compose bring-ups were denied, as
8.2's were; moving the command's `main`, now four near-identical copies with
provisioning's and the API-credit service's, and the storefronts' check helpers into the
engine kit — a shared helper is reasonable, and the round's review should weigh it.

Handoff. Every storefront starts only on a database its migration command built:
composition calls `require_compatible_storefront_database` where it called the
migration. A test that starts a storefront through its composition migrates first, as
the files 9.1 lists do. `utils/config.py`'s `_build_settings` (VM, API credits) is a
wrapper over `settings_source()`, kept for the tests that call it.

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
      that both landed here. Recount the unowned row on anchor-form spec citations
      that omit the `requirement-` prefix: section 4 deleted
      `vm_provisioning_adapter/legacy_backfill.py` and `market_fulfillment/backfill.py`,
      so its count of thirteen and its list of files are stale (32 F1). Run
      `make check-change-index`.
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
        (D7; added 2026-11-09 by section 9).
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
      - The vocabulary sweep (D16): every permanent document's use of *role* for a
        service becomes *service*; a requirement whose name or text changes is carried
        as a delta in this change's `specs/` before 11.10, and
        `openspec/specs/README.md` is updated where a capability's description uses the
        word.
      - The `deployment-state`, `storefront-publication`, `physical-provisioning`,
        `fulfillment`, and `site-capacity` `spec.md` files are written by the archive in
        11.11; the record names them. None of these capabilities has an `index.md`.
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
