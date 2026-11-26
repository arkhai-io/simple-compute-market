# A payout hold the seller chooses

## Why

A seller is paid nothing while a deal runs. The payments kit derives one hold for every
part of every mandate, `{afterStop: <dispute window>}`
(`kit/arkhai-payments/src/market_arkhai_payments/mandates.py`): a rate part's earnings
stay held until the part stops plus the dispute window, and a prepaid part's until the
term ends plus the window. The payments service then pays out a further delay of its own
after release. On-demand and spot VM are a supported configuration in marketplace 0.4.0,
and such a deal's maximum term may be days or years away, so its seller may wait that
long for the first payment (`docs/seller-quickstart.md`, "Payout").

The seller is rarely the party that carries that wait. A seller selling a site's
capacity pays the site by an arrangement this repository does not define, and held
earnings are usually the site's cost. The hold term settles one thing between the
parties to the deal: when the seller receives its money.

The hold is also what a buyer's remedies reach. A case protects only money still held,
and the premature-stop penalty, for a seller end the terms do not entitle, is collectible
only from the seller's earnings still held
(`openspec/specs/deal-lifecycle/architecture.md`, "External authorities"). Releasing
money earlier shortens what both can reach, so the hold and what the buyer is told about
it are designed together.

Two facts bound the design:

- The vendored payments contract offers exactly two hold shapes: `afterStop`, a duration
  after the part stops, and `for`, a duration after each amount is earned
  (`kit/arkhai-payments/schema/payments.schema.json`). It has no event that releases
  held money early. A `for` hold is the only way it can pay a seller during a deal.
- The vendored mediation contract expects `afterStop` on every part of a mandate, and
  its published vectors report a `for` hold as a mismatch
  (`kit/arkhai-mediation/src/market_arkhai_mediation/contract_data/mediation.vectors.json`,
  `mismatches-are-evidence`). The dispute authority rules without a person only under a
  clean mapping, so a deal under a `for` hold would lose its mechanical remedies on the
  contract as vendored.

## What Changes

- **An option may state a hold shape.** A codec-owned lifecycle term, in the Agreement's
  bytes and the option's ID, chosen by the seller per option. An option stating none has
  today's hold, so every published option keeps its ID and meaning.
- **The shapes are an open set.** A shape is added, never redefined; adding one changes
  no existing option. A reader that does not know an option's stated shape fails closed:
  a buyer drops the option, publication refuses to emit it, the registry matches it for
  no lifecycle filter, and the dispute authority reads its terms as unreadable. The
  mandate derivation, the buyer's display, the query projection, the dispute authority's
  mapping rule and the capability check each have one case per shape.
- **The first shape, and the only one built here: after earning.** Each amount a rate
  part earns is released the option's dispute window after it is earned; the rate part's
  hold is `for` the dispute window. The buyer keeps the full window to act on every
  period, a case protects what is still held, and the premature-stop penalty is
  collectible from at most the earnings of the trailing window.
- **The buyer's exact check and display.** The buyer re-derives the mandate under the
  stated shape and refuses any difference, as for every other field. Before approval it
  is shown until when each charge stays reversible and what a case and the penalty can
  still reach.
- **A query projection** of the stated shape, in a buyer's settlement clauses and both
  registry filter specifications.
- **The dispute authority's mapping.** The design states what SCM needs of the published
  mediation contract: its mapping reads the stated shape, expects the matching hold per
  part, and reads an unknown shape as unreadable terms. Implementation waits until a
  publication carrying that is vendored under `kit/arkhai-mediation`. The lane's
  mediation double then checks the expected hold as the authority does.
- **The payments kit's contract note** is corrected to the maximum hold extension the
  kit derives, and an unused constant that contradicts it is removed.

What the design leaves open is in its "Open Questions": how the term is spelled, which
parts the first shape applies to, what an option may say about a penalty its hold cannot
back, whether the default buyer refuses a stated shape, the display's wording, how SCM
knows an authority maps a shape, the projection's form, and where the seller states it.

## Capabilities

### Modified Capabilities

- `deal-lifecycle`: the hold-shape term, the open set and what an unknown shape does;
  "The dispute window sets the earliest payout" no longer holds for every amount.
- `settlement-servicing`: the mandate's hold derived per shape.
- `settlement-configuration`: the seller's key, and the dispute authority's advertised
  shapes if the design settles that.
- `buyer-orchestration`: the display per shape, and the default buyer's answer to a
  stated shape.
- `cli-query-language`: the projection among the common lifecycle fields.
- `test-compatibility`: a lane scenario, and the mediation double's mapping check.
- `storefront-publication`: only if the design settles a publication report or refusal
  for a penalty the hold cannot back.

### New Capabilities

None.

## Non-Goals

- Any shape but the first. A hold on a capped amount with everything above it released
  as it is earned, and release on calendar periods, are expected later; each needs a
  payments contract revision first (design D2).
- A hold shorter than the option's dispute window, and a duration the seller chooses
  freely (D4).
- A seller-funded bond, the codec's reserved `bond` term.
- The payments service's payout delay after release, which is the service's own.
- What a seller owes its site and when.
- Hosted qualification of the shape, which is
  `activate-per-period-compute-servicing`'s.

## Dependencies and Related Changes

- **An external gate, not a change.** Implementation waits for a published mediation
  contract that maps a stated hold shape, vendored under `kit/arkhai-mediation` with its
  vectors (D5). The design proceeds without it.
- **Builds on**, all archived: `agreed-evidence-and-early-termination` (the lifecycle
  codec, per-part holds and the dispute authority), `negotiate-open-ended-compute-terms`
  (the penalty, its default and the default buyer's refusals),
  `spot-deals-through-arkhai-payments` (the rate mandate's derivation and the buyer's
  exact check), `serve-running-rate-deals` (the penalty's collectible bound on the
  buyer's display), `add-arkhai-payments-lane-double` (both lane doubles) and
  `switch-on-hosted-per-period-vm` (the seller's and buyer's documentation of today's
  hold).
- `discover-open-ended-compute-listings` modifies the same `cli-query-language`
  requirement, "Common settlement fields include the lifecycle projections". Whichever
  lands second writes its delta against the other's text. A class is read from the
  early-termination entitlements alone, so the hold shape is no part of a class.
- `filter-listings-by-capacity-bounds` owns the registry's bound filters. This change
  adds a lifecycle projection, which needs nothing of the filter grammar that change
  extends.
- `activate-per-period-compute-servicing` depends on this change and qualifies hosted
  whatever shape it offers.

## Impact

`kit/deal-lifecycle` (the term, the capability check, the projection),
`kit/arkhai-payments` (the derivation, the publication input, its contract note and
README), `kit/arkhai-mediation` (the vendored contract and generated models),
`kit/settlement-runtime` (the display, and publication if the design adds a report),
`core/registry` (a row in each filter specification), `tools/mediation-lane-double` (the
mapping check), the VM storefront's settlement evidence, which records a `for` hold as
running from approval, the end-to-end lanes, `docs/seller-quickstart.md` and
`docs/buyer-quickstart.md`.

Compatibility is owed to `marketplace-v0.4.0`, the newest release tag, which carries
every form below as it stands on the development branch.

- **Options and Agreements.** An option stating no shape keeps its bytes, its ID and its
  mandate. An Agreement accepted under 0.4.0 states none and derives the mandate it
  always did. No stored record changes form and nothing migrates.
- **A 0.4.0 buyer** cannot decode an option stating a shape and drops it before its
  clauses run, keeping the listing's other options.
- **A 0.4.0 registry** stores and serves such an option and matches it for no lifecycle
  filter. It does not offer the new projection as a filter.
- **A 0.4.0 storefront** refuses a publication clause carrying the new key, so it
  publishes no stated shape.
- **A dispute authority on the mediation contract vendored today** ignores the term and
  reports the hold as a mismatch, which is why implementation waits (D5).
- **The registry's filter specification** gains a filter. Under the projection the
  design recommends, its value type and operator are ones released buyers already know,
  so their other queries keep working.

No compatibility path is built: every released reader fails closed, and
`docs/guidance/repository/package-versions.md`, "Compatibility is owed to what a release
has shipped", owes a released buyer nothing against a later storefront.

## Permanent documentation impact

- [ ] `docs/development/ARCHITECTURE.md`
- [x] Existing subsystem specification: the capabilities above.
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

- D1: `openspec/specs/deal-lifecycle/spec.md` and its companion, "Parts and terms";
  `openspec/specs/settlement-configuration/configuration.md` and
  `docs/seller-quickstart.md`, "Payout", for the seller's choice.
- D2: `openspec/specs/deal-lifecycle/spec.md` and its companion, "Parts and terms", for
  the open set and the fail-closed rule.
- D3: `openspec/specs/deal-lifecycle/architecture.md`, "Parts and terms", for the
  per-shape cases; `openspec/specs/cli-query-language/spec.md` for the projection.
- D4: `openspec/specs/settlement-servicing/spec.md` and its companion for the
  derivation; `openspec/specs/buyer-orchestration/spec.md` and its companion,
  `docs/buyer-quickstart.md` and `kit/arkhai-payments/README.md` for what the shape
  changes for a buyer and a seller.
- D5: `openspec/specs/deal-lifecycle/architecture.md`, "External authorities";
  `openspec/specs/test-compatibility/spec.md` and its companion for the mediation
  double's mapping check and the lane scenario.
- D6: no permanent destination — the correction is made in
  `kit/arkhai-payments/schema/SOURCE.md` itself.
