# Implementation Tasks

Paths are relative to the repository root. Decisions (`D<n>`) and corrections are
`design.md`'s; requirements are this change's delta specs under `specs/`.

Sections 1–13 need nothing from `admit-relay-proxies-by-grant`: the signer is built
to the grant format D16 states, from the tool's specification as that change's
documents on this branch give it, and `relay-server` takes the plugin's wheel, its
hash-pinned requirements, and its configuration as inputs (D23). Sections 14–16 need
the tool itself (`frp-grant-admission`) and start once `admit-relay-proxies-by-grant`
is archived; closeout waits on it too (D13).

Sections 4–16 were replanned against the design as reviewed in `reviews/55-design.md`
and triaged, which carries 45-design F2's list of stale tasks and the reconciliation
with `admit-relay-proxies-by-grant`; sections 1–3 are unchanged.

## Execution reconciliation

The admission-plugin prerequisite is archived and integrated. Preserve D13's four-round order and all completed task and handoff history. Sections 6–9 precede cleanup integration; sections 10–13 build the real lanes; sections 14–15 precede live admission and section 16. Writing harness code does not require prior live deployment.

The owner-authorized validation cadence applies prospectively to unfinished sections: focused meaningful checks, comment hygiene and packaging before intermediate commits; one full `make test` and combined independent implementation review per frozen source round. This supersedes per-section full-suite/review wording below, while preserving named native gates, integration suites, pipeline evidence and closeout obligations. Reuse passing evidence with unchanged relevant inputs; source changes or unresolved failures require affected checks. Record delegated technical decisions truthfully without claiming personal owner reading.

The native `relay-server` installer remains native under D23. Section 16 uses containerized frps and plugin sharing a network namespace. Review the relevant source and verify admission before live buyer qualification. The additive bounded-working-data change joins after verified section 9 termination; its new real-lane observations additionally require section 12. Preserve legacy absent-account behavior; receipt-backed bounded cleanup must still verify numeric-identity activity/data/IPC absence when NSS no longer names the account.

## 1. The relay machinery in the compute family kit

Delivers D2(a) and "Relay machinery belongs to the compute family": the relay
implementation leaves the VM adapter for `compute_provisioning.relays`, with no change
to behaviour, tables, route paths, or operation names.

- [x] 1.1 Move the `Relay` and `RelayPortLease` models from
      `domains/vms/provisioning/adapter/src/vm_provisioning_adapter/db.py` into
      `provisioning/compute/src/compute_provisioning/relays/db.py`, keeping table
      names, constraints, and indexes; `AnsiblePoolConfig` stays VM's. Point the
      service's schema creation and migration history
      (`provisioning/compute/service/src/compute_provisioning_service/db/database.py`,
      `db/migrations.py`) at the family models, and update the service's import
      boundary test (`tests/unit/test_import_boundaries.py`). (D2a)
      Done: the family tables have their own declarative base (as hosts and jobs
      do); schema creation creates it between the pool and VM metadata, since
      `ansible_pool_configs.relay_id` now references `Relay.__table__.c.id` across
      metadata. The `20261023` rebuild takes `Relay.__table__` for its FK render.
      The import boundary test's allow-list is unchanged (database and migrations
      still read VM's `AnsiblePoolConfig`); its comment now names only VM's table.
- [x] 1.2 Move the allocator, release effect, and reconciliation
      (`relay_port_allocator.py`), relay administration (`relay_service.py`), the
      definitions importer (`relay_definitions.py`), the rebinding refusals
      (`relay_rebinding.py`), and execution-time resolution (`relay_execution.py`)
      from `vm_provisioning_adapter/services/` into `compute_provisioning/relays/`.
      The rebinding checks read pool references through one family function that
      section 2 backs; until then it reads VM's column. (D2a)
      Done as `relays/allocator.py`, `service.py`, `definitions.py`,
      `rebinding.py`, `execution.py`. The one read is `pool_relay_id`, which in
      this section selects `ansible_pool_configs.relay_id` by name (the family
      imports no domain). The host pool-change hook moved with the rules as
      `RELAY_HOST_POOL_CHANGE_HOOKS`. The reconciliation loop's function-local
      `import asyncio` moved to module level. Docstrings speak of deliveries, not
      VMs, where the rule is the family's.
- [x] 1.3 Move the relay wire models and route contracts from
      `domains/vms/provisioning/client/src/vm_provisioning_operator/relays.py` and
      `routes.py` into `provisioning/compute/contracts/src/compute_provisioning_contracts/`,
      and the relay methods into `compute_provisioning_client` (sync and async);
      remove them from `vm_provisioning_operator`. Repoint every caller, the e2e
      harness's included (`e2e-tests/src/e2e_harness/provisioning_test_client.py`,
      `e2e-tests/tests/e2e/roles/scenarios/vms/conftest.py`). (D2a, the five-piece
      route pattern in `docs/development/ARCHITECTURE.md`)
      Done: `compute_provisioning_contracts/relays.py`; the seven relay contracts
      join `PROVISIONING_ROUTE_CONTRACTS` and `ADMIN_PROVISIONING_OPERATIONS`.
      The family client's `update_relay` sends exactly the fields set (as
      `update_host` does), so an explicit `label=None` clears. The e2e harness
      called no relay method; only the VM conftest's docstring named relays.
      Contracts unit test: relay routes are admin-only and an id never matches
      an action path (`make test-compute-provisioning-contracts`, unit, 122 passed).
- [x] 1.4 Put the framework-free relay route service in the family kit and bind it in
      the provisioning service (`compute_provisioning_service/controllers/`,
      `route_table.py`), administrator only, replacing
      `vm_provisioning_adapter/controllers/relays_controller.py` and its mount in
      `vm_provisioning_adapter/routers.py`. Every relay route resolves to exactly one
      contract. ("Relay administration admits only the administrator")
      Done: `relays/route_service.py` (`RelayRouteService`) and
      `controllers/relays_controller.py`, mounted in `main.py`; `route_table.py`
      needed no change, since the relay contracts are now the family's own. One
      behaviour differs from the VM controller: a token rotation refused by the
      drain rule answers 409, where it fell through to a 500 before.
- [x] 1.5 Register the release effect, the reconciliation worker, and the relay
      definitions document once in the service's composition
      (`compute_provisioning_service/container.py`, `app_runtime.py`), and the
      host-pool-change check as a family hook rather than VM's
      `HOST_POOL_CHANGE_HOOKS`; remove them from `build_vm_adapter_bundle` and
      `VmProvisioningRuntime`. VM's plan keeps its allocation call and its codec its
      relay endpoint, now through the family package. (D2a)
      Done through `compute_provisioning.relays.relay_contribution`, an
      `ExecutorAdapterBundle` named `relays` with no executor or provider,
      composed first beside VM's and bare metal's so the existing duplicate-kind
      and duplicate-task refusals cover it. The container owns one
      `RelayPortAllocator`, `RelayService`, and `RelayExecutionResolver` and
      injects the allocator and resolver into `build_vm_runtime`. `app_runtime.py`
      needed no change (it already resolved `container.relay_service()`).
- [x] 1.6 Move the relay tests with the code: VM adapter's
      `tests/integration/test_relay_administration.py`,
      `test_relay_port_allocator.py`, and `test_relay_port_leases.py` into
      `provisioning/compute/tests/integration/`, and the service's
      `test_relays_api.py` and `test_relay_migrations.py` onto the family imports.
      Update each moved package's `pyproject.toml` dependencies and locks, and
      remove a dependency nothing imports any longer. (D2a; `AGENTS.md` "Package and
      dependency discipline")
      Done, with a split: the parts of `test_relay_administration.py` that
      exercise VM's code (the pool configuration's reader split and repoint
      refusal, and a rotated token reaching `VmAnsibleCodec`'s variables) stay in
      VM as `tests/integration/test_relay_pool_configuration.py`, as does the
      lease-file test of two pools on one relay, which wrote `AnsiblePoolConfig`
      rows; the lease-file test that a pool with no relay stores none was dropped,
      `test_a_pool_with_no_relay_resolves_to_no_relay_fields` covering it. The
      family's resolution tests use a stand-in dataclass. A family
      `tests/integration/conftest.py` builds the relay schema. Versions: family kit
      0.24.0 (gains `arkhai-kit-config`, `pyyaml`; `cryptography` in dev), contracts
      0.13.0, client 0.10.0, VM adapter 0.17.0 (drops `pyyaml`; `cryptography`,
      which only its tests import, moves to dev), VM operator client 0.11.0;
      dependents' bounds raised; `make lock` run.
      `docs/development/RELEASING.md`'s row for the family kit gains
      `arkhai-kit-config` (`make test-release-tooling` holds it). The permanent
      `physical-provisioning` spec's Evidence line naming the moved test files
      now names their new paths.
      Correction (the owner's review of round 1): a wheel's version is bumped
      once per branch, and each package above was bumped once from `dev`; a
      later section does not bump any of them again. The bare-metal adapter's
      floor on the family kit rose from `>=0.20.0` to `>=0.24.0`. That is a raised
      floor, not four bumps: 0.24.0 is the first version with
      `compute_provisioning.relays`, which its pool configuration handler
      imports. The `pyproject.toml` comments that described behaviour were taken
      out (the family kit's `arkhai-kit-config` and `pyyaml` need none). The
      comment on each `cryptography` dev dependency now says what the tests
      import it for.
- [x] 1.7 Verify. Library integration: `make test-compute-provisioning`. Application
      integration through the typed client: `make test-provisioning`, including the
      relay API, the relay migrations, and a fulfillment against a relay-backed VM
      pool. Unit and integration: `make test-provisioning-adapter`,
      `make test-compute-provisioning-contracts`,
      `make test-compute-provisioning-client`, `make test-e2e-unit`. Then
      `make check-architecture` and `make check-packaging`.
      End-to-end: the VM lane (`e2e_deal`, `e2e_listing_shapes`,
      `e2e_compute_dynamic_listings`, `e2e_vm_introduction`) and the bare-metal lane
      (`e2e_bare_metal_mock_deal`) exercise the recomposed service on pools with no
      relay; no pipeline scenario runs a relay-backed pool, which section 11 owes.
      Results: `make test-compute-provisioning` (unit and library integration,
      350 passed); `make test-provisioning` (service unit 596 passed; application
      integration through the typed clients 501 passed, including
      `test_relays_api.py`, `test_relay_migrations.py`, and
      `test_fulfillment_api.py::TestRelayPortLifecycleOverTheApi`, a fulfillment
      on a relay-backed VM pool); `make test-provisioning-adapter` (218 passed);
      contracts 122 passed; client 74 passed; `make test-e2e-unit` 352 passed;
      `make check-architecture` and `make check-packaging` OK; `make test` passed.
      Composition unit test: `test_authority_composition.py` holds one allocator
      and one execution resolver shared with VM's runtime and the relay effect,
      document, and worker each registered once. The host-move rule, which now
      reads `pool_relay_id`, is exercised through the typed client by
      `test_host_pool_moves_api.py` (application integration, in the 501).
      End-to-end scenarios confirmed as listed; none added.

  Section 1 handoff:
  - `relay_contribution` takes its configuration as values: the container's
    `_relay_bundle` reads `relay_definitions_path` and the
    `relay_port_reconciliation_*` settings and passes a path and a
    `RelayReconciliationSchedule` (or None). The integration harness and the
    restart-safety test call `_relay_bundle` itself, so they compose exactly as
    production does. The restart-safety test's unmounted-document case set a
    setting nothing read; it now clears `relay_definitions_path`.
  - `pool_relay_id` (`relays/rebinding.py`) reads `ansible_pool_configs.relay_id`
    by table name: a family read of a VM table that section 2 removes by backing
    the function with `pool_relays`.
  - Section 2 must protect the migration chain: `_migrate_vm_pool_playbook_optional`
    (`20261023`) rebuilds `ansible_pool_configs` from the current model, copying
    only columns the model has. Once the model drops `relay_id`, a database
    older than `20261023` would lose its references there, before the new
    `pool_relays` migration copies them. On a fresh database `create_all` makes
    the table without `relay_id` and `20260901` adds it back, so the new
    migration must drop it on every database.
  - The fresh-context check's finding that a family kit reading a domain table
    by name is a hidden edge was accepted as temporary (section 2); its findings
    on configuration ownership, comment history, local imports in touched
    tests, `cryptography`'s placement, the restart-safety no-op, and the 1.6
    note were fixed; two stale permanent documents were added to closeout
    (17.5, 17.9). Declined: a floor on `arkhai-kit-config` (no package in the
    repository states one).

## 2. One relay reference for every pool

Delivers D2(b) and "Relay machinery belongs to the compute family" (both providers
accept `relay_id`) and the renamed "A relay binding is fixed for a lease's life".

- [x] 2.1 Add the family table `pool_relays(pool_id → resource_pools, relay_id →
      relays)` in `compute_provisioning/relays/db.py`, and one migration in
      `compute_provisioning_service/db/migrations.py` that creates it, copies any
      `ansible_pool_configs.relay_id`, and drops that column; drop the column from
      `AnsiblePoolConfig`. The migration is fail-forward (28 F4). (D2b)
      Done: `PoolRelay` and `20261101_001_pool_relays` (`_migrate_pool_relays`),
      which copies the references and drops the column by rebuilding the table
      from its model through `_rebuild_ansible_pool_configs`, the procedure
      `20261023` used, now shared. `20261023` passes `keep=("relay_id",)` so a
      database older than it keeps its references through that rebuild for the
      new migration to copy. The docstring states the fail-forward upgrade;
      `DEPLOYMENT_AND_CONFIG.md` records it at closeout (17.9).
- [x] 2.2 Read and write a pool's relay reference through one family function that
      runs the rebinding check, and have VM's `AnsiblePoolConfigHandler` and bare
      metal's `BareMetalPoolConfigHandler`
      (`domains/bare_metal/provisioning/adapter/src/bare_metal_provisioning_adapter/services/bare_metal_pool_config_handler.py`)
      accept `provider_config.relay_id` through it; bare metal accepts no other field.
      The redacted read, the execution read, and preserve-on-absent hold for both.
      (D2b)
      Done in `relays/pool_relays.py`: `set_pool_relay` (the one write, running
      `check_pool_relay_change` first), `pool_relay_id` (the one read, in
      `rebinding.py`), `validate_relay_reference` (one validation rule), and
      `relay_execution_fields` (the endpoint, window, and decrypted token both
      execution reads add). Bare metal's handler reads `{}` for a pool with no
      relay and `{"relay_id": …}` otherwise, so an unrelayed pool's document entry
      still compares equal; it takes `settings` for the token key (its runtime
      passes the config). Preserve-on-absent is the pool service's: a PATCH that
      omits `provider_config` never calls the handler. VM's adapter no longer
      imports `market_config`, so its `arkhai-kit-config` declaration (and
      `RELEASING.md`'s mention) went. Bare-metal adapter 0.13.0.
      Beyond the plan: the pool routes (`controllers/pools_controller.py`, PUT,
      PATCH, and import) answer a `RelayRebindingRefused` with 409 and its
      message; before, a refused VM repoint over the API escaped as a 500 naming
      nothing. `set_pool_relay` also refuses a relay that does not exist, as a
      `PoolValidationError` (400): the service's SQLite connections enforce no
      foreign keys, and a dangling `pool_relays` row would fail every later
      table rebuild's whole-database foreign-key check. The change's delta spec
      gains the MODIFIED requirement "Bare-metal inventory binds an existing
      provider pool" (its scenario rejected any non-empty bare-metal
      configuration) and a scenario for a pool naming no existing relay.
- [x] 2.3 The rebinding rules read `pool_relays`: a pool's relay reference, a host's
      pool, and a relay's address refuse a change while an affected host holds an
      active lease, for VM and bare-metal pools alike, and a host moving between a VM
      pool and a bare-metal pool on the same relay is free. ("A relay binding is
      fixed for a lease's life")
      Done: `pool_relay_id` reads `PoolRelay`; the relay-address rule reads leases
      and needed no change. The section-1 read of VM's table by name is gone.
- [x] 2.4 Tests. Library integration: the migration copies a reference and drops the
      column; a bare-metal pool's relay reference round-trips and survives an
      unrelated write. Application integration through the typed client: a
      bare-metal pool written with `relay_id`; a bare-metal pool's relay change
      refused during a lease; a host move across providers on one relay accepted.
      Placement differs from the plan where the code does: the migration is the
      service's, so its tests are the service's
      (`test_relay_migrations.py::TestThePoolRelaysMigration`, a stored database
      migrated through `run_migrations`, and `test_vm_pool_config_migration.py`,
      whose pre-`20261023` database now ends with its reference in
      `pool_relays`); the family's library integration
      (`provisioning/compute/tests/integration/test_pool_relays.py`) proves the
      reference round-trips, clears, is shared by two providers' pools, refuses
      a change or a clear during a lease and accepts it drained, refuses an
      unknown relay, and a host move across providers on one relay is free and
      to another relay refused; the validation rule is unit-tested
      (`tests/unit/test_relay_reference_validation.py`). A bare-metal pool's
      round trip and survival of an unrelated write are application integration
      through the typed pool client (`test_pool_relays_api.py`), with a foreign
      field refused (400), an unknown relay refused (400), the refused change by
      PATCH and by a PUT dropping the relay (409, naming the lease), the drained
      change, and the execution read resolving the relay's endpoint and token
      (read through the pool service the dispatch path calls); the import's 409
      mapping is untested. The cross-provider host move is
      `test_host_pool_moves_api.py::test_a_tunnelled_host_moves_to_a_bare_metal_pool_on_its_relay`.
      `test_authority_composition.py` holds both handlers built over the
      service's settings. No PostgreSQL run: the migration is proven on SQLite.
- [x] 2.5 Verify. `make test-compute-provisioning`, `make test-provisioning`,
      `make test-provisioning-adapter`, `make test-bare-metal`; `make check-packaging`.
      End-to-end: the VM and bare-metal lanes as in 1.7, on pools with no relay; none
      runs a relay-backed pool.
      Results: `make test-compute-provisioning` 370 passed (unit and library
      integration); `make test-provisioning` service unit 597 and application
      integration 511 passed; `make test-provisioning-adapter` 218 passed;
      `make test-bare-metal` passed (193, 543, 30, 90); `make check-packaging` OK;
      `make test` passed. End-to-end scenarios confirmed as listed; none added.
      Service 0.22.0 (a fail-forward migration and new 409 answers).

  Section 2 handoff:
  - Every pool's relay is `pool_relays`; read it with `pool_relay_id`, write it
    only with `set_pool_relay`. Section 8's bare-metal plan reads the resolved
    relay from `BareMetalPoolConfigHandler.read_config_for_execution`, which
    already adds `relay_execution_fields`.
  - A pool write a lease forbids answers 409 from the pool routes; the pool
    document import does too. `ResourcePoolService` itself still lets the
    error propagate to its caller.
  - `_migrate_pool_relays` copies references without filtering for relays that
    exist: a reference to no relay fails the migration loudly (PostgreSQL's
    foreign key, SQLite's rebuild check) rather than silently turning a relayed
    pool into a direct one. The copy and the rebuild are separate
    transactions; a rerun after a failed rebuild is safe (`NOT IN` guard).
  - Fresh-context check: fixed the spec delta gap, the unknown-relay write, two
    comments, a tombstone comment and assertion, the 400 assertion, the
    validation tests' level, the migration test's docstring, the unreachable
    create-route 409, import order, and the service version; the notes now
    state which 409 paths and execution reads are tested.

## 3. The relay holdings read

Delivers D9's holdings read and "Relay holdings are readable by the administrator".

- [x] 3.1 Add `GET /api/v1/relays/{relay_id}/leases`, administrator only: its route
      contract and wire models in `compute_provisioning_contracts`, its route service
      in `compute_provisioning.relays`, its binding in the service, and typed sync and
      async client methods. Each lease reports its port, host, owning reservation,
      `released_at`, and, once section 5 adds them, its grant expiry and signing key
      id; no credential. (D9)
      Done: contract `provisioning_relay_leases` (admin only); wire models
      `RelayLeaseView` (lease id, remote port, host, pool, `owner_kind` and
      `owner_id` for the owning reservation, `allocated_at`, `released_at`) and
      `RelayLeaseListResponse`; `RelayService.list_leases` (every row, held or
      released, by port; unknown relay refused) and
      `RelayRouteService.list_leases` (404 for an unknown relay); the binding in
      `relays_controller.py`; `list_relay_leases` on both family clients. Grant
      expiry and signing key id are section 5's to add to `RelayLeaseView`.
- [x] 3.2 Tests. Application integration through the typed client: a torn-down
      delivery's lease reads released and no other lease holds its port; a caller
      other than the administrator is refused.
      Done: `test_fulfillment_api.py::TestRelayPortLifecycleOverTheApi::test_a_failed_create_is_compensated_and_its_port_returns_with_the_capacity`
      now ends by reading the holdings once the capacity is released: the
      fulfillment's lease reads released, which, since a lease row is its port
      (`UNIQUE(relay_id, remote_port)`), is what shows no other lease holds the
      port (application integration, a real fulfillment through the typed
      clients). The fulfillment reaches `torn_down` by a compensating teardown
      of a failed create, not by an ordinary delivery's teardown; both release
      through the same release effect, and the suite has no relay-backed
      ordinary teardown to extend. `test_relays_api.py::TestHoldingsOverTheApi`
      reads held and released seeded leases by port through the typed client,
      a 404 for an unknown relay, and the seller refused by the canonical
      client before sending (the contract's role refusal, no status). That the
      server itself refuses a seller's signed read (403 before dispatch) is the
      middleware unit test
      `tests/unit/middleware/test_auth.py::test_the_relay_holdings_read_admits_the_administrator_only`,
      over a stand-in handler. No credential can appear in the response:
      `RelayLeaseView` has no field for one. The family's library integration,
      `test_relay_administration.py::TestHoldings`, proves the read's rows,
      order, and unknown-relay refusal against the database.
- [x] 3.3 Verify. `make test-provisioning`, `make test-compute-provisioning-contracts`,
      `make test-compute-provisioning-client`. End-to-end: none in the pipeline; the
      real lanes read it (sections 11 and 12).
      Results: `make test-provisioning` service unit 602 and application
      integration 514 passed; contracts 123 passed (the relay-route tests cover
      the leases path); client 74 passed; `make test-compute-provisioning` 373
      passed; `make test-e2e-unit` 352 passed; `make check-packaging` OK;
      `make test` passed. End-to-end scenarios confirmed: none in the pipeline.
      Fresh-context check: added the family library test and the leases path to
      the route comment, pinned the seller test to the client's refusal, and
      corrected these notes' claims; it found no layering, route-pattern,
      comment, import, or packaging break.

  Section 3 handoff:
  - Section 5 adds `grant_expires_at` and the signing key id to
    `RelayPortLease`, `RelayLeaseRecord`, and `RelayLeaseView` (all three map
    field for field; the route service builds the view from the record's
    `__dict__`).
  - A released lease row is reused when its port is leased again, so the
    holdings read shows a released delivery only until its port is reissued;
    section 5's quarantine holds the port, and so the row, until the grant
    expires.

## 4. A grant-signing key per relay

Delivers D17 and D19's key requirements: "Each relay holds its own grant-signing key".
Replanned against the reviewed design: the profile's form and its refusal, staging a
supplied key, and its redaction are new.

Files: `provisioning/compute/src/compute_provisioning/relays/` (`db.py`, `service.py`,
`definitions.py`, `route_service.py`, a new `keys.py`),
`provisioning/compute/service/src/compute_provisioning_service/db/migrations.py`,
`controllers/relays_controller.py`, `settings.toml`;
`provisioning/compute/contracts/src/compute_provisioning_contracts/relays.py`; the
family client; `provisioning/compute/pyproject.toml` and its lock.

- [x] 4.1 `relays/keys.py`: load a private key from the profile's form — strip
      surrounding whitespace, decode single-line standard base64, load PKCS#8 DER with
      `cryptography`, and refuse anything that is not an Ed25519 key, the error naming
      what was wrong and never carrying the value; generate a key; derive a key's id
      as its RFC 7638 JWK thumbprint (base64url SHA-256 of
      `{"crv":"Ed25519","kty":"OKP","x":"<raw public key, base64url>"}`); encode a
      public half as single-line standard base64 of its DER SubjectPublicKeyInfo.
      `compute_provisioning` declares `cryptography` at runtime (it is a dev
      dependency today, 1.6). (D17)
      Done: `GrantKey` (`generate`, `from_profile_form`, `profile_form`, `kid`,
      `public_key`, its private half kept out of `repr`), `GrantKeyError`,
      `thumbprint`, `public_key_text`. Every refusal is raised `from None`, so no
      parser error that might quote the bytes is chained. `cryptography` moved
      from the family kit's dev group to its runtime dependencies; no version
      was bumped, since every wheel this section touches was bumped once on
      this branch already (1.6).
- [x] 4.2 Grant-key state on the relay in `relays/db.py`, with an additive migration
      in the service's `migrations.py`: the active key encrypted under
      `ssh_decryption_key` as the token is, its id, and its activation time; a staged
      key, encrypted, with its id; and a family table of retired keys, each with its
      relay, id, and retirement time. Ids are stored for active, staged, and retired
      keys alike. (D17)
      Done: `relays` gains `grant_key_encrypted`, `grant_key_id`,
      `grant_key_public`, `grant_key_activated_at`, and the staged
      `staged_grant_key_encrypted`, `_id`, `_public`. The table
      `relay_retired_grant_keys` is keyed by `(relay_id, key_id)`. Migration
      `20261101_002_relay_grant_keys` adds them. Beyond the plan: each public
      half is stored beside its id, so a relay read never decrypts a private
      key. A relay stored before the migration holds no active key; 5.8's
      refusal covers its pools.
- [x] 4.3 The relay definitions document accepts and requires `grant_key_secret_key`
      on every entry, read once at creation as `token_secret_key` is and never
      restated for an existing relay. An entry naming none fails the import naming the
      entry; a named profile key with no value, or whose value 4.1 refuses, fails the
      import before any relay is created, naming the relay and the profile key and not
      the value. A relay created through the API with no key gets one the service
      generates. `settings.toml`'s relay definitions comment names the new field.
      (D17, D19)
      Done: `_reconcile` resolves every new entry's token and grant key before
      writing any relay, so the import fails with nothing created even through
      `import_relay_definitions`, whose writes each commit on their own. A
      missing-field refusal names the entry by index and by id.
      `RelayService.create_relay` takes `grant_key` and generates one when it
      is given none. A create through the API takes no key, so it always
      generates one. An existing relay's entry is never resolved, so a profile
      key that has since gone or changed does not fail a reconciliation. Two
      new entries resolving to one key fail before either is written. So does
      a new entry naming a key an existing relay holds or retired; its check
      is `RelayService.grant_key_conflict`. The provisioning chart's comments
      on relay entries (`values.yaml`, `templates/configmap.yaml`) name the
      new field.
- [x] 4.4 *Stage* and *activate*, in `RelayService`, the route service, the contracts
      (two admin-only routes, which `PROVISIONING_ROUTE_CONTRACTS` and
      `ADMIN_PROVISIONING_OPERATIONS` gain), the controller binding, and the family
      client's sync and async methods. Staging takes an optional private key in the
      request, in the profile's form under 4.1's checks and refused when it fails
      them, or generates one when none is supplied; it returns the staged key's
      `kid` and `public_key` and signs nothing with it. Activating makes the staged
      key the active one, retiring the previous key with the time. A supplied private
      key never appears in an access log, an error body, or the response: the request
      model holds it as a secret value, and its refusals name the problem only.
      (D17)
      Done: `POST /api/v1/relays/{relay_id}/grant-keys/stage`
      (`provisioning_relay_grant_key_stage`, request `RelayGrantKeyStage`,
      `private_key: SecretStr | None`, answering `RelayStagedGrantKey`) and
      `POST .../grant-keys/activate` (`provisioning_relay_grant_key_activate`,
      answering `RelayResponse`), both admin only. The client methods are
      `stage_relay_grant_key(relay_id, body=None)` and
      `activate_relay_grant_key`. The client builds the stage body from the
      secret's value, since a model serialization masks it.
      Decided here: a malformed supplied key answers 422 with the loader's
      message. Activating with nothing staged answers 409. Staging over a
      staged key replaces it. A key any relay holds (active or staged) or has
      retired is refused, both for staging and for a create. Shared by two
      relays, one leak would open both (D17), and signed again by the relay
      that retired it, its retirement time would no longer say when the plugin
      may drop it. The service has no access log of its own, and the only
      request logging is uvicorn's line of method, path, and status, so a key
      sent in the body cannot reach a log.
      The stage binding takes the body as any JSON (`Body(default=None)`, its
      schema restated in `openapi_extra`). The route service validates it
      against `RelayGrantKeyStage` and answers 422 with each problem's `loc`,
      `msg`, and `type`, never its input. An unknown field is located at
      `body` alone, since its name is input too. FastAPI's default validation answer
      quotes the input it refuses, so a bare-string body or a key inside a
      list would have come back in the error body, and the auth middleware
      stores response bodies in its replay table. `RelayGrantKeyStage` forbids
      unknown fields, so a misspelled `private_key` is refused rather than
      staging a generated key.
- [x] 4.5 Relay reads return `grant_keys` as D17 shows it — the active key's `kid`,
      `public_key`, and `activated_at`; any staged key's `kid` and `public_key`; and
      each retired key's `kid` and `retired_at`; its `grants_valid_until` reads
      the leases' grant expiry and is section 5's (5.6). No read, export, or
      reconciliation comparison returns a private key. (D17)
      Done: `RelayView.grant_keys` (`GrantKeysView` of `ActiveGrantKeyView`,
      `StagedGrantKeyView`, and `RetiredGrantKeyView`s, oldest first) and the
      wire `RelayResponse.grant_keys` (`RelayGrantKeys`, `RelayActiveGrantKey`,
      `RelayStagedGrantKey`, `RelayRetiredGrantKey`). None of these types has a
      field for a private key. `RelayRetiredGrantKey` has no
      `grants_valid_until` yet; 5.6 adds it.
- [x] 4.6 Tests. Unit (`provisioning/compute/tests/unit/`): 4.1's loader accepts the
      form with a trailing newline, and refuses a non-base64 value, a non-PKCS#8 value,
      and a non-Ed25519 key, the refusal never containing the value; the thumbprint of
      RFC 8037's published example public key equals its published thumbprint; the
      public half's encoding round-trips. Library integration
      (`provisioning/compute/tests/integration/test_relay_administration.py`): a stored
      key is ciphertext; an entry naming no grant key, a profile key with no value, and
      a malformed value each fail the import naming relay and profile key, creating no
      relay; a reconciliation never rewrites a key; activation retires the previous
      key with its time. Application integration through the typed client
      (`provisioning/compute/service/tests/integration/test_relays_api.py`): a relay
      read carries public halves and ids only; staging a supplied key returns its
      public half and thumbprint, a malformed supplied key is refused without the
      value in the error body, and the private key appears in no response or captured
      access log; staging leaves the active key unchanged until activation; a relay
      created through the API with no key reads an active key.
      Done. Unit, `tests/unit/test_relay_grant_keys.py`: the loader takes RFC
      8032's TEST 1 key, built from its seed and the RFC 8410 PKCS#8 prefix,
      with surrounding whitespace. It refuses a non-base64 value, a value
      broken across lines, a DER that is not a key, a raw seed, and a P-256
      key, and no refusal carries the value or chains a cause. Its thumbprint
      equals RFC 8037's published one, computed from the seed and from the
      published `x`. Its public half equals the SubjectPublicKeyInfo D17
      shows, and a generated key's public half round-trips.
      Library integration, `test_relay_administration.py`:
      - `TestGrantKeys`: a key is generated when none is supplied, a supplied
        key is the active one, and a stored key is ciphertext that decrypts
        under the profile key. No view's `repr` carries the active or staged
        private key. Staging leaves the active key and refuses a malformed
        key without its value. A key this relay holds or retired is refused
        for staging. Another relay's active, staged, or retired key is
        refused for staging, and its active or retired key for a create.
        Activation retires the previous key with its time, a list read agrees
        with it, and activation needs a staged key.
      - `TestRelayDefinitionDocuments`: the named profile key supplies the
        grant key. An entry naming none fails, naming the entry and creating
        nothing. An absent, blank, non-key, or truncated value fails naming
        the relay and the profile key, and a sound entry before it is not
        created either. Two entries naming one key fail, naming both and
        creating neither. An entry naming a key another relay holds fails,
        naming the holder, and a sound entry before it is not created. A
        reconciliation after a rotation leaves the rotated key active.
      Unit, `tests/unit/test_relay_route_service.py`: the stage route service
      over a mocked relay service. A bare key, a key in a list, a key in a
      list under the field, a number, and a key used as a field name each
      answer 422, located under `body`. No answer repeats the key or chains a
      cause, and the relay service is never called. A well-formed key is
      passed on, and no body or an empty one asks for a generated key.

      Application integration through the typed client,
      `test_relays_api.py::TestGrantKeysOverTheApi`: a relay created with no
      key reads an active one. Staging a supplied key answers its kid and
      public half, which shows the client sent the real value. Its private key
      is in no field of the parsed stage, get, or list responses: the check
      runs on the client's models, which drop unknown fields, so what it shows
      is that the wire models carry no key. It is also in no log record the
      in-process app emitted (`caplog` at DEBUG). This run has no server
      access log: under `ASGITransport` uvicorn writes none. Staging leaves
      the active key until activation retires it. A malformed supplied key
      answers 422 with no value in the error or the logs. Activating with
      nothing staged answers 409. As rejection-path tests, three bodies the
      typed client never sends are sent signed through its
      `authenticated_request`: the bare key as the body, the key inside a
      list, and a misspelled field. Each answers 422 without the key in the
      error, and stages nothing.
      Contracts unit: both routes are admin only and resolve past a bare relay
      id, and `RelayGrantKeyStage` masks its key in `repr` and serialization.
      Beyond the plan: `test_relay_migrations.py::TestTheGrantKeyMigration`, a
      stored relay table without the columns migrated, gaining them and the
      retired table, with no active key (the service's migrations against a
      real SQLite database, no application). The restart-safety documents and
      `test_database.py`'s list of migrations follow the new field and
      migration.
- [x] 4.7 Verify. `make test-compute-provisioning` (unit, library integration),
      `make test-provisioning` (application integration through the typed client),
      `make test-compute-provisioning-contracts`, `make test-compute-provisioning-client`;
      `make test`; `make check-packaging` (`cryptography` at runtime).
      End-to-end: none in the pipeline — no lane runs a relay-backed pool; the real
      lanes read the active key (sections 11 and 12).
      Results: `make test-compute-provisioning` 417 passed (unit and library
      integration); `make test-provisioning` service unit 608 and application
      integration 523 passed; contracts 128 passed; client 74 passed;
      `make test-provisioning-adapter` 218 passed; `make lock` run; `make test`
      passed; `make check-packaging` OK; `make check-change` fails only on the
      four citations of files sections 10–12 create. End-to-end scenarios
      confirmed: none in the pipeline exercises a grant key.

  Section 4 handoff:
  - The service's suites run the family kit from its built wheel, not from
    source. After editing `provisioning/compute/src`, run `make lock` (it
    rebuilds the wheelhouse and the locks) before `make test-provisioning`,
    or the service tests run the old kit. A stale run shows up as an
    `AttributeError` behind a 500.
  - A relay's active private key is `Relay.grant_key_encrypted`: the profile
    form, encrypted with `encrypt_secret` under `ssh_decryption_key`. Section
    5's signer decrypts it with `decrypt_secret` and loads it with
    `GrantKey.from_profile_form`. `grant_key_id` is the `kid` the grant's
    header names.
  - `RelayRetiredGrantKey` rows are `(relay_id, key_id, retired_at)`. 5.6's
    `grants_valid_until` is computed per retired key from the leases, and
    `RelayRetiredGrantKey`/`RetiredGrantKeyView` gain that field then.
  - Fresh-context check, run twice. It fixed:
    - the 422 echo (above), including a key used as a field name;
    - key reuse across relays, now refused by the importer before any write;
    - the chart comments and the forbidden extra field;
    - the P-256 test's cause check;
    - a test docstring pointing at a design not on this branch;
    - a rejection-path assertion on the response body's content;
    - comments that described section 5's signing and refusal as present;
      they now say only what this section does, and section 5 adds the
      rest;
    - notes that overstated.

    Declined, with reasons:
    - A relay create with no `ssh_decryption_key` answering 500. A
      deployment without the at-rest key can hold no relay credential, and a
      relay without a grant key is unusable (D19), so creation fails, and the
      error names the missing key.
    - A database constraint for one key, one relay. The rule spans active,
      staged, and retired keys across two tables, which no one unique index
      expresses. Relay administration is an operator's serial action, and
      the query refuses the misconfiguration the rule exists for.

## 5. Grants, port quarantine, and the checks before dispatch

Delivers D16, D17's retirement bound, D19, and the management-route check: "Every
relay proxy carries a signed grant", "Relay port leases are unique per relay" (the
quarantine), "Each relay holds its own grant-signing key" (a retired key's validity),
"A relay without an active grant key is refused before dispatch", and "A host's
management route does not use its pool's buyer relay". Replanned against the reviewed
design: no `iat`, the claims' types, `jti` the owning reservation, the expiry rounded
up to the second, and the reuse margin.

Files: `provisioning/compute/src/compute_provisioning/relays/` (`db.py`,
`allocator.py`, `execution.py`, `service.py`, `rebinding.py`, new `grants.py`),
the service's `migrations.py` and `settings.toml`, the contracts' `relays.py`;
`domains/vms/provisioning/adapter/src/vm_provisioning_adapter/` (`codec.py`,
`models/jobs_model.py`, `services/vm_fulfillment_plan.py`);
`provisioning/compute/pyproject.toml` and its lock.

- [x] 5.1 `relay_port_leases` gains `grant_expires_at` and the id of the key that
      signed its latest grant, by an additive migration. Allocation records
      `grant_expires_at` in the acceptance transaction: the reservation's lease end,
      which the plan passes to allocation, plus the grace setting
      `relay_grant_expiry_grace_seconds`, rounded up to the whole second and stored as
      naive UTC like the table's other times. The setting is documented in
      `settings.toml` beside the relay settings, its default covering the lease
      watchdog's grace and a teardown's retries, as its comment says. A re-tenancy of a
      released row overwrites both fields. (D16 lifecycle 1)
      Done: `RelayPortLease.grant_expires_at` and `grant_key_id`, by migration
      `20261101_003_relay_lease_grants`. `allocate` and `allocate_in_session` take a
      required `lease_ends_at`, so no plan can forget it, and `grant_expiry`
      computes the stored value. The family read
      `reservation_lease_end(db, capacity_reservation_id)` parses the
      reservation's `lease_end_utc`, and VM's plan reads it in the acceptance
      session through an injected `lease_end`. The allocator takes the grace and
      the margin as constructor values; the container's
      `_make_relay_port_allocator` reads both settings. Grace default 3600 s: a
      300 s watchdog grace plus three retries backing off 60/120/240 s with
      their runs, and room. Decided here: a relayed create whose reservation
      states no lease end is refused in preparation, on validation too, since a
      grant has no expiry without one. A leased reservation always carries one
      (`ReservationState.leased`). A new lease row's `created_at` is now set in
      UTC by the allocator rather than by the database's clock, as a reused
      row's already was, because retired keys' validity compares against it.
- [x] 5.2 The allocator does not reissue a released port until its `grant_expires_at`
      plus `relay_port_reuse_margin_seconds` (default 300, documented in
      `settings.toml` with the clock-synchronisation requirement) has passed, reading
      the margin when it selects a port, so a raised margin covers leases already
      released; a lease cut short leaves its port held back and allocation selects
      another. (D16 lifecycle 3; "Relay port leases are unique per relay", scenarios
      "A lease is cut short" and "The reuse margin is raised")
      Done in `_lowest_free`, now an instance method: a released row whose
      `grant_expires_at` is after now minus the margin counts as held. A lease
      with no recorded expiry, stored before the migration, is free once
      released, as it was.
- [x] 5.3 `relays/grants.py`: a header-and-claims signer — RFC 8785 JSON of each
      through `rfc8785`, unpadded base64url, joined with `.`, signed with an Ed25519
      private key through `cryptography` — with no JWT library. `compute_provisioning`
      declares `rfc8785` at runtime (the JCS library `kit/identity` uses).
      (D16 "Signing")
      Done: `sign_compact`. `rfc8785>=0.1.4` is a runtime dependency of the
      family kit, with a comment saying what imports it.
- [x] 5.4 The grant builder: from a lease and the relay's active key, the header
      exactly `{"alg":"EdDSA","kid":<thumbprint>,"typ":"frp-grant+jwt"}` and the claims
      `aud` (the relay id), `port` (the leased port), `exp` (the stored
      `grant_expires_at` converted as UTC to its integer epoch seconds — never through a
      naive `timestamp()`), `sub` (the lease's host, omitted when it records none,
      never `null`), and `jti` (the lease's `owner_id`, always present); no `iat` and
      no `nbf`. (D16)
      Done: `grant_claims`, `epoch_seconds`, and `sign_grant(lease, key)`. A
      lease with no recorded expiry is refused rather than signed.
- [x] 5.5 The execution resolver (`relays/execution.py`) signs the grant immediately
      before a job's variables are written, on every attempt, with the relay's
      then-active key, filling a `relay_grant` field the resolver's parameter
      contract gains beside `relay_token`, and records the signing key id on the lease;
      a relay with no active key raises `RelayUnusableAtExecutionError`. The grant
      never enters an accepted operation's persisted parameters. VM's job parameters
      (`models/jobs_model.py`) gain the field, and its codec writes it as the proxy's
      grant variable. Conformance to the tool's published vector is section 14's.
      (D16 lifecycle 2)
      Done:
      - `resolve_into(params, *, remote_port=None, owner_id=None)`. The domain
        passes the leased port of a job that adds a proxy, under whatever name
        its parameters store it, and the reservation that holds the lease. VM
        passes `vm_remote_port`, which a removal does not carry, and
        `escrow_uid`.
      - The resolver reads the relay row `FOR UPDATE`, so on PostgreSQL an
        activation cannot commit between reading the active key and signing;
        a grant signed that way would outlive the retired key's reported
        validity. SQLite ignores the lock, but serializes writers, so there
        the signing's write fails and the job's retry signs with the new key.
        No test exercises the race. It signs
        only for the port's held lease when that lease's owner is the job's
        reservation, and records `grant_key_id` in the same transaction. A
        grant authorizes its port alone. With no such lease, or no active key,
        it raises `RelayUnusableAtExecutionError`.
      - `VmJobParams.relay_grant` is persisted as `None` at preparation and
        filled only in the codec's `prepare`. VM's codec writes it as
        `relay_grant`.
      - An operator's VM create carries no reservation, so a relayed one now
        fails at execution: no grant can be signed for its proxy, and a relay
        enforcing admission would refuse it. That follows from a grant being
        per lease and the operator path leasing no port (correction 8); the
        owner may want it recorded. `test_vms_api.py`'s first relay-bearing
        create asserts this refusal by name, against a port another
        reservation holds; the second asserts that the failed job's read and
        logs carry no token. No grant was signed, so there is none to find.
      - Beyond the plan: the service's integration harness (`conftest.py`)
        built VM's codec with no relay resolver, so no relayed job there
        resolved anything, unlike production. It now builds the codec with
        the resolver as the container does.
- [x] 5.6 Relay reads report each retired key's `grants_valid_until`: the latest
      `grant_expires_at` among the relay's unreleased leases allocated before it was
      retired, or none when none remains; and the holdings read (`RelayLeaseRecord`,
      `RelayLeaseView`, field for field, per section 3's handoff) gains each lease's
      `grant_expires_at` and signing key id. (D17, 28 F2; D9)
      Done: `RetiredGrantKeyView.grants_valid_until`, computed in
      `RelayView.of` from the relay's held leases (`created_at` before
      `retired_at`), and the wire field on `RelayRetiredGrantKey`.
      `RelayLeaseRecord` and `RelayLeaseView` gain `grant_expires_at` and
      `grant_key_id`.
- [x] 5.7 The relay family supplies one set of the variable names carrying the grant,
      the relay token, and the client's admin password, and VM's codec takes its
      secret fields from it (`VM_SECRET_FIELDS`). (D3, 28 F3)
      Done: `relays/variables.py`, with `RELAY_TOKEN_VARIABLE` (`frp_auth_token`,
      the name VM's playbook reads today), `RELAY_GRANT_VARIABLE`
      (`relay_grant`), `RELAY_ADMIN_PASSWORD_VARIABLE`
      (`relay_admin_password`), and `RELAY_SECRET_VARIABLES`. Sections 6 and 7
      name the roles' inputs; if they rename one, they change it here, the one
      place.
- [x] 5.8 Fulfillment preparation refuses a pool whose relay holds no active grant
      key, naming the relay and the missing key, beside its refusals for a missing
      token or window, through a family check `vm_fulfillment_plan.py` calls and
      section 8's bare-metal plan will call. (D19)
      Done: `check_relay_usable(relay_id, fields)` in `relays/pool_relays.py`,
      over the execution read, which now carries the active key's
      `grant_key_id` (never the key). VM's `AnsiblePoolConfig` gains
      `grant_key_id`. The VM plan's own missing-field list is replaced by the
      family check.
- [x] 5.9 Refuse placing a host in a relay-backed pool when its connection address
      equals that relay's normalized address, and refuse setting a relay's address to
      the connection address of a host in a pool referencing it, naming the host and
      the relay; register the check with the family's host pool-change hooks
      (`RELAY_HOST_POOL_CHANGE_HOOKS`) and the relay update. (D19)
      Done, with two changes to the plan's means:
      - **The address comes from the codec.** The host authority treats a
        connection envelope as opaque, so the family cannot read `ssh_host`.
        `ConnectionCodec` gains `address(envelope)`, and `ConnectionCodecs`
        delegates to it; `SshConnectionCodec.address` returns `ssh_host`.
        This is the Ansible distribution's one version bump on this branch
        (0.6.0 → 0.7.0); the service's floor on it rises to 0.7.0 because the
        service composes that codec.
      - **The hooks are built from the codecs.** `RELAY_HOST_POOL_CHANGE_HOOKS`
        became `relay_host_pool_change_hooks(codecs)`, returning the rebinding
        hook and the management-route hook. The container builds one
        `connection_codecs` for the host authority, its hooks, and
        `RelayService`, which now takes `connection_codecs` (required). Its
        `update_relay` refuses moving the relay onto a served host's address
        with `ManagementRouteRefused`, which the route answers with 409.
      - **Beyond the plan:** a host placed at registration or by an inventory
        creating it now runs the pool-change hooks as a move from no pool.
        Before, only a move of an existing host ran them, so registering a
        host straight into a relay-backed pool skipped the check. The host
        route answers a refused registration with 409.
      - **Not covered:** a connection change on a host already placed, and a
        pool gaining a relay reference over its existing members. The
        requirement names two write paths, placing a host and setting a
        relay's address, and both are covered. These two other paths can
        still reach the forbidden state, and are recorded for the owner to
        decide.
- [x] 5.10 Tests. Unit (`provisioning/compute/tests/unit/`): the builder's header has
      exactly three members; its claims for a lease with a host, and for one without
      (no `sub`); `exp` is an integer equal to the stored expiry's UTC epoch seconds
      with the process time zone set to one other than UTC; `jti` is the owner id;
      a verifier written to D16 in the test — signature, `typ`, `kid` as the
      thumbprint, integer `exp`, string `sub` and `jti`, no `iat` or `crit` — accepts
      the grant and refuses a tampered one. Library integration
      (`provisioning/compute/tests/integration/`): `grant_expires_at` rounded up; the
      quarantine, including a raised margin reaching a released lease; a re-tenancy's
      grant carrying the new reservation as `jti`; the grant signed again on a retry
      with the then-active key and its id recorded; no grant in persisted parameters;
      a retired key's `grants_valid_until` across a job retried over a rotation.
      Application integration through the typed client
      (`provisioning/compute/service/tests/integration/`): a fulfillment refused for a
      relay with no active key; a host placement refused for its pool's relay address,
      and a relay address change refused for a placed host's address; the holdings read
      showing grant expiry and key id; a relayed job read, after success and after a
      failure past writing its variables, carrying no grant, token, or admin password.
      Done.

      Unit, `tests/unit/test_relay_grants.py`:
      - The header has exactly its three members, and the claims of a lease
        with a host and of one without (no `sub`) are as specified, serialized
        as canonical JSON.
      - `exp` is the stored expiry's UTC epoch seconds with the process time
        zone set to America/New_York, where a naive `timestamp()` differs.
      - A verifier written to D16 in the test (signature, `typ`, `alg`, `kid`
        equal to the key's `kid`, no `crit`, integer `exp`, string `sub` and
        `jti`, no `iat` or `nbf`) accepts the grant and refuses a tampered
        claim and another key's signature. That `kid` is the RFC 7638
        thumbprint is section 4's RFC 8037 test. A lease with no expiry is not
        signed.
      - `grant_expiry` rounds up to the second. `check_relay_usable` names the
        relay and its missing active key, and a disabled relay lacks
        everything.

      Library integration (`provisioning/compute/tests/integration/`):
      - `test_relay_port_allocator.py::TestGrantExpiryAndQuarantine`: the
        expiry rounded up, and a zoned lease end stored as UTC; a lease cut
        short holds its port, another is issued; the margin holds a port past
        its expiry; a raised margin reaches a lease released before it, and
        the old margin frees it; a re-tenancy replaces the grant fields.
        The allocator's existing tests use a long-past lease end, so their
        released ports are free at once.
      - `test_relay_administration.py::TestGrantsAtExecution`, through
        `RelayExecutionResolver`:
        - the grant's header, claims, and signature under the active key, the
          input parameters untouched, and the lease recording the key;
        - a retry after a rotation signs with the new key and records it,
          while the retired key's `grants_valid_until` is the lease's expiry
          and is none once the lease is released; a lease allocated after
          the retirement does not extend it;
        - no `sub` without a host, and a re-tenancy's `jti` is the new
          reservation;
        - no active key, no held lease on the port, or a lease another
          reservation holds (or a job naming none) fails the job, the last
          recording no key; a removal needs no grant;
        - the holdings record's grant fields.
      - `TestManagementRoute`, through the hooks and `update_relay` over a
        test codec: a host reached at its pool's relay address is refused,
        normalized and naming both; a host reached another way is placed; a
        relay is not moved onto a placed host's address.
      - `test_host_authority.py`: a placement at registration or inventory
        creation runs the hooks, and a refused one stores nothing.
      - Ansible unit: `SshConnectionCodec.address` is `ssh_host`, not
        `public_host`.

      Application integration through the typed client
      (`provisioning/compute/service/tests/integration/`):
      - `test_fulfillment_api.py`:
        - a relay with no active key is refused on validation, naming the
          relay and the key, and on begin, with no port held;
        - the failed-create test now reads the holdings after its create ran
          past writing its variables. The lease's `grant_expires_at` is the
          committed lease end plus the grace, and its `grant_key_id` is the
          relay's active key. No job read or log carries the token or a
          grant's fixed prefix;
        - a relayed create that succeeds (every job of its reservation
          succeeded) recorded the active key on its lease, and no job read or
          log carries the token or the grant's prefix.

        The harness's fake runner returns fixed output that never echoes the
        variables, so the log assertions show the grant and token stay out of
        the persisted parameters and the job read. They do not show the
        executor's redaction of printed output. That rests on the names being
        in the codec's `secret_fields` (VM codec unit test) and on the
        executor's own redaction tests.
      - `test_vms_api.py`: an operator's relayed create naming a port another
        reservation holds fails, naming the relay and port, with no key
        recorded on that lease; the failed job's read and logs carry no token.
      - `test_relay_migrations.py::TestTheLeaseGrantMigration`: a database
        with the grant-key migration recorded, and not the lease one, gains
        the lease columns.
      - `test_host_pool_moves_api.py`: placing a host at its pool's relay
        address is refused with 409, naming both, by registration, by
        inventory import, and by an update; a relay is not moved onto a
        placed host's address.
      - `test_authority_composition.py` (unit): the host authority carries
        both relay hooks over the codecs the relay service shares, and the
        allocator reads both settings.

      Not shown: the admin password in a job read. No job carries it as a
      variable yet; sections 6–7's tasks read it on the host, and its
      variable is among the redacted names (VM codec unit test).
- [x] 5.11 Verify. `make test-compute-provisioning` (unit, library integration),
      `make test-provisioning` (application integration through the typed client),
      `make test-provisioning-adapter`, `make test-compute-provisioning-contracts`,
      `make test-compute-provisioning-client`; `make test`; `make check-packaging`
      (`rfc8785` at runtime). End-to-end: none in the pipeline — no lane runs a
      relay-backed pool; the real lanes (sections 11 and 12) and the live run
      (section 16).
      Results:
      - `make test-compute-provisioning` 451 passed (unit and library
        integration);
      - `make test-provisioning`: service unit 609, application integration
        528 passed;
      - `make test-provisioning-adapter` 222 passed;
      - `make test-compute-provisioning-ansible` 135 passed;
      - contracts 128 passed, client 74 passed;
      - `make test-bare-metal` passed (193, 543, 30, 90);
      - `make lock` run; `make test` passed; `make check-packaging` OK;
      - `make check-change` fails only on the four citations of files
        sections 10–12 create.

      End-to-end scenarios confirmed: none in the pipeline runs a relay-backed
      pool, so none signs a grant.

  Section 5 handoff:
  - Section 8's bare-metal plan calls `check_relay_usable` and
    `reservation_lease_end`, and passes `lease_ends_at` to allocation.
    `BareMetalJobParams` gains the resolver's fields, `relay_grant` included.
    Its codec calls `resolve_into(params, remote_port=<its leased port>,
    owner_id=<the capacity reservation id>)`; without the reservation every
    grant is refused. It also adds `RELAY_SECRET_VARIABLES` to its secret
    fields.
  - VM's `reserved_var_keys` is computed from unresolved parameters, so a
    pool's `extra_vars` naming `frp_auth_token` or `relay_grant` is not
    refused at preparation. That gap predates this change, and section 7,
    which rewrites VM's relay variables, may close it.
  - The relay-variable names in `relays/variables.py` are what VM's playbook
    reads today, or will read. Sections 6–7 settle the roles' inputs and
    change the names there if they differ.
  - The real VM lane (section 11) shows whether a deal's reservation carries
    a lease end when fulfillment begins. Preparation refuses a relayed create
    without one.
  - Fresh-context check, run once over the section's whole diff. It fixed:
    - grants signed for any held lease on the port, now only the job's
      reservation's;
    - the activation race, closed by the `FOR UPDATE` read;
    - the lease columns folded into section 4's committed migration, now
      their own migration;
    - five comments that described a plan or were wrong;
    - two import orders, and the time-zone test's restore;
    - three tests' assertions;
    - overstated notes.

    Declined: the two management-route paths the requirement does not name
    (5.9, "Not covered"), recorded for the owner.

    A narrower second run over the fixes found no bug in them. It fixed the
    stale `owner_id` instruction above, the `FOR UPDATE` comment's claim on
    SQLite, two docstrings, an assertion that could not fail, two overstated
    notes, and the missing upgrade test from migration 002. Declined:
    seeding the lease and relay through the API in `test_vms_api.py` and the
    no-key fulfillment test. They follow the suites' existing helpers
    (`_relay_backed_reservation`, and `test_host_pool_moves_api.py`'s seeded
    lease), and driving a whole fulfillment in a VM-route test would test
    fulfillment.

- **Implementation triage of the whole change (reviews 65 and 70, validations 67
  and 71, owner's notes 68), made with the change archived.**
  - 65 F1 / 70 F1, closing 5.9's "Not covered" paths. `HostAuthority` gains
    connection-change hooks, run when a placed host gets a new connection by an
    update or an inventory without a move; a move runs the pool-change hooks,
    which see the new connection. Their refusal, `ConnectionChangeRefusedError`,
    is a `PoolChangeRefusedError`, so every host route and the import answer 409.
    The relays contribute `relay_host_connection_change_hooks`. `set_pool_relay`
    takes the connection codecs and checks every host the pool holds against a
    newly referenced relay. The composition root hands them through both
    runtimes to both pool-config handlers. A handler built without codecs
    refuses a relay for a pool holding hosts rather than skipping the check. The
    pools routes answer `ManagementRouteRefused` with 409. The spec's
    management-route requirement names all four writes, with two new scenarios,
    and the host-authority requirement names the connection-change hooks.
  - 65 F2 / 70 F2. `RelayPortAllocator` refuses a negative grant grace and a
    reuse margin that is not positive, naming the setting, so the service does
    not start with either. The settings comments, `DEPLOYMENT_AND_CONFIG.md`
    (with the grace's intended floor, stated rather than enforced) and the
    port-lease requirement say so, with a new scenario.
  - S16 (section 16's evidence against D9, the owner's item). Each D9 row is
    evidenced. `ROADMAP.md`'s Goal 1 no longer says the real lanes ran. An
    unowned gap row records that both real-provisioning modules have never run
    against a target.
  - 68 O1 and O2 were already fixed before this triage.
  - Checks:
    - `make test-compute-provisioning` passed (463): unit, plus library
      integration covering the hook mechanics, the pool-relay host check and the
      allocator refusals;
    - `make test-provisioning` passed (542): application integration through the
      typed clients, covering the update, import and both providers' pool writes
      refused with 409 and prior state kept; the composition unit tests cover the
      wiring and the settings refusals and boundaries;
    - `make test-provisioning-adapter` (284), `make -C domains test-bare-metal`
      and `make test-compute-provisioning-ansible` passed;
    - `make test` passed twice, the second time after the fresh-context fixes;
    - `make check-packaging` and `make check-comment-hygiene` passed;
    - `make check-change` fails only its `openspec validate` of an active change,
      because the untracked `reviews/` still sit at the unarchived path. Strict
      validation of the permanent specs (`openspec validate --specs --strict`)
      passed, as did `make check-doc-citations`.
  - Fresh-context check: nothing blocking. Fixed: the host-authority
    requirement did not name the new hooks; two overclaiming comments; a stale
    module docstring; an unneeded package export; the allocator refusal tested
    only through the container (now also directly); a repeated comment clause;
    and a paragraph's wrap. Recorded, not fixed:
    - Two concurrent writes, a connection edit and a pool relay change, can
      still reach the forbidden state on a database without row locks, as the
      existing relay-address and placement pair could. The spec makes no
      concurrency claim.
    - Re-importing an inventory now refuses one whose existing placed host
      already breaks the rule.

## 6. The family relay roles: one verified frp, the admin API locked down, and a relay that discloses nothing

Delivers D3 (the family project, the role search path, 28 F5, and `relay-server`
disclosing no secret), D4, D22, and the `no_log` half of 28 F3: "The buyer-facing
tunnel client is hardened on every host", "Hosts and relays run frp from one verified
pin", and the secret half of "A relay prepared by the family role runs admission and
discloses no secret" (its plugin install is section 14's). Replanned against the
reviewed design: `frp-binary` and `relay-server`'s secret handling are new, and the
roles take no image (D23).

Files: `provisioning/compute/iac/` (new: `pyproject.toml`, `Makefile`, `tests/`, lock,
`ansible/roles/{frp-binary,relay-client,relay-proxy,relay-server}/`,
`ansible/playbooks/relay-server.yaml`); `domains/vms/provisioning/iac/ansible/`
(`roles/frp-setup/` and `playbooks/frp/` leave, `ansible.cfg`); the root `Makefile`;
`provisioning/compute/service/Dockerfile` and `Dockerfile.dockerignore`.

- [x] 6.1 Create the IaC project `provisioning/compute/iac/` — `pyproject.toml`
      (`package = false`), `Makefile`, `tests/`, lock — following
      `domains/vms/provisioning/iac/`, and wire its tests into the root
      `test-provisioning-iac` target, so the aggregate `make test` and CI's
      `test-provisioning-iac` job run them. (D3; `docs/development/ARCHITECTURE.md`
      "Build, packaging, and initialization": aggregate targets run every included
      subproject's tests)
- [x] 6.2 Add `frp-binary`: defaults holding `frp_version: "0.61.1"`, `frp_archives`
      keyed by platform (`linux_amd64`, its official release URL and SHA-256), and
      `frp_install_root: /usr/local/lib/frp`, as D22 shows them. The digest is recorded
      from a download of the official archive, checked against the release's published
      checksum when recorded, and never read from that checksum at run time. The role
      refuses a version or platform with no digest, naming both; downloads the archive,
      checks its SHA-256 before extracting anything, installs the named binary at
      `/usr/local/lib/frp/<version>/<binary>`, skipping only when that exact path
      exists; and returns the path. (D22)
- [x] 6.3 Add `relay-client` under `provisioning/compute/iac/ansible/roles/`, from VM's
      `roles/vm-setup/tasks/frp-client.yml` and its templates: it includes `frp-binary`
      for `frpc`, and `frpc-buyers.service` runs the versioned path, never
      `/usr/local/bin/frpc`; the client renamed `frpc-buyers`
      (`/etc/frp/frpc-buyers.toml`, unit `frpc-buyers`), its configuration root-only,
      its admin API on a loopback port below 1024 (a variable with a privileged
      default) with a per-host password generated at preparation, and the relay address
      and token required inputs with no default, asserted. The frp version is part of
      the client's baseline, so a change restarts it. (D3, D4, D22)
- [x] 6.4 Add `relay-proxy` with *add* — check the client's baseline against the
      resolved relay and restart only when it changed, add a marked `tcp` proxy block
      with no load-balancer group (name, local address and port, remote port,
      `metadatas.grant`), reload through the authenticated admin API, and wait for the
      proxy to run — and *remove*, moving `remove_guest_proxy` from VM's
      `roles/vm-management/files/guest_teardown.sh`, which reloads and never restarts.
      Every task rendering, writing, sending, or reading the grant, the token, or the
      admin password sets `no_log`. (D3, D4, D16, 28 F3)
- [x] 6.5 Replace VM's `roles/frp-setup` and its playbook
      `playbooks/frp/frp-server-setup.yaml` with the family's `relay-server` and
      `playbooks/relay-server.yaml`: frps from `frp-binary` at its versioned path under
      a systemd unit; the relay token a required input with no default, never
      generated or printed; no debug output of credentials, no credentials file on the
      controller, no `set_stats` return, no dashboard with its nginx and certbot, and no
      reboot; `no_log` on every task rendering `frps.toml`; frps's `allowPorts`, its
      ufw rule, and fail2ban's ports from one variable, which must cover every
      issuer's range; a change to `frps.toml` or frps's version restarts frps. The
      plugin's install is section 14's. (D3, D20, D22; correction 13)
- [x] 6.6 Copy `provisioning/compute/iac` into the provisioning image and set
      `ANSIBLE_ROLES_PATH` to its roles (`provisioning/compute/service/Dockerfile`,
      `Dockerfile.dockerignore`); add the family roles' repository-relative path to
      the `roles_path` of `domains/vms/provisioning/iac/ansible/ansible.cfg`; keep the
      service's shared `ansible.cfg` free of domain paths. (28 F5)
- [x] 6.7 Tests in the family project, at the level `domains/vms/provisioning/iac/tests`
      holds: the role structure; `frp-binary` refusing an unknown version or platform,
      checking the digest before extraction, installing at the versioned path and
      skipping only when it exists, a failed digest installing nothing; every
      secret-bearing task's `no_log`; the admin port below 1024 and the password on
      every admin call; the proxy block `tcp` with no group; removal reloading and never
      restarting; `relay-server` requiring a token, with no task printing, writing to
      the controller, or returning a credential, and no dashboard, certbot, or reboot
      task; one variable feeding `allowPorts`, ufw, and fail2ban. Move VM's
      `test_frp_proxy_wait.py`, `test_cleanup_script_relay_teardown.py`, and the proxy
      half of `test_guest_teardown.py` here.
- [x] 6.8 Verify. `make -C provisioning/compute/iac test`, `make test-provisioning-iac`;
      `make test`; `make check-packaging` (the new project's lock). End-to-end: none —
      no pipeline lane prepares a host or a relay; the live run (section 16) is the
      evidence for `relay-client` and `relay-proxy`, and `relay-server`'s plugin
      install has its tests only (D23).
      Owed by validation: `tests.yml`, job `test · test-provisioning-iac` — its log
      shows the family project's tests run and pass beside VM's.

  Section 6 evidence and handoff:
  - The family IaC project is wired into root `test-provisioning-iac`, hence
    the existing `tests.yml` matrix job. `package = false` and its own lock
    keep it a test project rather than a distribution. The image copies the
    family tree and supplies `ANSIBLE_ROLES_PATH`; the shared service config
    has no domain path. VM's manual config gains the family role directory.
  - `frp-binary` defaults to linux_amd64 and accepts an explicit platform/map
    override. The retained official release archive bytes were hashed and
    matched to the published checksum rows; the defaults record the checksum
    file's digest. Runtime installation uses the pinned archive digest only.
    Native Ansible tests use synthetic local HTTP archives to prove unknown
    version/platform refusal before download, digest refusal before extraction
    with no installation, exact versioned-path skips, both binaries installed,
    and a management-path fixture left untouched. No archive is executed.
  - `relay-client` preserves proxy blocks while updating top-level connection
    fields, retains one generated per-host admin password, writes owner-only
    configuration, and rejects an admin port at or above the host's effective
    `ip_unprivileged_port_start`. The unit includes the versioned binary path;
    baseline or unit changes notify a restart. Local file integration proves
    password retention, distinct per-host passwords, configuration permissions,
    and preserved proxy content. Unit/restart wiring is checked structurally;
    no real systemd client was prepared by this section's tests.
  - `relay-proxy` takes `relay_proxy_action`, `relay_proxy_name` (the full
    proxy name), and, on add, `relay_proxy_local_ip`, `relay_proxy_local_port`
    (default 22), `relay_proxy_remote_port`, `relay_grant`, and the relay-client
    inputs. It writes a TCP proxy without a load-balancer group and authenticates
    every reload/status request. The native wait tests execute the shipped URI
    task against an authenticated HTTP stand-in, shortening retries and disabling
    `no_log` only for synthetic diagnostic results; structural tests independently
    require `no_log` in the shipped secret-bearing tasks. They prove status
    handling and authentication, not real frpc admission or carried traffic.
  - Every add/remove attempt installs the root-owned, owner-only helper at
    `/usr/local/lib/arkhai-relay/remove_proxy.sh`, exposing its path through
    `relay_proxy_teardown_library`. Generated cleanup scripts source it under
    `set -e` and call `remove_guest_proxy(config, full_name, reload_url)` as shell
    arguments. The helper reads the config's admin password, passes it through
    curl's stdin with bounded connection/request timeouts, and reloads only.
    Its exact markers are `# BEGIN/END ANSIBLE MANAGED RELAY PROXY <full_name>`;
    retry state is `<config>.reload-pending.<full_name>`. Success sets
    `GUEST_PROXY=absent` or `removed`; failed reload retains the record and fails.
    Library integration executes the shell against real files and authenticated
    loopback HTTP, proving neighbour/management preservation, missing-end refusal,
    absent configuration, and retry after a failed reload. Helper install ownership
    and ordering, and absence of restart commands, have structural coverage.
  - VM call sites and their cleanup-wrapper tests remain unchanged until section 7;
    this staging was accepted by the coordinating session under the delegated
    implementation authority. Family wait/removal coverage is present now, while
    the existing VM tests continue proving the old call sites. Section 7 removes
    the old embedded proxy function and switches generated cleanup scripts and
    ordinary teardown to the installed family helper. A missing required helper
    must fail cleanup. This section does not claim VM runtime has switched.
  - `relay-server` prepares native versioned frps, with a required supplied token,
    root-only config, no controller credential return/output, and one port-window
    variable for frps, ufw and fail2ban. Its structural checks and syntax check are
    evidence for these assets; native systemd installation and firewall changes
    were not run. The plugin installation remains section 14. The VM IaC README's
    removed-role paths and credential/dashboard procedures were reconciled now
    rather than leaving broken current references; broader promotion stays in 17.9.
  - Verification: the family suite passed 22 tests and 15 subtests; aggregate
    `make test-provisioning-iac` passed that suite and VM's 176 tests and 15 subtests.
    After adding the stable helper interface, the affected baseline/removal/asset
    suites passed 13 tests; unchanged installer/wait evidence is reused. The family
    native gate passed 10 tests with no skips using ansible-core 2.19.14 and
    ansible.posix 2.2.2. The added parse-only playbook separately passed syntax
    checking and imports every dynamic family task file. The gate's first local
    invocation used a bare interpreter without PyYAML; rerunning with the locked
    project's interpreter passed. No dependency was installed globally.
  - `make check-packaging` passed (including the new lock and architecture checks),
    `make check-comment-hygiene` passed, and `make check-change` passed. No dependency
    or lock input changed after packaging; subsequent helper and documentation edits
    have their affected focused/parse/change checks above. The full `make test` and
    independent fresh-context compliance/implementation review remain the single
    frozen sections 6–9 round checks under the accepted cadence, not claimed here.
    The image-based native aggregate is owed with section 7, when both domain call
    sites are wired; the local native run is not image validation.
  - End-to-end scenarios confirmed: no pipeline lane prepares a host or relay.
    Section 16 owes real client/proxy traffic and tenant checks, including refusal
    without the admin password and inability to bind its port as an unprivileged
    tenant. Native relay-server plugin installation has test-only evidence under D23.
    Owed by validation: `tests.yml`, job `test · test-provisioning-iac` — logs must
    show the family and VM IaC projects both run and pass. The workflow/job were
    checked against the matrix and the dispatchable workflow list.

## 7. VM's tasks on the family roles, and one relay block

Delivers D3 for VM, D12, and the codec half of 28 F3: "A relayed create reports its
relay under one block". Replanned against the reviewed design only in its references
to section 5's tasks.

- [x] 7.1 `roles/vm-setup` includes `relay-client` in place of `frp-client.yml`;
      `vm-create.yml`, `vm-undefine.yml`, and `vm-remove.yml` call `relay-proxy` with
      the guest's proxy and the job's grant; the old frp tasks, templates, and
      `restart frpc-vms` handler go, and VM's download of frpc with them (D22). (D3)
- [x] 7.2 Both create-fact variants print their relay block as `relay`; the codec
      (`domains/vms/provisioning/adapter/src/vm_provisioning_adapter/codec.py`) reads
      `relay`, its variables carry the grant (5.5), and its secret fields come from the
      family set (5.7); the mock output (`services/mock_output.py`) and the codec's
      tests (`tests/unit/test_vm_codec.py`, `test_vm_mock_output.py`) follow the
      shipped fact. (D12, 28 F3)
- [x] 7.3 Both domains' playbooks pass `ansible-playbook --syntax-check` under their
      own configuration and the image's environment (`make test-provisioning-iac-native`).
      (28 F5)
- [x] 7.4 Verify. `make test-provisioning-iac`, `make test-provisioning-adapter`,
      `make test-provisioning`; `make test-provisioning-iac-native` against a built
      provisioning image; `make test`. End-to-end: the VM lane (`e2e_deal`) exercises the codec
      through the mock profile's default output; no pipeline scenario runs a relayed
      create.
      Owed by validation: `tests.yml`, job `test · test-provisioning-iac` — the family
      project's and VM's IaC tests pass.

  Section 7 evidence and handoff:
  - VM host preparation includes `relay-client`; create includes `relay-proxy`
    with the exact name `vm-<guest>`, guest address, allocated port and the job's
    existing `relay_grant`. VM's duplicate binary download, baseline/proxy edits,
    status wait, templates, handler and overriding defaults are removed. The
    family owns the frp pin, privileged admin port and authenticated requests.
  - Create and remove install the family's `helper` task entry, exposing
    `relay_proxy_teardown_library` and the family configuration default. Generated
    cleanup scripts and the partial-create removal shell source that installed
    path, never a repository-relative family asset. They use the full proxy name
    and read the admin port from the root-only configuration, so standalone
    retries use the configured endpoint. Undefine calls the ordinary family remove
    role after its running-guest refusal. Failed proxy removal stops all three
    paths; pending records use `frpc-buyers.toml.reload-pending.vm-<guest>`.
  - Partial-create removal now applies proxy removal before undefining the domain
    or deleting storage. It still refuses an unattributable firewall rule before
    removing anything. Shell integration uses the shipped installed library with
    stateful process-boundary stand-ins: failed reloads retain pending evidence,
    retries reload even with no proxy block or domain, missing required helpers
    fail cleanup, and neighbouring guests, management configuration, shared NAT
    and unrelated rules remain. The existing undefine running-guest refusal is
    checked structurally for ordering; these tests do not create real guests or
    establish real SSH sessions.
  - Both create facts, the codec's result/detail and evidence reader, and the mock
    output now use `relay`. Codec unit coverage follows that contract. Historical
    migration fixtures retain their legacy `frp` key: those migrations read the
    old persisted format independently of the current codec. The existing execution-time grant
    resolution and `VM_SECRET_FIELDS` union with `RELAY_SECRET_VARIABLES` are
    unchanged and covered by the adapter suite. Shell tasks that invoke the
    credential-reading helper set `no_log`.
  - Default `make test-provisioning-iac` passed: family 13 tests with 10 native
    skips, VM 165 tests and 2 subtests with 3 native skips. Native evidence comes
    separately from `make test-provisioning-iac-native` against a freshly built
    provisioning image: all 3 VM native tests and all 10 family native tests
    passed with no skips. The VM native cases render both shipped relay fact
    variants and exercise the shipped family-role include with a controlled role
    at that boundary; they do not install a real client or carry traffic.
  - The native aggregate now consumes the image's packaged trees, not checkout
    bind mounts. It parsed all six VM playbooks under VM's configuration and the
    image's shared service configuration, both family playbooks, and bare metal's
    existing node-access playbook under its own and shared configurations. The
    shared configuration remains free of domain paths. To satisfy 7.3 before 8,
    bare metal gains its minimal role-search configuration now; other Ansible
    defaults, including host-key checking, are unchanged. Section 8 still owns
    bare-metal relay runtime/host-preparation wiring. The built image's actual
    ansible-core 2.19.14 and ansible.posix 1.5.4 passed; no collection pin changed.
  - `make test-provisioning-adapter` passed 222 tests. The provisioning service
    unit suite passed 609 tests. The application integration run passed 527
    tests and failed the historical relay-result migration fixture after that
    fixture was mistakenly renamed to `relay`. Restoring its original `frp`
    format left the fixture unchanged from HEAD, and the affected migration
    module then passed all 15 tests. The unaffected passing cases are reused;
    the broad service command's initial nonzero exit is not relabelled a clean
    full rerun. `make check-packaging`, `make check-comment-hygiene` and
    `make check-change` passed. The first focused IaC attempt caught an overly broad deletion of the
    UFW helper while extracting proxy code; the UFW helper was restored before
    the passing run. No dependency or lock changed. The full `make test` and
    independent combined compliance/implementation review remain the single
    frozen sections 6–9 round checks under the accepted cadence.
  - Deployment prerequisite: the source rename does not retire an already
    installed `frpc-vms` unit or convert its proxy markers/cleanup scripts. On a
    previously prepared host, drain and inspect owned buyer state, retire that
    old buyer unit/configuration, and prepare `frpc-buyers` before new buyer
    qualification. Preserve the separate management client. No production host,
    relay or service was changed by this section's checks.
  - The inherited extra-variable reservation gap described in section 5 remains:
    unresolved parameters do not reserve late relay credentials. This section
    changes no pool-variable policy; the combined review should assess the new
    family-role input names alongside that existing guard.
  - End-to-end scenarios confirmed: `e2e_deal` exercises the codec through default
    mock output; no pipeline scenario runs a relayed create. Section 16 owes real
    buyer traffic, session survival and management-tunnel preservation. Owed by
    validation: `tests.yml`, job `test · test-provisioning-iac` — both the family
    and VM IaC projects must run and pass. The existing VM pipeline's native gate
    additionally exercises the built image. This section claims no deployed or
    pipeline evidence.

## 8. Bare-metal relay access and host preparation

Delivers D1 and D3 for bare metal: "A bare-metal grant on a relay-backed pool
delivers a leased port". Replanned against the reviewed design only in its references
to section 5's tasks.

- [x] 8.1 `BareMetalFulfillmentPlan.prepare_create` leases a port through the
      acceptance session when the pool references a relay, passing the reservation's
      lease end and the host as VM's plan does (5.1), and refusing an unusable relay
      through the family check (window, token, active key; 5.8); `prepare_teardown`
      reads the relay from the lease. A pool with no relay prepares as today. (D1)
- [x] 8.2 `BareMetalAnsibleCodec` carries the relay reference and leased port in
      `BareMetalJobParams`, which gains the resolver's relay fields, `relay_grant`
      included, so the execution resolver fills the relay's address, token, and grant
      at execution (5.5); it names the family's secret variable set among its secret
      fields (5.7), and delivers `ssh -p <leased port> <tenant>@<relay address>` from
      the lease for a relayed grant; a grant with no relay delivers the host's buyer
      route as today (`grant_evidence`). The mock output (`services/mock_output.py`)
      follows. (D1, 28 F3)
- [x] 8.3 The `bare-metal-access` role calls `relay-proxy` *add* for a relayed grant,
      proxying `127.0.0.1:22`, and *remove* on reclaim, never touching the management
      client. (D1, D3)
- [x] 8.4 Add `domains/bare_metal/provisioning/iac/ansible/playbooks/host-kit/`
      with a host-preparation playbook applying `relay-client`, and an `ansible.cfg`
      whose `roles_path` names the family roles. (D3, 28 F5)
- [x] 8.5 Tests. Unit (`domains/bare_metal/provisioning/adapter/tests/`): the plan's
      lease and its refusals; the codec's relayed and unrelayed evidence and its
      redaction. Role assets
      (`provisioning/compute/service/tests/unit/test_bare_metal_ansible_assets.py`):
      the relay proxy on grant and reclaim, and the host-kit playbook's syntax.
      Application integration through the typed client: a relayed bare-metal
      fulfillment leases a port, its grant job's read carries no grant or token, and
      its release returns the port; a fulfillment on a pool whose relay has no active
      key is refused.
- [x] 8.6 Verify. `make test-bare-metal`, `make test-provisioning`,
      `make -C provisioning/compute/iac test`; `make test-provisioning-iac-native`;
      `make test`.
      End-to-end: the bare-metal lane (`e2e_bare_metal_mock_deal`) on a pool with no
      relay; no pipeline scenario runs a relayed grant.

  Section 8 evidence and handoff:
  - The bare-metal plan leases through the shared allocator in the acceptance
    session, recording host, pool, owning reservation and the reservation's
    scheduled lease end. Validation checks usability and expiry without taking
    a port. Reclaim resolves its relay from the active lease, clears its remote
    port and execution-only fields, and signs no grant. Direct pools keep their
    existing buyer-route evidence.
  - `BareMetalJobParams.capacity_reservation_id` is the signing owner; it is
    separate from the commercial `escrow_uid`. Persisted parameters hold only
    the relay reference and leased `remote_port`; address, token and grant are
    filled in an execution copy. The family resolver explicitly supports
    dataclasses and frozen Pydantic models, rejects unsupported objects and
    undeclared resolved fields, and preserves the input snapshot. The actual
    bare-metal model runs through application execution; VM's actual dataclass
    is covered by its relay-pool integration module. Both production composition
    and the integration harness pass the same allocator/resolver to bare metal.
  - The codec renders `relay_id`, `bare_metal_remote_port`, the family client
    inputs and `relay_grant`, and uses `RELAY_SECRET_VARIABLES`. A relayed grant
    requires its printed `relay` block to name the job's own leased port; the
    block supplies the relay address and the fact confirms the tenant. Its
    default mock, like VM's, has no execution-resolved address and therefore
    needs an explicit relayed-output boundary for a relayed case. The new
    application module supplies that controlled renderer; it does not claim
    that mock output registered a real proxy or carried traffic.
  - The role calls family `relay-proxy` with exact name
    `bm-<bare_metal_ssh_user>`, add target `127.0.0.1:22`, the leased remote port
    and execution grant. Reclaim removes this proxy before account lookup,
    including compensation where no account was created. Includes apply become
    and delegation to the selected host, with `no_log`. The separate management
    client is untouched. `playbooks/host-kit/host-setup.yaml` applies
    `relay-client`; the role-search configuration added in section 7 is retained.
  - Section 9 remains unimplemented: activity termination and removal of the
    existing swallowed lock/delete failures still belong there. The separate
    bounded working-data helper remains inactive; this section adds no data,
    IPC, identity-ledger or account-policy integration. The signing owner's
    reservation identity is available for that later integration, independently
    of the tenant name and commercial escrow identity.
  - Coordinator-authorized scoped context loading was used for this bounded
    assignment, reading the governing ownership, secrets, test, packaging,
    configuration and promotion guidance, applicable change decisions and
    requirements, completed handoffs and touched code. Literal full-document
    read compliance and personal owner reading are not claimed.
  - Shared cleanup follow-up for section 9: the coordinator reported a
    controlled real-frp observation where deleting protected client configuration
    left a live proxy forwarding while the helper reported it absent. Both the
    installed helper and `relay-proxy/tasks/remove.yml`'s early missing-config
    success need a focused refusal/read-error regression before the frozen round
    can qualify reclaim. This section does not fix or claim that missing-config
    path. No live host was changed by this section's tests.
  - Evidence: adapter unit/controlled-runner tests 109 passed before the
    final redaction case; family unit/library integration 454 passed, followed
    by the final resolver database module's 80 passes; actual VM relay-pool
    library integration 9 passed. The affected service run had 42 passes and one
    incorrect assertion expecting the sanitized begin error to name the missing
    key. The corrected relay application module passed both cases, checking the
    named issue through typed validation and 422 through begin. Final service
    composition/assets unit checks passed all 10 cases. These results do not
    relabel the initial nonzero service command a clean full rerun.
  - Family IaC default checks passed 13 tests with 10 native skips. Separately,
    `make test-provisioning-iac-native` passed against the newly built section
    image's packaged trees, without checkout mounts: VM 3 and family 10 native
    tests, no skips. All six VM playbooks passed under their own and shared
    configurations; both family playbooks and bare metal's node-access and new
    host-kit playbooks passed their configuration checks, with both bare-metal
    playbooks also parsed under the shared service configuration. Ansible was
    2.19.14 with ansible.posix 1.5.4. This proves local role boundaries and syntax,
    not real proxy traffic or host preparation. Only Python formatting/docstring
    cleanup followed that image build; the IaC and runtime behavior inputs are
    unchanged. Final `make check-packaging`, comment hygiene and
    `make check-change` passed.
  - `make test-bare-metal` passed: IaC helper checks 95 passed with 4 native
    cases deselected, domain 224 passed, storefront 557 passed, buyer 30 passed,
    and final adapter 110 passed, including the executor redaction case. The
    deselected helper-native cases are not activity-termination evidence and the
    helper remains inactive. No dependency or lock changed. The broad provisioning
    service suites are not repeated: affected bare-metal application and
    composition checks above supplement section 7's unchanged passing cases.
    The full `make test` and one independent combined compliance/implementation
    review remain the frozen sections 6–9 checks under the accepted cadence;
    there was no per-section fresh-context review and no owner-reading claim.
  - End-to-end scenarios confirmed: `e2e_bare_metal_mock_deal` remains the direct
    mock-profile lane; no pipeline scenario runs a relayed bare-metal grant or
    prepares a host. Section 16 owes real grant/reclaim, access revocation and
    management preservation. Owed by validation: `tests.yml`, job
    `test · test-provisioning-iac` — family and VM IaC projects must run and pass;
    the VM pipeline's native gate additionally checks the built image. Permanent
    D1/D3 behavior and rationale destinations remain 17.9's physical-provisioning
    spec/architecture and seller guides; promotion follows the reviewed code.

## 9. Reclaim ends the tenant's activity

Delivers D15: "A bare-metal reclaim ends the tenant's activity" and the modified "A
bare-metal reclaim tolerates an account its grant never created".

- [x] 9.1 In `roles/bare-metal-access/tasks/main.yml`, where the account exists and
      after the key is removed: end its sessions (`loginctl terminate-user`) and
      lingering (`loginctl disable-linger`), kill what remains (`pkill -KILL -u`),
      remove its crontab and `at` jobs, and only then keep, lock, or delete it. Drop
      `failed_when: false` from the lock and delete; fail the reclaim when a process of
      the account survives. The reclaim fact reports what was ended. (D15)
- [x] 9.2 The codec keeps the reclaim result diagnostic and records the new fact
      fields as detail. (D15; "A bare-metal reclaim's printed fact is a diagnostic")
- [x] 9.3 Tests (`test_bare_metal_ansible_assets.py`, the codec's tests): the order of
      the reclaim tasks, no swallowed failure, the absent-account path unchanged, the
      fact's new fields read.
- [x] 9.3a Correct the shared runtime-removal proof in
      `provisioning/compute/iac/ansible/roles/relay-proxy/files/remove_proxy.sh`
      and `tasks/remove.yml`: refuse missing/unreadable/failed configuration
      observations without discarding pending reload evidence. Gate VM's partial
      fallback, generated cleanup and undefine callers on codec-owned accepted
      `vm_relay_required`, reserved against provider extra variables. Add helper,
      actual task and caller regressions for both relay-required failure and
      explicit direct cleanup. This corrects the existing proven-runtime-cleanup
      requirement; it adds no migration framework.
- [x] 9.4 Verify. `make test-bare-metal`, `make test-provisioning`;
      `make test-provisioning-iac-native`; `make test`. End-to-end: `e2e_bare_metal_mock_deal` runs
      its reclaim through the mock profile's output; the live run (section 16) shows a
      real reclaim.

  Implementation scope clarification: `tenant_activity.py` is a Python 3.10+
  host command barrier, copied by the bare-metal role after key revocation and
  before account policy. Its activity diagnostics remain unchanged codec detail;
  they are not release evidence or protected receipts. The legacy absent-account
  role path still succeeds after required relay cleanup. A root-only explicit
  numeric-UID seam accepts identity supplied by a separately authorized caller
  after NSS disappearance; it creates no identity/receipt authority. Existing
  inactive working-data/UID/IPC helpers remain untouched. Focused helper and
  service/adapter checks plus native packaged role tests and packaging precede
  this section's commit. The single full suite and independent combined review
  remain the frozen sections 6–9 round checks under delegated cadence.
  Permanent promotion stays with 17.9: the physical-provisioning spec's reclaim
  activity and proven proxy removal requirements, its architecture's proof-driven
  release and buyer-access explanation, and operator prerequisite guidance.

  Implementation notes / handoff:
  - `tenant_activity.py` is installed root-owned and owner-only at
    `/usr/local/lib/arkhai-tenant-activity.py`. The ordinary invocation is
    `python3 <helper> <account> <observed_uid>`; it rejects a changed or conflicting
    NSS identity and refuses UID zero. A separately authorized protected-receipt
    caller may use `python3 <helper> --trusted-uid <account> <receipt_uid>` after
    NSS disappearance. That path ends observed session IDs, stops the UID's user
    manager, removes that account's linger marker and verifies both UID process
    classes. Missing-name cron/at state is never recreated: retained spool evidence
    fails closed. This is an explicit execution seam, not receipt authentication,
    allocation, reuse policy, or role activation. The ordinary role still skips
    the helper for absent accounts; the later bounded cleanup integration must
    deliberately compose the receipt authority and numeric seam.
  - The helper removes the crontab and attributable at jobs and independently
    observes processes, sessions, the user manager, lingering and scheduled state.
    Missing `atq` requires an inactive/absent `atd.service` plus inspection of
    supported queue/spool directories. Missing `crontab`, or absent NSS in numeric
    mode, requires absent named cron spools. Unreadable state and command failures
    fail the barrier; a bounded five-second settling window handles asynchronous
    process/systemd exit. Unit tests use injected command boundaries and a zero
    settling window for survivor cases. Python 3.10 parsing, import and construction were checked with the
    host interpreter; there is no host dependency on tomllib or third-party Python
    packages. No real tenant termination is claimed by these controlled tests.
  - Key revocation now precedes the barrier for every account policy, including
    deletion. Lock/delete use normal Ansible failure behavior. The result's
    `activity` object records `tenant_uid`, `sessions_ended`, `linger_disabled`,
    `processes_killed`, `crontab_removed`, `at_jobs_removed` and
    `activity_terminated`. Matching reclaim facts remain unchanged diagnostic
    detail; failure/success and capacity release still depend only on job status.
  - Shared removal reads and validates the protected configuration before accepting
    known absence, and refuses a missing/unreadable file or failed cat/grep/awk
    observation. Pending reload records survive failures. Valid no-marker/no-pending
    calls remain idempotent, and a failed reload still retries before success.
    This corrects section 6's earlier absent-configuration evidence rather than
    adopting it as a runtime absence proof. VM's generated cleanup, fallback and
    undefine skip relay work only on explicit accepted `vm_relay_required=false`;
    the codec always emits/reserves this key, so provider extras cannot override
    required cleanup. Manual callers default to requiring cleanup. The running-
    guest undefine refusal still precedes relay removal. Management and neighbour
    state remain outside this guest's removal.
  - Focused evidence: VM adapter unit/library checks 225 passed; bare-metal adapter
    unit/controlled-runner checks 110 passed; bare-metal IaC default helper checks
    114 passed, with four inactive working-data native cases deselected. These
    include 19 activity-helper unit cases, not real systemd/process termination.
    Composed service checks (assets plus bare-metal mock profile, relay and lease
    release application integration) 29 passed; mocked teardown failure keeps
    capacity held. Unchanged domain/storefront/buyer and broad service evidence
    is reused from sections 7–8, not relabelled as new runs.
  - The first broader IaC run passed the family suite but failed four VM cleanup
    fixture cases: extraction began after the new condition, and a legacy case
    still expected filesystem absence to imply direct mode. Corrected extraction
    and explicit direct-mode input passed all 50 affected cleanup/caller cases;
    the final clean aggregate passed family 16 (13 native skips) and VM 168 with
    two subtests (three native skips). The separate shared helper's final six
    file/HTTP regressions passed, including failed observation and retained
    pending evidence. A separate unprivileged collection-only uv probe could not
    write its cache; the authorized project runs above succeeded. One workflow-log
    read accidentally used system Python 3.10 and lacked tomllib; rerunning with
    the declared toolchain succeeded. Host-executed activity code does not import
    tomllib.
  - The final `arkhai:compute-provisioning-relay-section9-final` image was rebuilt
    after the last runtime/fixture edits. `make test-provisioning-iac-native`
    passed VM three and family 13 native cases with no skips from its packaged
    trees, with no checkout mounts: actual Ansible covers missing/unreadable
    config refusal, the absent-account role under all policies, and a failing
    activity command stopping before account policy. All six VM playbooks, both
    family playbooks and both bare-metal playbooks passed their configuration
    syntax checks, including shared service configuration. Ansible was 2.19.14
    with ansible.posix 1.5.4. Preliminary image checks also passed, but the final
    image is the current-assets evidence. These are local role/boundary checks,
    not native systemd host qualification, real proxy traffic, or hardware proof.
  - `make check-packaging` and `make check-change` passed, including architecture,
    comment hygiene, citations and strict OpenSpec validation. No dependency/lock
    input changed. Scoped context loading followed the coordinator's assignment;
    literal full-document reading, personal owner reading and a per-section
    fresh-context review are not claimed. The single full `make test` and combined
    independent compliance/implementation review remain the frozen sections 6–9
    round checks. No later section, live host, hardware, deployment or working-data
    role integration was started.
  - End-to-end scenarios confirmed: `e2e_bare_metal_mock_deal` exercises mock-profile
    reclaim and codec output only; no current pipeline scenario executes this real
    activity barrier or a relayed bare-metal reclaim. Section 16 still owes real
    termination, access revocation and management preservation. Owed by validation:
    `tests.yml`, job `test · test-provisioning-iac` — family and VM IaC must both
    run and pass; the VM pipeline's native gate must additionally check its built
    image. The controlled local results are not deployed or pipeline evidence.

### Role-input authority correction

- [x] Reserve family proxy action/identity/targets and runtime client controls in
  `provisioning/compute/src/compute_provisioning/relays/variables.py`; apply them
  to VM preparation and shared execution rendering, including stored extras.
- [x] Test VM create/teardown preparation, stored VM execution, bare-metal strict
  preparation/parameters, typed application refusal, and harmless native Ansible
  role-call precedence. Preserve unrelated provider options and inventory/host
  preparation settings; do not change Ansible's operator CLI authority.
- [x] Focused checks: VM codec/plan 208 passed; bare-metal codec/plan 99 passed;
  shared renderer 36 passed, including four harmless native Ansible add/remove
  probes for both domain identities; typed application rollback five passed.
  The native probes use newly rendered variables against Ansible 2.19 from the
  existing controlled image; they assert role inputs only and execute no real
  proxy operation. Comment hygiene and `make check-packaging` passed. The initial
  native-test signature collection error and reinit argument error were corrected
  before these results. The repository-wide citation scan finds three unrelated
  missing paths in other active changes; scoped citations are checked separately.
  Full suite, corrected CI, and integration into the validation head belong to
  the coordinator's frozen-source round, not these focused checks. Promote
  the authority clarification to the permanent physical-provisioning contract
  during closeout; completed sections above remain historical evidence.

## 10. The real-provisioning target, version 2

Delivers D5, D6's target half, and D7: the modified "A real-provisioning target is a
typed, versioned settings section".

- [x] 10.1 Replace the VM-only target reader with
      `e2e-tests/src/e2e_harness/real_provisioning_target.py`: section `REAL_PROVISIONING_TARGET`, profile
      `real-provisioning-target`, version 2's hosts with their domain, connection,
      access (relay by id, or direct with `public_host`), capacity, VM
      `listing_shape` fitting twice, and bare-metal `physical_host_id` and
      `ssh_host_public_key`; refuse version 1 with the conversion message, two hosts
      of one domain, and a field foreign to a host's domain or mode. (D5, D7)
- [x] 10.2 Replace the committed example `config-real-vm-target.yml.example` in
      `e2e-tests/config/` with `config-real-provisioning-target.yml.example`
      (documentation addresses and invented names, said so), and the ignore rule in
      `e2e-tests/.gitignore`. (D5)
- [x] 10.3 Tests. Unit (the planned `test_real_provisioning_target.py` module under `e2e-tests/tests/unit/`,
      replacing `test_real_vm_target.py`): every refusal names its field; a listing
      shape not fitting twice names the dimension; version 1 refused.
- [x] 10.4 Verify. `make test-e2e-unit`; `make test`. End-to-end: none; the real
      lanes read it.


### Target-profile build-context safeguard

Follow-up to 10.2: `.dockerignore` must exclude the renamed local target as well
as the retired filename, preserving the existing image boundary when
`e2e-tests/Dockerfile` copies its configuration directory. The committed example
remains in the image. This is a private-input exclusion correction, not a new
target format or a change to the scenario's behavior. Completed tasks above are
preserved.

An actual Docker build/COPY component check used visibly synthetic target files
and the same configuration-directory COPY. Before the correction the current
local filename entered the result; after it, both current and retired local
filenames were absent while the committed example remained. Fixture containers
were never started, and only their temporary contexts, containers and images
were removed. This check used a separate daemon, leaving the frozen source
validation undisturbed. It proves the build-context exclusion, not a leak from
an already-built image: the actual operator profiles remain outside this
checkout. Packaging, change/citation, privacy and diff checks passed. A bounded
fresh-context compliance check found only the initially missing evidence note,
now recorded here. No runtime, dependency, lock or scenario changes were made;
no hardware proof or second full-suite run is claimed. No end-to-end scenario
exercises an ignored local target in a build context; the dedicated component
check supplies that evidence.

### Section 10 handoff

The target reader, ignored profile and visibly fictitious example now use
`REAL_PROVISIONING_TARGET` version 2. The retired real target filename also remains
ignored, so an operator's unconverted private file cannot become an accidental
Git addition; this does not retain a version-1 reader. Typed discriminated hosts and access modes
refuse foreign fields, duplicate domains and a VM shape exceeding half the host's
capacity. Legacy version 1 and the old section name fail with field-mapping and
profile instructions. Each lane selects its domain explicitly; absent configuration
or an absent domain remains a named skip, while malformed configuration fails.
Existing VM consumers were migrated minimally so removing the retired module does
not break collection. The example defaults VM access to direct, and the VM fixture
refuses relay before any mutation until the next section implements that path.
Relay validation, listing-shape use and concurrent deals
remain section 11. Existing operator instructions and citations now describe the
actual target format; broader relay/operator promotion remains section 15 and
closeout.

`make test-e2e-unit` passed all 389 unit tests, including the version/domain/mode,
profile-loading and two-shape refusal cases plus existing VM lane coverage.
`make check-packaging` passed. The initial change check found a task citation to
the retired target module; it was corrected to the replacement and the final
`make check-change CHANGE=prove-relay-provisioning` passed. The lead fresh-context compliance check found the initial default example
offered relay before its runtime was implemented; the example, early preflight
refusal and operator prose were corrected, with an explicit refusal regression.
No finding was declined. No dependency or lock changed. Full `make test` and combined independent implementation review remain
frozen-round gates under the owner-authorized cadence; they were not repeated for
this intermediate section. This is configuration/source evidence, not hardware
or relay-traffic evidence. No end-to-end marker alone exercises the target reader;
real lanes consume it, and live evidence remains section 16. Owed by validation:
no additional push-only workflow beyond the normal frozen-round pipeline.

## 11. The real VM lane over a relay

Delivers D6's lane half, D8, D9's lane evidence, and D11's heartbeat session: the
modified "A real-provisioning VM scenario proves delivery on a real host".

- [x] 11.1 The real VM driver
      (`e2e-tests/tests/e2e/roles/scenarios/vms/real_compute_deal_driver.py`) reads its
      host from version 2, publishes `listing_shape`, registers its pool with
      `provider_config.relay_id` under relay access, and before writing anything reads
      the relay and requires it enabled with a token and an active grant key; under
      relay access the delivered address is the relay's and the port the leased one.
      Adoption compares against `listing_shape`. (D6, D7)
- [x] 11.2 Add the heartbeat session to `e2e-tests/tests/e2e/roles/helpers/ssh_access.py`:
      one `ssh` process printing the time each second with `ServerAliveInterval`, its
      liveness and longest gap readable, closed on demand. (D8, D11)
- [x] 11.3 Add the second-deal stages to
      `e2e-tests/tests/e2e/roles/scenarios/vms/test_real_provisioning_deal.py` between
      the first deal's access checks and its expiry: open the heartbeat; the second
      deal (negotiate, escrow, settle, create-job poll, active, access at its own port);
      the heartbeat across the create; the second deal cut short, its teardown-job poll,
      its capacity released and its port shown released by the holdings read; the
      heartbeat across the proxy removal, then closed. Each new field has one producer
      stage. (D8, D9)
- [x] 11.4 Check host connectivity through `GET /api/v1/hosts/{id}/connectivity` before
      and after each create and teardown. (D9, 8.4)
- [x] 11.5 The finaliser recovers both deals: it cuts short each live lease, confirms
      each guest gone, and names what it cannot confirm. (D8)
- [x] 11.6 Tests. Unit (`e2e-tests/tests/unit/test_real_vm_lane.py`,
      `test_compute_deal_stages.py`, `test_ssh_access.py`): the stage set's order and
      producers, the relay checks, the heartbeat's gap detection, recovery of two deals.
- [x] 11.7 Verify. `make test-e2e-unit`; `make test`. End-to-end: `e2e_vm_real_provisioning`, in no
      lane, skips without its target; the live run (section 16) runs it. The pipeline's
      lanes must still pass with the real module skipping.


### Section 11 handoff

The VM lane reads its domain's version-2 host, publishes its explicit guest
shape while declaring unchanged whole-host capacity, and reconciles an existing
listing against that guest shape. Relay access reads the configured relay before
worker holds or registration and again before supply writes, requires its identity,
enabled state, configured token and active grant key, and stores only `relay_id`
in the pool's provider configuration. The shared executor registration helper now
forwards explicit provider metadata; omitted metadata preserves existing callers.
Delivered relay addresses and ports are checked against the reservation's active
holding, and release checks retain the original grant expiry and refuse an active
owner on the same port; immediate reuse is not required.

One SSH process emits timestamps across the second deal's create and teardown.
Its reader drains output independently while jobs are polled, observes local and
remote gaps, requires the process still alive, and fails a gap over five seconds.
It is reaped on demand and by the run's SSH owner even after a failed stage. The
second deal's negotiation, escrow, submission intent, fulfillment, guest and access
have explicit producers; its normal expiry and teardown are followed by a guest
list, access refusal, relay holding and a returned-shape reservation. The first
guest remains active during that check and subsequently proves ordinary expiry
and whole-capacity return. Management connectivity is checked before and after
each create/teardown. The finalizer attempts both accepted deals even if one
recovery fails and reports both failures; no fleet-wide release is used.

Accepted D7a resolves a real contract conflict: the shared ready stage assumed a
whole-capacity deal and required a closed listing, which would make the second
negotiation impossible. Its explicit driver expectation is now `closed` for the
existing whole-capacity mock lanes and `open` for this smaller real VM deal. The
stage remains defined once and unchanged across its callers; no duplicate or
fallback implementation was added. The design records the rationale and permanent
destination. The current operator instructions describe the actual target and
lane; detailed relay installation/admission documentation remains section 15.

The final `make test-e2e-unit` passed all 405 unit tests (including controlled
subprocess SSH substitutes, not real SSH traffic). These cover stage order and
state producers/consumers, relay preflight refusals, typed pool request composition,
listing adoption, explicit ready-stage expectations, leased-port identity and
release evidence, both-deal recovery, and deterministic FIFO-driven heartbeat
gaps/EOF. An actual aggregate executor-registration test found a misrouted helper
argument during the source check; it was corrected, and the pool/host/async site
composition regression passed. Earlier runs are retained as failed evidence:
12 stale stage/fixture assertions, then two positional fixtures, then one missing
mock method spec; the last 405-test run is the passing source candidate. A later
typed pool test initially supplied a flat hint rather than the canonical family
shape; it was corrected to consume `capacity_source_for`, and its affected module
passed all 69 tests before the final whole harness run.

`make check-packaging` passed; no dependency, lock, package-layout or install inputs
changed in subsequent test/doc/helper-signature corrections, so that evidence is
reused. `make check-change CHANGE=prove-relay-provisioning` passed, including
comment hygiene. The no-target marker invocation completed with 47 explicit skips
and 645 deselections before any stack write; these skips are not live passes.
No physical guest or relay was exercised by this section. End-to-end coverage is
`e2e_vm_real_provisioning`, outside all default lanes, with actual execution owed
by section 16. Validation must still show every normal pipeline lane passes with
this real module skipping. Owed by validation: no extra push-only workflow beyond
the normal frozen-round pipeline. Full `make test` and one combined independent
review remain the frozen sections 10–13 gates under the owner-authorized cadence;
no additional broad per-section review was run. The lead accepted the D7a seam
correction and requested this consolidation; personal owner reading and prior
round formal triage are not claimed complete.

## 12. The real bare-metal lane

Delivers D10 and D11's pinned mode: "A real-provisioning bare-metal scenario proves
relay access on a real host".

- [x] 12.1 Add a pinned `known_hosts` mode to `ssh_access.py`. (D10, D11)
- [x] 12.2 Add the real bare-metal driver
      (the planned `real_compute_deal_driver.py` module under `e2e-tests/tests/e2e/roles/scenarios/bare_metal/`)
      implementing `ComputeDealDriver` without `MockGates`: it registers, from the
      target, a backed pool delivering and advertising bare metal with
      `provider_config.relay_id`, the host with its connection, and the declaration; it
      checks the relay as 11.1 does. (D10)
- [x] 12.3 Add the planned `test_real_provisioning_deal.py` module under `e2e-tests/tests/e2e/roles/scenarios/bare_metal/`,
      marker `e2e_bare_metal_real_provisioning` registered in `e2e-tests/pyproject.toml`
      and in no lane: every shared stage; bare metal's publication, listing-closing,
      and evidence-publication stages, adopting the open listing on its resource as
      D10 settles; the executor-real check; the settlement-preview host check;
      grant- and reclaim-job polls; tenant access with a key generated for the run at
      the delivered relay string and an unrelated key refused, the host key pinned
      from the target; connectivity checks; after release the string refused and the
      holdings read showing the lease released; a finaliser that cuts the lease short
      and names what it cannot confirm. (D10)
- [x] 12.4 Tests. Unit: the bare-metal real lane's stage set against the shared stages
      (`test_compute_deal_stages.py`), the driver's registration and relay checks, the
      pinned mode.
- [x] 12.5 Verify. `make test-e2e-unit`; `make test`. End-to-end: `e2e_bare_metal_real_provisioning`,
      in no lane, skips without a bare-metal host in its target; the live run (section
      16) runs it.

### Section 12 handoff

The opt-in `e2e_bare_metal_real_provisioning` module runs every canonical shared
stage and no mock stage. It validates the target's OpenSSH host key, real executor
and relay before any hold or supply write; reconciles a backed pool, management
connection and whole-machine declaration; adopts one open listing matching the
host/physical identity/shape; waits for actual grant/reclaim jobs; uses a generated
buyer key with the pinned host key and rejects an unrelated key; checks management
continuity and reservation-owned relay delivery/release with retained quarantine.
Its failure finalizer expires only its own lease and names unconfirmed recovery.
Before deployment, the operator must pause admission and reconcile older
resource declarations/pools/listings on that physical host. The lane refuses a
conflicting declaration instead of deleting or silently reassigning it.

Shared real observations moved into
`e2e-tests/tests/e2e/roles/helpers/real_provisioning.py`; VM keeps its imported
aliases and uses the same implementation. Gate-free bare-metal commercial/lease
methods are in its driver base. Domain publication-close/evidence bodies moved
to `publication_stages.py`, reused by mock and real scenarios; source checks now
resolve those inherited bodies so producers remain verified. Public listing
payloads intentionally carry no opaque resource id: adoption checks the target's
host/physical identity/shape after the declaration guard, and settlement still
requires the exact owned resource. Host-key parsing lives in
`e2e-tests/src/e2e_harness/ssh_host_key.py`, shared by target validation and the
pinned SSH mode. The committed key is an explicitly labelled RFC8032 offline
fixture, never a runtime key.

Focused harness evidence: the initial run passed 408 and failed two source-stage
checks while the extracted domain bodies were not yet included in their resolver;
after correction 441 passed. The expanded final run passed 451 tests (14.27s),
including typed pool/host/declaration composition, no-write refusal, stale and
ambiguous listing refusal, exact relay ownership, conservative/owned recovery,
pinned first-contact rejection and actual pytest fixture order. These are harness
unit/component-boundary tests, not a running application or hardware proof.
After import/constant cleanup, 170 affected tests passed; after harmless Unicode
comment normalization and the final owned-truncation assertion, all 238 affected
target/SSH/VM/bare-metal/stage tests passed (8.58s). Unchanged broader-suite
evidence is retained rather than relabelled as a new full run.
The no-target invocation reported 38 explicit skips / 273 deselected (1.00s),
with no holds or supply mutation. `make check-packaging` passed with transient
files on owned private-home storage; the earlier sandbox marker ENOSPC occurred
before its read command, and no passing tests were repeated for that disk remedy.
`make check-change` passed; final task-note/index checks are recorded with commit.

The owner-authorized cadence consolidates fresh-context compliance and independent
implementation review into the frozen sections 10–13 round, with full `make test`
and pipeline validation there. No broad extra section review or full repository
run is claimed. Section 16 still owes actual-host grant/reclaim, SSH, refusal and
released-holding evidence. The normal pipeline must collect this new marker as
opt-in/skipped without a target; it is added to no lane. Owed by validation: no
additional push-only workflow beyond that frozen-round pipeline.

## 13. One SSH helper

Delivers D11: "Real-lane SSH access goes through one helper".

- [x] 13.1 Move `e2e_bare_metal_deal`
      (`e2e-tests/tests/e2e/roles/scenarios/bare_metal/test_bare_metal_deal.py`) onto
      `ssh_access.py`'s pinned mode and its refused classification, keeping its
      behaviour; reduce `e2e-tests/tests/e2e/roles/helpers/bare_metal_access.py` to its
      purchase helpers. (D11)
- [x] 13.2 Tests. Unit: `test_ssh_access.py` covers the classification
      `bare_metal_access.py` had; a source check refuses an e2e scenario building its
      own `ssh` command.
- [x] 13.3 Verify. `make test-e2e-unit`; `make test`. End-to-end: `e2e_bare_metal_deal`, in no lane,
      keeps its configuration and skips without it.

- [x] 13.4 Keep marketplace credentials and EVM wallet inputs independent in
      the shared VM and bare-metal fixtures and their scenario consumers.
      `vms/conftest.py` reads optional buyer/seller marketplace schemes and
      seller credential, plus registry authority scheme; existing defaults
      remain EIP-191. Bare-metal conftest and its real module read optional
      `buyer_wallet_private_key`, falling back to the existing buyer credential.
      Test real signer/trust/typed-client composition with deterministic offline
      Ed25519 principals and a separate EVM wallet; preserve local defaults.
      Document the profile contract in the harness README. Focused E2E unit,
      packaging and change checks precede the intermediate commit; the frozen
      candidate still owes combined review/full validation and actual-host proof.

### Handoff — section 13

The installed bare-metal buyer scenario now maps its authenticated access view to
`SshEndpoint` and delegates execution and judgment to `ssh_access.py`. Its supplied
known-hosts file remains read-only and strict, and its supplied buyer key and
`BARE_METAL` configuration are unchanged. Each observation uses one fresh process
with no retry; only public-key authentication refusal establishes revocation.
The shared helper owns the probe marker and classification. The purchase helper
contains purchase/recovery behavior alone. Source tests reject literal SSH
builders in scenarios and other helpers, including builders passed to execution
wrappers, while allowing publication access-method data. This is a structural
regression check, not general analysis of arbitrary runtime command values.

Focused evidence: `make test-e2e-unit` passed all 462 tests (11.19s), including
both real-lane callers, pinned invocation, prior classification cases, one-shot
accepted/refused/transport/timeout behavior, and planted source-guard failures.
The initial run passed 460 and failed one newly added refused-result fixture
because it supplied the fake executable's exit code under the wrong field;
correcting that fixture and adding timeout coverage produced the passing run.
The first installed-marker smoke invocation skipped because its executable was
not on PATH. With the prepared executable on PATH, `e2e_bare_metal_deal` explicitly
skipped for absent `BARE_METAL.REGISTRY_URL`: one skipped / 310 deselected (2.45s).
No machine was contacted or purchase attempted. Packaging passed; final
comment-hygiene, citation, task/index and OpenSpec checks accompany the commit.

The owner-authorized frozen sections 10–13 round still owes the independent
implementation review, full `make test` and pipeline validation. Earlier 6–9
formal joins/personal reading remain pending. No new broad section review or
physical qualification is claimed. Owed by validation: the normal pipeline must
collect the installed marker as opt-in/skipped without configuration; configured
real purchase/access/release proof remains in section 16.

### Follow-up handoff — fixture identity and wallet separation

The lead verified that the controlled EVM settlement fixtures could not safely
reuse a service's existing Ed25519 marketplace principals: VM consumers assumed
EIP-191, and bare metal reused its marketplace seed as an EVM wallet key.
The accepted correction stays inside the harness. Shared VM signer/publisher
selection, registry trust, explicit buyer-principal consumers and introduction
CLI profile generation now honor optional marketplace/authority schemes.
Seller marketplace credentials fall back to the prior private key. Administrator
and service signer inputs remain separate. Bare metal's shared and real buyer
configurations read the same optional EVM key, with the prior credential fallback
for existing profiles. `e2e-tests/settings.toml` declares the defaults and
`e2e-tests/README.md` owns the exact external-profile contract. Nothing changes
service trust, retained state, public buyer APIs or payment architecture.

The initial new focused test passed two cases and reported four fixture errors:
it supplied deterministic Ed25519 seeds as hex rather than the identity kit's
canonical unpadded base64url. After correcting those fixture values,
`make test-e2e-unit` passed all 468 tests (12.47s). Six new cases load profiles
through the real external `CONFIG_DIRECTORY` boundary and compose actual typed
storefront, registry and site clients; they check exact Ed25519 signer/publisher
and registry principals, separate EVM key/address/RPC inputs in both real and
shared bare-metal fixtures, and unchanged local/docker defaults. No network or
machine is contacted. `make check-packaging` passed using owned temporary
storage; change/comment-hygiene/citation/task checks passed and the final staged
public-content check accompanies the commit.

This is an authorized intermediate source correction. The frozen final candidate
still owes combined independent review, full `make test`, pipeline validation and
actual-host purchase/access/release proof. Earlier formal joins/personal reading
are not advanced by these checks; no configured deployment is claimed.

## 14. The admission plugin on a relay, and the signer against its vector

Starts once `admit-relay-proxies-by-grant` is archived and `dev` merged in, so the
tool `frp-grant-admission` is on this branch. Delivers D18's conformance and pins
checks, D23's install, and D19 and D20's relay side: "A relay prepared by the family
role runs admission and discloses no secret", "Every relay proxy carries a signed
grant" (scenario "The signer is checked against the plugin's vector"), and "Hosts and
relays run frp from one verified pin" (the pin equal to the tool's). Replanned against
the reviewed design: a wheel and hash-pinned requirements, not an image; the
configuration taken as the plugin's own file; signing cases and the thumbprint, not
verdicts.

Files: `provisioning/compute/iac/ansible/roles/relay-server/` and the project's
`tests/`; `provisioning/compute/tests/unit/` (the vector check);
`provisioning/compute/iac/tests/` (the pins check).

- [x] 14.1 `relay-server` installs the plugin as a plain program from inputs it is given
      and never builds or fetches — `frp_grant_admission_wheel`,
      `frp_grant_admission_requirements` (hash-pinned, exported from the tool's lock),
      and `frp_grant_admission_config` (the plugin's own TOML, D20): it requires
      `python3` 3.11 or later on the relay, creates a virtual environment under
      `/opt/frp-grant-admission`, installs the requirements with `--require-hashes`
      and then the wheel with `--no-deps`, and runs the plugin as its own unprivileged
      user under a unit templated from the tool's systemd example. (D23)
- [x] 14.2 `relay-server` checks the configuration with the plugin's `check` before
      installing it, failing without replacing the running configuration when it does
      not load; writes it root-owned and readable by the plugin's group under
      `no_log`; and reloads the plugin on a change without restarting frps. frps
      gains the `[[httpPlugins]]` entry — `path = "/"`, `ops = ["NewProxy"]`, the
      plugin's loopback address — which restarts frps once. (D23; "A relay prepared
      by the family role runs admission and discloses no secret")
- [x] 14.3 The vector check (`provisioning/compute/tests/unit/`): it reads the tool's
      published vector (its `vector/frp-grant-1.json`) in place; for every signing case
      the family's header-and-claims signer (5.3), given the case's key, header, and
      claims, produces exactly the case's token, and the thumbprint case equals the
      family's key-id derivation (4.1). It runs no verification case. (D18)
- [x] 14.4 The pins check (`provisioning/compute/iac/tests/`): `frp-binary`'s version,
      URL, and SHA-256 for `linux_amd64` equal the tool's `frp-pins.toml`. (D18, D22)
- [x] 14.5 Tests in the family IaC project: the plugin's install refusing a Python
      older than 3.11, installing with `--require-hashes` then `--no-deps`, its unit as
      an unprivileged user; the configuration checked before it is installed, under
      `no_log`, a change reloading the plugin and not restarting frps; frps naming the
      plugin for `NewProxy` only; both domains' and the relay playbook's
      `--syntax-check`.
- [x] 14.6 Verify. `make test-compute-provisioning` (unit), `make -C provisioning/compute/iac test`,
      `make test-provisioning-iac`, `make test-provisioning-iac-native`; `make test`.
      End-to-end: none in the pipeline; the live run's relay is containerised (D23),
      so `relay-server`'s plugin install has its tests and syntax checks only, and
      section 16 proves the image path.
      Owed by validation: `tests.yml`, job `test · test-provisioning-iac` — its log
      shows the family project's tests, the pins check included, run and pass.

### Section 14 handoff

The native relay role takes the operator's wheel, hash-pinned requirements and
TOML as controller-file inputs. Python 3.11 is required before environment
creation. Dependencies install with required hashes and binary distributions;
the supplied wheel installs without dependency resolution. Content fingerprints
select an immutable release under `/opt/frp-grant-admission/releases/`; they do
not authenticate the operator's wheel independently. A success receipt follows
both installs and non-writable program-mode normalization, including restrictive
umasks without following interpreter symlinks. The candidate program checks a
private staged configuration; publication uses those exact checked bytes, not a
second read of the controller file. Invalid candidates leave current selection
and configuration intact. Old releases are retained.

The dedicated service account is checked for non-root UID/GID before and after
creation; privileged existing identities are refused before modification. The
configuration is root-owned and group-readable. The unit follows the tool's
example with a static dedicated user/group, and frps wants it without coupling a
plugin restart to existing frps connections. Initial startup and program changes
start/restart the plugin; ordinary key/range/issuer changes reload the running
unchanged program. The role waits for its listener before preparing frps. An
existing listener relocation is refused before publication or program switching:
HUP does not rebind the tool's socket. D23 records the accepted separate drained
maintenance limitation and its permanent destinations. Section 15 must describe
`current`, fixed-listener reload, and the positional `check <path>` CLI.

The consumer test reads the published vector in place, reproducing all three
signing cases and the thumbprint through the family implementation, without
running verifier cases. The existing family pin test already compares the full
amd64 version/URL/digest tuple with the tool's pins; it is reused rather than
duplicated. `make test-compute-provisioning` passed 458 tests. Final family IaC
default checks passed 24 tests with 19 native omissions explicitly reported;
`make test-provisioning-iac` also passed the unchanged VM default suite's 168 tests
and two subtests, with three native omissions.

Native evidence is composed under the accepted reuse cadence. An earlier complete
`make test-provisioning-iac-native` passed three VM and 18 family native cases,
with no skips, and both-domain/shared syntax. After the program-mode and account
guards, the final packaged image passed all six affected installer cases with no
skips, plus syntax again. Byte comparisons bind the reused three VM and 13
unaffected family cases to 122 unchanged source/image assets; no claim is made
that the whole aggregate was rerun on the final image. The final installer cases
use real pip, virtual environments, hashes, Ansible and filesystem publication
with an operator-supplied fixture CLI. Synthetic ownership adaptation isolates the
fixture; a root-container check then drops to a distinct non-root UID/GID and
executes the installed program reading a root-owned group-readable configuration.
Account creation, systemd actions and dependency ordering have structure checks;
this is not a native systemd host or real admission-traffic qualification.

Initial IaC checks caught an unquoted colon-ended pip option interpreted as a YAML
mapping; it was quoted and the corrected/final checks passed. `make check-packaging`
passed on final dependency/installation inputs. Comment hygiene and change checks
passed; no dependency or lock changed. Per the owner-authorized cadence, full
repository testing and a combined independent review remain frozen-round gates;
no extra broad section review or personal owner reading is claimed. The source-only
assignment does not advance prior formal joins. End-to-end: none of the pipeline
lanes proves native relay installation; the containerized live path remains
section 16. Owed by validation: `tests.yml`, job `test · test-provisioning-iac`,
showing the family tests including the pin check; final candidate packaged native
and full pipeline evidence remain coordinated validation obligations.

## 15. Operator documentation

Delivers the operator procedures D4, D15b, D16, D17, D19, D20, D22, and D23 call for,
against the tool as archived. Replanned against the reviewed design: the procedures the
reconciliation and 55-design added.

- [x] 15.1 `docs/development/VALIDATION_RUNBOOK.md` §21–26 for target version 2 and
      relayed hosts. (D5)
- [x] 15.2 A new runbook section for relays, preparing them:
      - one relay per operator as the recommended deployment, each with its own token,
        and a shared relay's limits — one token for every client, rotation touching
        every operator's hosts, and ending one operator's sessions restarting the relay
        under everyone (D20);
      - a VPS relay with `relay-server`: building the wheel with the tool's
        `make build` and exporting its requirements with
        `uv export --frozen --no-dev --no-emit-project` until the move-out publishes
        them, the wheel being the operator's input, its dependencies checked against
        the lock (D23);
      - a containerised relay: the plugin's image pinned by revision as a sidecar in
        frps's network namespace, its configuration mounted read-only and reloaded by
        SIGHUP, beside the upstream frps image at the pinned version, with the same
        `[[httpPlugins]]` entry (D23);
      - the frp version, and drained changes to `frps.toml` or frps's version (D3, D22);
      - relay definitions with `grant_key_secret_key`, the key generated with
        `openssl genpkey -algorithm ed25519 -outform DER | base64 -w0` and kept in the
        secrets profile (D17);
      - the plugin's configuration: an issuer per relay with its audience, its range
        containing the relay's window, and its public keys; onboarding a site to a
        shared relay (its public key and assigned range); the drain rule for narrowing
        a range or removing a key or an issuer (D19, D20);
      - the relay's and the service's clocks kept synchronised, with skew under
        `relay_port_reuse_margin_seconds` (D16);
      - the admission check — an ungranted proxy refused, the plugin's refusal in its
        log — before a relay-backed pool first serves buyers and after any change to
        the relay's plugin configuration (D19).
- [x] 15.3 The relay section, operating them:
      - key rotation keeping the profile current: generate, put in the profile, point
        the entry's `grant_key_secret_key` at it, stage it, add its public half to the
        plugin, activate; when a retired key may leave the plugin (its
        `grants_valid_until`, matched by the thumbprint `check` prints); a key the
        service generated surviving only with the database (D17);
      - emergency rotation as a choice per incident: remove a compromised key at once,
        refusing that operator's buyers at their next reconnect until their leases end,
        or keep it until its leases end, an attacker holding it able to sign only within
        that operator's range and on its relay; a leaked token having no path short of
        draining every lease; the gap recorded (D17);
      - a host teardown cannot reach: on a host the operator can still reach,
        `systemctl disable --now frpc-buyers`; otherwise the relay-side step — the
        leased port blocked at the relay's firewall and its established connections
        ended with `ss -K state established '( sport = :<port> )'` (`NET_ADMIN` in the
        relay's network namespace; on Kubernetes an ephemeral debug container; one frps
        restart where `ss -K` is unavailable), or `allowPorts` and a restart where the
        operator controls frps but not the firewall; the block's record (port, lease,
        grant expiry) and its lifting only after the expiry has passed and the
        registration has cleared; the step ending access through the relay only, full
        revocation needing the host recovered and reclaimed; and who does what on a
        relay run for other operators (D16, 55 F1);
      - tracing a plugin log line's `jti`: the holdings read while the tenancy's row
        stands, `GET /contract/leases/{jti}` once it has been reused (D16, 55 F3).
- [x] 15.4 `docs/seller-frp-setup.md`: the `frpc-buyers` client, its versioned frp
      binary, and its locked-down admin API; one relay per operator, buyer-only by
      default, management ports on another relay; a shared relay's limits; what a
      relay must run (frps with the admission plugin, an issuer for the relay); the
      operator's management client with its admin API off or authenticated. (D3, D4,
      D19, D20, D22)
- [x] 15.5 `docs/bare-metal-seller-quickstart.md`: relay-backed bare-metal pools and host
      preparation; a tunnel-reached host in a pool with no relay must state a buyer
      route; what reclaim ends. (D1, D15, D15b)
- [x] 15.6 `e2e-tests/README.md`: the real VM and bare-metal lanes, their profile, and
      the target's version 2, in place of "Real VM provisioning". (D5, D10)
- [x] 15.7 Verify. `make check-doc-citations CHANGE=prove-relay-provisioning`, its only
      remaining matches being files this change has yet to create; every command and
      path the new runbook steps name resolves against this branch. End-to-end: none;
      section 16 runs the runbook's admission check and the lanes.

### Section 15 handoff

Operator procedures now describe the implemented target-v2 VM/bare-metal lanes,
independent marketplace identities and controlled Anvil wallets, and buyer-only
relay preparation/admission/rotation/containment. Native content-addressed
releases, exact checked config publication, dedicated non-root identity and
fixed-listener drained maintenance are explicit. Container deployment remains
operator-supplied; its live proof and native installer component checks are
separate scopes. No deployed admission, hardware qualification, owner reading
or triage advancement is claimed by this documentation slice.

Verification: scoped documentation citations and local Markdown links/anchors,
TOML examples and documented command/path/API seams checked against source;
`make check-change CHANGE=prove-relay-provisioning`, `make check-packaging`,
and staged public-content checks passed. These are documentation/packaging
checks, not application or system qualification. Full repository tests and an
independent review remain assigned to the frozen combined round under the
accepted cadence override. No runtime or dependency files changed.

End-to-end: no pipeline scenario proves operator instructions. The real markers
`e2e_vm_real_provisioning` and `e2e_bare_metal_real_provisioning` exercise the
lane behavior only when configured with real targets. Section 16 still owes the
deployed ungranted-proxy refusal plus both real lanes and management-client
observations. No new push-only workflow/job obligation is added.

### Shared-machine drain checklist correction

The combined implementation review found the force-release checklist named a
stale tunnel configuration and omitted the proxy-name prefix. It now names
`frpc-buyers.toml.reload-pending.vm-<guest>`, matching the family client default
and VM teardown's `vm-<guest>` proxy. The existing checked section remains intact.
This changes documentation only; unchanged packaging inputs reuse the section's
passing packaging evidence. The correction passes change/citation, privacy and
diff checks; deployed force-release verification remains an operator obligation.

## 16. Live verification [log]

The physical observations below are recorded through the accepted Arkhai method
and its shipped buyer plus independent typed operator observations. The live
relay path used the pinned container/plugin topology; native installer evidence
remains a separate scope. Raw operational output stays outside this public
repository. Literal original Alkahest markers remain unrun. Platform, configuration,
proof-method, review, validation and no-incoming-base joins are recorded for the
unchanged source candidate; documentation closeout is recorded below.

### Accepted Arkhai proof method on this branch

The owner selected Arkhai-only TEST qualification. The alternative method in
`openspec/changes/archive/2026-11-02-qualify-arkhai-real-provisioning/design.md#accepted-method-mapping`
is accepted for the unfinished live observations below. It drives the shipped
buyer CLI and independent typed operator observations, reusing neutral SSH and
bounded-data helpers without importing complete chain-specific pytest drivers.
The named original markers remain available; an unrun marker is never reported
passed. Completed source tasks and original implementation history are preserved.

- [x] 16.1 **[log]** Actual negative admission on each buyer relay: missing, invalid-
      signature, wrong-port and out-of-range grants were refused by both lanes
      with matching plugin decisions and zero backend connections. This covers
      negative admission only; genuine paid delivery is recorded below. The
      original marker was not run.
- [x] 16.2 **[log]** Equivalent Arkhai two-CPU-VM relay cycle: both rentals met the
      negotiated CPU/memory/disk shape; unrelated keys were refused; the first
      SSH heartbeat stayed open through the second create/release; both leases
      naturally expired; ordinary teardown ended sessions, denied fresh access,
      and restored full capacity. This controlled CPU pair supplements the
      separately completed external GPU VM journey. The literal
      `e2e_vm_real_provisioning` marker was not run.
- [x] 16.3 **[log]** The paired relay/direct runs recorded unchanged management and
      libvirtd generations; authenticated management SSH remained reachable at
      the checked boundaries. No management restart or loss of control was
      observed.
- [x] 16.4 **[log]** The direct two-CPU-VM pair completed the second deal while the
      first heartbeat stayed open, met its negotiated shape, refused unrelated
      keys, naturally expired both leases, ended sessions and fresh access, and
      restored full capacity. Management and libvirtd generations stayed
      unchanged. This is controlled-path compatibility evidence, not external
      relay proof.
- [x] 16.5 **[log]** The external bare-metal GPU journey used the pinned relay endpoint
      and nonroot account, performed checked GPU work, refused an unrelated key,
      completed ordinary bounded reclaim, denied fresh access and restored
      capacity with management continuity. The literal
      `e2e_bare_metal_real_provisioning` marker was not run.
- [x] 16.6 **[log]** Repeated canonical registration/import and actual publication
      adoption preserved listing identities, states and pauses, retained relay
      quarantine, and created no duplicate allocator, host, pool, resource or
      listing. Protected state remained unchanged.
- [x] 16.7 Bind exact source/artifacts/configuration/run/payment/reservation/
      jobs/grants privately to each item and sibling relay section 6/8 proof;
      record sanitized outcomes here. The completed join matches all three
      actual final rental grants to lease ownership, host, port, expiry,
      audience and trusted-key metadata, and binds the installed client and
      enforcing relay/plugin configurations to the actual negative and paid
      paths. No grant token is retained or replayed offline. A later port was
      allocated while two released grants were still quarantined until grant
      expiry plus the configured reuse margin. Under D9, sibling section 6.1's
      session-preservation requirement is met by D8 step 3: both captured CPU
      create jobs performed authenticated `/api/reload` while the original SSH
      process heartbeat continued. This is not a separate CLI reload test.
      Sibling section 8.6 is met by the released holdings retaining grant expiry
      with no competing lease; reuse after expiry is covered at integration
      level by the frozen allocator suite, not claimed as a physical exact-port
      reuse. No unrun original marker or failed/repaired attempt is labelled
      passed.

## 17. Closeout

**Closeout record (2026-11-02).** 17.1 `make check-comment-hygiene` passed; reviewed comments describe current invariants. 17.2 The independent source review confirmed touched imports remain at module scope or have a recorded rationale. 17.3 D1–D23 placements follow repository documentation ownership; no package ownership or new code requirement is promoted here. 17.4 Section 16's current handoff was condensed; detailed implementation/evidence history remains, while rejected alternatives and operational limits remain in `design.md`. 17.5 Goal 1 now records both relay-backed real lanes and preserves the host-key, shared-login, emergency-rotation and future wheel-digest gaps with their triggers; unrelated gaps remain. 17.6 The Reach-hosts campaign row is in closeout and its existing graph/dependent gates remain unchanged until archive cleanup. 17.7 Current-source validation records packaging and all five architecture checks passed; no owned exception or agent-guidance check applies. Final combined-document `make check-packaging`, comment hygiene and all five owning architecture checks also passed before commit; the initial sandbox cache-write failure was preserved and the unchanged-source run completed with writable cache access. 17.8 Current-source CI 41534499721 passed all 23 jobs and public-content CI 41534499619 passed. Frozen runtime validation reuses CI 41402761003 (23 jobs), E2E 41402755345 (145 VM, 65 bare-metal, 1 API-credit pass with six payment-prerequisite skips), composed local evidence across 20 prerequisites after the recorded aggregate environment failure, and the four-workload/14-scenario Helm result, with original exclusions preserved. Real relay and physical outcomes remain separate from pipeline evidence; original Alkahest markers remain unrun. 17.9 All architecture, deployment, testing, runbook and quickstart destinations are promoted below; both normative deltas merged at archive. 17.10 `make check-doc-citations` and pinned strict validation passed. 17.11 Pinned archive merged 13 additions, 5 modifications and one renamed requirement in `physical-provisioning`, plus 2 additions and 2 modifications in `test-compatibility`; post-archive checks passed.


Per `openspec/README.md#plan-closeout-requirements`, in that order; closeout changes
documentation only, and a part needing a code edit returns the change to
implementation. `admit-relay-proxies-by-grant` must be archived first.

- [x] 17.1 **Comment hygiene.** Run `make check-comment-hygiene` and confirm the comments
      this change added state invariants, not this change; anything to fix returns the
      change to implementation.
- [x] 17.2 **Import placement.** Confirm the imports this change added or touched are at
      module level unless a verified reason keeps one local; one to move returns the
      change to implementation.
- [x] 17.3 **Documentation compliance.** Re-check each decision's destination below
      against `openspec/README.md`'s placement rules.
- [x] 17.4 **Narrative compression.** Compress completed-task notes to final behaviour,
      material evidence, deferred work, and destinations, moving rationale into
      `design.md` first.
- [x] 17.5 **Roadmap currency.** `docs/development/ROADMAP.md`, "Goal 1 — Consolidate
      physical-resource authority in the provisioning service": the current state
      records buyer access through family-owned relays for VM and bare metal, with
      admission by signed grants; remove the gap row "No end-to-end lane runs a
      relay-backed pool"; add unowned gap rows for `host_key_checking = False` in the
      provisioning service's Ansible configuration (D4), for admission at login on a
      shared relay, with its trigger (D21), for emergency rotation of both relay
      credentials across live hosts — re-issuing grants under a new key and rotating
      the token, each dropping sessions once — with its trigger (D17), and for pinning
      the plugin wheel's digest in `relay-server` once a release is published (D23).
      The concurrent-allocation gap row, which
      names VM's provisioning owner as the allocator's, names the compute family's
      relays instead (found by section 1's fresh-context check). Name the update in
      the promotion record.
- [x] 17.6 **Campaign index currency.** This change's row in
      `openspec/changes/README.md` ("Reach hosts and VMs that have no inbound route"),
      its campaign graph, and its `Depends on` once `admit-relay-proxies-by-grant` is
      archived; other rows' `Depends on` stay. Name the update in the promotion record.
- [x] 17.7 **Packaging.** `make check-packaging` and
      `make check-architecture-change CHANGE=prove-relay-provisioning`.
- [x] 17.8 **End-to-end pipeline.** Record the passing run the latest validation names:
      the VM lane and the bare-metal lane (section 1.7's scenarios and
      `e2e_bare_metal_mock_deal`) passing with the real lanes skipping; the real lanes'
      evidence is section 16's.
- [x] 17.9 **Promotion.** Write the permanent documents and the design-promotion record:
      - D2, D3: `docs/development/ARCHITECTURE.md` "Family kits" (the compute family
        kit's relays and the family IaC roles); `openspec/specs/physical-provisioning/architecture.md`
        "Buyer access to provisioned hosts", covering the direct bare-metal fallback and
        relay routes for both compute domains, with host-level client configuration
        belonging to the host and family roles found through the role search path;
        `openspec/specs/resource-pool-management/architecture.md`, whose account of a
        relay-changing host move names the VM adapter as refusing it, where the
        family's relay pool-change hook now does.
      - D1, D15b: `physical-provisioning/architecture.md` "The host registry owns the
        connection".
      - D3, D4, 28 F3: `physical-provisioning/architecture.md` "The relay token never
        reaches buyer-controlled hardware", gaining the token's boundary on a host and
        secrets kept out of job logs by `no_log` and the family's secret fields.
      - D14, D16, D17, D19, D20, D21, D22, D23: a new
        `physical-provisioning/architecture.md` section "Relay admission by signed
        grants" under "Buyer access to provisioned hosts" — per-lease grants and their
        lifecycle, conformance to the tool specification (no `iat`, JCS signing, exact
        claims, reservation `jti`, thumbprint ids, public-key format), the vector and
        pins checks, relay keys with the
        profile's form and rotation keeping the profile current, admission on every
        relay as the operator's installation, one relay per operator and a shared
        relay's limits, the emergency choice per incident, the host- and relay-side
        steps for a host teardown cannot reach and their limit, one verified frp pin at
        versioned paths, how a relay runs the plugin, and the wheel as the operator's
        input; native immutable program selection, exact checked configuration bytes,
        protected service identity/modes and separate drained listener relocation;
        the relay-never-calls-SCM principle in
        `docs/development/ARCHITECTURE.md` "Authority boundaries".
      - D18: the principle that SCM does not own generic infrastructure that is not
        specific to it, and conforms to a standalone component's published interface,
        in `docs/development/ARCHITECTURE.md` "Package and dependency layers".
      - D2(b), 28 F4: `docs/development/DEPLOYMENT_AND_CONFIG.md` "Migrations at
        startup", beside the `hosts.gpu_count` drop.
      - D16, D17: `docs/development/DEPLOYMENT_AND_CONFIG.md` "Definition documents",
        `grant_key_secret_key` beside `token_secret_key`; "Secrets are named, not
        carried", the grant key's profile form; and a new subsection "Relay grants and
        port reuse" under "Definition documents" for `relay_grant_expiry_grace_seconds`,
        `relay_port_reuse_margin_seconds`, and the clock-synchronisation requirement.
      - D5–D11: `docs/development/TESTING.md` "The real-provisioning lane", covering
        both lanes.
      - The operator procedures: section 15's runbook and seller documents, already
        written; confirm they match the archived behaviour.
      - The behaviour itself: `openspec/specs/physical-provisioning/spec.md` and
        `openspec/specs/test-compatibility/spec.md`, written by the archive in 17.11.
- [x] 17.10 **Documentation citations.** `make check-doc-citations CHANGE=prove-relay-provisioning`,
      then `openspec validate prove-relay-provisioning --strict`.
- [x] 17.11 **Archival.** Pinned archive merged the deltas into `physical-provisioning` and `test-compatibility`; the index row targets the dated archive. `make check-change CHANGE=prove-relay-provisioning` passed after archival.
