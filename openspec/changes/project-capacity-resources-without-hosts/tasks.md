# Tasks — project capacity declarations that name no host

Implements `design.md` decisions D1–D9 as amended by A1–A8. The pre-design
task list, none of which was complete, was replaced at planning; `design.md`
records why its approach was rejected.

Paths are relative to the repository root. Sections follow the migration
order: refusal landed before visibility.

## 1. Providers declare whether delivery needs a host

- [x] 1.1 The fail-closed predicate `pool_needs_host` and `HostRequirement` live
      in `kit/resource-pools/src/market_resource_pools/host_requirement.py`, a
      pool-level rule (A7). With no requirement, nothing is required; an
      unnamed provider needs a host; a non-`bool` value is refused.
- [x] 1.2 `FulfillmentProvider` declares `needs_host` with no default; a
      subclass of a declaring provider inherits it (A6). `provider_needs_host`
      reads it strictly.
- [x] 1.3 `AnsibleFulfillmentProvider` and `BareMetalFulfillmentProvider`
      declare `needs_host = True`.
- [x] 1.4 Every `FulfillmentProvider` test double declares its host need.
- [x] 1.5 Each adapter's `bundle.py` exports `HOST_REQUIREMENT`, derived from
      its provider classes, re-exported through its `runtime` module, the only
      adapter entrypoint the service may import.
- [x] 1.6 `compose_adapter_bundles` takes the expected requirement and refuses
      to start on a missing, extra, or disagreeing provider identity.
- [x] 1.7 The container merges the adapter exports once and passes the result
      to `CapacityLedgerService`, `PhysicalSettlementScheduler`, and
      composition.
- [x] 1.8 Unit coverage: the predicate, the declaration reader, composition
      refusal, and registry refusal (5R.2).

## 2. Admission applies the host requirement

- [x] 2.1 `CapacityLedgerService` takes an optional host requirement. None means
      nothing is enforced, which keeps API-credit admission unchanged.
- [x] 2.2 `_find_candidate`, shared by probe, reserve, and resize, skips a
      declaration naming no host where the pool's provider needs one, giving
      the ordinary no-capacity answer. `assign_settlement_resource_in_session`
      rechecks it beside the offering-mode recheck.
- [x] 2.3 Library integration coverage (A8):
      `kit/site/tests/integration/test_ledger_host_requirement.py`. Covers
      refusal, fall-through, the no-requirement and not-needed cases, an
      unregistered named host, resize, and the assignment write.

## 3. Scheduling applies the host requirement

- [x] 3.1 `PhysicalSettlementScheduler` takes the host requirement.
- [x] 3.2 New placement excludes a candidate naming no host where the pool's
      provider needs one, before policy, rebind, cursor, or assignment, on both
      the automatic and the constrained path. An existing assignment keeps its
      recorded host; one recording no host in such a pool is refused (A5).
- [x] 3.3 Library integration coverage (A8):
      `kit/fulfillment/tests/integration/test_scheduler_host_requirement.py`,
      including a seeded legacy assignment.
- [x] 3.4 Deployed-surface coverage through the typed clients:
      `provisioning/compute/service/tests/integration/test_host_requirement_api.py`
      (5R.4), and admission in `test_capacity_api.py`.

## 4. Dispatch fails closed; the static inventory is seed-only

- [x] 4.1 `AnsibleJobService` requires the host registry. A job for an
      unregistered host fails before any vars file, relay token, or playbook.
      The static-inventory fallback is removed.
- [x] 4.2 The tenant address is the record's `public_host`, else `ssh_host`,
      passed as `parse_playbook_result(tenant_address=…)`; no file lookup.
- [x] 4.3 Static-inventory readers and their mock mirrors are removed, along
      with the mock's `host_ip` argument and the `InventoryHost` and
      `InventoryResponse` models.
- [x] 4.4 `ProvisioningService` and its only test are tombstoned; nothing else
      constructed it.
- [x] 4.5 `BareMetalOperationsService` requires the host registry.
- [x] 4.6 Fixtures pass a host registry and register the hosts they dispatch
      to (evidence in A4). The unused `fake_inventory_path` fixture is removed.
- [x] 4.7 Unit coverage: the tenant address comes from the argument alone, and
      both services refuse construction without a registry. Fail-before-playbook
      is orchestration, proven at integration by 4.8.
- [x] 4.8 Integration coverage (`test_vms_api.py`): an unregistered host fails
      with no vars file, inventory, or playbook, even with an inventory file
      naming it; a registered host renders from its record.

## 5. The projection is built from declarations alone

- [x] 5.1 `load_capacity_resource_inventory(capacity_resources)` projects every
      declaration from the declaration alone: no host query and no host
      fields. A declaration with no recorded pool is reported in `default`.
- [x] 5.2 The `bare_metal.v2` view takes its host from the declaration. An
      enabled publication naming no host yields no view instead of failing the
      generation.
- [x] 5.3 `main.py` calls the new signature.
- [x] 5.4 Unit coverage asserts exact equality with frozen fixtures for a
      fungible pool and a specific-resource pool, plus each rule individually.
- [x] 5.5 Integration: a declaration naming no host appears through
      `SiteCapacityClient.resource_pool_projection()` and no entry carries host
      fields. A direct `Host` insert that claimed the projection needed one is
      removed.
- [x] 5.6 Projection consumers pass. The full VM storefront suite runs under
      root `make test` (`test-storefront`). The bare-metal view consumer runs
      under `test-bare-metal` (5R.7).

## 5R. Review corrections

- [x] 5R.1 Refuse an existing assignment recording no host (A5); covered at
      library integration and through the deployed app.
- [x] 5R.2 `ProviderRegistry` refuses a provider that does not declare its host
      need (A6); test doubles conform rather than weakening the contract.
- [x] 5R.3 The predicate is documented at pool level and refuses non-`bool`
      values (A7).
- [x] 5R.4 Scheduling-refusal integration uses the canonical typed clients for
      setup, scheduling, and acceptance; the raw-HTTP version is removed.
- [x] 5R.5 Task wording corrected to match the coverage actually written.
- [x] 5R.6 **Decision:** a library's real-database tests are integration tests
      (A8). This change's two moved to `tests/integration`, with tombstones at
      their `unit/` paths. `kit/fulfillment` gained a `tests/integration`
      package, and its test target runs both directories.
- [x] 5R.7 **Decision:** aggregates run every subproject's default tests, per
      `ARCHITECTURE.md`.
      - Root `make test` gained `test-bare-metal`: domain, storefront, buyer,
        and provisioning adapter. The buyer and adapter gained Makefiles with
        `reinit`.
      - `kit/site`'s test target honours `testpaths`.
      - CI gained the bare-metal buyer and adapter.
      - Subprojects use their relative `DIST_DIR`, so `uv sync` does not write
        absolute paths into committed locks.
      - The adapter's editable sibling sources are left for
        `remove-relative-uv-sources`.

- [x] 5R.8 Close every `reinit` gap. A `reinit` must reinstall each internal
      package its lock resolves from `.dist`. Otherwise a same-version rebuilt
      wheel is shadowed by the cached one.
      - **Symptom.** `domains/bare_metal/storefront` reinstalled neither
        `arkhai-kit-resource-pools`, `arkhai-kit-fulfillment`, nor
        `arkhai-kit-site`. Its environment kept the pre-change
        `market_resource_pools` and failed collection on `HostRequirement`.
      - **Audit.** Every Makefile's `reinit` recipe, including in-file
        prerequisites, was compared against its `uv.lock`. It found 15
        environments with gaps; all are closed, and the audit now reports none.
      - **Verified.** The pre-change `market_resource_pools` wheel was installed
        into the bare-metal storefront environment; its `make test` reinstalled
        the new one and passed (126). All 15 recipes parse under `make -n`, and
        no lockfile changed.

- [x] 5R.9 Make the 5R.8 audit a standing check.
      - **The check.** `scripts/check_reinit.py`, run by `make check-reinit`.
        For every project with a `tests` directory and a `uv.lock`, it requires
        `reinit`, or a recipe `reinit` depends on, to reinstall each internal
        package the lock resolves from a local wheel directory. It also
        requires a `reinit` target wherever such packages are installed.
        `scripts/tests/test_check_reinit.py` covers its rules and asserts the
        repository has no gaps.
      - **Newly covered.**
        - `domains/bare_metal`, `kit/capacity-publication`, and `kit/policy`
          gained `reinit` targets that `test` runs first.
        - `provisioning/compute` gained a Makefile, is in root `make test` as
          `test-compute-provisioning`, and passes (131).
        - `domains/vms/domain`'s tests ran nowhere. It gained a Makefile, is in
          root `make test` via `test-vms-domain`, is in CI, and passes (12).
      - **A pre-existing defect.** In `provisioning/compute`,
        `test_every_bound_mutation_contract_is_reachable[provisioning_relay_create]`
        derived its sample path without stripping the pattern's `$` anchor. It
        is fixed.
      - **Guidance.** `AGENTS.md` and `docs/prompts/implementation.md` require
        `make check-reinit` once tests pass, before a fileset is returned.
      - **Unrun here.** `kit/policy`'s `reinit` could not run in the
        implementation sandbox: `--upgrade-package` re-resolves its lock, and
        its `training` extra needs `torch` from an unreachable index, as with
        the VM storefront. Its lock is unchanged.

## 6. Closeout

- [x] 6.1 **Comment hygiene.** `make check-comment-hygiene` passes. Touched
      comments were read directly. The three that cited whole spec files now
      cite the promoted requirement headings.
- [x] 6.2 **Import placement.** One function-level import was added:
      `AnsibleResult` in `test_ansible_service.py`. It moved to module level
      for the two tests this change touched; the module already imports from
      the same source, and its suite passes. No production code gained a local
      import.
- [x] 6.3 **Documentation compliance.** Normative behaviour went to the three
      spec deltas. Rationale went to the `site-capacity` companion, the
      repository-wide layer rule to `ARCHITECTURE.md`, test methodology to
      `TESTING.md`, and operator behaviour to `DEPLOYMENT_AND_CONFIG.md` and the
      quickstarts.
- [x] 6.4 **Narrative compression.** This list now records final behaviour,
      evidence, and destinations. The fallback-dependency evidence moved to
      `design.md` (A4).
- [x] 6.5 **Roadmap currency** (`docs/development/ROADMAP.md`).
      - **Goal 7:** this change's gap row is removed, and the current-state
        prose says a declaration without a host reaches storefronts while
        admission still refuses it where the pool's provider needs a host.
      - **Goal 1:** its current state adds that host records are used only at
        dispatch and the inventory file is a seed input. No gap row changes.
- [x] 6.6 **Campaign index currency** (`openspec/changes/README.md`).
      - This change's row reads complete, awaiting archival.
      - `unbacked-listing-publication` is now blocked only on
        `pool-declared-advertisement-and-backing`.
      - `pools-6-fair-scheduling-policy`'s row records the disabled-host rule
        it owns.
      - Goal 1 gains a table of the two unowned findings: the bare-metal access
        address, and the single registration source.
      - Goal 1 gains a row for the new change
        `bring-host-inventory-under-definition-documents`, in design phase.
        Host inventory is the one mounted input that seeds only an empty
        registry and is never reconciled against its file; this change
        documented that rule, and that change owns replacing it. The roadmap's
        Goal 1 gap table maps to it.
      - The dependency graphs are unchanged until archival. One change
        directory was created, `bring-host-inventory-under-definition-documents`,
        and it is linked from the index and the roadmap. None was renamed or
        removed.
- [x] 6.7 **Documentation citations.**
      `make check-doc-citations CHANGE=project-capacity-resources-without-hosts`
      passes.
- [x] 6.8 **End-to-end pipeline.**
      - **Run.** The e2e workflow ran `make -C e2e-tests test-e2e` on
        2026-09-22 (11:03–11:08 UTC): 113 passed, 3 skipped, 264 deselected,
        0 failed.
      - **Scenarios exercising this change.**
        - `test_full_deal.py` and `test_full_deal_buyer_cli.py` register their
          executor hosts, then dispatch fulfillment to them through the
          registry-rendered inventory. That is the only path now.
        - `test_compute_dynamic_listings.py` publishes listings from the
          declaration-built resource-pool projection.
      - **Not exercised.** `test_pool_declared_offering_modes.py` was among the
        deselected scenarios, so no admission-refusal scenario ran end to end;
        that behaviour is proven in-process (3.4).
      - **Skips, all unrelated.**
        - `test_bare_metal_complete_deal` skipped because
          `BARE_METAL.REGISTRY_URL` is not configured.
        - Two `test_multi_registry.py` stages are declared skips owned by
          `repair-multi-storefront-scenario`.
- [x] 6.9 **Promotion.** The spec deltas were synced into
      `openspec/specs/{site-capacity,fulfillment,physical-provisioning}/spec.md`
      verbatim, each requirement exactly once. All three specs validate
      strictly. The record below lists every destination.
      - Promotion review found three passages the change had made stale:
        - `site-capacity`'s projection-metadata evidence still credited host
          records with attributes;
        - its site-identity boundary still called a `CapacityBucket` host-level;
        - `storefront-publication` still called admission host-granular.
      - Each was corrected in the permanent spec and mirrored verbatim into this
        change's delta as a MODIFIED requirement. `site-capacity` gains
        "Separate capacity and deal event semantics" and "Site identity
        ownership boundary"; `storefront-publication` gains "Storefronts cache
        independent site projections".
      - The `CapacityBucket` docstring in `kit/site/src/market_site/db.py` is
        corrected to match.
      - `test_capacity_api.py` now asserts that a GPU model held only on the
        host record never fills an undeclared attribute, which is the evidence
        the corrected sentence cites.
      - **Cross-change rebase.** `remove-relative-uv-sources` carried a MODIFIED
        block for "Bare-metal inventory binds an existing provider pool",
        written against the pre-promotion text. It differed only in line
        wrapping. It is rebased onto the promoted requirement, same words and
        its wrapping, so it no longer drops the new scenario, and it
        validates again.
      - **`openspec validate --all --strict`:** 73 passed, 19 failed of 92.
        - 18 of the failures fail identically on the tree before this change.
        - The 19th is `bring-host-inventory-under-definition-documents`, which
          has no deltas yet, like the other design-phase changes.
        - This change and all five specs it touches validate.

**Validation:**

| Suite | Result |
|---|---|
| `kit/resource-pools` | 107 passed |
| `kit/site` | 254 passed, including integration |
| `kit/fulfillment` | 176 passed, including integration |
| Kit aggregate | 15 suites passed |
| Provisioning unit | 664 passed |
| Provisioning integration | 245 passed |
| `test-bare-metal` | domain 75, storefront 126, buyer 11, adapter 2 |

Root `make test` passed before the 5R.6–5R.9 target changes. **Archival gate:**
record here the result of a root `make test` on the final tree. That run
includes `test-bare-metal`, `test-compute-provisioning`, and `test-vms-domain`,
along with the `reinit` targets added in 5R.8 and 5R.9. Typing is unrun: no
touched package configures a type checker.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| The resource-pool projection is built from capacity declarations alone and carries no host connection identity (D1) | `openspec/specs/site-capacity/spec.md#requirement-the-resource-pool-projection-is-built-from-capacity-declarations`; `#requirement-resource-pool-projection-metadata`; `#requirement-projected-inventory-is-internally-consistent` |
| Naming a host is optional for a declaration (D6) | `openspec/specs/site-capacity/spec.md#requirement-a-capacity-declaration-names-the-host-it-is-delivered-through` |
| Admission refuses a declaration naming no host where the pool's provider needs one (D5) | `openspec/specs/site-capacity/spec.md#requirement-admission-applies-the-pool-providers-host-requirement` |
| Providers declare the host requirement, registration and composition refuse disagreement, scheduling rechecks it, and a recorded no-host assignment is refused (D5, A1, A5, A6) | `openspec/specs/fulfillment/spec.md#requirement-a-provider-declares-whether-its-delivery-needs-a-host`; `#requirement-scheduling-applies-the-pool-providers-host-requirement` |
| Each execution layer rechecks the host requirement | `docs/development/ARCHITECTURE.md#resource-pools` |
| Execution inventory comes only from the registered host record; the inventory file is a seed input (D2, A3) | `openspec/specs/physical-provisioning/spec.md#requirement-execution-inventory-comes-only-from-the-registered-host-record`; `#requirement-host-inventory-is-connection-identity` |
| The tenant address falls back to the record's connection address (D3, A2) | `openspec/specs/physical-provisioning/spec.md#requirement-the-tenant-facing-host-address-falls-back-to-the-connection-address`; `docs/seller-quickstart.md` |
| The bare-metal view is built from its declaration (D4) | `openspec/specs/physical-provisioning/spec.md#requirement-a-bare-metal-publication-view-is-built-from-its-capacity-declaration`; `#requirement-bare-metal-inventory-binds-an-existing-provider-pool` |
| The host is joined at dispatch only, and why | `openspec/specs/site-capacity/architecture.md#declared-capacity-and-connection-identity` |
| Library integration tests and the host-requirement test matrix (A8) | `docs/development/TESTING.md#2-integration-tests`; `#test-file-layout`; `#host-requirement-enforcement` |
| Seed-only inventory and adding hosts after first boot (A4) | `docs/development/DEPLOYMENT_AND_CONFIG.md#definition-documents`; `docs/seller-quickstart.md`; `docs/bare-metal-seller-quickstart.md` |
| Roadmap Goals 7 and 1 | `docs/development/ROADMAP.md` |
| Campaign index rows and the two unowned findings | `openspec/changes/README.md` |
| Disabled-host admission and placement | Handed to `pools-6-fair-scheduling-policy` (temporary; not promoted) |
| Bare-metal duplicated host identity | Handed to `pools-8-capacity-projection-and-listing-hints` (temporary; not promoted) |
| One registration source per adapter package | Unowned follow-up, recorded in `openspec/changes/README.md` (temporary; not promoted) |
