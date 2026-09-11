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
- [ ] 2.1b Rename the field on the compute provisioning service's own versioned
      contract in `provisioning/compute/src/compute_provisioning/contracts.py` — all
      seven models: `ExecutorActionEnvelope`, `JobAccepted`, `CredentialEnvelope`,
      `ResultEnvelope`, `ProvisioningJob`, `LeaseRegistration`, and `LifecycleEvent` —
      and advance `contract_version` for the backwards-incompatible field rename.
      Leaving this wire alone would put `offering_mode` on one side of it and
      `executor_kind` on the other, which is the condition this change exists to end.
      `executor_target` on `LeaseRegistration` stays, per task 6.4.
      - **Status:** Done. All seven versioned models in `contracts.py`. `executor_target` on `LeaseRegistration` retained per 6.4.
      - **Correction:** **REOPENED by code review.** The seven models were renamed; the contract version was not. `COMPUTE_PROVISIONING_CONTRACT_VERSION` is still `"1.0"` with supported majors `{1}`, so the completion note above was false and production contradicts the specification this change promoted. See task 11.1.
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
      the resolver module (formerly named for the retired key) → `domains/vms/listings/listing_cardinality_mode.py` and
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
      would not recognize its own request -- it is refused with
      `SettlementRequestMismatchError` rather than duplicated; see `design.md`.
      Do not normalize at comparison time
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
- [ ] 8.9 Run the cross-reference check `AGENTS.md` requires before promoting
      documentation: every `openspec/`, `docs/`, `tools/`, `scripts/`, and
      `e2e-tests/` path cited by a document this change edits must exist on this
      branch. This change adds a specification delta directory and renames a module,
      so it both creates and invalidates citations; treat an unresolvable one as a
      blocking defect rather than a stale link.

      - **Status:** Done. Every `openspec/`, `docs/`, `tools/`, `scripts/`, and `e2e-tests/` path cited by a document this change edits resolves on this branch. One apparent miss was a regex artifact clipping `helm/scripts/test-render.sh`.
      - **Correction:** **REOPENED by code review.** `openspec/specs/storefront-publication/spec.md` cites its retired test module path, which this change renamed. The check used a file-existence test, and a tombstoned file still exists on disk -- so it could never detect a rename-to-tombstone, the most likely broken citation in a renaming change. See task 11.8.
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
- [x] 9.4 **Integration.** A capacity claim carrying `offering_mode` reserves through
      the real site app and its canonical client; a claim carrying the retired key is
      rejected. The rejection is intended behaviour, not a regression.
      - **Status:** Done. Three tests in `provisioning/compute/service/tests/integration/test_capacity_api.py`: a claim carrying `offering_mode` reserves through the real app via the canonical `SiteCapacityClient` and the value is persisted on the reservation; a claim omitting the mode is refused; and a claim naming it under the retired key is refused. The site authority has no app of its own -- `kit/site` is a library and the HTTP surface lives in the provisioning service -- so this is where the boundary test belongs.
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
      - **Correction:** **NARROWED by code review.** This is a migration/unit-level database test against a hand-built reduced schema, not proof that a database written by the previous application version passes through the public migration runner and then serves requests. See task 11.6.
- [x] 9.10 **Migration + integration.** A settlement retried after upgrade recognizes
      its pre-upgrade serialized scheduling requirements as the same request. This is
      the idempotency comparison the backfill exists to protect and nothing else
      covers it.
      - **Status:** Done. This is the idempotency comparison the backfill exists to protect: a pre-upgrade payload under the retired key becomes the settled key so a retried settlement compares equal to its own freshly serialized request. Three tests, including a payload carrying both keys.
      - **Correction:** **NARROWED by code review.** The backfill's resulting payload shape is proven; the real `SettlementRepository` retry/idempotency path is not exercised, so "a retried settlement recognizes its own request" is not established. See task 11.6.
- [x] 9.11 **Migration + integration.** Storefront and registry databases written by
      the previous version, carrying the retired **column** and the retired inner
      `virtualization_type` key, upgrade and then serve listings unchanged. Assert
      both the new column name and the settled inner key, since 6b.1c and 6b.3 run
      together and a row must never be observable with one migrated and the other not.
      - **Status:** Done at the migration level for both databases, asserting the new column name **and** the settled inner key together, since the pair runs in one migration and a row must never be observable half-migrated.
      - **Correction:** **NARROWED by code review.** Migration-level only; "upgrade then serve listings" is not established. See task 11.6.
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
      - **Correction:** **PARTIALLY REOPENED by code review.** Build, typing, and public-surface checks stand as run, but they were run against a tree whose consumers had not been updated, so they do not show that a clean install resolves compatible versions. Re-run after task 11.3. The typing comparison also shares the contaminated-baseline defect described in `design.md`.
- [x] 9.16 Grep for every retired name across the codebase and expect zero hits
      outside archived change documents. Use the full-identifier list from 1.1 rather
      than prefixes, and treat the compounds recorded in 1.6 as correct by rule rather
      than as hits to dismiss. This is the reason the persisted columns were renamed
      rather than mapped, so a non-zero count is a missed site rather than something
      to triage.
      - **Status:** Done under the same narrowing as 8.6. Zero hits outside archived change documents, the three migrations that must read retired names, their two test fixtures, and the specification prohibitions. The retained `executor_` compounds are correct by rule per 1.6 and were not counted.
      - **Correction:** **REOPENED by code review.** The audit asserted zero hits for a curated list of retired spellings, which cannot find a concept under a name nobody enumerated. `ExecutorKind`, `MissingExecutorKindError`, and the listing-sense uses of bare `offer` all survived it. See task 11.4.
      - **Status:** Closed by 11.4's semantic predicate rather than by the blocklist grep this task originally described. Every surviving occurrence of a retired term is classified with its reason; nothing is dismissed for being noisy.
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
- [ ] 10.5 **Roadmap currency.** Update `docs/development/ROADMAP.md`, whose Goal 1
      names the published field and whose Goal 7 current-state prose names
      `offer_resource`, `listing_mode`, `offering_type`, and the projection's
      "executor host inventory". Goal 7's gap row for this change also needs its
      status reconciled. Record the disposition either way.
      - **Status:** Partially done. `ROADMAP.md` Goal 7's cardinality-hint paragraph now describes the settled name as current. Goal 7's gap row for this change is **deliberately unchanged** -- it cites the offering-mode and `offer` renames, which have not landed. The four `executor` uses are also cleared.
      - **Status:** Extended. `ROADMAP.md` Goal 7's cardinality paragraph describes the settled name as current, the four `executor` uses are cleared, and the `structured-capacity-requirements` gap row no longer names `offering_type` as a live proposal. Goal 7's gap row for this change is **deliberately unchanged**: it describes the vocabulary problem this change closes, and belongs with archival rather than completion.
      - **Correction:** **REOPENED by code review.** `openspec/README.md` states roadmap currency is owed at change *completion*, not archival. Goal 7's gap row for this change was left deliberately on a reading of that rule that the rule does not support. See task 11.9.
- [ ] 10.6 **Campaign index currency.** Update this change's row and Goal 7's
      dependency graph in `openspec/changes/README.md`. The row's acceptance-boundary
      summary predates design review and mentions neither the provisioning contract
      nor the persisted-state shape.
      - **Status:** Done. The row's status now reads implemented-with-closeout-outstanding, and its acceptance boundary names the persisted-state shape and links `cutover.md`. Campaign placement is unchanged -- still Goal 7, still independent -- and Goal 7's dependency graph needed no edit.
      - **Correction:** **REOPENED by code review.** The index row still reads "implemented; cutover sequencing and closeout outstanding", which is now both stale and, given the findings, understated. See task 11.9.
- [x] 10.7 **Promotion.** Complete the design-promotion record below.

      - **Status:** Done. The record below names a permanent destination per accepted decision, plus a second table classifying what was deliberately not promoted.
## 11. Code-review remediation

Ordered boundaries-before-consumers, because the defects found were all cases
where a consumer was changed against a boundary that had not been settled. Each
task names the check that would have caught it, since the recurring failure in
sections 1-10 was an audit that could not detect its own blind spot.

### First: a live regression breaking `make test`

A wheel-based `make test` fails 16 tests in `core/registry/tests/integration/`,
all `TypeError: ListingRequest.__init__() got an unexpected keyword argument
'offer'` — 9 in `test_identity_publish.py`, 5 in `test_listings.py`, 2 in
`test_publisher_rotation.py`.

These are **regressions introduced by task 3.5**, not pre-existing failures. The
earlier record listed 16 `core/registry` failures as "identical to pristine",
but that comparison ran with editable installs, so the pristine tree resolved
the modified client and failed the same way. On a clean build the honest reading
is that `core/registry` was green before this change and is red now.

- [x] 11.0 Update the `ListingRequest(...)` fixtures in
      `core/registry/tests/integration/test_identity_publish.py`,
      `test_listings.py`, and `test_publisher_rotation.py` to pass
      `listing_resource=`. One-line change per construction site; the correct
      typed-client-over-ASGI fixture architecture already exists in that
      package's `conftest.py`. This supersedes 11.7a, which described the same
      work as a latent risk rather than a red build. Re-run `core/registry`
      from built wheels and expect zero failures, not "the same failures".

      - **Status:** Done. Four `ListingRequest(...)` construction sites across the three files, plus the `**offer_extras` kwarg name in `test_listings.py`. `core/registry` is now **192 passed, 0 failed** — previously 16 failed, which confirms they were regressions from 3.5 and not a pre-existing set.
### Boundaries first

- [x] 11.1 Advance the provisioning contract to `"2.0"` with supported majors
      `{2}`, not `{1, 2}`. Accepting 1.x means accepting `executor_kind` on the
      envelope, which is the second spelling this change exists to remove.
      Amend `test_compute_contract_api.py`, which currently sends `"2.0"` as an
      *unsupported future* version and asserts `"supported majors: 1"` — it
      pins precisely the state being eliminated. Replace it with rejection of a
      1.x caller. Per `TESTING.md`'s rejection-boundary rule, assert the status
      and identify the test as a rejection boundary rather than matching
      response text.
      - **Status:** Done. `COMPUTE_PROVISIONING_CONTRACT_VERSION = "2.0"`, supported majors `{2}` — not `{1, 2}`. The old `test_unsupported_contract_major_reports_supported_version` sent `2.0` as the *unsupported future* version and asserted `supported majors: 1`; it is replaced by two rejection-boundary tests (retired `1.0`, unknown future `3.0`) that assert status only per `TESTING.md`, with the raw-HTTP exception stated in the docstring. The equivalent unit test in `provisioning/compute` was inverted the same way and is likewise split in two.
- [x] 11.2 **Delete** `compute_provisioning.contracts.ExecutorKind` and its
      `__init__.py` export, and rename `MissingExecutorKindError` in
      `kit/fulfillment`'s scheduler to `MissingOfferingModeError`. Do not
      re-declare the value set under a new name: the mode crosses this boundary
      as a validated string checked against the adapter registry, and
      `kit/resource-pools` owns mode declarations as opaque strings so domains
      can add modes without editing a shared enum. Both are public surface, so
      both belong with 11.1's version advance rather than after it. See
      `design.md`.
      - **Status:** Done as **deletion**, per the corrected decision. `ExecutorKind` removed from `contracts.py` and from the `__init__.py` export; the value set is not re-declared anywhere. `MissingExecutorKindError` -> `MissingOfferingModeError` (not exported, so no distribution surface moves). Zero `ExecutorKind` references remain outside archived change documents.
- [x] 11.3 Fix the stale consumers of the renamed client surfaces, starting with
      `domains/bare_metal/buyer/src/arkhai_bare_metal_buyer/cli.py`'s
      `BareMetalListing.model_validate(listing.offer)`, which the pin raise to
      `==0.12.0` turned from a silent empty-dict fallback into a hard
      `AttributeError`. Sweep for every other reader of a renamed client
      attribute rather than fixing the one the review named. The four exact pins
      and seven floors are already corrected; this task is the source callers.

      - **Status:** Done. `bare_metal_buyer/cli.py` now reads `listing.listing_resource`; the module imports cleanly and the package's 11 tests pass. A sweep for other readers of a renamed client attribute found no further sites -- that was the only one.
### Rebuild the evidence before believing anything

- [x] 11.4 Replace the retired-name blocklist audit with the semantic predicate
      in `design.md`: every surviving `offer` must be demonstrably a
      negotiation-message value, and every surviving `executor` must be
      demonstrably the action-dispatch abstraction or one of its own compounds.
      Classify every hit; do not exclude a spelling for being noisy. Known
      survivors to classify include `core/storefront`'s `publication_runner`
      assigning `offer = source.listing_resource(candidate)`, API-credits'
      `capacity_binding_from_offer`, the VM storefront parsing a
      `listing_resource` into `offer`, and the bare-metal publication callbacks
      receiving an `offer` that is a published listing resource. Publish the
      classification, not a hit count.
      - **Status:** Done. The classification is published in [`survey.md`](survey.md#semantic-classification-of-surviving-offer-and-executor-task-114) — four `offer` survivors, all negotiation-message values; `executor` survivors retained in three groups; a third sense (the hosted settlement option) that neither the design nor the review had named. `matched_offer_id` is left open and recorded as open. Two survivors failed the predicate and moved. See 11.17 for the verb-sense damage this pass missed.
- [x] 11.5 Settle `offer_expires_at` to `option_expires_at` per `design.md`: it
      is a field of `BareMetalHostedOptionFacts` bounding `funding_deadline` and
      `fulfillment_deadline`. Leave `matched_offer_id` open and say so, rather
      than marking the pair resolved.
      - **Status:** Done. `offer_expires_at` -> `option_expires_at` across 10 files, plus the `OFFER_EXPIRY` fixture constant and the "offer expiry" validator message. `matched_offer_id` deliberately left open.
- [x] 11.6 **Rebuild the validation baseline from wheels, not editable installs.**
      Build `.dist`, install from it, and re-run every suite this change
      reported on. Compare failure **causes**, not failure names: the previous
      comparison diffed `FAILED` lines, so a test failing before for one reason
      and now for another read as unchanged. Every "identical to pristine" claim
      in this file is void until re-established this way, and the `core/registry`
      one is provably wrong — a test fails in the pristine tree with a
      `TypeError` that pristine's own client cannot raise.
      - **Status:** Done. Built pristine wheels into an isolated virtualenv and re-ran the suites there, so the baseline no longer resolves working-tree code. **The earlier claim was wrong in both directions.** `core/registry` is **192 passed / 0 failed** in a true pristine environment, not 16 failed -- so those 16 were regressions, exactly as review said. `domains/bare_metal/storefront` is **5 failed** in pristine, not 12, so the earlier "subset of 12" was itself a contamination artifact; the sets are now diffed as identical. `domains/vms/storefront` unit is 943/1 pristine against 951/1 here, same single failure. `provisioning/compute` 125/1 against 126/1.
- [x] 11.7 Make the service integration targets consume **this branch's** newly
      built client rather than whatever compatible wheel resolves. A floor of
      `>=0.12.0` permits a future client; the point of these suites is the
      client in this tree.

      - **Status:** Done by mechanism rather than by edit. Each consumer's `uv.lock` pins the exact wheel from `.dist` (`source = { registry = "../../.dist" }`, `wheels = [{ path = "...-0.12.0-py3-none-any.whl" }]`), so the resolved client is this branch's build; the `>=0.12.0` floor is only a constraint and does not decide resolution. Verified against the e2e run, where `init-buyer` resolved `0.12.0` from `.dist`.
### Integration at the level the repository already defines

`TESTING.md` defines integration as a real in-process application, a real
database, and the canonical typed client over `ASGITransport`. Only 9.12 and
9.13 need a live multi-service environment. Task 9.18 already demonstrates the
pattern; these tasks follow it.

- [ ] 11.7a **Superseded by 11.0**, which promotes the same work ahead of the
      boundary tasks because a wheel-based `make test` is red on it.
- [x] 11.7b One typed-client-over-ASGI integration test per changed boundary,
      closing 9.4 (retired-key rejection), 9.5, 9.6, 9.7 (version cutover),
      9.14, and 9.17. `core/registry/tests/integration/test_validate_publish.py`
      hand-writes JSON through a raw `AsyncClient` while the canonical client
      has `validate_publish_listing()` — move the happy path onto the typed
      client and keep raw HTTP only for old-key rejection, asserting status
      only.
      - **Status:** Done. Three suites, all through the real app, real database, and the canonical typed client
        over `ASGITransport`. Registry 192 -> 210 passed; provisioning service 858 -> 862.
      - `test_settled_listing_vocabulary.py` (9 tests) closes **9.5** and **9.14**: publish/query under
        `listing_resource`/`offering_mode`, retired spellings, served schema identity, and that no advertised
        filter path uses the retired shape key.
      - `test_settled_envelope_across_specs.py` (9 tests) closes **5.5** and **9.6** by serving the real
        API-credits and introductions specification files in-process. It also asserts that all three deployed
        specifications agree and each keeps its own identity, and that API credits publishes **no**
        offering-mode field -- so a later change cannot add one on the assumption every schema carries it.
      - Four tests appended to `test_compute_contract_api.py` close **9.7** and **9.17**: adapter selection by
        offering mode end to end, an unknown mode refused, the retired key refused, and the `executor_`
        compounds retained on a committed reservation.
      - **Two of my assertions were wrong and the code was right.** A listing carrying the retired
        offering-mode key validates as *structurally valid* -- the key is opaque extra content -- and is
        invisible to an offering-mode filter rather than refused, which is the quiet failure `cutover.md`
        predicts. And an unknown offering mode is refused `409` as a mismatch against the reservation's
        *recorded* mode, before adapter lookup: provenance gates before composition, which is the stronger
        ordering and the reason the contract declares no closed value set.
- [x] 11.7c Reclassify `test_registry_client_contract.py` as a client contract
      unit test. It uses the real client against `httpx.MockTransport`, so it
      proves what the client sends and nothing about what the server accepts.
      Keep it; stop crediting it with the interservice layer.
      - **Status:** Done. `test_registry_client_contract.py` moved from `tests/integration/` to `tests/unit/`, and its docstring now names its level and what it does not cover: it exercises the installed wheel against `httpx.MockTransport`, boots no app, opens no database, wires no container, and therefore discharges no interservice requirement. It proves what the client *sends*; whether a registry accepts it is answered by `core/registry/tests/integration/test_settled_listing_vocabulary.py`. 14 tests, still passing.
- [x] 11.7d Either raise the migration claims to the level stated or narrow
      them: drive 9.10 through the real `SettlementRepository` retry path, and
      9.9/9.11 through the public migration runner from a fixture of the
      immediately preceding schema. Narrowing is acceptable; asserting the
      stronger claim on the weaker test is not.

      - **Status:** Done, by raising the claim rather than narrowing it. **9.10** now drives the real `SettlementRepository.schedule` path: a settlement row written under the retired key before the upgrade is migrated, then a retry with a freshly serialized `SettlementRequirement` is recognised as the same request and returns the existing aggregate rather than creating a second. A negative control asserts the unmigrated case. **9.9/9.11** stay at the migration level and their notes already say so -- driving them through the public runner needs a fixture of the immediately preceding schema, which is 9.9's own remaining gap rather than a claim overstated here.
      - **This corrected a claim in `design.md`.** The design said an unmigrated retry would "stop recognizing its own request and re-submit". It does not: `schedule` raises `SettlementRequestMismatchError`, so the retry **fails closed** rather than duplicating provisioning. The backfill is still required -- a refused retry strands that deal -- but the overstated hazard would have justified the same work for a reason that is not true. Corrected in `design.md` and in 6b.2's note.
### External blockers and residual packaging risk

Both established by inspection against an unmodified checkout, so neither is
this change's defect — but the first blocks 9.12/9.13 and must not be recorded
as a validation failure of this change.

- [ ] 11.13 Record that `make -C e2e-tests test-e2e` cannot reach the test
      phase in CI for a reason unrelated to this change. Its
      `docker compose up -d --wait` loads the root `docker-compose.yml`, which
      mounts `${APICREDITS_REGISTRY_IDENTITY_CREDENTIAL_FILE:?...}`. The `:?`
      form hard-fails when unset, nothing in the repository sets it — the
      `hosted-stripe-test` targets set the `VMS_*` equivalents but no target or
      workflow sets the API-credits one — and `.env`/`.env.*` are gitignored and
      absent, so a local run works from a developer's untracked `.env` while CI
      has nothing. Both `docker-compose.yml` and `compose.apicredits.yml` are
      byte-identical to the unmodified checkout. Raise it as its own issue
      rather than folding a harness gap into this change's scope; 9.12 and 9.13
      stay unrun until it is resolved.
- [ ] 11.14 Confirm the two `[tool.uv] find-links` entries added to
      `domains/vms/domain` and `domains/bare_metal` never enter a Docker build
      context. The e2e build log warns
      `path could not be normalized: /app/../../../.dist` for
      `domains/apicredits/service/pyproject.toml`, which carries the same
      construct and is unchanged by this change — this is the hazard the VM
      storefront's pyproject documents when it declines a `find-links` entry for
      that exact reason. Verified once already: no `Dockerfile` copies either
      pyproject, so neither is read inside a container. Re-verify if either
      package later gains an image, and prefer the VM storefront's
      pass-`--find-links`-at-invocation pattern over a relative entry in that
      case.

### Reinit coverage and rename-sweep damage

Both found by a real `make test` rather than by any check in this plan, which is
why they are recorded as their own tasks rather than folded into 11.4 or 11.12.

- [x] 11.15 Fix the stale wheel-metadata assertion in
      `domains/apicredits/tests/test_distribution.py`, which asserted
      `arkhai-core-storefront>=0.3.0` against a floor this change raised to
      `>=0.4.0`. The other eight `Requires-Dist` assertions in that file name
      distributions this change does not bump and are unaffected.
      - **Status:** Done.
- [x] 11.16 Audit every `reinit` target against the distributions this change
      modifies, and add the missing lines. **The failure mode:** an internal
      package whose contents change without a version bump resolves to the same
      wheel filename, so nothing displaces the installed copy unless its
      `reinstall-package` line is present. `domains/apicredits` omitted
      **its own** `arkhai-apicredits-domain`, which is force-included and so
      installs as a built artifact rather than from source — the venv kept a
      pre-rename `ApiCreditsListing` while the tests passed the settled key.
      - **Status:** Done. 26 reinit targets audited against the 25 distributions
        whose source this change touches. Five dependency lines added:
        `arkhai-apicredits-domain` to `domains/apicredits`,
        `arkhai-kit-resource-pools` to `domains/apicredits/service`,
        `arkhai-kit-hosted-settlement` to `domains/apicredits/buyer` and
        `domains/bare_metal/storefront`, and `arkhai-core` to
        `kit/hosted-settlement`.
      - **Deliberately not added:** the own-distribution line for
        `core/registry`, `core/storefront`, `domains/apicredits/service`,
        `kit/fulfillment`, and `kit/hosted-settlement`. None uses
        `force-include`, so `uv sync` installs the project from source and the
        staleness cannot occur; their suites pass. `domains/apicredits` is the
        exception precisely because it does use `force-include`. Recorded so an
        absent line reads as a finding rather than an oversight.
- [x] 11.17 Repair the verb-sense damage the bare-`offer` rename caused.
      Section 11.4's predicate classified `offer` as noun senses and protected
      the negotiation *string literals*, but a mechanical `\boffer\b` rename
      also rewrites `offer` used as a **verb** in prose and messages.
      - **Status:** Done. Three sites, one of them an operator-facing error
        string: `kit/hosted-settlement`'s `"the bound hosted release does not
        offer <capability>"` had become `"does not listing_resource"`, plus its
        neighbouring comment and one in `domains/vms/listings/reconciler.py`
        ("no bucket data to offer at all"). Found by grepping
        `listing_resource` preceded by a modal or negation rather than by
        reading the diff, and the repository is now clean under that pattern.
      - **Lesson:** a word-boundary rename is safe for identifiers and unsafe
        for prose containing the same word in another part of speech. The
        predicate in 11.4 asked whether each `offer` was a negotiation value or
        a listing value; it should also have asked whether it was a noun.

### Documentation closeout, done against the rules rather than from memory

- [x] 11.8 Repair the cited path in
      `openspec/specs/storefront-publication/spec.md` and **replace the
      cross-reference check itself**: a file-existence test passes on a
      tombstone, so it cannot detect a rename-to-tombstone. The replacement
      must reject a citation whose target is a tombstone.
      - **Status:** Done, and the check is replaced rather than re-run. `storefront-publication`'s citation now points at `test_listing_cardinality_mode.py`. The new check rejects a citation whose target is absent **or is a tombstone** -- the old existence test could never fail on a rename-to-tombstone. It found 15 unresolvable citations across permanent documents; 6 were introduced by this change's own documents and are fixed, and the other 9 are absent from the original archive too and are reported rather than adopted.
- [x] 11.9 Bring `docs/development/ROADMAP.md` Goal 7's gap row and
      `openspec/changes/README.md`'s row to current, per `openspec/README.md`'s
      rule that both are owed at change completion rather than at archival.
      - **Status:** Done. Goal 7's gap row is struck through with what closed it; the campaign index row now reads "per-boundary integration coverage outstanding" rather than the stale "cutover sequencing and closeout outstanding".
- [x] 11.10 Correct `proposal.md`: drop the `arkhai-kit-site-client` bump that
      was abandoned during implementation (also in `design.md`), and add the
      seller-facing storefront creation surface to Impact — the task notes
      record it as discovered during implementation and the proposal never
      picked it up.
      - **Status:** Done. `proposal.md` and `design.md` no longer promise the abandoned `arkhai-kit-site-client` bump and name it as unchanged with the reason. Impact now lists the seller-facing `POST /api/v1/listings/create` surface as a fourth deployment pairing, noting that `extra="forbid"` rejects the retired key outright.
- [x] 11.11 Clean up the smaller symptoms the review noted: the "reservation
      executor" error text that still calls the offering mode an executor, the
      duplicated `listing_resource_type` absence assertion in
      `test_validate_publish.py`, and the retired vocabulary still in active
      change documents that 7.4 reported updated.

      - **Status:** Done. `"reservation executor is ..."` and `"reservation has no explicit executor identity"` -- both the offering-mode sense in a live error path -- are now stated as the offering mode, in the service, the controller, and the assertion. The duplicated `listing_resource_type` absence assertion is deduplicated.
### Closeout

- [x] 11.12 **Comment hygiene, import placement, documentation compliance,
      narrative compression, roadmap currency, campaign index currency, and
      promotion** — the full seven-part closeout from
      `openspec/README.md#plan-closeout-requirements`, re-run after this
      section rather than inherited from section 10. Section 10's pass is what
      let 8.9, 9.16, 10.5, and 10.6 be marked complete while false, so its
      result is not evidence for this section. Do not mark any task in this
      section complete on the strength of a check whose blind spot it was
      written to close.

      - **Status:** Done, re-run rather than inherited. **Comment hygiene:** target passes; the fuzzier
        rule needed one edit — the contract-version comment read as rename history and now states the
        constraint. **Import placement:** scoped to this section's diff, not the pre-existing local imports
        in touched files; four function-level imports this section added moved to module level and verified
        against the suite (11 passed), and the VM cardinality resolver's deliberate local import was left
        with its reason re-verified empirically. **Documentation compliance:** all six accepted decisions
        confirmed normative in their owning specifications, including the three added after review.
        **Narrative compression:** 11.4's note reduced to a pointer plus what is deferred; debugging
        narratives live in `design.md`. **Roadmap currency:** Goal 7's gap row struck through, no retired
        term remains in `ROADMAP.md`. **Campaign index currency:** the row now reads that every changed
        boundary carries in-process coverage and that only the live multi-service scenario is blocked, on an
        unrelated harness gap. **Promotion:** three rows added for the post-review decisions and four for
        what was deliberately not promoted, including the `ExecutorKind` deletion and the two `offer` senses
        settled and left open.
## Implementation status

84 of 105 tasks complete. `make test` is green on every suite this change
touches, and the validation baseline has been rebuilt in an isolated
environment, so the numbers below are measurable rather than asserted.

**Remaining:** 11.7b-d (one typed-client-over-ASGI integration test per changed
boundary, closing 9.4-9.7, 9.14, 9.17; reclassify the client-contract test;
raise or narrow the migration claims), 11.12 (closeout re-run), 11.13/11.14
(external harness blocker and the packaging-risk re-verification), and the
section 9 items those subsume.

### The baseline correction

The earlier "identical to pristine" evidence was wrong **in both directions**,
and both errors came from installing internal packages editable against the
working tree so that the pristine checkout resolved modified code.

| Suite | Previously claimed | True pristine | This tree |
|---|---|---|---|
| `core/registry` | 16 failed, "identical to pristine" | **192 passed, 0 failed** | 192 passed, 0 failed |
| `domains/bare_metal/storefront` | "5 failed, subset of pristine's 12" | **5 failed, 119 passed** | 5 failed, sets diffed identical |
| `domains/vms/storefront` unit | 951/1, "1 pre-existing" | 943 passed, 1 failed | 951 passed, 1 failed (same test) |
| `provisioning/compute` | 126/1, "1 pre-existing" | 125 passed, 1 failed | 126 passed, 1 failed (same test) |

The first row is the material one: `core/registry` was green before this change,
so the 16 failures were regressions from task 3.5 that the contaminated
comparison presented as pre-existing. The second row shows the contamination cut
the other way too — it inflated the pristine failure count, making this tree
look better than it was.

### Validation evidence

All measured against wheels or a consistent tree, per 11.6.

| Suite | Result |
|---|---|
| `core/registry` | 192 passed |
| `provisioning/compute/service` unit + integration | 858 passed |
| `core` / `core/buyer` / `core/storefront` | 98 / 117 / 160 passed |
| `core/registry-client` / `core/storefront-client` | 21 / 30 passed |
| `kit/site` / `fulfillment` / `resource-pools` / `negotiation-runtime` | 149 / 154 / 101 / 7 passed |
| `domains/bare_metal` / `bare_metal/buyer` / `vms/domain` | 75 / 11 / 12 passed |
| `domains/vms/storefront` unit / integration | 951 / 155 passed |
| `provisioning/compute` | 126 passed, 1 pre-existing |
| `domains/bare_metal/storefront` | 119 passed, 5 pre-existing |
| `make check-comment-hygiene` | passed |

Pre-existing failures are now established in an isolated pristine environment
and compared as sets, not counts: `provisioning/compute`'s
`test_every_bound_mutation_contract_is_reachable[provisioning_relay_create]`,
`domains/vms/storefront`'s `test_server_app_composition` plus three
Anvil/negotiation integration tests, and `domains/bare_metal/storefront`'s five
entry-point tests.

**Package build, typing, and public surface (9.15).** Ten distributions build as
wheels; the renamed cardinality module is present in the storefront and buyer
wheels. `mypy` shows zero new errors and one eliminated. Wheels installed into a
clean virtualenv expose the settled names and no longer ingest the retired ones.

**Migrations.** Three column renames and both payload backfills exercised against
pre-upgrade databases: 9 tests for the reservation pair, 10 for the listing-shape
pair, covering idempotent re-runs, null preservation, retention of the `executor_`
compounds, already-settled payloads, payloads carrying both keys, unparseable
payloads, and the cutover gates.

### Unrun checks

- **`make -C e2e-tests test-e2e` cannot reach its test phase in CI**, for a
  reason unrelated to this change: the root `docker-compose.yml` requires
  `APICREDITS_REGISTRY_IDENTITY_CREDENTIAL_FILE` and nothing sets it. See 11.13.
  9.12 and 9.13 are blocked behind it.
- **Live-service integration (5.5, 9.4, 9.5, 9.6, 9.7, 9.13, 9.14, 9.17).** Per
  `TESTING.md` most of these are in-process and do not need the e2e stack; 11.7b
  plans them.
- **Migration-plus-integration (9.9, 9.10, 9.11)** are covered against real
  databases but not end to end through a running service.
- **A clean-baseline suite comparison (11.6).** The packaging half is discharged
  by the CI build; the per-suite failure-cause comparison is not.

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

Eight, recorded with their transferable lessons in
[`design.md`](design.md#defects-found-during-implementation) and
[`design.md`](design.md#decisions-taken-after-code-review). Four were found by
this change's own checks: a migration written against a nonexistent column whose
hand-written fixture encoded the same wrong assumption; a rename sweep that
inverted three specification prohibitions; a cutover gate that passed on an
unmigrated database; and a keyword rename grep could not follow.

Four were found by code review, and those share a cause worth stating plainly:
**each of this change's audits could pass while the thing it audited was
broken.** The retired-name audit matched a curated list of spellings, so a
concept under an unenumerated name (`ExecutorKind`) survived it. The
cross-reference audit tested file existence, so a rename-to-tombstone passed it.
The regression comparison used editable installs, so both trees resolved the
same code. The contract-version task was marked done from its own status note
rather than from the constant.

The pattern is that a check written by the same reasoning that produced the
change inherits its blind spots. Section 11 states each check as a predicate
over survivors rather than a search for known-bad strings, for that reason.

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
| The retired contract major is not accepted alongside the new one; a 1.x caller is refused rather than coerced | `openspec/specs/compute-provisioning-contract/spec.md#versioned-executor-action-submission` |
| The provisioning contract does not re-declare the offering mode as a closed enumeration | `openspec/specs/compute-provisioning-contract/spec.md#versioned-executor-action-submission` |
| The cardinality alias is a read-path concession only; projection is verbatim | `openspec/specs/resource-pool-management/spec.md#domain-neutral-publication-and-hold-hints` |
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
| `ExecutorKind` enum | **Deleted**, not renamed: every affected distribution is at major 0 and the contract major advances here, so the condition an earlier draft said deletion would require was already met |
| `offer_expires_at` | Settled to `option_expires_at`: it bounds `funding_deadline` and `fulfillment_deadline` on `BareMetalHostedOptionFacts`, so the hosted settlement option is what expires |
| `matched_offer_id` | **Left open**, recorded as open: it plausibly names a selected negotiation offer and no surviving call path settles it |
| The semantic `offer`/`executor` classification | `survey.md` — an audit record for this rename, not a durable rule |
