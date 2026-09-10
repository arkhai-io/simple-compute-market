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

### `executor` is retired rather than reassigned

An earlier draft proposed keeping `executor` and settling it on the machine, since
`capacity-resource-administration` already used it that way. That was unnecessary.
`host` is already the word for the machine, and once `executor_kind` becomes
`offering_mode` the term has no remaining sense to carry.

The tell that `executor` was never about machines: `executor_kind`'s values include
`api_credits`, which has no machine anywhere. Reading the field as an executor is
what made a third sense look necessary.

A proposal to make `executor` the pool's delivery handler was considered and
rejected. `ARCHITECTURE.md`'s five uses of the word are all the offering-mode sense
— "defaults an executor mode", "a default executor", "other executor kinds" — while
`provider` has 39 uses as the handler. Reassigning the word would invert the
dominant usage, require renaming both other senses, and leave no word for the
machine.

So: **offering mode** for what is sold, **host** for the machine, **provider** for
the handler that delivers on it.

### No compatibility window, because the window is closing

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

- **[A behavioural change hides inside a large rename]** → The change asserts no
  behaviour change, which makes any behavioural diff a defect rather than a
  judgement call. Verify by running the full suite before and after with no expected
  assertion changes, and treat a changed assertion as a signal to stop.
- **[A rename site is missed on the wire]** → A missed producer or consumer of a
  required claim field fails loudly at the first reservation, which is the
  compatibility argument working in reverse. A missed *optional* published field
  fails quietly, so `listing_resource` and the offering-mode field need the grep
  audit that `executor_kind` does not.
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

1. Rename `executor_kind` to `offering_mode` across the claim wire and its
   producers and consumers, in one commit per package boundary.
2. Rename `offer_resource` to `listing_resource` and remove the `offer` alias.
3. Rename `virtualization_type` to `offering_mode` in the listing shape, the enum,
   the filter, and the buyer CLI flags.
4. Change the schema identity and bump both versions.
5. Rename `listing_mode` to `listing_cardinality_mode`, retaining the ingestion
   alias.
6. Retire `executor` from documentation and from the in-flight changes that adopted
   it.

Steps 1 through 4 are a coordinated deploy of storefront, sites, registries, and
buyer clients. Rollback is a coordinated rollback of the same set; no data migration
is involved, so a rollback loses nothing.
