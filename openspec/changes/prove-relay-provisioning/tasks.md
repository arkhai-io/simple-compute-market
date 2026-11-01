# Implementation Tasks

Paths are relative to the repository root. Decisions (`D<n>`) and corrections are
`design.md`'s; requirements are this change's delta specs under `specs/`.

Sections 1–13 need nothing from `frp-grant-admission`: the signer is built to the
grant format D16 states, and the family roles take the plugin's image and
configuration as inputs. Sections 14–16 need the plugin itself and start once
`frp-grant-admission` is archived; closeout waits on it too (D13).

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

- [ ] 4.1 Add the relay's Ed25519 grant-signing key columns (the active key
      encrypted under `ssh_decryption_key` with `market_config.secret_at_rest`, its
      id, a staged key, and retired key ids with their retirement time) in
      `compute_provisioning/relays/db.py`, with an additive migration. (D17)
- [ ] 4.2 The relay definitions document requires `grant_key_secret_key` on every
      entry, read once at creation as `token_secret_key` is; an entry naming none, or
      naming a profile key the profile lacks, fails the import naming it. A relay
      created through the API with no key gets one the service generates. (D17, D19)
- [ ] 4.3 Add the staging and activation operations to the relay routes, contracts,
      and client: staging generates a key pair in the service and returns its public
      half without signing with it; activating makes the staged key sign every later
      grant and retires the previous one. (D17)
- [ ] 4.4 Relay reads return the active key's id and public half, any staged key's,
      and each retired key's id with the time its grants stay valid until — the
      latest `grant_expires_at` among the relay's unreleased leases allocated before
      it was retired (28 F2). No read, export, or reconciliation comparison returns a
      private key. (D17)
- [ ] 4.5 Tests. Library integration: a stored key is ciphertext; a definitions entry
      without a grant key fails naming it; a reconciliation never rewrites a key.
      Application integration through the typed client: a relay read carries public
      halves only; staging leaves signing on the active key until activation; a
      retired key's validity follows the leases allocated before it, including a job
      retried across a rotation.
- [ ] 4.6 Verify. `make test-compute-provisioning`, `make test-provisioning`,
      `make test-compute-provisioning-contracts`,
      `make test-compute-provisioning-client`. End-to-end: none; the real lanes read
      the active key (sections 11 and 12).

## 5. Grants, port quarantine, and the checks before dispatch

Delivers D16, D19, and the management-route check: "Every relay proxy carries a
signed grant", "Relay port leases are unique per relay" (the quarantine), "A relay
without an active grant key is refused before dispatch", and "A host's management
route does not use its pool's buyer relay".

- [ ] 5.1 Allocation records `grant_expires_at` on the lease — the reservation's
      lease end plus a configured grace — in the acceptance transaction, with an
      additive migration adding it and the signing key id to `relay_port_leases`.
      (D16)
- [ ] 5.2 The allocator does not reissue a released port before its
      `grant_expires_at`; a lease cut short leaves its port held back and allocation
      selects another. ("Relay port leases are unique per relay", scenario "A lease is
      cut short")
- [ ] 5.3 Sign the grant from the lease immediately before a job's variables are
      written, on every attempt, with the relay's active key: an EdDSA JWT with
      header `kid` and claims `aud` (the relay id), `port`, `exp`, `sub` (the host),
      `jti` (the lease), and `iat`, exactly D16's format. Record the signing key id on
      the lease. The grant reaches the job through execution-time resolution and never
      its persisted parameters. Conformance to the plugin's published vector is
      section 14's. (D16)
- [ ] 5.4 The relay family supplies one set of the variable names carrying the grant,
      the relay token, and the client's admin password, and VM's codec takes its
      secret fields from it. (D3, 28 F3)
- [ ] 5.5 Fulfillment preparation refuses a pool whose relay holds no active grant
      key, naming the relay and the missing key, beside its refusals for a missing
      token or window (`vm_fulfillment_plan.py`, through the family check). (D19)
- [ ] 5.6 Refuse placing a host in a relay-backed pool when its connection address
      equals that relay's normalized address, and refuse setting a relay's address to
      the connection address of a host in a pool referencing it, naming the host and
      the relay; register the check with the host authority's pool-change hooks and
      the relay update. (D19)
- [ ] 5.7 Tests. Unit: the grant's header and claims for a lease, and a verifier
      written to D16 accepting it and refusing a tampered one. Library integration:
      the quarantine; the grant signed again on a retry with the then-active key; no
      grant in persisted parameters. Application integration through the typed
      client: a fulfillment refused for a relay with no active key; a host placement
      refused for its pool's relay address; a job read carrying no grant, token, or
      admin password.
- [ ] 5.8 Verify. `make test-compute-provisioning`, `make test-provisioning`,
      `make test-provisioning-adapter`; `make check-packaging` (the JWT signing
      dependency). End-to-end: none in the pipeline; the real lanes (sections 11 and
      12) and the live run (section 16).

## 6. The family relay roles, with the admin API locked down

Delivers D3 (the family project and role search path, 28 F5), D4, and the `no_log`
half of 28 F3: "The buyer-facing tunnel client is hardened on every host".

- [ ] 6.1 Create the IaC project `provisioning/compute/iac/` — `pyproject.toml`
      (`package = false`), `Makefile`, `tests/`, lock — following
      `domains/vms/provisioning/iac/`, and wire its tests into the root
      `test-provisioning-iac` target, so the aggregate `make test` and CI's
      `test-provisioning-iac` job run them. (D3; `docs/development/ARCHITECTURE.md`
      "Build, packaging, and initialization": aggregate targets run every included
      subproject's tests)
- [ ] 6.2 Add `relay-client` under `provisioning/compute/iac/ansible/roles/`, from
      VM's `roles/vm-setup/tasks/frp-client.yml` and its templates: the client renamed
      `frpc-buyers` (`/etc/frp/frpc-buyers.toml`, unit `frpc-buyers`), its
      configuration root-only, its admin API on a loopback port below 1024 (a
      variable with a privileged default) with a per-host password generated at
      preparation, and no defaulted relay address or token. (D3, D4)
- [ ] 6.3 Add `relay-proxy` with *add* — check the client's baseline against the
      resolved relay and restart only when it changed, add a marked block (name, local
      address and port, remote port, `metadatas.grant`), reload through the
      authenticated admin API, and wait for the proxy to run — and *remove*, moving
      `remove_guest_proxy` from VM's `roles/vm-management/files/guest_teardown.sh`.
      Every task rendering, writing, sending, or reading the grant, the token, or the
      admin password sets `no_log`. (D3, D4, 28 F3)
- [ ] 6.4 Move `roles/frp-setup` from `domains/vms/provisioning/iac/ansible/` to the
      family project as `relay-server`, installing frps without the dashboard and
      subdomain settings; installing the plugin is section 14's. Move its playbook
      `playbooks/frp/frp-server-setup.yaml` with it. (D3)
- [ ] 6.5 Copy `provisioning/compute/iac` into the provisioning image and set
      `ANSIBLE_ROLES_PATH` to its roles (`provisioning/compute/service/Dockerfile`,
      `Dockerfile.dockerignore`); add the family roles' repository-relative path to
      the `roles_path` of `domains/vms/provisioning/iac/ansible/ansible.cfg`; keep the
      service's shared `ansible.cfg` free of domain paths. (28 F5)
- [ ] 6.6 Tests in the family project, at the level `domains/vms/provisioning/iac/tests`
      holds: the role structure, every secret-bearing task's `no_log`, the admin port
      below 1024 and the password on every admin call, removal reloading and never
      restarting; move VM's `test_frp_proxy_wait.py`,
      `test_cleanup_script_relay_teardown.py`, and the proxy half of
      `test_guest_teardown.py` here.
- [ ] 6.7 Verify. `make -C provisioning/compute/iac test`, `make test-provisioning-iac`;
      `make check-packaging` (the new project's lock). End-to-end: none — no pipeline
      lane prepares a host; the live run (section 16) is the evidence.
      Owed by validation: `tests.yml`, job `test · test-provisioning-iac` — its log
      shows the family project's tests run and pass beside VM's.

## 7. VM's tasks on the family roles, and one relay block

Delivers D3 for VM, D12, and the codec half of 28 F3: "A relayed create reports its
relay under one block".

- [ ] 7.1 `roles/vm-setup` includes `relay-client` in place of `frp-client.yml`;
      `vm-create.yml`, `vm-undefine.yml`, and `vm-remove.yml` call `relay-proxy` with
      the guest's proxy and the job's grant; the old frp tasks, templates, and
      `restart frpc-vms` handler go. (D3)
- [ ] 7.2 Both create-fact variants print their relay block as `relay`; the codec
      (`domains/vms/provisioning/adapter/src/vm_provisioning_adapter/codec.py`) reads
      `relay`, its variables carry the grant, and its secret fields come from the
      family set (5.4); the mock output (`services/mock_output.py`) and the codec's
      tests (`tests/unit/test_vm_codec.py`, `test_vm_mock_output.py`) follow the
      shipped fact. (D12, 28 F3)
- [ ] 7.3 Both domains' playbooks pass `ansible-playbook --syntax-check` under their
      own configuration and the image's environment (`make test-provisioning-iac-native`).
      (28 F5)
- [ ] 7.4 Verify. `make test-provisioning-iac`, `make test-provisioning-adapter`,
      `make test-provisioning`; `make test-provisioning-iac-native` against a built
      provisioning image. End-to-end: the VM lane (`e2e_deal`) exercises the codec
      through the mock profile's default output; no pipeline scenario runs a relayed
      create.
      Owed by validation: `tests.yml`, job `test · test-provisioning-iac` — the family
      project's and VM's IaC tests pass.

## 8. Bare-metal relay access and host preparation

Delivers D1 and D3 for bare metal: "A bare-metal grant on a relay-backed pool
delivers a leased port".

- [ ] 8.1 `BareMetalFulfillmentPlan.prepare_create` leases a port through the
      acceptance session when the pool references a relay, refusing an unusable relay
      as VM's plan does (window, token, active key); `prepare_teardown` reads the relay
      from the lease. A pool with no relay prepares as today. (D1)
- [ ] 8.2 `BareMetalAnsibleCodec` carries the relay reference and leased port in
      `BareMetalJobParams`, resolves the relay's address, token, and grant at execution,
      names the family's secret variable set among its secret fields, and delivers
      `ssh -p <leased port> <tenant>@<relay address>` from the lease for a relayed
      grant; a grant with no relay delivers the host's buyer route as today
      (`grant_evidence`). The mock output (`services/mock_output.py`) follows. (D1,
      28 F3)
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
      the relay proxy on grant and reclaim. Application integration through the typed
      client: a relayed bare-metal fulfillment leases a port and its release returns it.
- [ ] 8.6 Verify. `make test-bare-metal`, `make test-provisioning`,
      `make -C provisioning/compute/iac test`; `make test-provisioning-iac-native`.
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
      `make test-provisioning-iac-native`. End-to-end: `e2e_bare_metal_mock_deal` runs
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
- [ ] 10.4 Verify. `make test-e2e-unit`. End-to-end: none; the real lanes read it.

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
- [ ] 11.7 Verify. `make test-e2e-unit`. End-to-end: `e2e_vm_real_provisioning`, in no
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
- [ ] 12.5 Verify. `make test-e2e-unit`. End-to-end: `e2e_bare_metal_real_provisioning`,
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
- [ ] 13.3 Verify. `make test-e2e-unit`. End-to-end: `e2e_bare_metal_deal`, in no lane,
      keeps its configuration and skips without it.

## 14. The admission plugin on a relay, and the signer against its vector

Starts once `frp-grant-admission` is archived. Delivers D18's installation and
conformance, D19, and D20: "Every relay proxy carries a signed grant" (conforming to
the plugin's specification) and "A relay without an active grant key is refused
before dispatch" (the relay's side).

- [ ] 14.1 `relay-server` installs the plugin from its released image, renders its
      configuration — the issuers with each key's id, public half, audience, and port
      range — from inputs the operator gives, and adds frps's `[[httpPlugins]]` entry
      for `NewProxy`. (D3, D18, D20)
- [ ] 14.2 An SCM test signs the plugin's published vector claims with its key through
      the family signer and requires the vector's verdicts. (D18)
- [ ] 14.3 Tests in the family IaC project: the plugin's configuration renders the
      issuers given, and frps names the plugin.
- [ ] 14.4 Verify. `make test-compute-provisioning`, `make -C provisioning/compute/iac test`.
      End-to-end: none in the pipeline; the live run (section 16).

## 15. Operator documentation

Delivers the operator procedures D4, D15b, D16, D17, D19, and D20 call for, against
the plugin as released.

- [ ] 15.1 `docs/development/VALIDATION_RUNBOOK.md` §21–26 for target version 2 and
      relayed hosts, and a new section for relays: preparing a relay with
      `relay-server` and the plugin; relay definitions with `grant_key_secret_key`;
      staging, configuring, and activating a key, and when a retired key may leave the
      plugin; the admission check (an ungranted proxy refused, the plugin's refusal in
      its log) before a relay-backed pool first serves buyers and after any plugin
      change; onboarding a site to a shared relay (its public key and assigned range);
      and the relay step for a host teardown cannot reach. (D16, D17, D19, D20)
- [ ] 15.2 `docs/seller-frp-setup.md`: the `frpc-buyers` client and its locked-down admin
      API; a buyer-only relay by default, management ports on another relay; the
      operator's management client with its admin API off or authenticated. (D3, D4,
      D19)
- [ ] 15.3 `docs/bare-metal-seller-quickstart.md`: relay-backed bare-metal pools and host
      preparation; a tunnel-reached host in a pool with no relay must state a buyer
      route; what reclaim ends. (D1, D15, D15b)
- [ ] 15.4 `e2e-tests/README.md`: the real VM and bare-metal lanes, their profile, and
      the target's version 2, in place of "Real VM provisioning". (D5, D10)
- [ ] 15.5 Verify. `make check-doc-citations CHANGE=prove-relay-provisioning`, its only
      remaining matches being files this change has yet to create.

## 16. Live verification [log]

Requires a VM host and a bare-metal host (which may be a virtual machine), prepared
with `relay-client`, reached through a management relay, and a buyer relay running
frps with the admission plugin. The owner supplies each item's output, free of
addresses, project, cluster, namespace, and host names; until then the change is
`blocked in implementation`. Each item is also evidence for
`relay-vm-access-without-a-dashboard`'s sections 6 and 8, recorded here (D9).

- [ ] 16.1 **[log]** The runbook's admission check: an ungranted proxy refused by the
      deployed relay, the plugin's refusal in its log. (relay change 8.2, restated)
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
implementation. `frp-grant-admission` must be archived first.

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
      provisioning service's Ansible configuration (D4) and for admission at login on a
      shared relay, with its trigger (D21). The concurrent-allocation gap row, which
      names VM's provisioning owner as the allocator's, names the compute family's
      relays instead (found by section 1's fresh-context check). Name the update in
      the promotion record.
- [ ] 17.6 **Campaign index currency.** This change's row in
      `openspec/changes/README.md` ("Reach hosts and VMs that have no inbound route"),
      its campaign graph, and its `Depends on` once `frp-grant-admission` is archived;
      other rows' `Depends on` stay. Name the update in the promotion record.
- [ ] 17.7 **Packaging.** `make check-packaging` and
      `make check-architecture-change CHANGE=prove-relay-provisioning`.
- [ ] 17.8 **End-to-end pipeline.** Record the passing run the latest validation names:
      the VM lane and the bare-metal lane (section 1.7's scenarios and
      `e2e_bare_metal_mock_deal`) passing with the real lanes skipping; the real lanes'
      evidence is section 16's.
- [ ] 17.9 **Promotion.** Write the permanent documents and the design-promotion record:
      - D2, D3: `docs/development/ARCHITECTURE.md` "Family kits" (the compute family
        kit's relays and the family IaC roles); `openspec/specs/physical-provisioning/architecture.md`
        "Buyer access to rented VMs", renamed for both domains, with the host-level
        client configuration belonging to the host;
        `openspec/specs/resource-pool-management/architecture.md`, whose account of a
        relay-changing host move names the VM adapter as refusing it, where the
        family's relay pool-change hook now does.
      - D1, D15b: `physical-provisioning/architecture.md` "The host registry owns the
        connection".
      - D4: `physical-provisioning/architecture.md`, the token's boundary on a host.
      - D14, D16, D17, D19, D20: `physical-provisioning/architecture.md`, a section on
        relay admission; the relay-never-calls-SCM principle in
        `docs/development/ARCHITECTURE.md` "Authority boundaries".
      - D18: the principle that SCM does not own generic infrastructure that is not
        specific to it in `docs/development/ARCHITECTURE.md` "Package and dependency
        layers".
      - D2(b), 28 F4: `docs/development/DEPLOYMENT_AND_CONFIG.md` "Migrations at
        startup", beside the `hosts.gpu_count` drop; D17's `grant_key_secret_key` in
        "Definition documents".
      - D5–D11: `docs/development/TESTING.md` "The real-provisioning lane", covering
        both lanes.
      - The behaviour itself: `openspec/specs/physical-provisioning/spec.md` and
        `openspec/specs/test-compatibility/spec.md`, written by the archive in 17.11.
- [ ] 17.10 **Documentation citations.** `make check-doc-citations CHANGE=prove-relay-provisioning`,
      then `openspec validate prove-relay-provisioning --strict`.
- [ ] 17.11 **Archival.** `openspec archive prove-relay-provisioning -y`, merging the
      deltas into `physical-provisioning` and `test-compatibility`; point the index row at
      the archived directory.
