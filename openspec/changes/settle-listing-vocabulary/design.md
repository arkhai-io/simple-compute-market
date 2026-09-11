# Design — settle the listing vocabulary

## Context

This change began as a rename of one projected pool hint, `listing_mode`, whose
name did not state its scope. Reviewing that name against its neighbours turned up
a wider problem: the marketplace has four names for the offering mode, three
meanings for `offer`, and three meanings for `executor`. Each was individually
survivable and each had a plausible local history, which is how a codebase reaches
four names for one value.

## Goals / Non-Goals

**Goals.** One name per concept. Land before the changes that would otherwise add
fields under the old names.

Business semantics do not change. Observable contract behaviour does, deliberately:
retired names are rejected, schema identities and versions move, CLI flags change.
"No behaviour change" is therefore not this change's validation oracle — see
Risks / Trade-offs for the one that is.

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

#### The rule is about the head noun, not the prefix

`executor_` appears in names that are not synonym uses and do not move. Read them as
possessives and the distinction is mechanical:

| Name | Reading | Disposition |
|---|---|---|
| `executor_kind` | *the kind of executor* — the kind **is** the mode, so no possessive reading rescues it | Renamed to `offering_mode` |
| `executor_ref` | *the executor's reference* — where the action-dispatch abstraction locates what it acts on | Retained |
| `executor_target` | *the target of an executor action* | Retained |
| `ExecutorActionEnvelope` | *an envelope for an executor action* | Retained |

An action dispatcher legitimately has targets, references, and actions. In those
compounds `executor` carries exactly the action-dispatch sense this change preserves,
so retaining them is not a deferral — there is nothing left to retire in them.

State this positively wherever the "nothing else" rule is written down, because the
bare rule reads as covering the compounds: **`executor_`-prefixed compounds naming
the abstraction's own targets, references, or actions retain the name, since
`executor` carries its action-dispatch sense in them. What is retired is `executor`
as the head noun for the mode, the machine, or the handler.** Without that sentence a
reader applying the rule literally would rename `CapacityReservation.executor_target`
and `executor_ref` — roughly 300 further sites across `kit/site`, both provisioning
adapters, `ExecutorLeaseService`, and the bare-metal lease and release paths — on the
strength of a prefix match.

The same sentence is what makes the grep audit meetable. Auditing `executor` as a
prefix produces hits that are correct by this rule and must be dismissed one at a
time; auditing the full identifiers `executor_kind`, `EXECUTOR_KIND_CLAIM_KEY`, and
`VM_EXECUTOR_KIND` produces an assertion that can actually reach zero.

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

| Persisted item | Database | Strategy |
|---|---|---|
| `capacity_reservations.executor_kind` column | Compute provisioning service | Column rename via the versioned migration framework — `_add_column_if_missing`, backfill, `_drop_columns_via_table_rebuild`, recorded under a migration ID |
| `listings.offer_resource` column | Registry | Column rename via a new Alembic revision after `017_publisher_replay_leases` |
| `listings.offer_resource` column | Storefront (shared by both compute domains) | Column rename via a new `core_storefront.sqlite_migrations` migration |
| `settlement_records.scheduling_requirements` `Column(JSON)` | Compute provisioning service | Backfill the `executor_kind` key inside the payload |
| `virtualization_type` key nested inside the storefront listing payload | Storefront | Backfill the key inside the payload |

**Three of these are column renames, not backfills.** An earlier version of this
matrix described the storefront and registry listing shapes as "`offer_resource`
JSON" to be backfilled. That misread both: `core/registry/src/db/models.py` declares
`offer_resource = Column(JSON, nullable=False)` and
`core/storefront/src/core_storefront/sqlite_client.py` declares `offer_resource TEXT
NOT NULL` in the `listings` DDL. In both, `offer_resource` is the *column name* and
the JSON is its content — a row backfill does nothing to a column name. Each needs
the same expand/backfill/rebuild treatment as the reservation column, in its own
database and its own migration framework.

So the shape is three column renames across three databases and two genuine payload
backfills. The payload backfills are the `executor_kind` key inside
`scheduling_requirements`, and the `virtualization_type` key nested inside the
storefront listing payload — the latter written today by the bare-metal storefront's
own `_migrate_common_domain_bindings`, which sets
`offer_resource["virtualization_type"] = "bare_metal"`.

Each database has an existing versioned framework, so none of this needs new
machinery: `Migration("YYYYMMDD_NNN_…", fn)` in the compute provisioning service
(latest `20260901_001`), `Migration` in `core_storefront.sqlite_migrations` (latest
`20260815_001`, with bare metal appending its own through `_domain_migrations`), and
Alembic in the registry (latest `017`). The storefront `listings` table is
core-owned and shared by both compute storefronts, so its rename belongs to the
domain-neutral migration set rather than to either domain.

`migrate-registry-to-postgres` also rewrites registry persistence. It is blocked on
external infrastructure and on step 2 of its own chain, so there is no ordering
conflict to resolve here; the requirement is simply that whenever that chain lands it
targets the renamed column, not `offer_resource`.

**The column renames are a deliberate choice against the cheaper option.** A column
name is internal storage rather than a contract, so mapping each at the boundary and
leaving the columns alone would have worked. They are renamed anyway because the
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

### The cardinality hint's derived names move with it, including the status field

The hint is not only a policy-tag key. The name propagates into a module
(`domains/vms/listings/listing_mode.py`), a resolver (`resolve_vm_listing_mode`), a
kit reader (`raw_listing_mode`, `LISTING_MODE_POLICY_TAG`), two reconciler row keys
(`listing_mode` and `listing_mode_explanation`), and one HTTP response field —
`listing_mode_explanations` on `GET /api/v1/system/status`, modelled in
`core/storefront/models/system_models.py` and read back through
`core/storefront-client`.

All of them move. The resolver becomes `resolve_vm_listing_cardinality_mode`, the
module is renamed to match, and the response field becomes
`listing_cardinality_mode_explanations`.

**The status field looked like it added a buyer boundary to the cutover, and does
not.** `/api/v1/system/status` is admin-gated in both compute domains: bare metal
calls `_admin(...)` on the route, and the VM storefront's admin-identity and
service-peer middleware both special-case that exact path. `core/storefront-client`
is an operator and peer client for it, not a buyer client. So renaming the field
moves an operator surface that already ships with the service it describes, which
this change's deployment posture already assumes — it does not extend the cutover to
buyers.

Keeping the field would have been the alternative. Rejected: it would leave a retired
name on a live wire, explaining fallbacks for a key now called
`listing_cardinality_mode`, in the one place operators actually read the
explanation. That is precisely the several-names-for-one-thing condition this change
exists to end, preserved at the surface where it would confuse the most.

The deprecated *ingestion* alias is unaffected by this. It applies to the projected
policy tag a site emits, which is the only key an unupgraded peer can send.

### The provisioning contract wire moves with its selector

`provisioning/compute/src/compute_provisioning/contracts.py` carries `executor_kind`
on seven versioned models — `ExecutorActionEnvelope`, `JobAccepted`,
`CredentialEnvelope`, `ResultEnvelope`, `ProvisioningJob`, `LeaseRegistration`, and
`LifecycleEvent`. An earlier version of this plan named only "both provisioning
adapters" and `ExecutorAdapter`'s selector attribute, leaving whether this wire moves
unstated.

It moves. Renaming the adapter's selector while leaving the field that carries the
selected value would put `offering_mode` on one side of the wire and `executor_kind`
on the other — the same one-concept-two-names condition that motivated the change,
reintroduced inside the subsystem being fixed. Carrying a field rename as a version
bump is what a versioned contract is for: `VersionedContractModel`'s
`contract_version` is this file's own compatibility axis, and
`compute-provisioning-contract` already requires that unsupported major versions be
rejected with actionable version information rather than coerced.

This adds a third service boundary to the cutover — storefront to provisioning
service — and a delta against
`openspec/specs/compute-provisioning-contract/spec.md`, which was missing from the
affected-capability inventory. `executor_target` on `LeaseRegistration` stays, per
the compound rule above.

### Four smaller dispositions

**`offer_resource_type` is dropped, not renamed.** `ValidatePublishResponse` carries a
cosmetic resource-type tag derived by sniffing the payload for `gpu_model` or
`token`. Renaming it mechanically yields `listing_resource_type`, preserving a field
whose own docstring already says it exists only for client back-compat and is meant
to be dropped. Dropping it is cheaper and removes that docstring — which names a
change ID and is an existing comment-hygiene violation — from a file this change
already edits. Note it is a different axis from the offering mode and never was a
fourth name for it.

**Client distributions take a minor version bump.** `arkhai-core-registry-client`
(0.11.0), `arkhai-core-storefront-client` (0.17.0), and `arkhai-kit-site-client`
(0.2.0) all change public surface — renamed attributes, renamed response fields, a
dropped field. Callers must not resolve a pre-rename client against a post-rename
service, and the version is the only signal that carries that.

**`ListingRequest.offer` and `ListingSummary.offer` are renamed to
`listing_resource`.** These are Python attributes holding the seller's published
shape, distinct from the `d.get("offer")` ingestion alias removed separately.
`ListingRequest.to_dict()` already emits `"offer_resource": self.offer`, so the
attribute never reaches the wire under this spelling — and `ValidatePublishRequest`
in the same module already spells the same concept `offer_resource`, so the module
contradicts itself today. This is the clearest case in the change: `offer` returning
to mean a negotiation message is a stated goal, and an attribute named `offer` that
holds a listing is the collision itself.

**The offering-mode term has precedent in the code already.** `kit/site`'s ledger
defines and exports `UndeclaredOfferingModeError`, and `kit/resource-pools` exports
`pool_delivers_offering_mode` over `deliverable_modes`, whose module docstring calls
its members "opaque offering-mode names". `offering_mode` is therefore the name
already in use at the authority layer, not a new coinage imposed on it — which is
what makes it the right target rather than one of the four names being retired. The
`VirtualizationType` enum becomes `OfferingMode`; no class by that name exists today,
since the kit treats modes as opaque strings.

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
  persisted columns rather than mapping them is what makes that audit trustworthy: a
  surviving retired name in storage would leave permanent hits to triage.
- **[The grep audit is run on prefixes and cannot reach zero]** → Match full
  identifiers, not prefixes. `listing_mode` is a substring of `listing_model`, so a
  prefix search reports `test_listing_model_capacity_identity.py` and every listing
  model as a hit; `offer` is a substring of both `offer_resource` and `offering_mode`,
  so searching it reports the new vocabulary as if it were the old. And `executor` as
  a prefix reports the compounds the rule above deliberately retains. An audit whose
  expected result is "zero after dismissing a list of known false positives" is not
  an audit, so the retired-name list is the full identifiers.
- **[A pre-upgrade row is missed by a backfill]** → Both backfilled payloads are
  JSON, so a missed row is not a type error and will not surface until a retry or a
  listing read. Count rows carrying the retired key after the backfill rather than
  sampling, and run the count as a cutover gate before mutations resume. The three
  column renames carry the opposite risk profile: a missed column rename fails at
  open rather than silently, which is why only the payload backfills need the count
  gate.
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

### Closed during design review

Recorded because each was raised against a document that did not answer it, and a
later reader who finds the same evidence should find the decision rather than reopen
it.

- **Do `executor_target` and `executor_ref` move?** No, and not as a deferral. They
  are compounds in which `executor` keeps its retained action-dispatch sense. The
  rule is now stated positively in `physical-provisioning`.
- **Are the storefront and registry listing shapes backfills?** No — both are column
  names. Three column renames, not one.
- **Does the cardinality hint's derived family move, including the status field?**
  Yes, all of it. The status field is admin-gated, so no buyer boundary joins the
  cutover.
- **Does the provisioning contract wire move?** Yes, under a contract-version bump,
  with a `compute-provisioning-contract` delta that was missing from the
  affected-capability inventory.
- **Is `offer_resource_type` renamed?** Dropped.
- **Does `structured-capacity-requirements` need any of its `offering_type` item
  after this?** Expected not — the concept exists and this change collapses it — but
  that change's owner should confirm rather than have it deleted from outside.

## Migration Plan

1. Rename `listing_mode` to `listing_cardinality_mode` — the policy tag, the kit
   reader, the VM resolver and its module, the reconciler row keys, and the
   `listing_cardinality_mode_explanations` status field — retaining the ingestion
   alias. Independent of the cutover and safe to land first.
2. Retire `executor` as a head noun in documentation and in the in-flight changes
   that adopted it, leaving the action-dispatch abstraction and its `executor_`
   compounds alone.
3. Quiesce authenticated mutations per the identity-contract pattern.
4. Rename `executor_kind` to `offering_mode` across the claim wire and its producers
   and consumers, including `ExecutorAdapter`'s selector and the seven versioned
   provisioning contract models, one commit per package boundary.
5. Rename `offer_resource` to `listing_resource` across the generic registry
   envelope, all three filter specifications, and the clients; rename the
   `ListingRequest`/`ListingSummary` attributes; remove the `offer` alias and drop
   `offer_resource_type`.
6. Rename `virtualization_type` to `offering_mode` in the listing shape, the
   `VirtualizationType` enum — which becomes `OfferingMode` — the compute filter, and
   the buyer CLI flags.
7. Change the schema identity, bump every affected specification version, bump the
   provisioning `contract_version`, and bump the three client distributions.
8. Migrate the persisted state: three column renames under recorded migration IDs in
   their three frameworks, and both payload backfills, with a post-backfill count of
   rows still carrying a retired key as a gate.
9. Verify every participant reports the pinned version, then resume mutations.

Steps 3 through 9 are one coordinated cutover of storefront, sites, registries, the
provisioning service, and buyer clients. Rollback is limited to the boundary before
step 8; after migrated state has taken effects, recovery is rolling forward rather
than restoring stale state, which is the same constraint the identity-contract
pattern already carries.
