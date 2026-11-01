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

- [ ] 4.1 `relays/keys.py`: load a private key from the profile's form — strip
      surrounding whitespace, decode single-line standard base64, load PKCS#8 DER with
      `cryptography`, and refuse anything that is not an Ed25519 key, the error naming
      what was wrong and never carrying the value; generate a key; derive a key's id
      as its RFC 7638 JWK thumbprint (base64url SHA-256 of
      `{"crv":"Ed25519","kty":"OKP","x":"<raw public key, base64url>"}`); encode a
      public half as single-line standard base64 of its DER SubjectPublicKeyInfo.
      `compute_provisioning` declares `cryptography` at runtime (it is a dev
      dependency today, 1.6). (D17)
- [ ] 4.2 Grant-key state on the relay in `relays/db.py`, with an additive migration
      in the service's `migrations.py`: the active key encrypted under
      `ssh_decryption_key` as the token is, its id, and its activation time; a staged
      key, encrypted, with its id; and a family table of retired keys, each with its
      relay, id, and retirement time. Ids are stored for active, staged, and retired
      keys alike. (D17)
- [ ] 4.3 The relay definitions document accepts and requires `grant_key_secret_key`
      on every entry, read once at creation as `token_secret_key` is and never
      restated for an existing relay. An entry naming none fails the import naming the
      entry; a named profile key with no value, or whose value 4.1 refuses, fails the
      import before any relay is created, naming the relay and the profile key and not
      the value. A relay created through the API with no key gets one the service
      generates. `settings.toml`'s relay definitions comment names the new field.
      (D17, D19)
- [ ] 4.4 *Stage* and *activate*, in `RelayService`, the route service, the contracts
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
- [ ] 4.5 Relay reads return `grant_keys` as D17 shows it — the active key's `kid`,
      `public_key`, and `activated_at`; any staged key's `kid` and `public_key`; and
      each retired key's `kid` and `retired_at`; its `grants_valid_until` reads
      the leases' grant expiry and is section 5's (5.6). No read, export, or
      reconciliation comparison returns a private key. (D17)
- [ ] 4.6 Tests. Unit (`provisioning/compute/tests/unit/`): 4.1's loader accepts the
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
- [ ] 4.7 Verify. `make test-compute-provisioning` (unit, library integration),
      `make test-provisioning` (application integration through the typed client),
      `make test-compute-provisioning-contracts`, `make test-compute-provisioning-client`;
      `make test`; `make check-packaging` (`cryptography` at runtime).
      End-to-end: none in the pipeline — no lane runs a relay-backed pool; the real
      lanes read the active key (sections 11 and 12).

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

- [ ] 5.1 `relay_port_leases` gains `grant_expires_at` and the id of the key that
      signed its latest grant, by an additive migration. Allocation records
      `grant_expires_at` in the acceptance transaction: the reservation's lease end,
      which the plan passes to allocation, plus the grace setting
      `relay_grant_expiry_grace_seconds`, rounded up to the whole second and stored as
      naive UTC like the table's other times. The setting is documented in
      `settings.toml` beside the relay settings, its default covering the lease
      watchdog's grace and a teardown's retries, as its comment says. A re-tenancy of a
      released row overwrites both fields. (D16 lifecycle 1)
- [ ] 5.2 The allocator does not reissue a released port until its `grant_expires_at`
      plus `relay_port_reuse_margin_seconds` (default 300, documented in
      `settings.toml` with the clock-synchronisation requirement) has passed, reading
      the margin when it selects a port, so a raised margin covers leases already
      released; a lease cut short leaves its port held back and allocation selects
      another. (D16 lifecycle 3; "Relay port leases are unique per relay", scenarios
      "A lease is cut short" and "The reuse margin is raised")
- [ ] 5.3 `relays/grants.py`: a header-and-claims signer — RFC 8785 JSON of each
      through `rfc8785`, unpadded base64url, joined with `.`, signed with an Ed25519
      private key through `cryptography` — with no JWT library. `compute_provisioning`
      declares `rfc8785` at runtime (the JCS library `kit/identity` uses).
      (D16 "Signing")
- [ ] 5.4 The grant builder: from a lease and the relay's active key, the header
      exactly `{"alg":"EdDSA","kid":<thumbprint>,"typ":"frp-grant+jwt"}` and the claims
      `aud` (the relay id), `port` (the leased port), `exp` (the stored
      `grant_expires_at` converted as UTC to its integer epoch seconds — never through a
      naive `timestamp()`), `sub` (the lease's host, omitted when it records none,
      never `null`), and `jti` (the lease's `owner_id`, always present); no `iat` and
      no `nbf`. (D16)
- [ ] 5.5 The execution resolver (`relays/execution.py`) signs the grant immediately
      before a job's variables are written, on every attempt, with the relay's
      then-active key, filling a `relay_grant` field the resolver's parameter
      contract gains beside `relay_token`, and records the signing key id on the lease;
      a relay with no active key raises `RelayUnusableAtExecutionError`. The grant
      never enters an accepted operation's persisted parameters. VM's job parameters
      (`models/jobs_model.py`) gain the field, and its codec writes it as the proxy's
      grant variable. Conformance to the tool's published vector is section 14's.
      (D16 lifecycle 2)
- [ ] 5.6 Relay reads report each retired key's `grants_valid_until`: the latest
      `grant_expires_at` among the relay's unreleased leases allocated before it was
      retired, or none when none remains; and the holdings read (`RelayLeaseRecord`,
      `RelayLeaseView`, field for field, per section 3's handoff) gains each lease's
      `grant_expires_at` and signing key id. (D17, 28 F2; D9)
- [ ] 5.7 The relay family supplies one set of the variable names carrying the grant,
      the relay token, and the client's admin password, and VM's codec takes its
      secret fields from it (`VM_SECRET_FIELDS`). (D3, 28 F3)
- [ ] 5.8 Fulfillment preparation refuses a pool whose relay holds no active grant
      key, naming the relay and the missing key, beside its refusals for a missing
      token or window, through a family check `vm_fulfillment_plan.py` calls and
      section 8's bare-metal plan will call. (D19)
- [ ] 5.9 Refuse placing a host in a relay-backed pool when its connection address
      equals that relay's normalized address, and refuse setting a relay's address to
      the connection address of a host in a pool referencing it, naming the host and
      the relay; register the check with the family's host pool-change hooks
      (`RELAY_HOST_POOL_CHANGE_HOOKS`) and the relay update. (D19)
- [ ] 5.10 Tests. Unit (`provisioning/compute/tests/unit/`): the builder's header has
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
- [ ] 5.11 Verify. `make test-compute-provisioning` (unit, library integration),
      `make test-provisioning` (application integration through the typed client),
      `make test-provisioning-adapter`, `make test-compute-provisioning-contracts`,
      `make test-compute-provisioning-client`; `make test`; `make check-packaging`
      (`rfc8785` at runtime). End-to-end: none in the pipeline — no lane runs a
      relay-backed pool; the real lanes (sections 11 and 12) and the live run
      (section 16).

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

- [ ] 6.1 Create the IaC project `provisioning/compute/iac/` — `pyproject.toml`
      (`package = false`), `Makefile`, `tests/`, lock — following
      `domains/vms/provisioning/iac/`, and wire its tests into the root
      `test-provisioning-iac` target, so the aggregate `make test` and CI's
      `test-provisioning-iac` job run them. (D3; `docs/development/ARCHITECTURE.md`
      "Build, packaging, and initialization": aggregate targets run every included
      subproject's tests)
- [ ] 6.2 Add `frp-binary`: defaults holding `frp_version: "0.61.1"`, `frp_archives`
      keyed by platform (`linux_amd64`, its official release URL and SHA-256), and
      `frp_install_root: /usr/local/lib/frp`, as D22 shows them. The digest is recorded
      from a download of the official archive, checked against the release's published
      checksum when recorded, and never read from that checksum at run time. The role
      refuses a version or platform with no digest, naming both; downloads the archive,
      checks its SHA-256 before extracting anything, installs the named binary at
      `/usr/local/lib/frp/<version>/<binary>`, skipping only when that exact path
      exists; and returns the path. (D22)
- [ ] 6.3 Add `relay-client` under `provisioning/compute/iac/ansible/roles/`, from VM's
      `roles/vm-setup/tasks/frp-client.yml` and its templates: it includes `frp-binary`
      for `frpc`, and `frpc-buyers.service` runs the versioned path, never
      `/usr/local/bin/frpc`; the client renamed `frpc-buyers`
      (`/etc/frp/frpc-buyers.toml`, unit `frpc-buyers`), its configuration root-only,
      its admin API on a loopback port below 1024 (a variable with a privileged
      default) with a per-host password generated at preparation, and the relay address
      and token required inputs with no default, asserted. The frp version is part of
      the client's baseline, so a change restarts it. (D3, D4, D22)
- [ ] 6.4 Add `relay-proxy` with *add* — check the client's baseline against the
      resolved relay and restart only when it changed, add a marked `tcp` proxy block
      with no load-balancer group (name, local address and port, remote port,
      `metadatas.grant`), reload through the authenticated admin API, and wait for the
      proxy to run — and *remove*, moving `remove_guest_proxy` from VM's
      `roles/vm-management/files/guest_teardown.sh`, which reloads and never restarts.
      Every task rendering, writing, sending, or reading the grant, the token, or the
      admin password sets `no_log`. (D3, D4, D16, 28 F3)
- [ ] 6.5 Replace VM's `roles/frp-setup` and its playbook
      `playbooks/frp/frp-server-setup.yaml` with the family's `relay-server` and
      `playbooks/relay-server.yaml`: frps from `frp-binary` at its versioned path under
      a systemd unit; the relay token a required input with no default, never
      generated or printed; no debug output of credentials, no credentials file on the
      controller, no `set_stats` return, no dashboard with its nginx and certbot, and no
      reboot; `no_log` on every task rendering `frps.toml`; frps's `allowPorts`, its
      ufw rule, and fail2ban's ports from one variable, which must cover every
      issuer's range; a change to `frps.toml` or frps's version restarts frps. The
      plugin's install is section 14's. (D3, D20, D22; correction 13)
- [ ] 6.6 Copy `provisioning/compute/iac` into the provisioning image and set
      `ANSIBLE_ROLES_PATH` to its roles (`provisioning/compute/service/Dockerfile`,
      `Dockerfile.dockerignore`); add the family roles' repository-relative path to
      the `roles_path` of `domains/vms/provisioning/iac/ansible/ansible.cfg`; keep the
      service's shared `ansible.cfg` free of domain paths. (28 F5)
- [ ] 6.7 Tests in the family project, at the level `domains/vms/provisioning/iac/tests`
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
- [ ] 6.8 Verify. `make -C provisioning/compute/iac test`, `make test-provisioning-iac`;
      `make test`; `make check-packaging` (the new project's lock). End-to-end: none —
      no pipeline lane prepares a host or a relay; the live run (section 16) is the
      evidence for `relay-client` and `relay-proxy`, and `relay-server`'s plugin
      install has its tests only (D23).
      Owed by validation: `tests.yml`, job `test · test-provisioning-iac` — its log
      shows the family project's tests run and pass beside VM's.

## 7. VM's tasks on the family roles, and one relay block

Delivers D3 for VM, D12, and the codec half of 28 F3: "A relayed create reports its
relay under one block". Replanned against the reviewed design only in its references
to section 5's tasks.

- [ ] 7.1 `roles/vm-setup` includes `relay-client` in place of `frp-client.yml`;
      `vm-create.yml`, `vm-undefine.yml`, and `vm-remove.yml` call `relay-proxy` with
      the guest's proxy and the job's grant; the old frp tasks, templates, and
      `restart frpc-vms` handler go, and VM's download of frpc with them (D22). (D3)
- [ ] 7.2 Both create-fact variants print their relay block as `relay`; the codec
      (`domains/vms/provisioning/adapter/src/vm_provisioning_adapter/codec.py`) reads
      `relay`, its variables carry the grant (5.5), and its secret fields come from the
      family set (5.7); the mock output (`services/mock_output.py`) and the codec's
      tests (`tests/unit/test_vm_codec.py`, `test_vm_mock_output.py`) follow the
      shipped fact. (D12, 28 F3)
- [ ] 7.3 Both domains' playbooks pass `ansible-playbook --syntax-check` under their
      own configuration and the image's environment (`make test-provisioning-iac-native`).
      (28 F5)
- [ ] 7.4 Verify. `make test-provisioning-iac`, `make test-provisioning-adapter`,
      `make test-provisioning`; `make test-provisioning-iac-native` against a built
      provisioning image; `make test`. End-to-end: the VM lane (`e2e_deal`) exercises the codec
      through the mock profile's default output; no pipeline scenario runs a relayed
      create.
      Owed by validation: `tests.yml`, job `test · test-provisioning-iac` — the family
      project's and VM's IaC tests pass.

## 8. Bare-metal relay access and host preparation

Delivers D1 and D3 for bare metal: "A bare-metal grant on a relay-backed pool
delivers a leased port". Replanned against the reviewed design only in its references
to section 5's tasks.

- [ ] 8.1 `BareMetalFulfillmentPlan.prepare_create` leases a port through the
      acceptance session when the pool references a relay, passing the reservation's
      lease end and the host as VM's plan does (5.1), and refusing an unusable relay
      through the family check (window, token, active key; 5.8); `prepare_teardown`
      reads the relay from the lease. A pool with no relay prepares as today. (D1)
- [ ] 8.2 `BareMetalAnsibleCodec` carries the relay reference and leased port in
      `BareMetalJobParams`, which gains the resolver's relay fields, `relay_grant`
      included, so the execution resolver fills the relay's address, token, and grant
      at execution (5.5); it names the family's secret variable set among its secret
      fields (5.7), and delivers `ssh -p <leased port> <tenant>@<relay address>` from
      the lease for a relayed grant; a grant with no relay delivers the host's buyer
      route as today (`grant_evidence`). The mock output (`services/mock_output.py`)
      follows. (D1, 28 F3)
- [ ] 8.3 The `bare-metal-access` role calls `relay-proxy` *add* for a relayed grant,
      proxying `127.0.0.1:22`, and *remove* on reclaim, never touching the management
      client. (D1, D3)
- [ ] 8.4 Add `domains/bare_metal/provisioning/iac/ansible/playbooks/host-kit/`
      with a host-preparation playbook applying `relay-client`, and an `ansible.cfg`
      whose `roles_path` names the family roles. (D3, 28 F5)
- [ ] 8.5 Tests. Unit (`domains/bare_metal/provisioning/adapter/tests/`): the plan's
      lease and its refusals; the codec's relayed and unrelayed evidence and its
      redaction. Role assets
      (`provisioning/compute/service/tests/unit/test_bare_metal_ansible_assets.py`):
      the relay proxy on grant and reclaim, and the host-kit playbook's syntax.
      Application integration through the typed client: a relayed bare-metal
      fulfillment leases a port, its grant job's read carries no grant or token, and
      its release returns the port; a fulfillment on a pool whose relay has no active
      key is refused.
- [ ] 8.6 Verify. `make test-bare-metal`, `make test-provisioning`,
      `make -C provisioning/compute/iac test`; `make test-provisioning-iac-native`;
      `make test`.
      End-to-end: the bare-metal lane (`e2e_bare_metal_mock_deal`) on a pool with no
      relay; no pipeline scenario runs a relayed grant.

## 9. Reclaim ends the tenant's activity

Delivers D15: "A bare-metal reclaim ends the tenant's activity" and the modified "A
bare-metal reclaim tolerates an account its grant never created".

- [ ] 9.1 In `roles/bare-metal-access/tasks/main.yml`, where the account exists and
      after the key is removed: end its sessions (`loginctl terminate-user`) and
      lingering (`loginctl disable-linger`), kill what remains (`pkill -KILL -u`),
      remove its crontab and `at` jobs, and only then keep, lock, or delete it. Drop
      `failed_when: false` from the lock and delete; fail the reclaim when a process of
      the account survives. The reclaim fact reports what was ended. (D15)
- [ ] 9.2 The codec keeps the reclaim result diagnostic and records the new fact
      fields as detail. (D15; "A bare-metal reclaim's printed fact is a diagnostic")
- [ ] 9.3 Tests (`test_bare_metal_ansible_assets.py`, the codec's tests): the order of
      the reclaim tasks, no swallowed failure, the absent-account path unchanged, the
      fact's new fields read.
- [ ] 9.4 Verify. `make test-bare-metal`, `make test-provisioning`;
      `make test-provisioning-iac-native`; `make test`. End-to-end: `e2e_bare_metal_mock_deal` runs
      its reclaim through the mock profile's output; the live run (section 16) shows a
      real reclaim.

## 10. The real-provisioning target, version 2

Delivers D5, D6's target half, and D7: the modified "A real-provisioning target is a
typed, versioned settings section".

- [ ] 10.1 Replace `e2e-tests/src/e2e_harness/real_vm_target.py` with
      `real_provisioning_target.py`: section `REAL_PROVISIONING_TARGET`, profile
      `real-provisioning-target`, version 2's hosts with their domain, connection,
      access (relay by id, or direct with `public_host`), capacity, VM
      `listing_shape` fitting twice, and bare-metal `physical_host_id` and
      `ssh_host_public_key`; refuse version 1 with the conversion message, two hosts
      of one domain, and a field foreign to a host's domain or mode. (D5, D7)
- [ ] 10.2 Replace the committed example `config-real-vm-target.yml.example` in
      `e2e-tests/config/` with `config-real-provisioning-target.yml.example`
      (documentation addresses and invented names, said so), and the ignore rule in
      `e2e-tests/.gitignore`. (D5)
- [ ] 10.3 Tests. Unit (`e2e-tests/tests/unit/test_real_provisioning_target.py`,
      replacing `test_real_vm_target.py`): every refusal names its field; a listing
      shape not fitting twice names the dimension; version 1 refused.
- [ ] 10.4 Verify. `make test-e2e-unit`; `make test`. End-to-end: none; the real
      lanes read it.

## 11. The real VM lane over a relay

Delivers D6's lane half, D8, D9's lane evidence, and D11's heartbeat session: the
modified "A real-provisioning VM scenario proves delivery on a real host".

- [ ] 11.1 The real VM driver
      (`e2e-tests/tests/e2e/roles/scenarios/vms/real_compute_deal_driver.py`) reads its
      host from version 2, publishes `listing_shape`, registers its pool with
      `provider_config.relay_id` under relay access, and before writing anything reads
      the relay and requires it enabled with a token and an active grant key; under
      relay access the delivered address is the relay's and the port the leased one.
      Adoption compares against `listing_shape`. (D6, D7)
- [ ] 11.2 Add the heartbeat session to `e2e-tests/tests/e2e/roles/helpers/ssh_access.py`:
      one `ssh` process printing the time each second with `ServerAliveInterval`, its
      liveness and longest gap readable, closed on demand. (D8, D11)
- [ ] 11.3 Add the second-deal stages to
      `e2e-tests/tests/e2e/roles/scenarios/vms/test_real_provisioning_deal.py` between
      the first deal's access checks and its expiry: open the heartbeat; the second
      deal (negotiate, escrow, settle, create-job poll, active, access at its own port);
      the heartbeat across the create; the second deal cut short, its teardown-job poll,
      its capacity released and its port shown released by the holdings read; the
      heartbeat across the proxy removal, then closed. Each new field has one producer
      stage. (D8, D9)
- [ ] 11.4 Check host connectivity through `GET /api/v1/hosts/{id}/connectivity` before
      and after each create and teardown. (D9, 8.4)
- [ ] 11.5 The finaliser recovers both deals: it cuts short each live lease, confirms
      each guest gone, and names what it cannot confirm. (D8)
- [ ] 11.6 Tests. Unit (`e2e-tests/tests/unit/test_real_vm_lane.py`,
      `test_compute_deal_stages.py`, `test_ssh_access.py`): the stage set's order and
      producers, the relay checks, the heartbeat's gap detection, recovery of two deals.
- [ ] 11.7 Verify. `make test-e2e-unit`; `make test`. End-to-end: `e2e_vm_real_provisioning`, in no
      lane, skips without its target; the live run (section 16) runs it. The pipeline's
      lanes must still pass with the real module skipping.

## 12. The real bare-metal lane

Delivers D10 and D11's pinned mode: "A real-provisioning bare-metal scenario proves
relay access on a real host".

- [ ] 12.1 Add a pinned `known_hosts` mode to `ssh_access.py`. (D10, D11)
- [ ] 12.2 Add the real bare-metal driver
      (`e2e-tests/tests/e2e/roles/scenarios/bare_metal/real_compute_deal_driver.py`)
      implementing `ComputeDealDriver` without `MockGates`: it registers, from the
      target, a backed pool delivering and advertising bare metal with
      `provider_config.relay_id`, the host with its connection, and the declaration; it
      checks the relay as 11.1 does. (D10)
- [ ] 12.3 Add `e2e-tests/tests/e2e/roles/scenarios/bare_metal/test_real_provisioning_deal.py`,
      marker `e2e_bare_metal_real_provisioning` registered in `e2e-tests/pyproject.toml`
      and in no lane: every shared stage; bare metal's publication, listing-closing,
      and evidence-publication stages, adopting the open listing on its resource as
      D10 settles; the executor-real check; the settlement-preview host check;
      grant- and reclaim-job polls; tenant access with a key generated for the run at
      the delivered relay string and an unrelated key refused, the host key pinned
      from the target; connectivity checks; after release the string refused and the
      holdings read showing the lease released; a finaliser that cuts the lease short
      and names what it cannot confirm. (D10)
- [ ] 12.4 Tests. Unit: the bare-metal real lane's stage set against the shared stages
      (`test_compute_deal_stages.py`), the driver's registration and relay checks, the
      pinned mode.
- [ ] 12.5 Verify. `make test-e2e-unit`; `make test`. End-to-end: `e2e_bare_metal_real_provisioning`,
      in no lane, skips without a bare-metal host in its target; the live run (section
      16) runs it.

## 13. One SSH helper

Delivers D11: "Real-lane SSH access goes through one helper".

- [ ] 13.1 Move `e2e_bare_metal_deal`
      (`e2e-tests/tests/e2e/roles/scenarios/bare_metal/test_bare_metal_deal.py`) onto
      `ssh_access.py`'s pinned mode and its refused classification, keeping its
      behaviour; reduce `e2e-tests/tests/e2e/roles/helpers/bare_metal_access.py` to its
      purchase helpers. (D11)
- [ ] 13.2 Tests. Unit: `test_ssh_access.py` covers the classification
      `bare_metal_access.py` had; a source check refuses an e2e scenario building its
      own `ssh` command.
- [ ] 13.3 Verify. `make test-e2e-unit`; `make test`. End-to-end: `e2e_bare_metal_deal`, in no lane,
      keeps its configuration and skips without it.

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

- [ ] 14.1 `relay-server` installs the plugin as a plain program from inputs it is given
      and never builds or fetches — `frp_grant_admission_wheel`,
      `frp_grant_admission_requirements` (hash-pinned, exported from the tool's lock),
      and `frp_grant_admission_config` (the plugin's own TOML, D20): it requires
      `python3` 3.11 or later on the relay, creates a virtual environment under
      `/opt/frp-grant-admission`, installs the requirements with `--require-hashes`
      and then the wheel with `--no-deps`, and runs the plugin as its own unprivileged
      user under a unit templated from the tool's systemd example. (D23)
- [ ] 14.2 `relay-server` checks the configuration with the plugin's `check` before
      installing it, failing without replacing the running configuration when it does
      not load; writes it root-owned and readable by the plugin's group under
      `no_log`; and reloads the plugin on a change without restarting frps. frps
      gains the `[[httpPlugins]]` entry — `path = "/"`, `ops = ["NewProxy"]`, the
      plugin's loopback address — which restarts frps once. (D23; "A relay prepared
      by the family role runs admission and discloses no secret")
- [ ] 14.3 The vector check (`provisioning/compute/tests/unit/`): it reads the tool's
      published vector (its `vector/frp-grant-1.json`) in place; for every signing case
      the family's header-and-claims signer (5.3), given the case's key, header, and
      claims, produces exactly the case's token, and the thumbprint case equals the
      family's key-id derivation (4.1). It runs no verification case. (D18)
- [ ] 14.4 The pins check (`provisioning/compute/iac/tests/`): `frp-binary`'s version,
      URL, and SHA-256 for `linux_amd64` equal the tool's `frp-pins.toml`. (D18, D22)
- [ ] 14.5 Tests in the family IaC project: the plugin's install refusing a Python
      older than 3.11, installing with `--require-hashes` then `--no-deps`, its unit as
      an unprivileged user; the configuration checked before it is installed, under
      `no_log`, a change reloading the plugin and not restarting frps; frps naming the
      plugin for `NewProxy` only; both domains' and the relay playbook's
      `--syntax-check`.
- [ ] 14.6 Verify. `make test-compute-provisioning` (unit), `make -C provisioning/compute/iac test`,
      `make test-provisioning-iac`, `make test-provisioning-iac-native`; `make test`.
      End-to-end: none in the pipeline; the live run's relay is containerised (D23),
      so `relay-server`'s plugin install has its tests and syntax checks only, and
      section 16 proves the image path.
      Owed by validation: `tests.yml`, job `test · test-provisioning-iac` — its log
      shows the family project's tests, the pins check included, run and pass.

## 15. Operator documentation

Delivers the operator procedures D4, D15b, D16, D17, D19, D20, D22, and D23 call for,
against the tool as archived. Replanned against the reviewed design: the procedures the
reconciliation and 55-design added.

- [ ] 15.1 `docs/development/VALIDATION_RUNBOOK.md` §21–26 for target version 2 and
      relayed hosts. (D5)
- [ ] 15.2 A new runbook section for relays, preparing them:
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
- [ ] 15.3 The relay section, operating them:
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
- [ ] 15.4 `docs/seller-frp-setup.md`: the `frpc-buyers` client, its versioned frp
      binary, and its locked-down admin API; one relay per operator, buyer-only by
      default, management ports on another relay; a shared relay's limits; what a
      relay must run (frps with the admission plugin, an issuer for the relay); the
      operator's management client with its admin API off or authenticated. (D3, D4,
      D19, D20, D22)
- [ ] 15.5 `docs/bare-metal-seller-quickstart.md`: relay-backed bare-metal pools and host
      preparation; a tunnel-reached host in a pool with no relay must state a buyer
      route; what reclaim ends. (D1, D15, D15b)
- [ ] 15.6 `e2e-tests/README.md`: the real VM and bare-metal lanes, their profile, and
      the target's version 2, in place of "Real VM provisioning". (D5, D10)
- [ ] 15.7 Verify. `make check-doc-citations CHANGE=prove-relay-provisioning`, its only
      remaining matches being files this change has yet to create; every command and
      path the new runbook steps name resolves against this branch. End-to-end: none;
      section 16 runs the runbook's admission check and the lanes.

## 16. Live verification [log]

Requires a VM host and a bare-metal host (which may be a virtual machine), prepared
with `relay-client`, reached through a management relay, and a buyer relay for each
lane's release, each with its own token and key: frps in a container with the
plugin's image as a sidecar (D20, D23). The owner supplies each item's output, free of
addresses, project, cluster, namespace, and host names; until then the change is
`blocked in implementation`. Each item is also evidence for
`relay-vm-access-without-a-dashboard`'s sections 6 and 8, recorded here (D9).
Unchanged by the replanning but for its relays.

- [ ] 16.1 **[log]** The runbook's admission check on each buyer relay: an ungranted
      proxy refused, the plugin's refusal in its log. (relay change 8.2, restated; D19)
- [ ] 16.2 **[log]** `e2e_vm_real_provisioning` under relay access passes: the guest
      reached at the relay and leased port; an unrelated key refused; the heartbeat
      held through the second deal's create and teardown; the second port released;
      connectivity before and after each create and teardown; the guest gone and access
      ended after expiry. (relay change 6.1, 8.1, 8.3, 8.4, 8.5, 8.6 restated)
- [ ] 16.3 **[log]** The management client's status across that run shows no restart.
      (relay change 8.4)
- [ ] 16.4 **[log]** `e2e_vm_real_provisioning` under direct access passes, its second
      deal included.
- [ ] 16.5 **[log]** `e2e_bare_metal_real_provisioning` passes: the tenant reached at the
      relay and leased port with the pinned host key; an unrelated key refused; after
      reclaim the string refused and the lease released; connectivity unchanged.
- [ ] 16.6 **[log]** A rerun of each lane against the same stack reconciles its
      registrations and adopts its listing.
- [ ] 16.7 Record the evidence against each item here, and the relay change's section 6
      and 8 items it closes, for that change's closeout.

## 17. Closeout

Per `openspec/README.md#plan-closeout-requirements`, in that order; closeout changes
documentation only, and a part needing a code edit returns the change to
implementation. `admit-relay-proxies-by-grant` must be archived first.

- [ ] 17.1 **Comment hygiene.** Run `make check-comment-hygiene` and confirm the comments
      this change added state invariants, not this change; anything to fix returns the
      change to implementation.
- [ ] 17.2 **Import placement.** Confirm the imports this change added or touched are at
      module level unless a verified reason keeps one local; one to move returns the
      change to implementation.
- [ ] 17.3 **Documentation compliance.** Re-check each decision's destination below
      against `openspec/README.md`'s placement rules.
- [ ] 17.4 **Narrative compression.** Compress completed-task notes to final behaviour,
      material evidence, deferred work, and destinations, moving rationale into
      `design.md` first.
- [ ] 17.5 **Roadmap currency.** `docs/development/ROADMAP.md`, "Goal 1 — Consolidate
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
- [ ] 17.6 **Campaign index currency.** This change's row in
      `openspec/changes/README.md` ("Reach hosts and VMs that have no inbound route"),
      its campaign graph, and its `Depends on` once `admit-relay-proxies-by-grant` is
      archived; other rows' `Depends on` stay. Name the update in the promotion record.
- [ ] 17.7 **Packaging.** `make check-packaging` and
      `make check-architecture-change CHANGE=prove-relay-provisioning`.
- [ ] 17.8 **End-to-end pipeline.** Record the passing run the latest validation names:
      the VM lane and the bare-metal lane (section 1.7's scenarios and
      `e2e_bare_metal_mock_deal`) passing with the real lanes skipping; the real lanes'
      evidence is section 16's.
- [ ] 17.9 **Promotion.** Write the permanent documents and the design-promotion record:
      - D2, D3: `docs/development/ARCHITECTURE.md` "Family kits" (the compute family
        kit's relays and the family IaC roles); `openspec/specs/physical-provisioning/architecture.md`
        "Buyer access to rented VMs", renamed "Buyer access through relays" for both
        domains, with the host-level client configuration belonging to the host and
        the family roles found through the role search path;
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
        grants" under "Buyer access through relays" — per-lease grants and their
        lifecycle, the grant's conformance to the tool's specification (no `iat`, JCS
        signing, claim types, `jti` the owning reservation, thumbprint ids, public
        keys in the plugin's format), the vector and pins checks, relay keys with the
        profile's form and rotation keeping the profile current, admission on every
        relay as the operator's installation, one relay per operator and a shared
        relay's limits, the emergency choice per incident, the host- and relay-side
        steps for a host teardown cannot reach and their limit, one verified frp pin at
        versioned paths, how a relay runs the plugin, and the wheel as the operator's
        input; the relay-never-calls-SCM principle in
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
- [ ] 17.10 **Documentation citations.** `make check-doc-citations CHANGE=prove-relay-provisioning`,
      then `openspec validate prove-relay-provisioning --strict`.
- [ ] 17.11 **Archival.** `openspec archive prove-relay-provisioning -y`, merging the
      deltas into `physical-provisioning` and `test-compatibility`; point the index row at
      the archived directory.
