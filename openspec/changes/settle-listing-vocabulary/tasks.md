# Tasks — settle the listing vocabulary

## 1. Survey

- [ ] 1.1 Grep every producer, consumer, test, fixture, operator pool-definitions
      sample, and document for each renamed name: `listing_mode`, `executor_kind`,
      `offer_resource`, the bare `offer` spelling of a published shape,
      `virtualization_type`, `VirtualizationType`, `vms.compute`, and `executor` used
      as vocabulary. Record the full list before editing; a rename's risk is entirely
      in the sites it misses.
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
      filter specification by identity), and `physical-provisioning` (whose release
      lookup is selected by the claim's mode field). Task 12.5's assertion that no
      permanent specification still names a retired term is only meetable if the
      inventory is complete first.
- [ ] 1.5 Enumerate every persisted use, separately from wire use: the
      `CapacityReservation` column, the `scheduling_requirements` JSON payload, and
      the storefront and registry JSON listing shapes. Live peer coordination does
      not address rows already written.

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
- [ ] 2.2 Rename `virtualization_type` to `offering_mode` in the published listing
      shape, the `VirtualizationType` enum and its type name, the bare-metal schema
      literal, the registry filter, and the buyer CLI flags in both the VM and
      bare-metal buyers.
- [ ] 2.3 Confirm the assignment sites now read as identity rather than translation —
      `arkhai_vms/storefront_adapter.py` assigning from `candidate["offering_mode"]`,
      the bare-metal storefront assigning from `registration.binding.offering_mode`,
      and `listing_service.py` reading it back — and remove any conversion left over
      from the two names having differed.
- [ ] 2.4 Confirm `pool_delivers_offering_mode` now takes the claim's `offering_mode`
      directly with no intermediate name at the ledger, the scheduler, or fulfillment.

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

## 5. Schema identity and versions

- [ ] 5.1 Change `schema.id` from `vms.compute` to `compute.market` in
      `core/registry/filter-spec.yaml`, and update `VMS_SCHEMA_ID` and every buyer
      compatibility declaration that names it.
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

## 6. Retire `executor` as a synonym

- [ ] 6.1 Replace `executor` with `host` in
      `capacity-resource-administration`'s "Host is executor identity only" and in
      `project-capacity-resources-without-hosts`' executor correlation, executor
      inventory, and executor-correlated-fields language, including their spec deltas
      and task lists.
- [ ] 6.2 Replace `ARCHITECTURE.md`'s four uses of `executor` in the offering-mode
      sense — "defaults an executor mode", "a default executor", "other executor
      kinds", and the diagram's "future executors".
- [ ] 6.3 Leave `provider` alone as the pool's delivery handler.
- [ ] 6.4 Leave `ExecutorAdapter`, `ExecutorAdapterRegistry`,
      `ExecutorActionEnvelope`, `UnsupportedExecutorActionError`, and
      `ExecutorMismatchError` named as they are. That abstraction validates,
      submits, and polls execution actions and is none of the other three concepts;
      only its selector moves, in task 2.1a.
- [ ] 6.5 Confirm `physical-provisioning`'s separation of executor registration and
      dispatch from provider fulfillment still reads correctly after the selector
      rename, and amend its release-lookup requirement, which is selected by the
      claim's mode field.

## 6b. Persisted state

- [ ] 6b.1 Rename the `CapacityReservation.executor_kind` column through the
      versioned migration framework — `_add_column_if_missing`, backfill,
      `_drop_columns_via_table_rebuild` — recorded under a migration ID. The cheaper
      option was to leave the column and map at the boundary; it is renamed so that a
      grep for the retired name is trustworthy evidence no site was missed.
- [ ] 6b.2 Backfill the `scheduling_requirements` JSON payload.
      `settlement_repository.py` compares `record.scheduling_requirements ==
      serialized_requirements` structurally, so a pre-upgrade payload under the
      retired key is not equal to a newly serialized one and a retried settlement
      would stop recognizing its own request. Do not normalize at comparison time
      instead — that is permanent compatibility code carrying a retired name.
- [ ] 6b.3 Backfill the storefront and registry JSON listing shapes.
- [ ] 6b.4 Count rows still carrying any retired key after each backfill and make a
      non-zero count a cutover gate. Both payloads are JSON, so a missed row is not a
      type error and would not surface until a retry or a listing read.
- [ ] 6b.5 Sequence the cutover per `DEPLOYMENT_AND_CONFIG.md`'s identity-contract
      pattern: quiesce authenticated mutations, migrate, verify every participating
      registry, storefront, peer, authority, and client reports the pinned version,
      then resume. Record that rollback is limited to the boundary before 6b.1.

## 7. Downstream change documents

- [ ] 7.1 Update `unbacked-listing-publication` and
      `publish-indicative-listing-rates` for `listing_resource` and `offering_mode`,
      including their spec deltas and filter paths.
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
      `resource-pool-management`, `deployment-state`, and `physical-provisioning`.
- [ ] 8.6 After synchronization, confirm no permanent specification still names
      `executor_kind`, `virtualization_type`, `offer_resource`, or `offering_type`,
      and that `listing_mode` survives only as the deprecated ingestion alias. This is
      only meetable if 1.4's inventory was complete; if it names a capability with no
      delta, stop rather than narrowing the assertion.

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
      new-vocabulary fixtures resolve to the same effective values at every
      boundary the survey identified.
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
- [ ] 9.11 **Migration + integration.** Storefront and registry databases holding
      pre-upgrade JSON listing shapes survive the backfill and serve listings
      unchanged.
- [ ] 9.12 **System.** Old-producer cardinality skew across deployable services. This
      is system-level evidence for the alias, not a substitute for 9.8.
- [ ] 9.13 **System.** The cutover gate rejects an incompatible peer before mutations
      resume, per the identity-contract pattern.
- [ ] 9.14 **Integration.** A buyer client declaring the new schema identity queries a
      bumped registry successfully; one declaring the retired identity does not.
- [ ] 9.15 **Boundary-change validation.** Follow
      `docs/development/TESTING.md`'s boundary-change procedure: package build and
      type checks, and confirm every renamed package still exposes its expected public
      surface. Four package boundaries and one service boundary move here.
- [ ] 9.16 Grep for every retired name across the codebase and expect zero hits
      outside archived change documents. This is the reason the persisted column was
      renamed rather than mapped, so a non-zero count is a missed site rather than
      something to triage.

## 10. Closeout

- [ ] 10.1 **Comment hygiene.** Run `make check-comment-hygiene` and resolve every
      match. A rename tempts explanatory comments naming the old key; the local
      rationale to keep is the alias's skew-protection purpose, not any rename's
      history.
- [ ] 10.2 **Import placement.** Review imports this change added or touched and
      migrate function-level ones to module level where no genuine circular import or
      documented lazy-load reason exists. Verify against the real test suite; a rename
      of this size is where a latent circular import surfaces.
- [ ] 10.3 **Documentation compliance.** Re-check accepted decisions against
      `openspec/README.md`'s placement table. The one-name rule and the
      listing-not-offer rule both state behaviour implementations must satisfy, so
      confirm they landed as normative requirements.
- [ ] 10.4 **Narrative compression.** Shorten completed-task notes to final naming
      decisions, the rejected alternatives for `executor`, the migration strategy per
      persisted item, and the deferred alias removal question.
- [ ] 10.5 **Roadmap currency.** Assess `docs/development/ROADMAP.md`, including
      Goal 1's mention of the published field. Record the disposition either way.
- [ ] 10.6 **Campaign index currency.** Update this change's row and Goal 7's
      dependency graph in `openspec/changes/README.md`.
- [ ] 10.7 **Promotion.** Complete the design-promotion record below.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| One name for the offering mode across claim wire, pool declarations, durable binding, and published listing | `openspec/specs/storefront-publication/spec.md`, `openspec/specs/site-capacity/spec.md` |
| The cardinality hint's normative scope; absence encodes "no cardinality question" | `openspec/specs/storefront-publication/spec.md` |
| A seller's published shape is a listing; `offer` is a negotiation message | `openspec/specs/registry-discovery/spec.md` |
| The compute schema identity names the family, not one domain | `openspec/specs/registry-discovery/spec.md` |
| `executor` names only the action-dispatch abstraction; its synonym uses are retired — the machine is a host, the handler is a provider, the mode is an offering mode | `docs/development/ARCHITECTURE.md` |
