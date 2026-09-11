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

- [ ] 1.1 Grep every producer, consumer, test, fixture, operator pool-definitions
      sample, and document for each renamed name. **Match full identifiers, not
      prefixes or fragments** — the retired list is `listing_mode`,
      `LISTING_MODE_POLICY_TAG`, `raw_listing_mode`, `resolve_vm_listing_mode`,
      `listing_mode_explanation`, `listing_mode_explanations`, `executor_kind`,
      `EXECUTOR_KIND_CLAIM_KEY`, `VM_EXECUTOR_KIND`, `_VM_EXECUTOR_KIND`,
      `offer_resource`, `offer_resource_type`, the bare `offer` spelling of a
      published shape, `virtualization_type`, `VirtualizationType`, `vms.compute`,
      and `offering_type`. Record the full list before editing; a rename's risk is
      entirely in the sites it misses.
- [ ] 1.1a Use full-identifier matching deliberately rather than as style, because
      three retired names are substrings of names that stay: `listing_mode` matches
      `listing_model` and every `test_listing_model_*` file; `offer` matches both
      `offer_resource` and the replacement `offering_mode`, so searching it reports
      the new vocabulary as retired; and `vms.compute` matches
      `arkhai_vms.compute_requirements` (2 of 43 hits). An audit whose expected
      result is "zero after dismissing a known false-positive list" is not an audit,
      so task 9.16 is only meetable if the retired list is full identifiers.
- [ ] 1.1b Separate the two distinct uses of `vms.compute` before editing either. The
      registry `schema.id` and `VMS_SCHEMA_ID` are renamed; `domain_identity` fixture
      values in `e2e-tests` are a different axis — the production domain identity is
      `compute.v1` (`VM_PROVISION_KIND`) and the durable listing binding freezes it.
      Decide per site; do not globally replace.
- [ ] 1.2 Mark which side of the storefront-to-site boundary each site sits on. Only
      `listing_mode` keeps an alias, so every other boundary site must move in one
      coordinated deploy.
- [ ] 1.3 Separate optional published fields from required wire fields in that list. A
      missed required-claim site fails loudly at the first reservation; a missed
      optional published field fails quietly, so `listing_resource` needs the closest
      grep audit.
- [ ] 1.4 **Publish the survey output as the affected-capability inventory** before
      editing. It must include at minimum `resource-pool-management` (which names
      `listing_mode` normatively), `deployment-state` (which selects the compute
      filter specification by identity), `physical-provisioning` (whose release
      lookup is selected by the claim's mode field), and
      `compute-provisioning-contract` (whose versioned models carry the mode field).
      Task 8.6's assertion that no permanent specification still names a retired term
      is only meetable if the inventory is complete first.
- [ ] 1.5 Enumerate every persisted use, separately from wire use. Live peer
      coordination does not address rows already written, and these divide into two
      kinds needing different treatment:
      **column names**, which a row backfill cannot touch —
      `capacity_reservations.executor_kind`, `listings.offer_resource` in the registry
      database, and `listings.offer_resource` in the storefront database; and
      **keys inside payloads** — the `executor_kind` key in
      `settlement_records.scheduling_requirements`, and the `virtualization_type` key
      nested in the storefront listing payload.
- [ ] 1.6 Record the retained `executor_` compounds explicitly as part of the survey
      output: `executor_ref`, `executor_target`, `ExecutorActionEnvelope`,
      `ExecutorAdapter`, `ExecutorAdapterRegistry`, `ExecutorLeaseService` and its
      registration/update carriers, `UnsupportedExecutorActionError`, and
      `ExecutorMismatchError`. These are correct by the head-noun rule and are not
      pending work. Recording them once, with the rule, is what lets a later auditor
      dismiss them by rule rather than re-deriving the judgement per site.

## 2. Offering mode: one name

- [ ] 2.1a Rename `ExecutorAdapter.executor_kind` to `offering_mode` and update
      `ExecutorAdapterRegistry`'s selection, keeping every type name in that module
      unchanged. The adapter is selected by the offering mode it serves; the
      abstraction is not the mode.
- [ ] 2.1 Rename `executor_kind` to `offering_mode` on the capacity claim, through
      `kit/site` (`EXECUTOR_KIND_CLAIM_KEY`, `_requested_executor_kind`, the ledger
      and authority signatures), `kit/fulfillment` (`SettlementRequirement`, the
      scheduler, backfill, fulfillment), both provisioning adapters, and the
      storefront claim builders including `_VM_EXECUTOR_KIND` and the API-credit
      producers. Keep the field required.
- [ ] 2.1b Rename the field on the compute provisioning service's own versioned
      contract in `provisioning/compute/src/compute_provisioning/contracts.py` — all
      seven models: `ExecutorActionEnvelope`, `JobAccepted`, `CredentialEnvelope`,
      `ResultEnvelope`, `ProvisioningJob`, `LeaseRegistration`, and `LifecycleEvent` —
      and advance `contract_version` for the backwards-incompatible field rename.
      Leaving this wire alone would put `offering_mode` on one side of it and
      `executor_kind` on the other, which is the condition this change exists to end.
      `executor_target` on `LeaseRegistration` stays, per task 6.4.
- [ ] 2.2 Rename `virtualization_type` to `offering_mode` in the published listing
      shape, the `VirtualizationType` enum — whose type name becomes `OfferingMode` —
      the bare-metal schema literal, the registry filter, and the buyer CLI flags in
      both the VM and bare-metal buyers, including the bare-metal listing CLI's
      hardcoded `virtualization_type="bare_metal"` query argument.
- [ ] 2.3 Confirm the assignment sites now read as identity rather than translation —
      `arkhai_vms/storefront_adapter.py` assigning from `candidate["offering_mode"]`,
      the bare-metal storefront assigning from `registration.binding.offering_mode`,
      and `listing_service.py` reading it back — and remove any conversion left over
      from the two names having differed.
- [ ] 2.4 Confirm `pool_delivers_offering_mode` now takes the claim's `offering_mode`
      directly with no intermediate name at the ledger, the scheduler, or fulfillment.
- [ ] 2.5 Confirm the name is not newly coined at the layer that receives it:
      `kit/site` already defines and exports `UndeclaredOfferingModeError`, and
      `kit/resource-pools` already exports `pool_delivers_offering_mode` over
      `deliverable_modes`, whose module docstring calls its members opaque
      offering-mode names. If any of those has to change spelling to accommodate this
      rename, the target name is wrong — stop rather than widening the change.

## 3. Listing, not offer

- [ ] 3.1 Rename `offer_resource` to `listing_resource` across the listing models,
      storefront services, migrations, publication paths, registry filter paths,
      `core/storefront-client`, and `core/registry-client`.
- [ ] 3.2 Remove the `offer` alias in `core/registry-client`, which currently reads
      `d.get("offer") or d.get("offer_resource")`. Retaining it would keep the
      collision the rename exists to remove.
- [ ] 3.3 Leave `message_type="offer"` in `kit/negotiation-runtime` alone. That is the
      meaning `offer` is being returned to.
- [ ] 3.4 Audit the publication CLIs, which pass `offer=` positionally in at least
      one place, so a rename does not silently bind the wrong argument.
- [ ] 3.5 Rename the `ListingRequest.offer` and `ListingSummary.offer` **attributes**
      to `listing_resource` in `core/registry-client`. These are distinct from the
      ingestion alias removed in 3.2: `ListingRequest.to_dict()` already emits
      `"offer_resource": self.offer`, so the attribute never reached the wire under
      this spelling. `ValidatePublishRequest` in the same module already spells the
      same concept `offer_resource`, so the module contradicts itself today, and an
      attribute named `offer` that holds a listing is the collision itself.
- [ ] 3.6 Drop `offer_resource_type` rather than renaming it — from
      `ValidatePublishResponse` in `core/registry-client`, from
      `core/registry/src/api/validate_model.py`, and from
      `_derive_offer_resource_type` and its call site in `validate_routes.py`. It is a
      cosmetic tag derived by sniffing the payload for `gpu_model` or `token` while
      the accept/reject decision is the schema's. Delete the function's docstring with
      it rather than updating it: the docstring names a change ID and is an existing
      comment-hygiene violation in a file this change already edits. Update the
      `e2e-tests` and registry integration assertions that read the field.

## 4. Cardinality hint

- [ ] 4.1 Emit `listing_cardinality_mode` from the resource-pool projection alongside
      the existing key, and accept the new key in operator-supplied pool definitions.
- [ ] 4.2 Prefer the new key in the storefront hint consumers, falling back to the old
      one and emitting an operator-visible deprecation notice when the alias is taken.
- [ ] 4.3 Cover the skew case directly: an unupgraded projection carrying only the old
      key must resolve to the same cardinality it resolves to today, not to the
      structural default. This is the defect the alias exists to prevent and it needs
      its own test rather than being implied by the alias's presence.
- [ ] 4.4 Confirm the hint is still read live from the current projection at each point
      of need and is not persisted into storefront-local storage. The rename must not
      become an occasion to cache it.
- [ ] 4.5 Stop emitting the old key from the producer once consumers accept both. Do
      not remove consumer-side alias acceptance in this change; its removal is an open
      question in `design.md` with no owner yet.
- [ ] 4.6 Rename the hint's derived internals, which the alias does not cover — the
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
- [ ] 4.7 Rename the operator-facing explanation field `listing_mode_explanations` →
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

## 5. Schema identity and versions

- [ ] 5.1 Change `schema.id` from `vms.compute` to `compute.market` in
      `core/registry/filter-spec.yaml`, and update `VMS_SCHEMA_ID` and every buyer
      compatibility declaration that names it. Per 1.1b, do not sweep
      `domain_identity` fixtures in the same pass.
- [ ] 5.2 Bump the compute filter-spec `version` and its `schema.version` together,
      since a renamed required listing-shape field and a changed identity are both
      backwards-incompatible.
- [ ] 5.3 Rename `offer_resource` to `listing_resource` in
      `domains/apicredits/registry/filter-spec.yaml` and
      `core/registry/filter-spec.introductions.yaml`, including their `required` sets
      and every `$.offer_resource.*` filter path, and bump each specification's
      version. Both keep their own schema identities — only the envelope field moves.
      An earlier plan asserted these needed only confirmation because they publish no
      offering-mode field; that is true of the mode and false of the envelope.
- [ ] 5.4 Update the comments in every filter-spec that refers to `vms.compute` by
      name.
- [ ] 5.5 **Integration.** An API-credits listing and an introduction listing each
      publish and are queried successfully under the renamed envelope, through the
      canonical `RegistryClient` against the real registry app.
- [ ] 5.6 Bump the minor version of every client distribution whose public surface
      moves: `arkhai-core-registry-client` (renamed attributes, removed alias, dropped
      field), `arkhai-core-storefront-client` (renamed status field), and
      `arkhai-kit-site-client` (claim field). A pre-rename client must not resolve
      against a post-rename service, and the distribution version is the only signal
      that carries that. Confirm the reinit targets upgrade these from `.dist` per
      `AGENTS.md`'s package discipline.

## 6. Retire `executor` as a synonym

- [ ] 6.1 Replace `executor` with `host` in `capacity-resource-administration`'s "Host
      is executor identity only" and in `project-capacity-resources-without-hosts`'
      executor correlation, executor inventory, and executor-correlated-fields
      language, including their spec deltas and task lists.
- [ ] 6.2 Replace `ARCHITECTURE.md`'s four uses of `executor` in the offering-mode
      sense — "defaults an executor mode", "a default executor", "other executor
      kinds", and the diagram's "future executors". Leave "VM executor arguments",
      which is the action-dispatch sense.
- [ ] 6.3 Leave `provider` alone as the pool's delivery handler.
- [ ] 6.4 Leave the action-dispatch abstraction and its compounds named as they are.
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
- [ ] 6.5 Confirm `physical-provisioning`'s separation of executor registration and
      dispatch from provider fulfillment still reads correctly after the selector
      rename, and amend its release-lookup requirement, which is selected by the
      claim's mode field.
- [ ] 6.6 State the head-noun rule **positively** wherever the retirement is written
      down, in `ARCHITECTURE.md`'s shared vocabulary and in `physical-provisioning`'s
      registration requirement: `executor_`-prefixed compounds naming the
      abstraction's own targets, references, or actions retain the name; what is
      retired is `executor` as the head noun for the mode, the machine, or the
      handler. Stating only the prohibition invites a later reader to apply it to a
      prefix match and rename roughly 300 further sites across `kit/site`, both
      provisioning adapters, `ExecutorLeaseService`, and the bare-metal lease and
      release paths on the strength of that match.

## 6b. Persisted state

- [ ] 6b.1 Rename the `capacity_reservations.executor_kind` column through the compute
      provisioning service's versioned migration framework — `_add_column_if_missing`,
      backfill, `_drop_columns_via_table_rebuild` — recorded under a new migration ID
      following the existing `YYYYMMDD_NNN_description` convention after
      `20260901_001_relay_reachable_hosts`. Name it for the resulting schema, not for
      this change. The cheaper option was to leave the column and map at the boundary;
      it is renamed so that a grep for the retired name is trustworthy evidence no
      site was missed.
- [ ] 6b.1b Rename the registry's `listings.offer_resource` column through a new
      Alembic revision after `017_publisher_replay_leases`, updating
      `core/registry/src/db/models.py`. This is a column name holding JSON, not a
      payload carrying an `offer_resource` key — an earlier plan listed it as a
      backfill, which would have left the column untouched.
- [ ] 6b.1c Rename the storefront's `listings.offer_resource` column through a new
      `core_storefront.sqlite_migrations` migration after
      `20260815_001_storefront_domain_bindings`, updating the `CREATE TABLE listings`
      DDL and the roughly twenty references in
      `core/storefront/src/core_storefront/sqlite_client.py`. The table is core-owned
      and shared by both compute storefronts, so this belongs to the domain-neutral
      migration set rather than to either domain's `_domain_migrations`.
- [ ] 6b.2 Backfill the `executor_kind` key inside the
      `settlement_records.scheduling_requirements` payload.
      `settlement_repository.py` compares `record.scheduling_requirements ==
      serialized_requirements` structurally, so a pre-upgrade payload under the
      retired key is not equal to a newly serialized one and a retried settlement
      would stop recognizing its own request. Do not normalize at comparison time
      instead — that is permanent compatibility code carrying a retired name.
- [ ] 6b.3 Backfill the `virtualization_type` key nested inside the storefront listing
      payload, in the same migration as 6b.1c so a row is never observable with the
      new column name and the retired inner key. The bare-metal storefront's
      `_migrate_common_domain_bindings` writes that key today; update it to the
      settled name so it does not reintroduce the retired key on a later run.
- [ ] 6b.4 Count rows still carrying a retired key after each **payload** backfill
      (6b.2, 6b.3) and make a non-zero count a cutover gate. Both payloads are JSON,
      so a missed row is not a type error and would not surface until a retry or a
      listing read. The three column renames carry the opposite profile — a missed one
      fails at open rather than silently — so they need no count gate.
- [ ] 6b.5 Sequence the cutover per `DEPLOYMENT_AND_CONFIG.md`'s identity-contract
      pattern: quiesce authenticated mutations, migrate, verify every participating
      registry, storefront, provisioning service, peer, authority, and client reports
      the pinned version, then resume. Record that rollback is limited to the boundary
      before 6b.1.
- [ ] 6b.6 Record that `migrate-registry-to-postgres` must target the renamed column.
      That change is blocked on external infrastructure and on step 2 of its own
      chain, so there is no ordering conflict to resolve here — only a requirement on
      whichever lands second.

## 7. Downstream change documents

- [ ] 7.1 Update `unbacked-listing-publication` and `publish-indicative-listing-rates`
      for `listing_resource` and `offering_mode`, including their spec deltas and
      filter paths.
- [ ] 7.2 Amend `structured-capacity-requirements` to use `offering_mode` instead of
      proposing `offering_type`, in both its proposal and its task list. Leave the
      decision to delete the item entirely to that change's owner — whether it has
      anything left to do is theirs, whether it may introduce a fourth name for one
      concept is not.
- [ ] 7.3 Correct the **active spec deltas** carrying retired vocabulary:
      `multi-domain-storefront-composition/specs/storefront-publication`, and both
      `pools-8-capacity-projection-and-listing-hints` deltas. A delta is the path by
      which a retired name would synchronize back into a permanent specification, so
      these are corrected here rather than left to their owners.
- [ ] 7.4 Update the prose in `bare-metal-buyer-domain`,
      `pools-7-storefront-fulfillment-cutover`,
      `pools-9-retire-local-physical-authority`, and
      `publish-multidimensional-listing-shape`, which reference retired names in
      designs and task lists without carrying them in deltas.

## 8. Specification

- [ ] 8.1 Synchronize the `MODIFIED` cardinality-hint requirement, replacing the
      existing requirement in full rather than adding a second one.
- [ ] 8.2 Synchronize the `MODIFIED` listing-mapping requirement, which now states
      that one name is used for the offering mode on every surface and that the
      published shape is a listing rather than an offer.
- [ ] 8.3 Synchronize the added `site-capacity` and `registry-discovery` requirements.
- [ ] 8.4 Update `openspec/specs/storefront-publication/architecture.md`, which names
      the published field.
- [ ] 8.5 Synchronize deltas for every capability in task 1.4's inventory, including
      `resource-pool-management`, `deployment-state`, `physical-provisioning`, and
      `compute-provisioning-contract`.
- [ ] 8.6 After synchronization, confirm no permanent specification still names
      `executor_kind`, `virtualization_type`, `offer_resource`, `offer_resource_type`,
      or `offering_type`, and that `listing_mode` survives only as the deprecated
      ingestion alias. This is only meetable if 1.4's inventory was complete; if it
      names a capability with no delta, stop rather than narrowing the assertion.
- [ ] 8.7 Synchronize the `compute-provisioning-contract` delta, which was missing from
      the affected-specification list until design review. Its four modified
      requirements cover the selector on the action envelope, job status, the typed
      result and credential envelopes, and lease control — and the contract-version
      advance that carries them.
- [ ] 8.8 Correct the two permanent documents outside `openspec/specs` that name a
      retired term and are not covered by 6.2:
      `docs/development/DEPLOYMENT_AND_CONFIG.md`'s reference to the compute
      registry's `vms.compute` filter specification, and
      `docs/development/TESTING.md`'s `virtualization_type` example.
- [ ] 8.9 Run the cross-reference check `AGENTS.md` requires before promoting
      documentation: every `openspec/`, `docs/`, `tools/`, `scripts/`, and
      `e2e-tests/` path cited by a document this change edits must exist on this
      branch. This change adds a specification delta directory and renames a module,
      so it both creates and invalidates citations; treat an unresolvable one as a
      blocking defect rather than a stale link.

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

- [ ] 9.1 **Unit.** Transformation equivalence: paired old-vocabulary and
      new-vocabulary fixtures resolve to the same effective values at every boundary
      the survey identified.
- [ ] 9.2 **Unit.** Exhaustive cardinality key resolution: new key, deprecated alias,
      both present, unrecognized value, absence.
- [ ] 9.3 **Unit.** `ExecutorAdapterRegistry` registration, duplicate registration,
      and unsupported-action lookup still behave identically after the selector
      rename.
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
- [ ] 9.8 **Integration.** The producer serializes `listing_cardinality_mode` through
      the real projection API, read back through the canonical site client, and the
      storefront resolves cardinality from it.
- [ ] 9.9 **Migration + integration.** A database written by the previous version,
      containing the retired reservation column, upgrades and then recovers an
      existing reservation and its job correctly.
- [ ] 9.10 **Migration + integration.** A settlement retried after upgrade recognizes
      its pre-upgrade serialized scheduling requirements as the same request. This is
      the idempotency comparison the backfill exists to protect and nothing else
      covers it.
- [ ] 9.11 **Migration + integration.** Storefront and registry databases written by
      the previous version, carrying the retired **column** and the retired inner
      `virtualization_type` key, upgrade and then serve listings unchanged. Assert
      both the new column name and the settled inner key, since 6b.1c and 6b.3 run
      together and a row must never be observable with one migrated and the other not.
- [ ] 9.12 **System.** Old-producer cardinality skew across deployable services. This
      is system-level evidence for the alias, not a substitute for 9.8.
- [ ] 9.13 **System.** The cutover gate rejects an incompatible peer before mutations
      resume, per the identity-contract pattern.
- [ ] 9.14 **Integration.** A buyer client declaring the new schema identity queries a
      bumped registry successfully; one declaring the retired identity does not.
- [ ] 9.15 **Boundary-change validation.** Follow `docs/development/TESTING.md`'s
      boundary-change procedure: package build and type checks, and confirm every
      renamed package still exposes its expected public surface. Four package
      boundaries and two service boundaries move here — the claim wire and the
      provisioning contract.
- [ ] 9.16 Grep for every retired name across the codebase and expect zero hits
      outside archived change documents. Use the full-identifier list from 1.1 rather
      than prefixes, and treat the compounds recorded in 1.6 as correct by rule rather
      than as hits to dismiss. This is the reason the persisted columns were renamed
      rather than mapped, so a non-zero count is a missed site rather than something
      to triage.
- [ ] 9.17 **Integration.** An action submitted through the provisioning contract
      carrying `offering_mode` dispatches to the registered adapter; one carrying the
      retired key is rejected as carrying no offering mode; and a caller pinned to the
      previous `contract_version` is refused with actionable version information
      rather than coerced. The lease path retains `executor_target` alongside the
      renamed mode field in the same registration.
- [ ] 9.18 **Integration.** The admin-gated status route returns
      `listing_cardinality_mode_explanations`, read back through
      `core/storefront-client`'s status model, with the fallback explanation still
      reaching an operator for a supplied-but-unrecognized value and still absent for
      an absent one. The liveness probe continues to omit the field.

## 10. Closeout

- [ ] 10.1 **Comment hygiene.** Run `make check-comment-hygiene` and resolve every
      match. A rename tempts explanatory comments naming the old key; the local
      rationale to keep is the alias's skew-protection purpose and the head-noun rule
      behind the retained compounds, not any rename's history. Two existing violations
      sit in files this change edits and are resolved by deletion rather than
      rewording: `_derive_offer_resource_type`'s docstring naming a change ID (3.6),
      and `kit/site`'s `ledger.py` comment explaining which columns no longer exist.
- [ ] 10.2 **Import placement.** Review imports this change added or touched and
      migrate function-level ones to module level where no genuine circular import or
      documented lazy-load reason exists. Verify against the real test suite; a rename
      of this size is where a latent circular import surfaces. The VM cardinality
      resolver's importers keep deliberate local imports with a stated reason — verify
      that reason still holds after 4.6's module rename rather than relocating them on
      the strength of the rename alone.
- [ ] 10.3 **Documentation compliance.** Re-check accepted decisions against
      `openspec/README.md`'s placement table. The one-name rule, the
      listing-not-offer rule, and the head-noun/compound rule all state behaviour
      implementations must satisfy, so confirm each landed as a normative requirement
      rather than as design prose only.
- [ ] 10.4 **Narrative compression.** Shorten completed-task notes to final naming
      decisions, the rejected alternatives for `executor`, the migration strategy per
      persisted item, the five design-review dispositions, and the deferred alias
      removal question. Remove this file's "Plan revisions" note once its content is
      reflected in the promotion record below.
- [ ] 10.5 **Roadmap currency.** Update `docs/development/ROADMAP.md`, whose Goal 1
      names the published field and whose Goal 7 current-state prose names
      `offer_resource`, `listing_mode`, `offering_type`, and the projection's
      "executor host inventory". Goal 7's gap row for this change also needs its
      status reconciled. Record the disposition either way.
- [ ] 10.6 **Campaign index currency.** Update this change's row and Goal 7's
      dependency graph in `openspec/changes/README.md`. The row's acceptance-boundary
      summary predates design review and mentions neither the provisioning contract
      nor the persisted-state shape.
- [ ] 10.7 **Promotion.** Complete the design-promotion record below.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| One name for the offering mode across claim wire, pool declarations, durable binding, and published listing | `openspec/specs/storefront-publication/spec.md`, `openspec/specs/site-capacity/spec.md` |
| The offering mode names the field on the provisioning action, job, result, credential, lease, and lifecycle-event contracts, under a contract-version advance | `openspec/specs/compute-provisioning-contract/spec.md` |
| The cardinality hint's normative scope; absence encodes "no cardinality question"; the deprecated spelling survives on the ingestion path and nowhere else | `openspec/specs/storefront-publication/spec.md`, `openspec/specs/resource-pool-management/spec.md` |
| A seller's published shape is a listing; `offer` is a negotiation message, including as a client attribute | `openspec/specs/registry-discovery/spec.md` |
| The compute schema identity names the family, not one domain | `openspec/specs/registry-discovery/spec.md` |
| `executor` names only the action-dispatch abstraction as a head noun; its synonym uses are retired — the machine is a host, the handler is a provider, the mode is an offering mode | `docs/development/ARCHITECTURE.md` |
| `executor_`-prefixed compounds naming that abstraction's own targets, references, and actions retain the name; the prohibition is on the head noun, not the prefix | `openspec/specs/physical-provisioning/spec.md`, `docs/development/ARCHITECTURE.md` |
| Release-status lookup is selected by the reservation's recorded offering mode | `openspec/specs/physical-provisioning/spec.md` |
| The compute-family registry instance is selected by the family schema identity | `openspec/specs/deployment-state/spec.md` |
| Goal 7 current state and gap ownership after the rename | `docs/development/ROADMAP.md` |
| This change's status and campaign placement | `openspec/changes/README.md` |
