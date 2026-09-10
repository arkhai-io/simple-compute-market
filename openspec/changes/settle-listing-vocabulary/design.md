# Design — settle the listing vocabulary

## Context

This change began as a rename of one projected pool hint, `listing_mode`, whose
name did not state its scope. Reviewing that name against its neighbours turned up
a wider problem: the marketplace has four names for the offering mode, three
meanings for `offer`, and three meanings for `executor`. Each was individually
survivable and each had a plausible local history, which is how a codebase reaches
four names for one value.

## Goals / Non-Goals

**Goals.** One name per concept. No behaviour change. Land before the changes that
would otherwise add fields under the old names.

**Non-Goals.** No compatibility window for the wire renames, no adjacent renames
that are already consistent, no new concepts.

## Decisions

### `virtualization_type` is in scope, and the evidence is unambiguous

This was the least obvious inclusion, so the evidence is recorded rather than
summarized.

`storefront-publication` states it normatively: *"Public
`offer_resource.virtualization_type` MUST equal the recorded offering mode."* Its
architecture companion adds that the field *"is projected from this binding, not
guessed."*

Six code sites assign it from the offering mode or read it back as one:
`arkhai_vms/storefront_adapter.py` writes `"virtualization_type":
candidate["offering_mode"]`; the bare-metal storefront writes
`offer["virtualization_type"] = registration.binding.offering_mode` in publication
and `offer_resource["virtualization_type"] = domain_binding.offering_mode` in its
client; `domain_migration.py` writes `offer["virtualization_type"] =
selection.offering_mode`; `listing_service.py` reads `offering_mode =
normalized_offer.get("virtualization_type")`; and `publication_service.py` compares
it against the capacity binding.

The enum's own docstring describes the offering mode — *"how the host exposes the
resource to the buyer... the seller picks the deployment mode for each listing"* —
and its members are `bare_metal | vm | container`, the same set the offering mode
takes in the compute family.

**One argument for including it was wrong and is dropped.** An earlier version of
this reasoning said the name is nonsense for `api_credits`. API credits do not
publish the field at all — they have their own filter-spec and their own schema
identity, and `virtualization_type` appears nowhere in that domain. The argument
that survives needs no such reach: `bare_metal` is a member of an enum called
`VirtualizationType`, and bare metal is the absence of virtualization. The field
asserts a virtualization type for listings that have none.

### `offer` is left to the negotiation, `listing` to the seller

`offer` is a live negotiation `message_type` in `kit/negotiation-runtime`, sent by
either party. It is also `offer_resource`, the seller's published shape, and
separately just `offer` — `core/registry-client` accepts either spelling for the
same field. Three meanings, one of which has two spellings.

Buyers make offers; only sellers make listings. So the published shape becomes
`listing_resource` and the `offer` alias is removed rather than retained, because
retaining it keeps the collision that motivated the rename.

**This is a generic envelope field, not a compute one.** An earlier version of this
plan renamed it in the compute filter specification and asserted the API-credits
specification merely needed confirming, on the grounds that it publishes no
offering-mode field. That confused two things: API credits indeed have no offering
mode to rename, but `domains/apicredits/registry/filter-spec.yaml` lists
`offer_resource` in its `required` set and filters `$.offer_resource.service_name`,
and `filter-spec.introductions.yaml` does the same with
`$.offer_resource.region`. The core registry routes, models, `RegistryClient`, and
`StorefrontClient` are all generic over the field.

So the rename is marketplace-wide across all three deployed specifications, each
bumping its own version. The alternative — compute calls its shape
`listing_resource` while the generic envelope stays `offer_resource` — would leave a
semantic half-boundary where the same field has two names depending on which
registry serves it, which is the condition being removed rather than a smaller
version of the fix.

### Four concepts, four names, and `executor` keeps one of them

An earlier draft of this design said `executor` had no remaining sense once
`executor_kind` became `offering_mode`, and retired the word outright. That was
wrong: `provisioning/compute/src/compute_provisioning/adapters.py` defines
`ExecutorAdapter` as a Protocol that validates action parameters, submits work, and
validates results and credentials, with `ExecutorAdapterRegistry` selecting adapters
"strictly by declared executor identity", alongside `ExecutorActionEnvelope`,
`UnsupportedExecutorActionError`, and `ExecutorMismatchError`. That is an
action-dispatch abstraction. It is not the machine, not the thing being sold, and
not the pool's fulfillment provider — `physical-provisioning` keeps executor
registration and dispatch separate from provider fulfillment deliberately.

| Concept | Name |
|---|---|
| What the seller is offering: `vm`, `bare_metal`, `container`, `api_credits` | `offering_mode` |
| The machine and its connection identity | `host` |
| The fulfillment implementation selected for a pool | `provider` |
| The component that validates, submits, and polls an execution action | `executor` |

So what is retired is `executor` as a *synonym*: for the machine, for the offering
mode, or for the provider. The abstraction keeps the word, and its selector moves —
`ExecutorAdapter.executor_kind` becomes `offering_mode`. "The executor adapter for
the `vm` offering mode" reads correctly and says something the old spelling could
not, because the old spelling used one word for the selector and the selected.

Renaming the abstraction to something like `action_adapter` was the alternative.
Rejected: it is churn across the provisioning contracts to eliminate a word that has
one coherent use, and the ambiguity being fixed is the synonymy rather than the
existence of the term.

A proposal to make `executor` the pool's delivery handler was also considered and
rejected. `ARCHITECTURE.md`'s uses of the word are the offering-mode sense —
"defaults an executor mode", "a default executor", "other executor kinds" — while
`provider` has 39 uses as the handler. Reassigning it would invert the dominant
usage and collide with the action abstraction above.

### The persisted state needs a strategy per item

An earlier version of this design said no data migration was involved, reasoning
from the live storefront-to-site topology being one-to-one. That solves peer skew and
says nothing about rows already written. `ARCHITECTURE.md` is explicit that
non-additive schema changes use expand/contract, so an unexamined hard rename of
persisted names is not available.

| Persisted item | Strategy |
|---|---|
| `CapacityReservation.executor_kind` column | Rename via the versioned migration framework — `_add_column_if_missing`, backfill, `_drop_columns_via_table_rebuild`, recorded under a migration ID |
| `scheduling_requirements` `Column(JSON)` | Backfill the key inside the cutover window |
| `offer_resource` JSON in storefront listings | Backfill |
| `offer_resource` JSON in registry rows | Backfill |

**The column rename is a deliberate choice against the cheaper option.** A column
name is internal storage rather than a contract, so mapping it at the boundary and
leaving the column alone would have worked. It is renamed anyway because the
validation strategy for a rename of this size is *grep*: a clean search for a retired
name across the codebase is the evidence that no site was missed, and a surviving
column keeps producing hits an auditor has to sift and dismiss one by one. Cheap
migration, much cheaper verification.

**The JSON backfill is not optional.** `settlement_repository.py` compares
`record.scheduling_requirements == serialized_requirements` — a structural dict
comparison against the persisted column, doing settlement idempotency work. A
pre-upgrade `{"executor_kind": "vm"}` is not equal to a newly serialized
`{"offering_mode": "vm"}`, so a retried settlement after upgrade would stop
recognizing its own request and re-submit. Leaving the stored payload and
normalizing at comparison time was the alternative; rejected because it is a
permanent piece of compatibility code carrying a retired name forever, which is the
opposite of what this change is for.

The cutover uses the identity-contract pattern `DEPLOYMENT_AND_CONFIG.md` already
documents: authenticated mutations stay quiesced until every participating registry,
storefront, service peer, hosted authority, and client reports the pinned version,
the identity-bearing state migrates, and then effects resume. Rollback is limited to
the boundary before the cutover.

### No compatibility window on the wire, because the window is closing

The cardinality hint gets a deprecated ingestion alias and the wire renames do not.
That asymmetry is deliberate rather than inconsistent.

`listing_mode` is an *optional* projected key whose absence resolves silently to a
domain's structural default. A consumer that recognized only the new key would read
an unupgraded site's projection as absent and reclassify its listing cardinality
without erroring — a silent wrong answer, which is what the alias prevents.

`executor_kind` is *required*: `_requested_executor_kind(claim, required=True)`
raises when it is missing. A skew failure there is loud and immediate, not silent.
Combined with the deployment facts — the claim wire crosses the storefront-to-site
boundary, that relationship is one-to-one today, and every party running a
storefront runs its own site — a hard rename costs a coordinated deploy that every
known operator already performs.

That window closes as sites multiply. Under the scoped one-to-many work a hard
rename means one storefront and N sites deploying in lockstep; under many-to-many it
would be untenable and an alias would become mandatory. The cheapest moment to fix
the wire is now, and this is the reason rather than mere convenience.

### The schema identity changes because the version is moving anyway

`schema.id: vms.compute` names one domain for a schema that carries bare metal and
containers, and buyer commands match compatibility on that identity. Changing it is
backwards-incompatible on its own, which is normally enough reason to defer — but the
listing-shape renames bump the version regardless, so the incompatibility is already
being paid for. `compute.market` follows the `introductions.market` convention the
other deployed spec already uses.

### Landing before Goal 7 rather than after

`unbacked-listing-publication` publishes a backing field into the listing shape and
adds an exact filter on it; `publish-indicative-listing-rates` publishes a rate
there. Both have deltas and task lists naming `offer_resource` paths. Renaming
afterwards would rewrite both immediately.

The cost is real and belongs in the record: this makes every Goal 7 change wait on a
rename spanning four packages and 51 files of `offer_resource`, and Goal 7 loses the
one change previously assessed as ready to implement. The trade is accepted because
the alternative is doing the rename against more code, later, with a compatibility
window that does not exist yet.

## Risks / Trade-offs

- **[A business-semantic change hides inside a large rename]** → The oracle cannot
  be "no assertion changed", because this change deliberately changes contract
  behaviour: retired names are rejected, schema identities move, CLI flags change.
  The oracle is **semantic equivalence after normalization** — an old fixture in the
  retired vocabulary and its counterpart in the settled vocabulary must produce
  equivalent capacity, publication, reservation, negotiation, and fulfillment
  effects — paired with deliberate coverage that retired boundary names are
  rejected where the cutover intends it. An assertion that changes for any other
  reason is the defect.
- **[A rename site is missed]** → A missed producer or consumer of a required claim
  field fails loudly at the first reservation. A missed *optional* published field
  fails quietly, so `listing_resource` needs the grep audit most. Renaming the
  persisted column rather than mapping it is what makes that audit trustworthy: a
  surviving retired name in storage would leave permanent hits to triage.
- **[A pre-upgrade row is missed by a backfill]** → Both backfilled payloads are
  JSON, so a missed row is not a type error and will not surface until a retry or a
  listing read. Count rows carrying the retired key after the backfill rather than
  sampling, and run the count as a cutover gate before mutations resume.
- **[Goal 7 slips further]** → Accepted, with the sequencing argument above as the
  reason. If the campaign needs to start sooner than this change can land, the
  fallback is to keep `listing_mode` alone in a narrow change and defer the rest —
  which reopens the window question.
- **[Buyer clients desynchronize from registries]** → Buyer commands declare schema
  compatibility, so a client querying a bumped registry gets a compatibility failure
  rather than wrong results. That is the mechanism working; it still means clients
  ship with registries.

## Open questions

- **Does the `listing_mode` ingestion alias have a removal date?** Deliberately
  deferred, as before: there is no fleet-wide deployment signal to gate removal on,
  since sellers self-host. Recorded here rather than prescribed in `tasks.md`.
- **Does `structured-capacity-requirements` need any of its `offering_type` item
  after this?** Expected not — the concept exists and this change collapses it — but
  that change's owner should confirm rather than have it deleted from outside.

## Migration Plan

1. Rename `listing_mode` to `listing_cardinality_mode`, retaining the ingestion
   alias. Independent of the cutover and safe to land first.
2. Retire `executor` as a synonym in documentation and in the in-flight changes that
   adopted it, leaving the action-adapter abstraction alone.
3. Quiesce authenticated mutations per the identity-contract pattern.
4. Rename `executor_kind` to `offering_mode` across the claim wire and its producers
   and consumers, including `ExecutorAdapter`'s selector, one commit per package
   boundary.
5. Rename `offer_resource` to `listing_resource` across the generic registry
   envelope, all three filter specifications, and the clients; remove the `offer`
   alias.
6. Rename `virtualization_type` to `offering_mode` in the listing shape, the
   `VirtualizationType` enum, the compute filter, and the buyer CLI flags.
7. Change the schema identity and bump every affected specification version.
8. Migrate the persisted state: the column rename under a recorded migration ID, and
   both JSON backfills, with a post-backfill count of rows still carrying a retired
   key as a gate.
9. Verify every participant reports the pinned version, then resume mutations.

Steps 3 through 9 are one coordinated cutover of storefront, sites, registries, and
buyer clients. Rollback is limited to the boundary before step 8; after migrated
state has taken effects, recovery is rolling forward rather than restoring stale
state, which is the same constraint the identity-contract pattern already carries.
