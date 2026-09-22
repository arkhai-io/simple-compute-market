# Tasks — project capacity declarations that name no host

Implements `design.md` decisions D1–D9 as amended by A1–A4. The pre-design task
list, none of which was complete, was replaced at planning; `design.md` records
why its approach (an additive inversion omitting host fields) was rejected.

Paths are relative to the repository root. Sections follow the migration order
in `design.md`: refusal lands before visibility. Section 5 must not merge ahead
of Sections 2 and 3, or a declaration naming no host becomes publishable before
admission refuses it.

Suites named below:

| Suite | Command |
|---|---|
| `resource-pools` | `make -C kit/resource-pools test` |
| `site` | `make -C kit/site test` |
| `fulfillment` | `make -C kit/fulfillment test` |
| `provisioning` | `make -C provisioning/compute/service test`, which also covers the VM provisioning adapter |
| `bare-metal-adapter` | `uv run pytest -q` in `domains/bare_metal/provisioning/adapter` |

Each suite runs against wheels rebuilt from this branch (`make dist`) and
reinstalled by the package's `reinit` target, per `ARCHITECTURE.md`'s
packaging rules.

## 1. Providers declare whether delivery needs a host

- [ ] 1.1 Add the fail-closed predicate beside `pool_delivers_offering_mode` in
      `kit/resource-pools/src/market_resource_pools/hints.py`, and export it
      from `kit/resource-pools/src/market_resource_pools/__init__.py`.
      - With no supplied requirement, no pool needs a host.
      - With a supplied requirement, a provider identity it does not name needs
        a host.
- [ ] 1.2 Require a class-level `needs_host` declaration on
      `FulfillmentProvider` in `kit/fulfillment/src/market_fulfillment/provider.py`.
      A subclass that does not declare it cannot be registered.
- [ ] 1.3 Declare `needs_host = True` on both concrete providers:
      - `AnsibleFulfillmentProvider`
        (`domains/vms/provisioning/adapter/src/vm_provisioning_adapter/services/ansible_fulfillment_provider.py`);
      - `BareMetalFulfillmentProvider`
        (`domains/bare_metal/provisioning/adapter/src/bare_metal_provisioning_adapter/services/bare_metal_fulfillment_provider.py`).
- [ ] 1.4 Declare it on every test double subclassing `FulfillmentProvider`:
      - `provisioning/compute/service/tests/unit/test_composition.py`;
      - `provisioning/compute/service/tests/unit/services/test_fulfillment_convergence.py`;
      - `provisioning/compute/service/tests/unit/services/test_fulfillment_convergence_after_legacy_backfill.py`.

      Re-run the subclass search at implementation time rather than trusting
      this list.
- [ ] 1.5 Export each adapter package's host requirement, keyed by provider
      identity and derived from its provider class attributes (A1), from:
      - `domains/vms/provisioning/adapter/src/vm_provisioning_adapter/bundle.py`;
      - `domains/bare_metal/provisioning/adapter/src/bare_metal_provisioning_adapter/bundle.py`.
- [ ] 1.6 In `provisioning/compute/service/src/compute_provisioning_service/composition.py`,
      accept the expected host requirement and refuse to start when it does not
      name exactly the registered provider identities, or when a registered
      provider instance declares differently. Validate before any other state is
      built, beside `_validate_provider_pairing`.
- [ ] 1.7 In `provisioning/compute/service/src/compute_provisioning_service/container.py`,
      merge the two package exports once and pass the result to
      `CapacityLedgerService`, `PhysicalSettlementScheduler`, and composition.
- [ ] 1.8 **Unit.**
      - The predicate: known needs host, known needs none, unknown with a
        supplied requirement, no requirement.
      - Composition refusal for a missing identity, an extra identity, and a
        disagreeing declaration, each asserting no registry is returned.
      - A provider subclass without the declaration is refused.

**Validation:** `resource-pools`, `fulfillment`, `provisioning`,
`bare-metal-adapter`.

## 2. Admission applies the host requirement

- [ ] 2.1 Accept an optional host requirement in `CapacityLedgerService.__init__`
      in `kit/site/src/market_site/ledger.py`. No requirement means none is
      enforced, which keeps API-credit composition unchanged.
- [ ] 2.2 In `_find_candidate`, skip a declaration that names no host when its
      pool's provider needs one, using the 1.1 predicate against the pool's
      `provider`. Load pools the way the offering-mode check already does,
      beside it and before hold accounting.
      - `probe`, `reserve`, and `resize_reservation` all select through
        `_find_candidate`, so they share the rule.
      - The skip is not an undeclared-mode refusal: an unmatched claim gets the
        ordinary no-capacity answer.
- [ ] 2.3 **Unit** (`kit/site/tests/unit`):
      - a host-requiring pool's declaration naming no host neither probes nor
        reserves, and creates no hold;
      - another eligible declaration is chosen instead;
      - a provider absent from a supplied requirement is refused;
      - with no requirement, the same declaration is admitted;
      - a declaration naming an unregistered host is admitted (registration is
        dispatch's check);
      - resize applies the same rule.

**Validation:** `site`, then `provisioning` (the ledger is exercised through the
real app there).

## 3. Scheduling applies the host requirement

- [ ] 3.1 Accept the host requirement in `PhysicalSettlementScheduler.__init__`
      in `kit/fulfillment/src/market_fulfillment/scheduler.py`.
- [ ] 3.2 In `_eligible_candidates_in_transaction`, exclude a candidate whose
      declaration names no host when its pool's provider needs one.
      - The explicit-constraint path selects from the same list, so it rejects
        such a candidate as `NoEligibleSettlementResourceError` before policy,
        rebind, or cursor write.
      - Leave the existing-assignment branch unchanged (D5): its host is frozen
        on the record.
- [ ] 3.3 **Unit** (`kit/fulfillment/tests/unit`):
      - automatic selection never picks the excluded candidate;
      - with no other candidate, no rebind, cursor save, or assignment occurs,
        asserted on the scheduling unit of work;
      - an explicit constraint naming it is rejected without cursor access;
      - an existing assignment whose declaration was later re-registered without
        a host is still returned.
- [ ] 3.4 **Integration**
      (`provisioning/compute/service/tests/integration/`).
      - Setup:
        - register a pool with provider `ansible` through `ProvisioningClient`;
        - register in it a declaration naming no host, and one naming a
          registered host, through `SiteCapacityAdminClient`;
        - reserve through `SiteCapacityClient`.
      - Assert the reservation binds the hosted declaration.
      - Then register only a declaration naming no host and assert the reserve
        answer is no capacity.
      - Scheduling through the compute provisioning client with an explicit
        constraint on the declaration naming no host answers 422
        `no_eligible_resource`.
      - The provider boundary is mocked and asserted never invoked. This is an
        effect-prevention claim, so it belongs at this level.

**Validation:** `fulfillment`, `provisioning`.

## 4. Dispatch fails closed; the static inventory is seed-only

- [ ] 4.1 In `domains/vms/provisioning/adapter/src/vm_provisioning_adapter/services/job_service.py`:
      - make `host_service` a required constructor argument;
      - resolve the host record before any playbook starts;
      - fail the job with a message naming the unregistered host when there is
        no record;
      - delete the `resolved_inventory_path` fallback (currently `:486-512`).
- [ ] 4.2 Pass the tenant address as the record's `public_host`, else its
      `ssh_host`, into `parse_playbook_result`. In
      `domains/vms/provisioning/adapter/src/vm_provisioning_adapter/services/ansible_service.py`,
      use that address alone and delete the static-file lookups (currently
      `:585-590`).
- [ ] 4.3 Delete the static-inventory readers left without a caller (A3):
      - `parse_inventory`, `get_inventory`, `lookup_host_ip`,
        `lookup_public_host`, and the static `check_connectivity` in
        `ansible_service.py`;
      - their mirrors in `services/mock_ansible_service.py`;
      - `InventoryHost` and `InventoryResponse` in `models/ansible.py`, keeping
        `ConnectivityResult`.

      Confirm each has no caller before deleting it.
- [ ] 4.4 Tombstone the unused legacy service and its only test:
      - `domains/vms/provisioning/adapter/src/vm_provisioning_adapter/services/provisioning_service.py`;
      - `provisioning/compute/service/tests/unit/services/test_provisioning_service.py`.

      Re-confirm no production import first.
- [ ] 4.5 In `domains/bare_metal/provisioning/adapter/src/bare_metal_provisioning_adapter/services/bare_metal_operations_service.py`,
      make `host_service` required and remove the branch that skips host
      validation without it.
- [ ] 4.6 Update constructors and fixtures that omit `host_service` or stub the
      deleted readers:
      - `provisioning/compute/service/tests/integration/conftest.py`
        (`fake_ansible`'s `lookup_host_ip`);
      - `tests/integration/test_test_controller.py`;
      - `tests/unit/services/test_ansible_service.py`;
      - `tests/unit/services/test_programmable_mock.py`;
      - bare-metal adapter tests.

      Leave `inventory_path`, `inventory_ini`, and `app_runtime.py`'s seeding
      unchanged; they are the seed input.
- [ ] 4.7 **Unit.**
      - The tenant address prefers `public_host`, falls back to `ssh_host`, and
        never reads a file.
      - A job for an unregistered host fails before `start_playbook`.
      - Bare-metal validation refuses an unregistered host with no optional
        path.
- [ ] 4.8 **Integration.** Through the real app with the Ansible boundary mocked:
      - a VM job whose `host_id` names no registered host fails with the
        playbook never started, while a static inventory file naming that host
        is present in settings;
      - a registered host's job renders from its record.

**Validation:** `provisioning`, `bare-metal-adapter`.

## 5. The projection is built from declarations alone

- [ ] 5.1 Rewrite `load_capacity_resource_inventory` in
      `provisioning/compute/service/src/compute_provisioning_service/services/capacity_inventory.py`
      as a function of declarations alone (D1).
      - No session or `Host` query, one entry per declaration.
      - Identity, pool, type, capacity, reported `available`, attributes (minus
        `bare_metal_publication`), and `enabled` all come from the declaration.
      - No `host_id` or `public_host` attribute is added.
      - Remove the duplicate-host guard; registration owns uniqueness.
- [ ] 5.2 Build the `bare_metal.v2` view from the declaration (D4).
      - Its `host_id` is the declaration's field.
      - `available` is the declaration's `enabled` and whole-resource
        availability.
      - An enabled publication naming no host yields no view instead of raising.
- [ ] 5.3 Update `_capacity_resource_inventory` in
      `provisioning/compute/service/src/compute_provisioning_service/main.py`
      to the new signature.
- [ ] 5.4 **Unit.** Rewrite
      `provisioning/compute/service/tests/unit/services/test_capacity_inventory.py`
      against frozen declaration fixtures covering fungible and specific-resource
      pools. Cover:
      - a declaration naming no host;
      - a declaration naming an unregistered host;
      - no host fields on any entry;
      - `enabled` from the declaration alone;
      - undeclared attributes absent rather than null;
      - reported availability only;
      - the view from the declaration, including an enabled publication with no
        host yielding no view while the rest of the generation projects;
      - the allowlist refusal for a private publication capability, kept.

      Assert exact equality with the fixtures. These are the contractual
      regression evidence; a deployment diff is supplementary only.
- [ ] 5.5 **Integration** (`provisioning/compute/service/tests/integration/test_capacity_api.py`).
      - A declaration naming no host, registered through
        `SiteCapacityAdminClient`, appears through
        `SiteCapacityClient.resource_pool_projection()` with its capacity and
        attributes and no host fields.
      - Correct the comment in
        `test_site_resource_pools_projection_surfaces_pool_metadata` that says a
        host row is required.
      - Keep `test_the_resource_pool_projection_publishes_declarations_not_hosts`'s
        assertion that a host no declaration names is not projected.
- [ ] 5.6 Re-run the storefront consumers of the projection. Confirm that no
      reader of the removed attributes was missed; the design trace found none.
      - `make -C domains/vms/storefront test`, covering the reconciler and the
        projection cache.
      - `domains/bare_metal` `uv run pytest -q`, covering
        `trusted_bare_metal_projection`.

**Validation:** `provisioning`, the two storefront suites in 5.6.

## 6. Closeout

- [ ] 6.1 **Comment hygiene.** Run `make check-comment-hygiene` and resolve every
      match. Then read every comment and docstring this change touched for the
      violations the target does not catch.
      - `capacity_inventory.py`'s module docstring states why the projection
        reads no host record.
      - The ledger and scheduler checks state the fail-closed rule and point to
        `openspec/specs/site-capacity/spec.md` and
        `openspec/specs/fulfillment/spec.md`.
      - Remove stale docstrings that describe the static fallback, such as
        `ansible_service.py:10` and the tenant-address docstring.
- [ ] 6.2 **Import placement.** For each import this change added or touched,
      move function-level imports to module level unless an actual circular
      import (verified by attempting the move) or a documented lazy-load reason
      keeps it local. Verify each move against the real suites. Include the
      container and composition imports of the adapter packages' host
      requirements.
- [ ] 6.3 **Documentation compliance.** Re-check D1–D9 and A1–A4 against
      `openspec/README.md`'s placement table.
      - Behaviour implementations must satisfy lands as normative requirements.
      - Rationale lands in `openspec/specs/site-capacity/architecture.md`.
      - The layer-recheck rule lands in `ARCHITECTURE.md`.
- [ ] 6.4 **Narrative compression.** Shorten completed-task notes to final
      behaviour, material evidence (the 5.4 fixture equality, 3.4 and 4.8
      effect-prevention), and permanent destinations. Move any debugging
      narrative into `design.md` first.
- [ ] 6.5 **Roadmap currency** (`docs/development/ROADMAP.md`).
      - **Goal 7:** remove this change's gap row, and replace the current-state
        sentence "The resource-pool projection enumerates host inventory, so a
        seller who declares sellable capacity with no host behind it declares
        into a void…" with the resulting state.
      - **Goal 1:** add that execution inventory is sourced only from the host
        registry and the projection carries no host connection identity. No gap
        row changes.
      - Record both dispositions in the promotion record.
- [ ] 6.6 **Campaign index currency** (`openspec/changes/README.md`).
      - Set this change's Goal 7 row to complete, awaiting archival, and keep
        the dependency graph edge to `unbacked-listing-publication`.
      - Update that row's "blocked on the three above" once this change is
        complete.
      - Add to the unowned-work table: the bare-metal access playbook reports no
        tenant address (A2).
      - This change creates, renames, and removes no change directory, so no
        link reconciliation is owed.
- [ ] 6.7 **Documentation citations.** Run
      `make check-doc-citations CHANGE=project-capacity-resources-without-hosts`
      and resolve every match.
      - An unresolvable citation is a blocking defect under `AGENTS.md`.
      - The target also rejects a citation to a tombstone. Section 4.4
        tombstones two files, so confirm no document cites them.
- [ ] 6.8 **End-to-end pipeline.** Run the end-to-end pipeline
      (`make -C e2e-tests test-e2e`) and record the run, its result, and the
      scenarios exercising this change:
      - `tests/e2e/roles/scenarios/vms/test_compute_dynamic_listings.py`
        (projection-backed listings under the reshaped projection);
      - `test_full_deal.py` and `test_full_deal_buyer_cli.py` (registry-rendered
        dispatch and the tenant address);
      - `test_pool_declared_offering_modes.py` (admission unchanged for a hosted
        declaration).

      If the pipeline cannot run for a reason unrelated to this change, record
      the blocker, name the cause and its owning change, and treat the gated
      validations as unrun.
- [ ] 6.9 **Promotion.** Complete the record below. This is post-code-review,
      per `AGENTS.md`.
      - Promote the three spec deltas.
      - Add to `openspec/specs/site-capacity/architecture.md`'s "Declared
        capacity and connection identity" that the host is joined only at
        dispatch, and why.
      - Add to `docs/development/ARCHITECTURE.md#resource-pools` that each
        execution layer rechecks a pool provider's host requirement as it does
        offering modes.
      - Add to `docs/development/TESTING.md` a host-requirement enforcement
        matrix beside "Pool Offering-Mode Enforcement".
      - Add to `docs/development/DEPLOYMENT_AND_CONFIG.md` that the inventory
        file is a seed input, with A4's consequence.
      - In `docs/seller-quickstart.md`, keep the `public_host` fallback
        sentence, now true on every deployment, and add A4.
      - In `docs/bare-metal-seller-quickstart.md`, replace "mounted inventory"
        with the seed-input statement and add A4.
      - Report any unrun suite, including typing: none of the touched packages
        configures a type checker today.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| The resource-pool projection is built from capacity declarations alone and carries no host connection identity (D1) | `openspec/specs/site-capacity/spec.md` — pending |
| Naming a host is optional for a declaration (D6) | `openspec/specs/site-capacity/spec.md` — pending |
| Admission refuses a declaration naming no host where the pool's provider needs one (D5) | `openspec/specs/site-capacity/spec.md` — pending |
| Providers declare the host requirement; composition verifies it; scheduling rechecks it (D5, A1) | `openspec/specs/fulfillment/spec.md` — pending |
| Each execution layer rechecks the host requirement | `docs/development/ARCHITECTURE.md#resource-pools` — pending |
| Execution inventory comes only from the registered host record; the static file is a seed input (D2, A3) | `openspec/specs/physical-provisioning/spec.md` — pending |
| The tenant address falls back to the record's connection address (D3, A2) | `openspec/specs/physical-provisioning/spec.md`, `docs/seller-quickstart.md` — pending |
| The bare-metal view is built from its declaration (D4) | `openspec/specs/physical-provisioning/spec.md` — pending |
| The host is joined at dispatch only, and why | `openspec/specs/site-capacity/architecture.md` — pending |
| Host-requirement test matrix | `docs/development/TESTING.md` — pending |
| Seed-only inventory and adding hosts after first boot (A4) | `docs/development/DEPLOYMENT_AND_CONFIG.md`, both quickstarts — pending |
| Roadmap Goals 7 and 1 | `docs/development/ROADMAP.md` — pending |
| Campaign index row and unowned bare-metal access address | `openspec/changes/README.md` — pending |
| Disabled-host admission and placement | Handed to `pools-6-fair-scheduling-policy` (temporary; not promoted here) |
| Bare-metal duplicated host identity | Handed to `pools-8-capacity-projection-and-listing-hints` (temporary; not promoted here) |
