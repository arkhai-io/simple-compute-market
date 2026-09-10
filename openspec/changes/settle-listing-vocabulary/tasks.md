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
      optional published field fails quietly, so `listing_resource` and the
      offering-mode field need the grep audit that `executor_kind` does not.

## 2. Offering mode: one name

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
- [ ] 5.2 Bump the filter-spec `version` and the `schema.version` together, since a
      renamed required listing-shape field and a changed identity are both
      backwards-incompatible.
- [ ] 5.3 Leave the API-credits filter-spec's own identity alone, and confirm it
      publishes no offering-mode field so nothing there needs renaming.
- [ ] 5.4 Update the comments in both filter-specs that refer to `vms.compute` by name.

## 6. Retire `executor`

- [ ] 6.1 Replace `executor` with `host` in
      `capacity-resource-administration`'s "Host is executor identity only" and in
      `project-capacity-resources-without-hosts`' executor correlation, executor
      inventory, and executor-correlated-fields language, including their spec deltas
      and task lists.
- [ ] 6.2 Replace `ARCHITECTURE.md`'s four uses of `executor` in the offering-mode
      sense — "defaults an executor mode", "a default executor", "other executor
      kinds", and the diagram's "future executors".
- [ ] 6.3 Leave `provider` alone as the pool's delivery handler.

## 7. Downstream change documents

- [ ] 7.1 Update `unbacked-listing-publication` and
      `publish-indicative-listing-rates` for `listing_resource` and `offering_mode`,
      including their spec deltas and filter paths.
- [ ] 7.2 Note in `structured-capacity-requirements` that `offering_type` is not to be
      introduced, leaving the decision to delete the item to that change's owner
      rather than deleting it from outside.

## 8. Specification

- [ ] 8.1 Synchronize the `MODIFIED` cardinality-hint requirement, replacing the
      existing requirement in full rather than adding a second one.
- [ ] 8.2 Synchronize the `MODIFIED` listing-mapping requirement, which now states
      that one name is used for the offering mode on every surface and that the
      published shape is a listing rather than an offer.
- [ ] 8.3 Synchronize the added `site-capacity` and `registry-discovery` requirements.
- [ ] 8.4 Update `openspec/specs/storefront-publication/architecture.md`, which names
      the published field.
- [ ] 8.5 After synchronization, confirm no permanent specification still names
      `executor_kind`, `virtualization_type`, `offer_resource`, or `offering_type`,
      and that `listing_mode` survives only as the deprecated ingestion alias.

## 9. Validation

Levels are named deliberately. Per `docs/development/TESTING.md`, integration means
the real app, a real database, a wired DI container, and the service's canonical typed
client over `ASGITransport`.

- [ ] 9.1 Run the full suite before and after. This change asserts no behaviour
      change, so a changed assertion is a defect and a signal to stop rather than a
      test to update.
- [ ] 9.2 **Unit.** Exhaustive cardinality key resolution: new key, deprecated alias,
      both present, unrecognized value, absence.
- [ ] 9.3 **Integration.** A capacity claim carrying `offering_mode` reserves through
      the real site app and its canonical client; a claim carrying the retired key is
      refused.
- [ ] 9.4 **Integration.** A listing publishes and is queried through the canonical
      `RegistryClient` under `listing_resource` and `offering_mode`; a submission
      using a retired spelling is rejected.
- [ ] 9.5 **Integration.** The producer serializes `listing_cardinality_mode` through
      the real projection API, read back through the canonical site client, and the
      storefront resolves cardinality from it.
- [ ] 9.6 **System.** Old-producer cardinality skew across deployable services. This is
      system-level evidence for the alias, not a substitute for 9.5.
- [ ] 9.7 **Integration.** A buyer client declaring the new schema identity queries a
      bumped registry successfully, and one declaring the retired identity does not.
- [ ] 9.8 **Boundary-change validation.** Follow
      `docs/development/TESTING.md`'s boundary-change procedure: package build and type
      checks, plus an audit of every public producer and consumer of each renamed name.
      Three of these cross package boundaries and one crosses a service boundary.

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
      decisions, the rejected alternatives for `executor`, and the deferred alias
      removal question.
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
| `executor` is retired: the machine is a host, the handler is a provider, the mode is an offering mode | `docs/development/ARCHITECTURE.md` |
