# Design: publish-shape-bounds

## Context

**What a seller states and the storefront resolves.** A stated VM listing shape, in a
pool's `listing_shapes` hint or the storefront's override, may give any quantity field a
constraint mapping in place of its scalar: `offer` is what the listing sells, and `min`
and `max` bound what an agreed shape may state (`market-composition`'s "Shape
constraints are stated inline and strictly"). Each listing's policy resolves from two
tiers, per bound: the constraints its own stated shape carries, over the storefront's
configured default, `[admissibility.defaults.vm]`. An override's shapes replace the
hint's whole and inherit none of its constraints, and a generated shape takes the
default alone (`domains/vms/listings/src/arkhai_vms_listings/listing_shapes.py`,
`resolve_vm_listing_shapes`; `storefront-publication`'s "A VM listing's admissibility
resolves per listing"). `settings.toml` ships no default.

**What a listing publishes.** Its base shape and nothing of its policy. Derivation
flattens each listing's offer into `listing_resource` under the compute family's flat
names and uses the resolved policy only to decide whether the offer may be published
(`domains/vms/listings/src/arkhai_vms_listings/reconciler.py`, `_admissible_shapes` and
`_shape_listing_resource`). The policy is held nowhere after derivation. The
configuration reference says of a range that it is "never published"
(`openspec/specs/storefront-publication/configuration.md`). A seller's constraints are
readable only in the pool's hint, the override store, the storefront's settings and the
administrator's derivation report.

**What the seller checks in a round.** For a round that carries a shape the VM seller
resolves the listing's policy again, from the pool projection it holds, the stored
override and the configured default, and refuses a shape outside it as
`shape_inadmissible`, naming each violated bound in text
(`domains/vms/storefront/src/market_storefront/services/negotiation_shapes.py`,
`check_requested_shape`). It then refuses any quantity above the advertised one as
`shape_exceeds_advertised`, in the place of a feasibility check it does not compose,
compares GPU model and region, and refuses any shape but the listing's own on a
flat-priced listing
(`domains/vms/storefront/src/market_storefront/negotiation_runtime.py`,
`prepare_requested_shape`). A quantity the advertised shape does not state offers none,
so a buyer cannot add one.

**What a buyer reads and does before opening.** The offer, the rates
(`pricing.rate_structure`), the GPU model and the region. The VM buyer applies the
advertised cap itself: `negotiate` refuses a `--shape` above the listing's, and `buy`
drops every candidate the shape exceeds from the listings its registry query returned
(`domains/vms/buyer/src/arkhai_vms_buyer/opening_shape.py`, `shape_excess`;
`buy_cli.py`). That is a local narrowing after the registry query, beside the one buyer
commands apply for settlement clauses (`buyer-orchestration`'s "Buyer normal path
consumes two DSLs"). No buyer code reads a constraint, and neither side builds a
counter-shape: `--shape` is an opening a person chooses.

**The kit.** `kit/capability-admissibility` is the only reader of a constraint. A
parsed declaration and a resolved policy are opaque values, and no operation returns a
range for a dimension independent of the rest of a shape (`market-composition`'s
"Capability shape admissibility is owned by one kit"). It reads both forms a constraint
is written in: `split_listing_shape` splits a stated shape into its base shape and a
declaration, `parse_declaration` reads a constraint-only document, and `resolve` turns
declarations into a policy. Nothing goes the other way. `capacity-shape-envelope`'s
design left that to this change: a listing discloses "its own shape in D5's inline
form, resolved against the configured default", and this change "adds the operation
that renders a resolved policy back into that form" (its D13). The VM domain package
depends on the kit, so a VM buyer installs it; the compute family's vocabulary package,
`domains/compute`, allows only the shape kit.

**How a listing-level term travels.** Each compute storefront hands core publication a
`publication_terms` mapping, which core sends as top-level listing terms without naming
any (`core/storefront/src/core_storefront/registry_publication.py`,
`publish_listing_to_registries`). `pricing` and `available_until_utc` travel that way
today. The registry stores the complete body a publication was admitted with and
serves it with the seller's signed publication (`registry-discovery`'s "Accepted
listing content is retained" and "Seller publication evidence is independently
verifiable"). The compute filter specification declares `pricing`, closed, and does not
name `available_until_utc`.

**What marketplace 0.4.0 does with a term it does not know.**

- The registry's listing schema is open at its top level and inside `listing_resource`
  (`core/registry/src/core_registry/filter-spec.yaml`). It refuses six names it owns in
  its responses and three retired ones, types every flat quantity of `listing_resource`
  as an integer, and closes `pricing`. A new top-level term is admitted, stored and
  served; a range on `listing_resource.gpu_count` is refused.
- The registry client keeps unknown keys of a listing, and the VM listing model drops
  an unknown top-level key (`domains/vms/listings/src/arkhai_vms_listings/models.py`,
  `Listing`). The bare-metal listing payload, which is `listing_resource`, refuses any
  key it does not define (`domains/bare_metal/src/arkhai_bare_metal/schema.py`,
  `BareMetalListing`).
- A buyer's query compiler reads a filter specification whose listing schema changed
  as before; it refuses a specification that declares a value type or a missing-value
  rule it does not know (`core/registry-client/src/registry_client/query.py`).

**Listings that negotiate no shape.** A bare-metal listing sells one whole machine. Its
shape is its Physical Resource's declaration, its override states no shapes, bare-metal
publication composes no admissibility, and its negotiation carries no shape
(`openspec/specs/storefront-publication/architecture.md`, "Bare-metal listing shapes").
A flat-priced VM listing prices only its own shape and refuses any other, whatever its
policy admits.

**The cap is about to move.** `negotiation-capacity-feasibility-probe` asks the site
about the claim a round would reserve and lifts the advertised-shape cap. What then
bounds a larger ask where a seller stated no maximum is that change's Q1, whose
alternatives are that the cap lifts wherever admissibility admits, or that a quantity
with no stated `max` keeps the advertised quantity as its ceiling.

## Decisions

### D1 — The constraints travel as a top-level listing term supplied through `publication_terms`

A compute listing's resolved shape constraints are one listing-level term at the top
level of the published listing, beside `pricing`. The listing's domain supplies it in
`publication_terms`; core publication, the registry client and the registry carry it as
they carry any admitted term, and none of them names a constraint.

`listing_resource` stays what it is: the capacity description, in flat names, that a
claim is built from and every dimension filter reads. Listing-level terms do not
accumulate inside it (`negotiation-driven-capacity-resize`'s design, D7), and the
registry keeps the whole admitted document, so a term outside it is stored, served and
covered by the seller's signature with no registry code.

Rejected:

- A range in place of a flat quantity, `listing_resource.gpu_count: {offer: 2, max: 8}`.
  A 0.4.0 registry refuses it, and every dimension filter, claim builder and buyer that
  reads `gpu_count` as a number breaks.
- A key added inside `listing_resource`. The bare-metal listing payload refuses a key
  it does not define, so it cannot be the family's carrier, and it puts a second
  vocabulary inside the commitment a claim is built from.
- A member of `pricing`. It is closed, and a range is not a price.
- A storefront route a buyer reads per listing. It is a second fetch for every
  candidate and an unsigned read, where the registry already holds the seller's signed
  publication.

### D2 — The term is the compute family's, VM is its only producer, and a listing that negotiates no shape publishes none

The term, its carrier and the buyer-side reader are defined once, for the compute
family: both domains publish under one registry schema and one capability schema, so a
buyer reads any compute listing's term through the same code.

VM publication is the only producer. A listing that negotiates no shape publishes no
constraints:

- **A bare-metal listing.** It sells one whole machine and its negotiation carries no
  shape, so there is nothing a buyer could ask for that a range would bound. The reason
  is stated where the difference lives, in bare-metal publication and the
  `storefront-publication` companion's "Bare-metal listing shapes"
  (`docs/guidance/repository/family-kits.md`, "Sibling domains behave alike").
- **A flat-priced VM listing.** It refuses every shape but its own, so publishing its
  policy would advertise a range its seller refuses. A buyer already reads that from
  the absence of `pricing.rate_structure`.

Rejected:

- Bare metal publishing its shape as fixed, `min` and `max` equal to the offer. It
  needs the admissibility kit composed in bare-metal publication to say what the
  offering mode already says, and the same reading would have a flat-priced VM listing
  publish a fixed range too.
- A VM-only term and reader. A second compute domain that negotiates a shape would add
  a second reader of the same form.

### D3 — The kit renders a resolved policy and stays the only reader of a constraint

`kit/capability-admissibility` gains one operation: it renders a resolved policy as a
published document in the form Q2 settles. The rendering names no tier. Read back
through the kit with the same schema, it yields a policy that answers every question
exactly as the one rendered. That round trip is the operation's contract, proven in the
kit's own suite against a schema with no compute vocabulary.

Nothing else reads or writes a constraint. Publication holds the policy as an opaque
value and passes it to the kit; a buyer passes the published term to the kit and asks
it about a shape; core, the registry client and the registry carry the term opaquely.
Disclosure is therefore not readable bounds: the published document is the form a
seller writes, and a buyer still compares no number itself.

Every caller, through the interface alone:

| Caller | What it does |
|---|---|
| VM publication | renders each listing's resolved policy when it derives the listing |
| A compute buyer | reads a listing's term through the kit and asks whether a shape is admissible, or which values one dimension may take given the rest |
| Core publication, the registry client, the registry | carry the term as data |
| A reader outside this repository | reads the term as the form the configuration reference documents for a stated listing shape |

Rejected:

- Publication walking the policy's fields to build the document. It is a second reader
  of a constraint, and a later constraint key would have to be taught to it.
- An operation returning a minimum and a maximum per dimension. It is the unconditional
  range the kit exists not to give: every caller comparing numbers encodes a box, and a
  seller's policy may later couple dimensions.

### D4 — The registry filters nothing on the term, and a buyer narrows locally

The compute filter specification declares the term in its listing schema and adds no
filter over it. A buyer narrows the listings its registry query returned by evaluating
each listing's term through the kit, as the VM buyer already narrows by the advertised
shape. The evaluation is exact, stays exact when a constraint relates two dimensions,
and leaves the kit the only reader of a constraint.

Its cost is that a query returns listings whose sellers would refuse the shape, and the
buyer discards them after fetching them. The change index records a registry filter
over constraints as unowned in Goal 2's campaign, to be revisited when that cost is
measured.

If a filter is ever added, what a listing that states no bound answers is not decided
again here. `filter-listings-by-capacity-bounds` settles that question once for the
filter grammar, and a constraint filter applies its answer by convention.

Rejected:

- A filter per quantity over the term's `min`, in today's grammar. It reads constraint
  numbers in the registry, is only a necessary condition once a coupled form exists,
  and adds a declaration per quantity and bound.
- Moving the filters into `filter-listings-by-capacity-bounds`. That change would then
  wait for this one's term, and it is another goal's work.

### D5 — The seller judges against the policy in force and pins nothing

The seller resolves a listing's policy when it evaluates a round, as it does today, and
judges the requested shape against that. The published term is a copy. A copy older
than the policy costs a buyer a refusal for admissibility and never a wrong deal, and a
change of range alone refreshes the published listing in place, since a listing's
identity is its base shape.

Rates are held to what was last published because a buyer derives money from them. No
amount is derived from a range, so nothing needs the same hold.

Rejected: pinning a thread to the constraints published when it opened. It would hold a
seller to a range it has since narrowed, for a term that prices nothing, and add a
digest to every opening.

### D6 — A buyer does not verify the term

A buyer reads the term from the registry listing and evaluates it. It does not check it
against the seller's publication evidence. The term is inside the publication body the
registry retains with the seller's signature, so it is seller-signed at no cost and a
buyer that wants to check it can; none needs to, because D5 makes a wrong copy cost one
refused opening.

Rejected: verifying it as retained pricing is verified. That check exists because a
quote derives from the rates.

### D7 — A bound the policy does not state is not published

The term states what the listing's resolved policy states and nothing else. A side of a
range no tier states is absent from it, a quantity no tier constrains carries no range,
and a listing whose policy constrains nothing publishes no term. An absent bound is not
a default and not a promise (`docs/development/ARCHITECTURE.md`, "Omission states no
commitment"). The term never says which tier supplied a bound.

One alternative of Q1 would have publication add a ceiling the policy does not hold. If
the design session chooses it, this decision is restated with it.

Rejected: publishing every quantity's range in full, with the kit's unbounded answer
written out. It turns an absence into a statement the seller did not make.

### D8 — The change is Goal 2's own, and nothing gates it

The change stays a change of its own under Goal 2: it is the buyer-facing half of a
seller saying which shapes it would sell. It depends on no other change. Every piece it
builds on is released, and the changes it meets, at the buyer's check before opening and
in the compute filter specification, are reverified against by whichever lands second.

Rejected:

- Folding it into `negotiation-capacity-feasibility-probe`. That change's work is the
  negotiation runtime and the storefront's capacity path; this one's is the kit,
  publication and the buyer's reader.
- Folding it into `filter-listings-by-capacity-bounds`. This change adds no filter
  (D4).
- Archiving it as delivered. Constraints are published nowhere.

## Open Questions

Each is decided in this change's design session.

### Q1 — What the term claims where a seller refuses a shape its policy admits

It is tied to `negotiation-capacity-feasibility-probe`'s Q1 and is settled with it.
Nothing above depends on it but D7's last paragraph.

Two listings of one pool, as their seller stated them:

```yaml
listing_shapes:
  vm:
    - gpu: { model: A100, count: { offer: 2, min: 1, max: 8 } }   # listing A
      cpu: { count: 16 }
    - gpu: { model: A100, count: 1 }                               # listing B
      cpu: { count: 8 }
```

Today the seller refuses three GPUs on listing A as `shape_exceeds_advertised`, though
its policy admits eight. The probe's Q1 decides what replaces that cap: under its (a) a
listing sells whatever its policy admits and its site can serve; under its (b) a
quantity with no stated `max` keeps the advertised quantity as its ceiling.

Each alternative below is given for the GPU count, with no configured default.

- (a) The term is the policy as resolved. Listing A publishes `min: 1, max: 8` and
  listing B publishes no term, now and after the probe. The term says what the seller
  would sell from an empty pool and is one of the seller's checks; until the cap lifts,
  A's maximum cannot be bought, and a buyer keeps applying the cap beside the term.
- (b) The term is what the seller would accept. Until the cap lifts, listing A
  publishes `max: 2` and listing B `max: 1`; afterwards A publishes `max: 8`, and B
  publishes `max: 1` under the probe's (b) and nothing under its (a). A reader needs no
  second rule. Publication must then state the ceiling as a constraint, which it cannot
  for a quantity the listing omits, and the probe change must change what is published.
- (c) The change lands after the probe, so the term and the seller's answer never
  differ. It adds an ordering that is not a technical gate.

Under the probe's (b), where that ceiling lives decides this question. As the lowest
tier of a listing's resolved policy it is published with the rest, and (a) and (b) here
are one answer. As a separate refusal in the round it is in no policy, and a buyer
needs a second rule beside the kit's answer.

Recommended: (a), with the published requirement saying that admitting a shape says
nothing about whether the site can serve it, as the admissibility model already does.
It would move to (c) if the probe is expected in the same release, and to (b) if the
term must be all a buyer outside this repository needs.

### Q2 — What the term holds

A listing as a 0.4.0 storefront publishes it:

```yaml
listing_id: 3f6c1c0e9b7d4a52
storefront_url: https://storefront.example.com
listing_resource:
  pool_id: vm-california
  region: us-west
  offering_mode: vm
  capacity_backing: backed
  sla: 99.0
  gpu_model: A100
  gpu_count: 2
  vcpu_count: 16
pricing:
  rate_structure:
    gpu: [{ asset: USD, rate: "1.20", per: hour }]
    cpu: [{ asset: USD, rate: "0.04", per: hour }]
max_duration_seconds: 604800
# settlement_options and demands elided
```

Its seller stated `gpu.count` as `{offer: 2, min: 1, max: 8}` and constrained memory,
which the listing does not offer, to at most 512 GiB. The term, under each alternative:

```yaml
# (a) the listing's own shape in the inline form
listing_shape:
  gpu:    { model: A100, count: { offer: 2, min: 1, max: 8 } }
  cpu:    { count: 16 }
  memory: { gib: { max: 512 } }

# (b) the constraints alone, in the configured default's syntax
shape_constraints:
  gpu:    { count: { min: 1, max: 8 } }
  memory: { gib: { max: 512 } }
```

- (a) is the form `capacity-shape-envelope`'s design chose for disclosure (its D13):
  each range reads beside its offer, as a seller wrote it. A buyer reads it with the
  kit's existing split and resolve. It states the offer twice, flat in
  `listing_resource` and family-grouped in the term, so the two could disagree.
  `listing_resource` stays the commitment; publication builds both from one resolved
  shape, and a buyer treats a term whose base shape is not `listing_resource`'s as
  unknown.
- (b) states the commitment once and is read with the kit's existing declaration
  parser. The range sits apart from the offer it surrounds.

A 0.4.0 registry admits, stores and serves either as a property its schema does not
name. A 0.4.0 buyer drops either and negotiates as it does today. A buyer whose kit
does not know a constraint key in the term, one added after it was built, is told so by
the kit, treats the term as unknown and relies on refusals.

Recommended: (a). It would move to (b) if one statement of the offer matters more than
reading a range beside it.

### Q3 — What a buyer command does with the term

- **`negotiate`** refuses a `--shape` the listing's term does not admit, naming the
  kit's problems, before it opens, where today it refuses only a shape above the
  advertised one.
- **`buy`** drops the candidates whose terms do not admit the requested shape from the
  listings its query returned, and reports them, as it does for the advertised cap
  (D4).
- **Display.** A listing is shown with its term in the form published. Whether a
  command also answers "what may I ask of this listing", from the kit's values query,
  is open.
- **A term the buyer cannot read**, or none, is unknown, not a refusal: the buyer opens
  and relies on the seller's answer.
- **Where the family's reader lives** (D2). In the compute family's vocabulary package,
  `domains/compute`, whose allowlist would gain the admissibility kit, or in a
  compute-family package of its own if the vocabulary package is to go on depending on
  the shape kit alone. Bare metal has no listing to read a term from today.
- **The cap check** stays, changes or goes as Q1 and the probe's Q1 settle.

Recommended: the first four as written, the reader in `domains/compute` so a second
compute domain adds none, and no values query in this change.

### Q4 — How the compute schema declares the term

The declaration under Q2 (a), in the compute filter specification's listing schema:

```yaml
# (a) declared; constraint keys open
listing_shape:
  type: object
  additionalProperties:            # a family
    type: object
    additionalProperties:          # a field: a scalar, or a constraint mapping
      anyOf:
        - { type: [integer, string] }
        - { type: object }

# (b) as (a), with the constraint mapping closed on today's keys, as `pricing` is closed
        - type: object
          additionalProperties: false
          minProperties: 1
          properties:
            offer: { type: integer, minimum: 1 }
            min:   { type: integer, minimum: 1 }
            max:   { type: integer, minimum: 1 }
```

- (a) A registry refuses a term that is not a shape and admits a constraint key it has
  never seen. The kit is what fails closed on a key, at the storefront and the buyer.
- (b) A misspelt key is refused at publication. A registry then refuses a later key,
  such as a ratio, until its specification is updated, so registries upgrade before
  storefronts publish one.
- (c) Not declared, as `available_until_utc` is today. Nothing is edited, and a term of
  any structure is stored.

The schema names no family under any of them, as `pricing.rate_structure` names none.

Recommended: (a). A domain adds a listing term by declaring it in its filter
specification (`openspec/specs/registry-discovery/architecture.md`, "Retained
publication documents"), and the constraint vocabulary is the kit's to close.

### Q5 — Where the storefront keeps the term between derivation and publication

- (a) Recorded on the listing record as a term of sale, in a column of its own, as
  `rate_structure` and `available_until_utc` are. It refreshes in place, is outside the
  listing's identity and every digest, and registry repair republishes it from the
  record. One additive migration.
- (b) Rendered when the publication candidate is built, from the projection the
  storefront holds. No column, but a repair or a reopen then depends on a held
  projection, and a listing held through a site outage would republish without its
  term.

Recommended: (a).

### Q6 — Whether a refusal carries the kit's problems as data

`capacity-shape-envelope`'s design gave `negotiation-driven-capacity-resize` an input:
an admissibility refusal carries the kit's problems, their paths and codes, so a buyer
can counter. It landed as text. A refusal is the other way a buyer learns a bound, and
the only way for a listing published before this change.

- (a) This change adds the structured problems to the refusal.
- (b) A row in the change index under Goal 2's unowned work, revisited when a buyer
  tool builds counter-shapes from refusals.

Recommended: (b). It is `negotiation-protocol` work, on the wire a negotiation reply
travels, and a buyer that reads the published term has what the refusal would tell it.
The row is added when the design session takes this answer.

### Q7 — What the term and its contents are called

- **The wire name.** `listing_shape` under Q2 (a): it is the architecture's name for
  what one listing offers in the family-grouped form
  (`docs/development/ARCHITECTURE.md`, "One name per concept"). The compute filter
  specification already uses that key for the listing's JSON Schema, in its own file
  and not on the wire. `shape_constraints` under Q2 (b).
- **The words in requirements.** The specifications say "constraints", "admissibility"
  and "resolved policy". "Bounds" names the two capacity bounds of a listing,
  `max_duration_seconds` and `available_until_utc`, and is not used for a range.
- **The change's name** stays: the roadmap and archived designs cite it.

Recommended: as written.

### Q8 — Provisional answers

Each follows from something settled or from the nearest precedent, and is confirmed or
moved in the design session.

- **The requirement this change adds to `storefront-publication`**, its delta written
  once Q1 and Q2 settle: "A compute listing publishes its resolved shape constraints".
  It states D1, D2, D5 and D7. The withdrawn delta's two scenarios return under it: a
  buyer evaluates a candidate shape against a listing's term before proposing it, and a
  shape admissible under a stale copy is refused for admissibility.
- **Requirements this change modifies.** `storefront-publication`'s "VM publication
  never advertises an inadmissible offer", whose scenario "Constraints change after
  publication" gains that the published term is refreshed in place;
  `market-composition`'s "Capability shape admissibility is owned by one kit", which
  gains the render operation and its round trip (D3). No `negotiation-protocol`
  requirement changes unless Q6 settles on (a).
- **The requirement added to `registry-discovery`**, beside "The compute schema carries
  a listing's asking rate": the compute schema declares the term and no filter reads
  it (D4, Q4).
- **`buyer-orchestration`.** If Q3 gives the buyer's evaluation a requirement, it sits
  beside "The match cap counts candidates the buyer can settle with".
- **The kit's version.** A new public operation is a minor version, from 0.1.1.
- **Companion and reference text.** The `storefront-publication` companion's "Shape
  constraints" and "Bare-metal listing shapes"; the `market-composition` companion's
  "Capability shape admissibility"; the configuration reference's sentence that a range
  is never published; `docs/development/ARCHITECTURE.md`, "Discovery and negotiation".
- **Test levels.** The render operation, its round trip and its neutrality are unit
  tests in the kit. Derivation, the refresh in place on a changed range, the listings
  that publish no term and registry repair are VM storefront application integration.
  Retention of the term and a listing without one are registry application
  integration. The buyer's evaluation is a unit test of the reader and one row in the
  VM lane, beside its smaller-shape purchase, on mock provisioning.
- **Hardware.** Nothing here needs a GPU, and nothing touches the Ansible layer or how
  an adapter executes it, so no real-host run is owed.
- **Documents.** `docs/operator-handbook.md`, where it describes a pool's
  `listing_shapes`, says a stated range is published; `docs/buyer-quickstart.md` says
  how a buyer reads one.

### Q9 — Implementation cadence

Recommended: one round, one session. The kit's operation, derivation and publication,
the schema's declaration, the buyer's reader and the documents are one slice: a
published term nobody reads is not useful, and the reader has nothing to read without
it.

## Verification

Provisional levels are in Q8. Every lane row is mock-provisioning evidence.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| D1 a top-level listing term through `publication_terms` | `openspec/specs/storefront-publication/spec.md` and `architecture.md`, "Shape constraints"; `openspec/specs/registry-discovery/architecture.md`, "Retained publication documents" |
| D2 the compute family's term, VM its only producer | `openspec/specs/storefront-publication/spec.md` and `architecture.md`, "Bare-metal listing shapes" and "Shape constraints" |
| D3 the kit renders, and stays the only reader | `openspec/specs/market-composition/spec.md` and `architecture.md`, "Capability shape admissibility" |
| D4 no registry filter; the buyer narrows locally | `openspec/specs/registry-discovery/spec.md` and `architecture.md`; `docs/buyer-quickstart.md` |
| D5 the policy in force, nothing pinned | `openspec/specs/storefront-publication/spec.md`; `openspec/specs/negotiation-protocol/architecture.md`, "Evaluation order" |
| D6 no verification of the term | `openspec/specs/registry-discovery/architecture.md`, "Seller publication evidence" |
| D7 an unstated bound is not published | `openspec/specs/storefront-publication/spec.md`; `openspec/specs/storefront-publication/configuration.md` |
| D8 Goal 2's own change, ungated | `docs/development/ROADMAP.md`, Goal 2 |
