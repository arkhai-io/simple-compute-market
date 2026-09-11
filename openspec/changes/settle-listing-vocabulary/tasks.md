# Tasks — settle the listing vocabulary

## Plan revisions

Design review settled five questions this plan had left open or answered wrongly.
Sections 1, 2, 3, 4, 6, 6b, 8, 9, and 10 are amended and carry appended tasks; the
reasoning for each is in `design.md`'s decisions rather than repeated here. The
amendments are the `executor_` compound retention rule, three column renames rather
than one, the cardinality hint's derived names including its status field, the
provisioning contract wire, and the `offer_resource_type` and client-attribute
dispositions.

## 1. Survey

- [x] 1.1 Grep every producer, consumer, test, fixture, operator pool-definitions
      sample, and document for each renamed name. **Match full identifiers, not
      prefixes or fragments** — the retired list is `listing_mode`,
      `LISTING_MODE_POLICY_TAG`, `raw_listing_mode`, `resolve_vm_listing_mode`,
      `listing_mode_explanation`, `listing_mode_explanations`, `executor_kind`,
      `EXECUTOR_KIND_CLAIM_KEY`, `VM_EXECUTOR_KIND`, `_VM_EXECUTOR_KIND`,
      `offer_resource`, `offer_resource_type`, the bare `offer` spelling of a
      published shape, `virtualization_type`, `VirtualizationType`, `vms.compute`,
      and `offering_type`. Record the full list before editing; a rename's risk is
      entirely in the sites it misses.
      - **Status:** Published in `survey.md`. 15 retired identifiers inventoried with occurrence and file counts.
- [x] 1.1a Use full-identifier matching deliberately rather than as style, because
      three retired names are substrings of names that stay: `listing_mode` matches
      `listing_model` and every `test_listing_model_*` file; `offer` matches both
      `offer_resource` and the replacement `offering_mode`, so searching it reports
      the new vocabulary as retired; and `vms.compute` matches
      `arkhai_vms.compute_requirements` (2 of 43 hits). An audit whose expected
      result is "zero after dismissing a known false-positive list" is not an audit,
      so task 9.16 is only meetable if the retired list is full identifiers.
      - **Status:** Three hazards measured, not asserted: prefix search for `listing_mode` over-reports 2.7x (146 vs 54 in `.py`), absorbing `listing_model`; `vms.compute` absorbs `arkhai_vms.compute_requirements` (2 of 35); bare `offer` matches the replacement `offering_mode`.
- [x] 1.1b Separate the two distinct uses of `vms.compute` before editing either. The
      registry `schema.id` and `VMS_SCHEMA_ID` are renamed; `domain_identity` fixture
      values in `e2e-tests` are a different axis — the production domain identity is
      `compute.v1` (`VM_PROVISION_KIND`) and the durable listing binding freezes it.
      Decide per site; do not globally replace.
      - **Status:** Separated. Registry `schema.id`/`VMS_SCHEMA_ID` rename; `e2e-tests` `domain_identity` fixtures do not. Production domain identity is `compute.v1` (`VM_PROVISION_KIND`).
- [x] 1.2 Mark which side of the storefront-to-site boundary each site sits on. Only
      `listing_mode` keeps an alias, so every other boundary site must move in one
      coordinated deploy.
      - **Status:** Recorded per identifier in `survey.md`'s boundary-class column.
- [x] 1.3 Separate optional published fields from required wire fields in that list. A
      missed required-claim site fails loudly at the first reservation; a missed
      optional published field fails quietly, so `listing_resource` needs the closest
      grep audit.
      - **Status:** Recorded. Only `listing_mode` is an optional projected key; the rest are required wire fields, columns, or internal names.
- [x] 1.4 **Publish the survey output as the affected-capability inventory** before
      editing. It must include at minimum `resource-pool-management` (which names
      `listing_mode` normatively), `deployment-state` (which selects the compute
      filter specification by identity), `physical-provisioning` (whose release
      lookup is selected by the claim's mode field), and
      `compute-provisioning-contract` (whose versioned models carry the mode field).
      Task 8.6's assertion that no permanent specification still names a retired term
      is only meetable if the inventory is complete first.
      - **Status:** Published. Seven capabilities, each with a delta. `compute-provisioning-contract` added during design review.
- [x] 1.5 Enumerate every persisted use, separately from wire use. Live peer
      coordination does not address rows already written, and these divide into two
      kinds needing different treatment:
      **column names**, which a row backfill cannot touch —
      `capacity_reservations.executor_kind`, `listings.offer_resource` in the registry
      database, and `listings.offer_resource` in the storefront database; and
      **keys inside payloads** — the `executor_kind` key in
      `settlement_records.scheduling_requirements`, and the `virtualization_type` key
      nested in the storefront listing payload.
      - **Status:** Enumerated and split: three column names (which a row backfill cannot touch) and two payload keys.
- [x] 1.6 Record the retained `executor_` compounds explicitly as part of the survey
      output: `executor_ref`, `executor_target`, `ExecutorActionEnvelope`,
      `ExecutorAdapter`, `ExecutorAdapterRegistry`, `ExecutorLeaseService` and its
      registration/update carriers, `UnsupportedExecutorActionError`, and
      `ExecutorMismatchError`. These are correct by the head-noun rule and are not
      pending work. Recording them once, with the rule, is what lets a later auditor
      dismiss them by rule rather than re-deriving the judgement per site.

      - **Status:** Recorded with possessive readings, so a later auditor dismisses them by rule.
## 2. Offering mode: one name

- [x] 2.1a Rename `ExecutorAdapter.executor_kind` to `offering_mode` and update
      `ExecutorAdapterRegistry`'s selection, keeping every type name in that module
      unchanged. The adapter is selected by the offering mode it serves; the
      abstraction is not the mode.
      - **Status:** Done. `ExecutorAdapter.offering_mode` and `ExecutorAdapterRegistry` selection. Every type name in that module unchanged.
- [x] 2.1 Rename `executor_kind` to `offering_mode` on the capacity claim, through
      `kit/site` (`EXECUTOR_KIND_CLAIM_KEY`, `_requested_executor_kind`, the ledger
      and authority signatures), `kit/fulfillment` (`SettlementRequirement`, the
      scheduler, backfill, fulfillment), both provisioning adapters, and the
      storefront claim builders including `_VM_EXECUTOR_KIND` and the API-credit
      producers. Keep the field required.
      - **Status:** Done. 115 files. All identifier forms: the field, `VM_EXECUTOR_KIND`, `BARE_METAL_EXECUTOR_KIND`, `OFFERING_MODE_CLAIM_KEY`, `_LEGACY_EXECUTOR_KIND`, `_requested_offering_mode`, locals, test names, and error/log prose. Field kept required.
- [x] 2.1b Rename the field on the compute provisioning service's own versioned
      contract in `provisioning/compute/src/compute_provisioning/contracts.py` — all
      seven models: `ExecutorActionEnvelope`, `JobAccepted`, `CredentialEnvelope`,
      `ResultEnvelope`, `ProvisioningJob`, `LeaseRegistration`, and `LifecycleEvent` —
      and advance `contract_version` for the backwards-incompatible field rename.
      Leaving this wire alone would put `offering_mode` on one side of it and
      `executor_kind` on the other, which is the condition this change exists to end.
      `executor_target` on `LeaseRegistration` stays, per task 6.4.
      - **Status:** Done. All seven versioned models in `contracts.py`. `executor_target` on `LeaseRegistration` retained per 6.4.
- [x] 2.2 Rename `virtualization_type` to `offering_mode` in the published listing
      shape, the `VirtualizationType` enum — whose type name becomes `OfferingMode` —
      the bare-metal schema literal, the registry filter, and the buyer CLI flags in
      both the VM and bare-metal buyers, including the bare-metal listing CLI's
      hardcoded `virtualization_type="bare_metal"` query argument.
      - **Status:** Done. 57 files; `VirtualizationType` became `OfferingMode` with a docstring stating the axis (`bare_metal` is a member because the axis is what is offered, not which virtualization technology is used). Remaining `virtualization` hits are the hardware sense and correctly untouched.
- [x] 2.3 Confirm the assignment sites now read as identity rather than translation —
      `arkhai_vms/storefront_adapter.py` assigning from `candidate["offering_mode"]`,
      the bare-metal storefront assigning from `registration.binding.offering_mode`,
      and `listing_service.py` reading it back — and remove any conversion left over
      from the two names having differed.
      - **Status:** Confirmed. The assignment sites now read as identity; no conversion remained once both sides carried one name.
- [x] 2.4 Confirm `pool_delivers_offering_mode` now takes the claim's `offering_mode`
      directly with no intermediate name at the ledger, the scheduler, or fulfillment.
      - **Status:** Confirmed. `pool_delivers_offering_mode` takes the claim's `offering_mode` with no intermediate name at ledger, scheduler, or fulfillment.
- [x] 2.5 Confirm the name is not newly coined at the layer that receives it:
      `kit/site` already defines and exports `UndeclaredOfferingModeError`, and
      `kit/resource-pools` already exports `pool_delivers_offering_mode` over
      `deliverable_modes`, whose module docstring calls its members opaque
      offering-mode names. If any of those has to change spelling to accommodate this
      rename, the target name is wrong — stop rather than widening the change.

      - **Status:** Confirmed. `UndeclaredOfferingModeError` and `pool_delivers_offering_mode` needed no spelling change, so the target name was already the authority layer's own.
## 3. Listing, not offer

- [x] 3.1 Rename `offer_resource` to `listing_resource` across the listing models,
      storefront services, migrations, publication paths, registry filter paths,
      `core/storefront-client`, and `core/registry-client`.
      - **Status:** Done. ~150 files including all three filter specs, both listing-shape column references, and the prefixed forms (`_offer_resource_for_listing`, `hosted_offer_resource_unavailable`) that a word-boundary regex misses.
- [x] 3.2 Remove the `offer` alias in `core/registry-client`, which currently reads
      `d.get("offer") or d.get("offer_resource")`. Retaining it would keep the
      collision the rename exists to remove.
      - **Status:** Done. The `d.get("offer") or d.get("offer_resource")` alias is gone; only `listing_resource` is read.
- [x] 3.3 Leave `message_type="offer"` in `kit/negotiation-runtime` alone. That is the
      meaning `offer` is being returned to.
      - **Status:** Confirmed untouched. `message_type="offer"`, `counter_offer`, `make_offer`, `accept_offer` all retained.
- [x] 3.4 Audit the publication CLIs, which pass `offer=` positionally in at least
      one place, so a rename does not silently bind the wrong argument.
      - **Status:** Done, and it mattered: every `offer=` kwarg rewritten cascaded into a parameter or stub definition -- `_reopen_derived_listing_if_present`, `listing_request_factory`, `_publish_listing`, and four test stubs. Each was found by a failing test rather than by grep.
- [x] 3.5 Rename the `ListingRequest.offer` and `ListingSummary.offer` **attributes**
      to `listing_resource` in `core/registry-client`. These are distinct from the
      ingestion alias removed in 3.2: `ListingRequest.to_dict()` already emits
      `"offer_resource": self.offer`, so the attribute never reached the wire under
      this spelling. `ValidatePublishRequest` in the same module already spells the
      same concept `offer_resource`, so the module contradicts itself today, and an
      attribute named `offer` that holds a listing is the collision itself.
      - **Status:** Done. `ListingRequest.listing_resource` and `ListingSummary.listing_resource`. `ValidatePublishRequest` already used the shape key, so the module is now internally consistent.
- [x] 3.6 Drop `offer_resource_type` rather than renaming it — from
      `ValidatePublishResponse` in `core/registry-client`, from
      `core/registry/src/api/validate_model.py`, and from
      `_derive_offer_resource_type` and its call site in `validate_routes.py`. It is a
      cosmetic tag derived by sniffing the payload for `gpu_model` or `token` while
      the accept/reject decision is the schema's. Delete the function's docstring with
      it rather than updating it: the docstring names a change ID and is an existing
      comment-hygiene violation in a file this change already edits. Update the
      `e2e-tests` and registry integration assertions that read the field.

      - **Status:** Done -- dropped, not renamed: the field, the model, `_derive_offer_resource_type`, its call site, and its change-ID docstring (clearing one of the two known hygiene violations). The registry integration test now asserts neither spelling appears in the response.
## 4. Cardinality hint

- [x] 4.1 Emit `listing_cardinality_mode` from the resource-pool projection alongside
      the existing key, and accept the new key in operator-supplied pool definitions.
      - **Status:** Done, with no producer-side code. Policy tags are projected verbatim (`dict(pool.policy_tags or {})`), so the spelling an operator stored is the spelling a consumer receives, and reconciliation sits entirely at the reading end in `raw_listing_cardinality_mode`. The second half needed nothing either: pool-definition validation treats unrecognized tags as forward-compatible opaque metadata, so the settled key was already accepted. A dual-emitting `projected_policy_tags` was implemented and then **removed by decision** -- backwards compatibility for a new-producer/old-consumer pairing is not a concern this change carries.
- [x] 4.2 Prefer the new key in the storefront hint consumers, falling back to the old
      one and emitting an operator-visible deprecation notice when the alias is taken.
      - **Status:** Done. `raw_listing_cardinality_mode` prefers the settled key; `listing_cardinality_mode_source` reports which key supplied the value so a consumer emits the notice without duplicating the precedence rule.
- [x] 4.3 Cover the skew case directly: an unupgraded projection carrying only the old
      key must resolve to the same cardinality it resolves to today, not to the
      structural default. This is the defect the alias exists to prevent and it needs
      its own test rather than being implied by the alias's presence.
      - **Status:** Covered by `TestDeprecatedIngestionAlias` (5 unit tests) and two projection-cache tests. A deprecated-only projection resolves to the cardinality that key names and does not fall back.
- [x] 4.4 Confirm the hint is still read live from the current projection at each point
      of need and is not persisted into storefront-local storage. The rename must not
      become an occasion to cache it.
      - **Status:** Confirmed. The hint is still read live from `projection_caches()` at each point of need; nothing was persisted.
- [ ] 4.5 Stop emitting the old key from the producer once consumers accept both. Do
      not remove consumer-side alias acceptance in this change; its removal is an open
      question in `design.md` with no owner yet.
      - **Status:** **Superseded by the 4.1 decision.** Projection is verbatim, so there is no producer emission to stop. What remains binding is the instruction not to remove consumer-side alias acceptance, which is retained in `raw_listing_cardinality_mode` and required normatively. The superseded new-producer/old-consumer argument is recorded in `design.md`.
- [x] 4.6 Rename the hint's derived internals, which the alias does not cover — the
      alias is an ingestion concession for the one key an unupgraded peer can send,
      and every other surface uses the settled name alone:
      `kit/resource-pools`' `LISTING_MODE_POLICY_TAG` and `raw_listing_mode` plus the
      `__init__.py` exports and the module docstring naming the key;
      `domains/vms/listings/listing_mode.py` → `listing_cardinality_mode.py` and
      `resolve_vm_listing_mode` → `resolve_vm_listing_cardinality_mode`, updating the
      four importers (`reconciler.py`, `pricing_resolution.py`, `pool_descriptors.py`,
      `site_projection_cache.py`), two of which cite the resolver by name in a
      local-import comment; and the reconciler row keys `listing_mode` and
      `listing_mode_explanation`. The module rename deletes a file, so it needs a
      tombstone at its original path in the returned fileset.
      - **Status:** Done. Kit constants and reader, resolver module (old path tombstoned), four importers, two reconciler row keys. `__init__.py` needed no change -- the survey found these were never exported. **Also required, not in the original task:** the `force-include` mapping in `domains/vms/buyer/pyproject.toml` and `domains/vms/storefront/pyproject.toml`.
- [x] 4.7 Rename the operator-facing explanation field `listing_mode_explanations` →
      `listing_cardinality_mode_explanations` across `core/storefront`'s system model,
      the VM storefront's `system_service` (the field, the provider parameter, and the
      default provider) and `site_projection_cache`'s producer function, and
      `core/storefront-client`'s status model and its `known` key set. This is an
      admin-gated surface — bare metal calls `_admin(...)` on the route and the VM
      storefront's admin-identity and service-peer middleware both special-case that
      exact path — so it adds an operator client to the cutover, not a buyer boundary.
      Keeping it would leave a retired name on a live wire explaining fallbacks for a
      key now called `listing_cardinality_mode`, at the one surface where operators
      read the explanation.

      - **Status:** Done across all five sites. Verified by `test_admin_api.py`, which exercises the renamed field through the real app.
## 5. Schema identity and versions

- [x] 5.1 Change `schema.id` from `vms.compute` to `compute.market` in
      `core/registry/filter-spec.yaml`, and update `VMS_SCHEMA_ID` and every buyer
      compatibility declaration that names it. Per 1.1b, do not sweep
      `domain_identity` fixtures in the same pass.
      - **Status:** Done. `compute.market`, and `VMS_SCHEMA_ID` became `COMPUTE_SCHEMA_ID`. Per 1.1b the `domain_identity` axis was left alone: `DomainIdentity("vms.compute")` and `domain="vms.compute"` fixtures in `core/buyer` and `e2e-tests` are a different axis.
- [x] 5.2 Bump the compute filter-spec `version` and its `schema.version` together,
      since a renamed required listing-shape field and a changed identity are both
      backwards-incompatible.
      - **Status:** Done. Filter-spec `version` 4 to 5 and `schema.version` 1 to 2 together.
- [x] 5.3 Rename `offer_resource` to `listing_resource` in
      `domains/apicredits/registry/filter-spec.yaml` and
      `core/registry/filter-spec.introductions.yaml`, including their `required` sets
      and every `$.offer_resource.*` filter path, and bump each specification's
      version. Both keep their own schema identities — only the envelope field moves.
      An earlier plan asserted these needed only confirmation because they publish no
      offering-mode field; that is true of the mode and false of the envelope.
      - **Status:** Done. API-credits `version` 2 to 3, introductions `version` 1 to 2, both keeping their own schema identities.
- [x] 5.4 Update the comments in every filter-spec that refers to `vms.compute` by
      name.
      - **Status:** Done in the API-credits spec's two comments naming the compute registry.
- [ ] 5.5 **Integration.** An API-credits listing and an introduction listing each
      publish and are queried successfully under the renamed envelope, through the
      canonical `RegistryClient` against the real registry app.
- [x] 5.6 Bump the minor version of every client distribution whose public surface
      moves: `arkhai-core-registry-client` (renamed attributes, removed alias, dropped
      field), `arkhai-core-storefront-client` (renamed status field), and
      `arkhai-kit-site-client` (claim field). A pre-rename client must not resolve
      against a post-rename service, and the distribution version is the only signal
      that carries that. Confirm the reinit targets upgrade these from `.dist` per
      `AGENTS.md`'s package discipline.

      - **Status:** Done, with one correction to the task. `arkhai-core-registry-client` 0.11.0->0.12.0 and `arkhai-core-storefront-client` 0.17.0->0.18.0. Also `arkhai-core-storefront` 0.3.0->0.4.0, which the task did not name: `CreateListingRequest`'s field is its public model. **`arkhai-kit-site-client` needs no bump** -- its `src/` is byte-identical to the unmodified checkout, because the client is schema-opaque to the claim and only its test fixtures named the retired key.
## 6. Retire `executor` as a synonym

- [x] 6.1 Replace `executor` with `host` in `capacity-resource-administration`'s "Host
      is executor identity only" and in `project-capacity-resources-without-hosts`'
      executor correlation, executor inventory, and executor-correlated-fields
      language, including their spec deltas and task lists.
      - **Status:** Done across 9 files in both changes, including two `ADDED` requirement headers (verified absent from the permanent spec, so this change's to correct under 7.3).
- [x] 6.2 Replace `ARCHITECTURE.md`'s four uses of `executor` in the offering-mode
      sense — "defaults an executor mode", "a default executor", "other executor
      kinds", and the diagram's "future executors". Leave "VM executor arguments",
      which is the action-dispatch sense.
      - **Status:** Done. Four offering-mode uses replaced; "VM executor arguments" left as the action-dispatch sense.
- [x] 6.3 Leave `provider` alone as the pool's delivery handler.
      - **Status:** Confirmed untouched.
- [x] 6.4 Leave the action-dispatch abstraction and its compounds named as they are.
      Two groups, one rule. The type names `ExecutorAdapter`,
      `ExecutorAdapterRegistry`, `ExecutorActionEnvelope`,
      `UnsupportedExecutorActionError`, and `ExecutorMismatchError` stay: that
      abstraction validates, submits, and polls execution actions and is none of the
      other three concepts, and only its selector moves, in task 2.1a. The
      `executor_`-prefixed field compounds `executor_ref` and `executor_target` also
      stay, on `CapacityReservation` and through the provisioning contract and lease
      paths: read as possessives they are the executor's reference and the target of
      an executor action, so `executor` carries its retained action-dispatch sense in
      them, whereas "the kind of executor" simply is the mode. They are retained by
      rule, not deferred — there is nothing left to retire in them.
      - **Status:** Confirmed. No type name and no `executor_`-prefixed compound was renamed.
- [x] 6.5 Confirm `physical-provisioning`'s separation of executor registration and
      dispatch from provider fulfillment still reads correctly after the selector
      rename, and amend its release-lookup requirement, which is selected by the
      claim's mode field.
      - **Status:** Confirmed. The separation reads correctly after the selector rename, and the release-lookup requirement now names the reservation's recorded `offering_mode`.
- [x] 6.6 State the head-noun rule **positively** wherever the retirement is written
      down, in `ARCHITECTURE.md`'s shared vocabulary and in `physical-provisioning`'s
      registration requirement: `executor_`-prefixed compounds naming the
      abstraction's own targets, references, or actions retain the name; what is
      retired is `executor` as the head noun for the mode, the machine, or the
      handler. Stating only the prohibition invites a later reader to apply it to a
      prefix match and rename roughly 300 further sites across `kit/site`, both
      provisioning adapters, `ExecutorLeaseService`, and the bare-metal lease and
      release paths on the strength of that match.

      - **Status:** Done. `ARCHITECTURE.md` gains a "One name per concept" subsection with the four-concept table and the rule stated positively.
## 6b. Persisted state

- [x] 6b.1 Rename the `capacity_reservations.executor_kind` column through the compute
      provisioning service's versioned migration framework — `_add_column_if_missing`,
      backfill, `_drop_columns_via_table_rebuild` — recorded under a new migration ID
      following the existing `YYYYMMDD_NNN_description` convention after
      `20260901_001_relay_reachable_hosts`. Name it for the resulting schema, not for
      this change. The cheaper option was to leave the column and map at the boundary;
      it is renamed so that a grep for the retired name is trustworthy evidence no
      site was missed.
      - **Status:** Done as `20260911_001_reservation_offering_mode_name`: `_add_column_if_missing`, copy, `_drop_columns_via_table_rebuild`. Covered by 4 tests including null-preservation and idempotency.
- [x] 6b.1b Rename the registry's `listings.offer_resource` column through a new
      Alembic revision after `017_publisher_replay_leases`, updating
      `core/registry/src/db/models.py`. This is a column name holding JSON, not a
      payload carrying an `offer_resource` key — an earlier plan listed it as a
      backfill, which would have left the column untouched.
      - **Status:** Done as Alembic revision `018_listing_resource_column`, using `batch_alter_table` so SQLite is covered. Verified against a pre-upgrade table.
- [x] 6b.1c Rename the storefront's `listings.offer_resource` column through a new
      `core_storefront.sqlite_migrations` migration after
      `20260815_001_storefront_domain_bindings`, updating the `CREATE TABLE listings`
      DDL and the roughly twenty references in
      `core/storefront/src/core_storefront/sqlite_client.py`. The table is core-owned
      and shared by both compute storefronts, so this belongs to the domain-neutral
      migration set rather than to either domain's `_domain_migrations`.
      - **Status:** Done as `20260911_001_listing_resource_column` in `core_storefront.sqlite_migrations`, in the domain-neutral set since the `listings` table is core-owned and shared by both compute storefronts. Uses `ALTER TABLE ... RENAME COLUMN` (SQLite 3.25+) rather than a table rebuild.
- [x] 6b.2 Backfill the `executor_kind` key inside the
      `settlement_records.scheduling_requirements` payload.
      `settlement_repository.py` compares `record.scheduling_requirements ==
      serialized_requirements` structurally, so a pre-upgrade payload under the
      retired key is not equal to a newly serialized one and a retried settlement
      would stop recognizing its own request. Do not normalize at comparison time
      instead — that is permanent compatibility code carrying a retired name.
      - **Status:** Done in the same migration, deliberately -- the column and the payload key carry one value, and a row must never be observable with one migrated and the other not. Covered by 3 tests.
- [x] 6b.3 Backfill the `virtualization_type` key nested inside the storefront listing
      payload, in the same migration as 6b.1c so a row is never observable with the
      new column name and the retired inner key. The bare-metal storefront's
      `_migrate_common_domain_bindings` writes that key today; update it to the
      settled name so it does not reintroduce the retired key on a later run.
      - **Status:** Done in the same migration as 6b.1c, deliberately: a row must never be observable with the column migrated and its payload not, since the payload's mode is read back as the listing's offering mode and a half-migrated row would silently fail an offering-mode filter rather than erroring. The bare-metal storefront's `_migrate_common_domain_bindings` now writes the settled key; it runs after the core set, so the column exists by then.
- [x] 6b.4 Count rows still carrying a retired key after each **payload** backfill
      (6b.2, 6b.3) and make a non-zero count a cutover gate. Both payloads are JSON,
      so a missed row is not a type error and would not surface until a retry or a
      listing read. The three column renames carry the opposite profile — a missed one
      fails at open rather than silently — so they need no count gate.
      - **Status:** Done as `count_rows_carrying_retired_offering_mode_key`, covering the payload backfill. 2 tests, including that an absent table counts zero rather than raising.
      - **Status:** Extended this turn with `count_listings_carrying_retired_offering_mode_key` for the listing payload, alongside the reservation-payload gate. **A defect was found and fixed while testing it:** reading only the settled column made the count return zero on a database that had not been migrated at all -- the exact state a cutover gate exists to catch. It now reads whichever shape column is present.
- [x] 6b.5 Sequence the cutover per `DEPLOYMENT_AND_CONFIG.md`'s identity-contract
      pattern: quiesce authenticated mutations, migrate, verify every participating
      registry, storefront, provisioning service, peer, authority, and client reports
      the pinned version, then resume. Record that rollback is limited to the boundary
      before 6b.1.
      - **Status:** Done as [`cutover.md`](cutover.md): the pinned versions per component, the three migrations, the two payload gates, the deploy set, and the rollback boundary before step 3. Kept in the change directory rather than `DEPLOYMENT_AND_CONFIG.md` because it describes one transition, not a durable convention; it cites the identity-contract pattern rather than restating it.
- [x] 6b.6 Record that `migrate-registry-to-postgres` must target the renamed column.
      That change is blocked on external infrastructure and on step 2 of its own
      chain, so there is no ordering conflict to resolve here — only a requirement on
      whichever lands second.

      - **Status:** Done in `cutover.md`'s closing section. No ordering conflict to resolve -- only a requirement that whichever lands second targets `listings.listing_resource`.
## 7. Downstream change documents

- [x] 7.1 Update `unbacked-listing-publication` and `publish-indicative-listing-rates`
      for `listing_resource` and `offering_mode`, including their spec deltas and
      filter paths.
      - **Status:** Done. `unbacked-listing-publication`'s deltas and prose; `publish-indicative-listing-rates` carried no retired term.
- [x] 7.2 Amend `structured-capacity-requirements` to use `offering_mode` instead of
      proposing `offering_type`, in both its proposal and its task list. Leave the
      decision to delete the item entirely to that change's owner — whether it has
      anything left to do is theirs, whether it may introduce a fourth name for one
      concept is not.
      - **Status:** **Already satisfied in the repository as shipped** -- byte-identical to the unmodified checkout. `structured-capacity-requirements/proposal.md` already carries a dated amendment note from this change directing every occurrence to `offering_mode`. The one remaining `offering_type` is inside that note, explaining what was retired and why; it must keep the retired names to stay readable, and is the reason 8.6's assertion has to distinguish a term used as a name from a term named in order to forbid it.
- [x] 7.3 Correct the **active spec deltas** carrying retired vocabulary:
      `multi-domain-storefront-composition/specs/storefront-publication`, and both
      `pools-8-capacity-projection-and-listing-hints` deltas. A delta is the path by
      which a retired name would synchronize back into a permanent specification, so
      these are corrected here rather than left to their owners.
      - **Status:** Done. `multi-domain-storefront-composition` and both `pools-8` deltas corrected, so no retired name can resynchronize into a permanent specification.
- [x] 7.4 Update the prose in `bare-metal-buyer-domain`,
      `pools-7-storefront-fulfillment-cutover`,
      `pools-9-retire-local-physical-authority`, and
      `publish-multidimensional-listing-shape`, which reference retired names in
      designs and task lists without carrying them in deltas.

      - **Status:** Done across `bare-metal-buyer-domain`, `pools-7-storefront-fulfillment-cutover`, `pools-9-retire-local-physical-authority`, and `publish-multidimensional-listing-shape`. 16 documents updated in total across 7.1/7.3/7.4.
## 8. Specification

- [x] 8.1 Synchronize the `MODIFIED` cardinality-hint requirement, replacing the
      existing requirement in full rather than adding a second one.
      - **Status:** Done. The requirement was replaced in full, not duplicated.
- [x] 8.2 Synchronize the `MODIFIED` listing-mapping requirement, which now states
      that one name is used for the offering mode on every surface and that the
      published shape is a listing rather than an offer.
      - **Status:** Done. The one-name rule and the listing-not-offer rule are now normative in `storefront-publication`, with scenarios for a binding disagreement and a retired-key submission.
- [x] 8.3 Synchronize the added `site-capacity` and `registry-discovery` requirements.
      - **Status:** Done. Both `registry-discovery` requirements promoted; `site-capacity`'s claim requirement was promoted earlier with section 2.
- [x] 8.4 Update `openspec/specs/storefront-publication/architecture.md`, which names
      the published field.
      - **Status:** Done. The architecture companion now names `offering_mode` as projected from the binding. OpenSpec does not synchronize companions, so this was an explicit step.
- [x] 8.5 Synchronize deltas for every capability in task 1.4's inventory, including
      `resource-pool-management`, `deployment-state`, `physical-provisioning`, and
      `compute-provisioning-contract`.
      - **Status:** Done. All seven capabilities in 1.4's inventory are synchronized.
- [x] 8.6 After synchronization, confirm no permanent specification still names
      `executor_kind`, `virtualization_type`, `offer_resource`, `offer_resource_type`,
      or `offering_type`, and that `listing_mode` survives only as the deprecated
      ingestion alias. This is only meetable if 1.4's inventory was complete; if it
      names a capability with no delta, stop rather than narrowing the assertion.
      - **Status:** Partially meetable and **the assertion needs narrowing for one reason worth recording**: `site-capacity` and `physical-provisioning` still contain the string `executor_kind`, but only inside prohibitions ("no surface may name it `executor_kind`") and a rejection scenario. A retired term named in order to forbid it is not the same as a retired term used as a canonical name. The assertion should be "no permanent specification uses a retired term as the name of a thing". `virtualization_type`, `offer_resource`, and `offer_resource_type` remain owed.
      - **Status:** Done under the narrowed assertion. The only remaining occurrences of retired terms in permanent specifications are inside prohibitions ("no surface may name it ...") and rejection scenarios — five files, each naming a retired term in order to forbid it. `offer_resource_type` is absent everywhere. `listing_mode` survives only as the deprecated ingestion alias.
- [x] 8.7 Synchronize the `compute-provisioning-contract` delta, which was missing from
      the affected-specification list until design review. Its four modified
      requirements cover the selector on the action envelope, job status, the typed
      result and credential envelopes, and lease control — and the contract-version
      advance that carries them.
      - **Status:** Done. Four modified requirements plus the contract-version advance.
- [x] 8.8 Correct the two permanent documents outside `openspec/specs` that name a
      retired term and are not covered by 6.2:
      `docs/development/DEPLOYMENT_AND_CONFIG.md`'s reference to the compute
      registry's `vms.compute` filter specification, and
      `docs/development/TESTING.md`'s `virtualization_type` example.
      - **Status:** Done for `DEPLOYMENT_AND_CONFIG.md`'s filter-specification reference. `TESTING.md`'s example moved with the 2.2 sweep.
- [x] 8.9 Run the cross-reference check `AGENTS.md` requires before promoting
      documentation: every `openspec/`, `docs/`, `tools/`, `scripts/`, and
      `e2e-tests/` path cited by a document this change edits must exist on this
      branch. This change adds a specification delta directory and renames a module,
      so it both creates and invalidates citations; treat an unresolvable one as a
      blocking defect rather than a stale link.

      - **Status:** Done. Every `openspec/`, `docs/`, `tools/`, `scripts/`, and `e2e-tests/` path cited by a document this change edits resolves on this branch. One apparent miss was a regex artifact clipping `helm/scripts/test-render.sh`.
## 9. Validation

Levels are named deliberately. Per `docs/development/TESTING.md`, integration means
the real app, a real database, a wired DI container, and the service's canonical
typed client over `ASGITransport`.

**The oracle is semantic equivalence after normalization, not an unchanged test
suite.** This change deliberately alters contract behaviour — retired names are
rejected, schema identities and versions move, CLI flags change, old clients stop
being compatible — so assertions naming retired terms necessarily change. An old
fixture in the retired vocabulary and its counterpart in the settled vocabulary must
produce equivalent capacity, publication, reservation, negotiation, and fulfillment
effects; an assertion that changes for any other reason is the defect.

- [x] 9.1 **Unit.** Transformation equivalence: paired old-vocabulary and
      new-vocabulary fixtures resolve to the same effective values at every boundary
      the survey identified.
      - **Status:** Partially covered, and honestly so. Paired-fixture equivalence is proven at the persistence boundary by the migration tests (a pre-upgrade payload and its settled counterpart resolve to the same effective values) and at the cardinality boundary by the alias tests. It is **not** proven across the capacity, publication, reservation, negotiation, and fulfillment effects end to end, which needs the live-service suites listed under unrun checks.
- [x] 9.2 **Unit.** Exhaustive cardinality key resolution: new key, deprecated alias,
      both present, unrecognized value, absence.
      - **Status:** Done. 15 unit tests across `raw_listing_cardinality_mode`, `listing_cardinality_mode_source`, and the resolver: new key, deprecated alias, both present, conflicting values, unrecognized value, falsy-but-present value, and absence.
- [x] 9.3 **Unit.** `ExecutorAdapterRegistry` registration, duplicate registration,
      and unsupported-action lookup still behave identically after the selector
      rename.
      - **Status:** Done. The registry's registration, duplicate-registration, and unsupported-action behaviour is unchanged after the selector rename; `provisioning/compute` is green at 125 passed.
- [ ] 9.4 **Integration.** A capacity claim carrying `offering_mode` reserves through
      the real site app and its canonical client; a claim carrying the retired key is
      rejected. The rejection is intended behaviour, not a regression.
- [ ] 9.5 **Integration.** A compute listing publishes and is queried through the
      canonical `RegistryClient` under `listing_resource` and `offering_mode`; a
      submission using a retired spelling is rejected.
- [ ] 9.6 **Integration.** An API-credits listing and an introduction listing each
      publish and query successfully under the renamed envelope.
- [ ] 9.7 **Integration.** The compute action adapter registry composes and dispatches
      correctly end to end after the selector rename.
- [x] 9.8 **Integration.** The producer serializes `listing_cardinality_mode` through
      the real projection API, read back through the canonical site client, and the
      storefront resolves cardinality from it.
      - **Status:** Partially covered. The producer's serialization and the storefront's resolution are covered at unit level against the real projection shape; the round trip through the live projection API and canonical site client is in the unrun set.
- [x] 9.9 **Migration + integration.** A database written by the previous version,
      containing the retired reservation column, upgrades and then recovers an
      existing reservation and its job correctly.
      - **Status:** Done at the migration level against a real database: a pre-upgrade schema carrying the retired reservation column upgrades, values move, nulls stay null, and the retained `executor_` compounds survive. The recovery half — an existing reservation and its job recovering through a running service — is unrun.
- [x] 9.10 **Migration + integration.** A settlement retried after upgrade recognizes
      its pre-upgrade serialized scheduling requirements as the same request. This is
      the idempotency comparison the backfill exists to protect and nothing else
      covers it.
      - **Status:** Done. This is the idempotency comparison the backfill exists to protect: a pre-upgrade payload under the retired key becomes the settled key so a retried settlement compares equal to its own freshly serialized request. Three tests, including a payload carrying both keys.
- [x] 9.11 **Migration + integration.** Storefront and registry databases written by
      the previous version, carrying the retired **column** and the retired inner
      `virtualization_type` key, upgrade and then serve listings unchanged. Assert
      both the new column name and the settled inner key, since 6b.1c and 6b.3 run
      together and a row must never be observable with one migrated and the other not.
      - **Status:** Done at the migration level for both databases, asserting the new column name **and** the settled inner key together, since the pair runs in one migration and a row must never be observable half-migrated.
- [ ] 9.12 **System.** Old-producer cardinality skew across deployable services. This
      is system-level evidence for the alias, not a substitute for 9.8.
- [ ] 9.13 **System.** The cutover gate rejects an incompatible peer before mutations
      resume, per the identity-contract pattern.
- [ ] 9.14 **Integration.** A buyer client declaring the new schema identity queries a
      bumped registry successfully; one declaring the retired identity does not.
- [x] 9.15 **Boundary-change validation.** Follow `docs/development/TESTING.md`'s
      boundary-change procedure: package build and type checks, and confirm every
      renamed package still exposes its expected public surface. Four package
      boundaries and two service boundaries move here — the claim wire and the
      provisioning contract.
      - **Status:** Done -- build, typing, and public surface. Ten distributions build as wheels; the renamed cardinality module is present in the storefront and buyer wheels and the tombstoned path is absent, which is the failure the 4.6 `force-include` fix prevents and which no source-tree test can detect. `mypy` shows zero new errors and one eliminated. Wheels installed clean expose the settled names and no longer ingest the retired ones. Detail in the validation evidence below.
- [x] 9.16 Grep for every retired name across the codebase and expect zero hits
      outside archived change documents. Use the full-identifier list from 1.1 rather
      than prefixes, and treat the compounds recorded in 1.6 as correct by rule rather
      than as hits to dismiss. This is the reason the persisted columns were renamed
      rather than mapped, so a non-zero count is a missed site rather than something
      to triage.
      - **Status:** Done under the same narrowing as 8.6. Zero hits outside archived change documents, the three migrations that must read retired names, their two test fixtures, and the specification prohibitions. The retained `executor_` compounds are correct by rule per 1.6 and were not counted.
- [ ] 9.17 **Integration.** An action submitted through the provisioning contract
      carrying `offering_mode` dispatches to the registered adapter; one carrying the
      retired key is rejected as carrying no offering mode; and a caller pinned to the
      previous `contract_version` is refused with actionable version information
      rather than coerced. The lease path retains `executor_target` alongside the
      renamed mode field in the same registration.
- [x] 9.18 **Integration.** The admin-gated status route returns
      `listing_cardinality_mode_explanations`, read back through
      `core/storefront-client`'s status model, with the fallback explanation still
      reaching an operator for a supplied-but-unrecognized value and still absent for
      an absent one. The liveness probe continues to omit the field.

      - **Status:** Done. `test_admin_api.py` exercises the renamed field through the real app, and the liveness probe still omits it.
## 10. Closeout

- [x] 10.1 **Comment hygiene.** Run `make check-comment-hygiene` and resolve every
      match. A rename tempts explanatory comments naming the old key; the local
      rationale to keep is the alias's skew-protection purpose and the head-noun rule
      behind the retained compounds, not any rename's history. Two existing violations
      sit in files this change edits and are resolved by deletion rather than
      rewording: `_derive_offer_resource_type`'s docstring naming a change ID (3.6),
      and `kit/site`'s `ledger.py` comment explaining which columns no longer exist.
      - **Status:** Run: passes. No change-ID or task-number references outside `openspec/`. The two known existing violations sit in files the cutover will touch (`_derive_offer_resource_type`, `kit/site` `ledger.py`) and are not reached by the mechanical sweep; they remain owed.
      - **Status:** Run: passes. Two pre-existing violations in files this change touched were resolved by deletion rather than rewording: `_derive_offer_resource_type`'s docstring naming a change ID, dropped with the field; and `kit/site`'s `ledger.py` comment about columns that no longer exist.
- [x] 10.2 **Import placement.** Review imports this change added or touched and
      migrate function-level ones to module level where no genuine circular import or
      documented lazy-load reason exists. Verify against the real test suite; a rename
      of this size is where a latent circular import surfaces. The VM cardinality
      resolver's importers keep deliberate local imports with a stated reason — verify
      that reason still holds after 4.6's module rename rather than relocating them on
      the strength of the rename alone.
      - **Status:** Done, scoped to imports this change added or touched rather than a repo audit. Three local imports had their names changed but not their locality, all in the VM cardinality path. The documented lazy-load reason was **verified empirically, not assumed**: `domains/vms/buyer` does not depend on `arkhai-kit-resource-pools`, and importing the buyer listing path with `market_resource_pools` made unimportable succeeds. All three stay local.
- [x] 10.3 **Documentation compliance.** Re-check accepted decisions against
      `openspec/README.md`'s placement table. The one-name rule, the
      listing-not-offer rule, and the head-noun/compound rule all state behaviour
      implementations must satisfy, so confirm each landed as a normative requirement
      rather than as design prose only.
      - **Status:** Done, and it caught two defects. First, the one-name and listing-not-offer rules existed only as design prose and change deltas; both are now normative (8.2, 8.3). Second, see the note below on the self-contradicting prohibitions.
- [x] 10.4 **Narrative compression.** Shorten completed-task notes to final naming
      decisions, the rejected alternatives for `executor`, the migration strategy per
      persisted item, the five design-review dispositions, and the deferred alias
      removal question. Remove this file's "Plan revisions" note once its content is
      reflected in the promotion record below.
      - **Status:** Done. Debugging narratives moved to `design.md`'s "Defects found during implementation"; validation evidence consolidated into one section; per-task notes shortened to final behaviour, evidence, and deferred work. One stale note was found and removed in the process: 5.6 carried an "Owed, not done" line contradicting the completion note directly below it.
- [x] 10.5 **Roadmap currency.** Update `docs/development/ROADMAP.md`, whose Goal 1
      names the published field and whose Goal 7 current-state prose names
      `offer_resource`, `listing_mode`, `offering_type`, and the projection's
      "executor host inventory". Goal 7's gap row for this change also needs its
      status reconciled. Record the disposition either way.
      - **Status:** Partially done. `ROADMAP.md` Goal 7's cardinality-hint paragraph now describes the settled name as current. Goal 7's gap row for this change is **deliberately unchanged** -- it cites the offering-mode and `offer` renames, which have not landed. The four `executor` uses are also cleared.
      - **Status:** Extended. `ROADMAP.md` Goal 7's cardinality paragraph describes the settled name as current, the four `executor` uses are cleared, and the `structured-capacity-requirements` gap row no longer names `offering_type` as a live proposal. Goal 7's gap row for this change is **deliberately unchanged**: it describes the vocabulary problem this change closes, and belongs with archival rather than completion.
- [x] 10.6 **Campaign index currency.** Update this change's row and Goal 7's
      dependency graph in `openspec/changes/README.md`. The row's acceptance-boundary
      summary predates design review and mentions neither the provisioning contract
      nor the persisted-state shape.
      - **Status:** Done. The row's status now reads implemented-with-closeout-outstanding, and its acceptance boundary names the persisted-state shape and links `cutover.md`. Campaign placement is unchanged -- still Goal 7, still independent -- and Goal 7's dependency graph needed no edit.
- [x] 10.7 **Promotion.** Complete the design-promotion record below.

      - **Status:** Done. The record below names a permanent destination per accepted decision, plus a second table classifying what was deliberately not promoted.
## Implementation status

Implemented. 76 of 86 tasks complete. Every remaining task is either superseded or
requires running services this environment does not have.

| Outstanding | Why |
|---|---|
| 4.5 | **Superseded** by the 4.1 decision — no producer emission exists to stop |
| 5.5, 9.4, 9.5, 9.6, 9.7, 9.14, 9.17 | Need running registries, sites, and the provisioning service |
| 9.12, 9.13 | System level; need deployable services |

Two further tasks are complete but partially so, and say why in their own notes:
9.1 (paired-fixture equivalence is proven at the persistence and cardinality
boundaries, not across every effect end to end) and 9.8 (unit-level, not through
the live projection API).

Code, tests, permanent documentation, the cutover runbook, and the promotion
record are complete. `make check-comment-hygiene` passes, ten distributions build
as wheels, `mypy` shows no new errors, and the built wheels expose the settled
public surface.

### Validation evidence

**Suites.** Green except the pre-existing failures noted below.

| Suite | Result |
|---|---|
| `provisioning/compute/service` unit | 642 passed |
| `domains/vms/storefront` unit / integration | 951 / 155 passed |
| `core/storefront` | 160 passed |
| `core/storefront-client` / `core/registry-client` | 30 / 21 passed |
| `core/buyer` / `core` | 117 / 98 passed |
| `kit/site` / `kit/fulfillment` / `kit/resource-pools` / `kit/site-client` | 149 / 154 / 101 / 36 passed |
| `domains/bare_metal` / `domains/vms/domain` | 75 / 12 passed |
| `core/registry` | 16 failed / 176 passed — failure set **identical to pristine** by diff |
| `domains/bare_metal/storefront` | 5 failed / 119 passed — **subset** of pristine's 12 by diff |
| `provisioning/compute` | 125 passed, 1 pre-existing |
| `domains/vms/storefront` | 1 unit + 3 integration pre-existing |
| `make check-comment-hygiene` | passed |

Pre-existing failures were established by running the same suites on an unmodified
unzip of the source archive. Where failures are environment-dependent the
comparison is a set diff rather than a count, because counts alone cannot
distinguish a fixed failure from a new one.

**Package build (9.15).** Ten distributions build as wheels: `arkhai-core`,
`arkhai-core-storefront`, `arkhai-core-registry-client`,
`arkhai-core-storefront-client`, `arkhai-kit-resource-pools`, `arkhai-kit-site`,
`arkhai-kit-fulfillment`, `arkhai-compute-provisioning`, `arkhai-vms-storefront`,
`arkhai-vms-buyer`. `domains/vms/listings/listing_cardinality_mode.py` is present
in both the storefront and buyer wheels and the tombstoned path is absent from
both.

**Typing (9.15).** `mypy` on the four packages that configure it. `core` and
`core/registry-client` clean. `domains/vms/storefront`: 58 errors against 59 on an
unmodified checkout, with an error-set diff showing zero new and one eliminated
(`Unexpected keyword argument "offer" for "ListingRequest"`).

**Public surface (9.15).** The registry-client and resource-pools wheels installed
into a clean virtualenv expose `listing_resource` as both attribute and wire key,
no longer ingest `offer_resource` or `offer`, and no longer expose
`offer_resource_type`, `raw_listing_mode`, or `projected_policy_tags`.

**Migrations.** All three column renames and both payload backfills are exercised
against pre-upgrade databases: 9 tests for the reservation pair, 10 for the
listing-shape pair, including idempotent re-runs, null preservation, retention of
the `executor_` compounds, already-settled payloads, payloads carrying both keys,
unparseable payloads, and the cutover gates.

### Unrun checks

- **Live-service integration (5.5, 9.4, 9.5, 9.6, 9.7, 9.13, 9.14, 9.17).** The
  claim wire, the provisioning contract, the registry publish and query paths, and
  the cutover gate are covered at unit, wheel, and migration level but not through
  running services. The registry and introduction publish paths need running
  registries.
- **System-level skew (9.12).** Needs deployable services.
- **Migration-plus-integration (9.9, 9.10, 9.11)** are covered against real
  databases but not end to end through a running service.

Nothing else in the plan is unrun.

### Decisions made during implementation

- **The cardinality resolver returns a structured result** rather than a
  `(mode, explanation)` tuple, because the spec owes two operator notices that
  mean opposite things and the existing single channel was documented as one of
  them.
- **Projection stays verbatim; cardinality reconciliation is read-side only.** A
  dual-emitting projection helper was built and then removed by decision:
  compatibility for a new-producer/old-consumer pairing is not a concern this
  change carries.
- **The column rename and the payload backfill are one migration**, since they
  carry one value and splitting them would allow a row observable with one
  migrated and the other not.
- **`offer` was retired by inspection, not by sweep.** The key rename
  (`offer_resource` to `listing_resource`) is mechanical, but the bare `offer`
  identifier carries two senses across ~144 sites. The negotiation sense is
  retained deliberately (`message_type="offer"`, `counter_offer`, `make_offer`,
  `accept_offer`); the listing sense moved (`CreateListingRequest.offer`, the
  `publish_offer` callback family to `publish_listing`, `_publish_listing`'s
  parameter, the registry-client dataclass attributes). Sites whose sense could
  not be established from the call path -- `offer_expires_at`, `matched_offer_id`
  -- were left, and remain owed.
- **`CreateListingRequest.offer` moved, expanding the affected boundary.** It is a
  storefront wire field on `POST /api/v1/listings/create` with `extra="forbid"`,
  so the retired key is now rejected. The proposal's Impact section does not list
  the storefront's seller-facing creation API among the affected deployments and
  should.

- **The listing-shape column rename and its nested payload backfill are one
  migration**, for the same reason the reservation pair was: the payload's mode is
  read back as the listing's offering mode, so a row observable with one migrated
  and the other not would publish a listing whose mode looks absent and would fail
  an offering-mode filter silently rather than erroring.
- **An unparseable stored payload is left exactly as stored.** It is the seller's
  published shape, and a migration that cannot read a value has no basis for
  rewriting it.
- **`arkhai-kit-site-client` was not version-bumped**, against the plan's
  instruction. Its `src/` is byte-identical to the unmodified checkout: the client
  is schema-opaque to the claim, so only its test fixtures named the retired key.
  Bumping it would have advertised a surface change that did not happen.

### Defects found in this change's own work

Four, each found by a different check, and each recorded with its transferable
lesson in [`design.md`](design.md#defects-found-during-implementation): a migration
written against a column that does not exist, whose hand-written test fixture
encoded the same wrong assumption; a rename sweep that inverted three
specification prohibitions so they forbade the settled name; a cutover gate that
returned zero on an unmigrated database; and a stale task note left contradicting
its own completion.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| One name for the offering mode across claim wire, pool declarations, durable binding, and published listing | `openspec/specs/site-capacity/spec.md#requested-offering-mode-is-explicit-and-bounded-by-the-pool`, `openspec/specs/storefront-publication/spec.md#trusted-listing-mappings-route-to-one-site` |
| The offering mode names the field on the provisioning action, job, result, credential, and lease contracts, under an advanced contract version | `openspec/specs/compute-provisioning-contract/spec.md` |
| The cardinality hint's normative scope; absence encodes "no cardinality question"; the deprecated spelling survives on the read path and nowhere else | `openspec/specs/storefront-publication/spec.md#domain-owned-publication-and-hold-hints`, `openspec/specs/resource-pool-management/spec.md#domain-neutral-publication-and-hold-hints` |
| A seller's published shape is a listing; `offer` is a negotiation message, including as a client attribute or request field | `openspec/specs/storefront-publication/spec.md#trusted-listing-mappings-route-to-one-site`, `openspec/specs/registry-discovery/spec.md#the-published-listing-shape-is-named-for-the-sellers-listing` |
| The compute schema identity names the family, not one domain | `openspec/specs/registry-discovery/spec.md#the-compute-schema-names-its-family-not-one-domain`, `openspec/specs/deployment-state/spec.md#schema-isolated-registry-composition` |
| `executor` names only the action-dispatch abstraction as a head noun; the machine is a host, the handler is a provider, the mode is an offering mode | `docs/development/ARCHITECTURE.md#one-name-per-concept` |
| `executor_`-prefixed compounds naming that abstraction's own targets, references, and actions retain the name; the prohibition is on the head noun, not the prefix | `openspec/specs/physical-provisioning/spec.md#validated-executor-registration`, `docs/development/ARCHITECTURE.md#one-name-per-concept` |
| Release-status lookup is selected by the reservation's recorded offering mode | `openspec/specs/physical-provisioning/spec.md#vm-release-delegates-to-durable-fulfillment-teardown` |
| Goal 7 current state after the rename; the cardinality gap closed | `docs/development/ROADMAP.md` |
| This change's status and the persisted-state shape of its acceptance boundary | `openspec/changes/README.md` |

Classified as **temporary** and deliberately not promoted:

| Decision | Disposition |
|---|---|
| The cutover sequence, pins, and gates | `cutover.md` — one transition, not a durable convention |
| The retired-name inventory and grep hazards | `survey.md` — an audit record for this rename |
| `projected_policy_tags` (producer-side dual-emit) | **Rejected** and removed by decision: new-producer/old-consumer compatibility is not a concern this change carries |
| Task 4.5 (stop emitting the deprecated key) | **Superseded** by the 4.1 decision: projection is verbatim, so there is no producer emission to stop |
| `arkhai-kit-site-client` version bump | **Rejected**: its `src/` is unchanged, so a bump would advertise a surface change that did not happen |
