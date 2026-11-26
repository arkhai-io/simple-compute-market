# Design: offer-a-seller-chosen-payout-hold

## Context

**What a mandate holds today.** The payments kit derives one hold for every part of
every mandate, once and rate alike: `{afterStop: <the option's dispute window>}`
(`kit/arkhai-payments/src/market_arkhai_payments/mandates.py`, `derive_part_terms`).
A rate part's earnings therefore stay held until the part stops plus the dispute
window; a prepaid `once` part's until the Agreement's term end plus the window; a
setup part's until the Agreement start, clamped to approval, plus the window. The
buyer derives the same mandate and refuses any difference before approving it
(`check`, in the same module). A seller receives nothing while a deal runs. The seller
quickstart says so (`docs/seller-quickstart.md`, "Payout").

**The payments contract's hold shapes.** The vendored payments contract offers exactly
two (`kit/arkhai-payments/schema/payments.schema.json`, `Hold`):

- `afterStop`: "Collectable this long after this part stops."
- `for`: "Collectable this long after earning: approval for once, period end or stop
  for rate."

They differ by what the duration is measured from, not by its length. Under `for` a
rate part holds the earnings of the trailing duration and releases each period's amount
once that long has passed since the period ended, while the deal runs; a `once` part
releases its amount that long after approval, whatever its term. The kit's fixture
engine models both, a `for` hold per earned amount
(`kit/arkhai-payments/src/market_arkhai_payments/fixtures/authority.py`, `maturity`).
The contract has no event that releases held money early: a part's lifecycle events are
`start`, `stop`, `reverse`, `extend` and `lift`. A hold that keeps a capped amount and
releases everything above it, or one that releases on calendar dates, is not expressible
in it. A case's `extend` protects only money still held when the payment authority
accepts it, and a rate part earns a period's amount only when the period ends or the
part stops (`openspec/specs/deal-lifecycle/architecture.md`, "External authorities").
How long after release the payments service pays a seller out is the service's own
figure, not a term of the contract.

**What the dispute authority's contract expects.** The vendored mediation contract maps
the Agreement a filing carries onto the mandate it expects, per part
(`kit/arkhai-mediation/src/market_arkhai_mediation/contract_data/mediation.schema.json`,
`AgreementProjection`, `MappingLifecycle`, `ExpectedLifecycle`). The expected hold has
one form, `ExpectedAfterStop`, on every part. The mapping's lifecycle objects admit
keys they do not name, so a term the mapping does not know is ignored and the expected
hold stays `afterStop`. The published vector `mismatches-are-evidence` reports a part
whose hold is `{"for": "P14D"}` as a mismatch against the expected
`{"afterStop": "PT1209600S"}`
(`kit/arkhai-mediation/src/market_arkhai_mediation/contract_data/mediation.vectors.json`);
durations are compared by value, since the same vector's `{"afterStop": "P14D"}` on
another part is no mismatch. A mismatch is evidence for an operator, never a filing
refusal, and the authority rules a `delivery_end` without a person only under a clean
mapping (`deal-lifecycle`'s companion, "External authorities"). Its remedies are defined
over money still held: the penalty reverses "min(amount, earned amounts still held)"
and "Never needs money beyond what is held". The lane's mediation double checks no
mapping (`tools/mediation-lane-double/src/mediation_lane_double/service.py`).

**The terms codec.** An option's `lifecycle` holds `adjudication`, `early_termination`,
`delivery_deadline_seconds` and the reserved `bond`
(`kit/deal-lifecycle/src/market_deal_lifecycle/terms.py`). Every term model forbids
keys it does not name, so a reader refuses an option stating a term it does not know.
An absent optional term is left out of the encoding, and the option's ID covers the
encoded lifecycle. What a mechanism or an authority can realize reaches the codec as
capabilities its caller supplies, `TermContext.supported_partial_periods` and
`supports_bond` among them, and `validate_terms` refuses a term outside them. A dispute
authority's advertisement copy keeps fields the neutral layer does not interpret
(`kit/deal-lifecycle/src/market_deal_lifecycle/configuration.py`,
`AuthorityAdvertisement`).

**What the buyer reads and where.** One kit function builds both compute buyers'
lifecycle display (`kit/settlement-runtime/src/market_settlement_runtime/buyer_terms.py`,
`lifecycle_disclosure`). Its "Premature-stop penalty" row says the penalty is
collectible only from the seller's earnings still held, "under this option's holds, what
the deal has earned so far and not yet been paid"; its "Cases and holds" row says "holds
last through stop plus the dispute window". The default buyer refuses four terms, each
with its own waiver, from one table (`TERM_WAIVERS`). The codec projects seven common
query fields from the terms
(`kit/deal-lifecycle/src/market_deal_lifecycle/projections.py`), which a buyer's
settlement clause evaluates and both registry filter specifications declare
(`core/registry/src/core_registry/filter-spec.yaml`,
`core/registry/filter-spec.introductions.yaml`).

**The penalty.** An on-demand option takes a default premature-stop penalty of 24
periods' price (`kit/settlement-runtime/src/market_settlement_runtime/rate_publication.py`),
and the default buyer refuses an option that does not entitle the payee to stop and
states no positive penalty. The penalty is for any seller end the terms do not entitle,
a spot end without notice included.

**Who waits for held money.** The storefront's seller is the payee. A seller that sells
a site's capacity pays that site by an arrangement this repository does not define, so
the party that carries the cost of held earnings is usually the site. The hold term
settles one thing between the parties to the deal: when the seller receives its money.

**Released.** `marketplace-v0.4.0` carries all of the above, and the cited code is
unchanged since. A buyer of that release drops an option whose lifecycle it cannot
decode before its clauses run
(`kit/arkhai-payments/src/market_arkhai_payments/settlement_config.py`,
`arkhai_payments_buyer_compatibility`). A registry of that release stores and serves
such an option and matches it for no lifecycle filter
(`core/registry/src/core_registry/api/filter_eval.py`). A storefront of that release
refuses a publication clause carrying a key it does not know.

## Decisions

### D1 — An option may state a hold shape, and stating none is the hold every option has today

An option's lifecycle may state a hold shape: how long the payment authority keeps what
the deal has earned reversible and uncollectable by the seller. An option that states
none has the hold every option has today, each part's earnings held until the part's
stop or end plus the dispute window. The seller chooses per option, so one listing may
offer the same capacity under two holds at two prices.

The stated shape is a codec-owned lifecycle term. It is in the Agreement's bytes and in
the option's ID, so the buyer approves the hold it read and a seller that changes it
publishes a different option.

Stating none is not a default the seller may leave to the storefront: it is the absence
of any earlier release, as an option that states no `early_termination` grants no
entitled stop.

Rejected:

- One uniform hold. It either keeps every seller waiting or changes every buyer's
  protection.
- A duration as the whole term. The payments contract defines a hold by what it is
  measured from, and a number of seconds can name neither a hold on a capped amount nor
  a calendar release.
- A storefront-wide setting. The hold is a term of each deal, read by its buyer.

### D2 — The shapes are an open set, and a shape a reader does not know fails closed

The term names one shape out of a set that grows. This change builds one (D4). Others
are expected: a hold on a capped amount with everything above it released as it is
earned, and release on calendar periods, are the two named so far. Neither is in scope,
and each needs a payments contract revision first, since the contract offers `afterStop`
and `for` and nothing else.

- **A shape is added, never redefined.** A shape's name and its own parameters fix its
  meaning. A different meaning is a different shape. Adding one changes no existing
  option's bytes, ID or meaning, whether that option states an earlier shape or none.
- **Every reader fails closed.** A reader that does not know an option's stated shape
  does not select, publish, derive, display or match that option as though it stated
  another, or none:
  - the codec refuses to decode it, so a buyer drops the option and keeps the listing's
    others, as it does any term it cannot read;
  - publication refuses to emit a shape its mechanism's installed payment contract
    cannot encode, or that the option's dispute authority does not map (D5), as it
    refuses a partial-period treatment the installed contract cannot encode;
  - the registry matches the option for no lifecycle filter;
  - the dispute authority's mapping reads it as unreadable terms (D5).

Rejected:

- Reading an unknown shape as today's hold. A buyer would approve, and an authority
  rule on, a hold the option does not state.
- A version number over the whole set, raised with each shape. Every reader would refuse
  every option at the new number, including those stating shapes it knows.

### D3 — Each consumer has one case per shape

Five things read the stated shape: the mandate derivation, the buyer's display, the
query projection, the dispute authority's mapping rule and the capability check of D2.
Each is a case per shape with no fall-through: a shape with no case is refused, never
handled as another's. A later shape adds one case to each and edits none of the
existing ones.

The buyer's exact check needs no case of its own. It re-derives the mandate through the
same derivation and compares the whole of it, so it holds for any shape the derivation
has a case for.

Rejected: one general rule parameterised to cover later shapes. The two shapes named in
D2 share no parameter with the first, and a rule written for shapes that do not exist
yet would be opinion about them.

### D4 — The first shape releases each period's earnings the dispute window after they are earned

The one shape this change builds is "after earning": each amount a rate part earns is
released the option's dispute window after it is earned. The mandate's rate part carries
`{for: <dispute window>}` where an option stating none carries
`{afterStop: <dispute window>}`. The shape has no parameter of its own: the window is
the option's `adjudication.dispute_window_seconds`, which already covers the delivery
deadline plus the dispute authority's advertised minimum.

For an hourly deal with the quickstart's fifteen-day window:

| | Stating none | After earning |
|---|---|---|
| Rate part's hold | `{"afterStop": "P15D"}` | `{"for": "P15D"}` |
| An hour's charge is collectable by the seller | 15 days after the deal stops | 15 days after that hour ends |
| Held at any moment in a long deal | Everything earned so far | The last 360 hours' earnings |
| A case filed today can protect | Everything earned so far | The last 360 hours' earnings |
| A penalty of 24 hours' price is fully backed | Once 24 hours are earned | Once 24 hours are earned |

What it changes for the buyer, which every document a buyer reads states:

- A charge is reversible for the dispute window after its period ends, or after the
  stop for the period in progress. After that it is the seller's, and no case, reversal
  or penalty reaches it.
- A case protects what is still held when the payment authority accepts its extension.
  The buyer has the same window to act on any period that it has today on the last one.
- The premature-stop penalty is collectible from at most the earnings of the trailing
  window still held after refunds.

What it does not change: who may stop and on what notice, how a stop or the term end
prices the period in progress, the first period earning nothing until it ends, and each
part's maximum hold extension.

Which parts besides the rate part take the shape is Q2.

Rejected:

- A duration the seller chooses freely. It would let a hold fall below the minimum
  window the dispute authority advertises. It may return as a shape of its own.
- A window shorter than the option's dispute window for this shape. The buyer would
  have less time to act on an early period than the terms say it has on the last.

### D5 — The dispute authority maps the stated shape, and implementation waits for the contract that says so

A deal whose mandate the dispute authority cannot map cleanly is never ruled without a
person. That would remove, for exactly the options that release money earlier, the one
remedy that needs nobody's attention: the seller's own filing of an end it was not
entitled to. So this change is implemented only against a published mediation contract
that maps the stated shape.

What SCM needs of that contract:

1. **The mapping reads the term.** The Agreement projection reads the option's stated
   hold shape from the Agreement's `settlement.lifecycle`, where the codec puts it (Q1).
2. **The expected hold is per shape.** With no shape stated, every part's expected hold
   is `afterStop` the dispute window, as now. With "after earning" stated, the expected
   hold of each part the shape applies to (the rate part; Q2) is `for` the dispute
   window, and every other part's stays `afterStop`. The expected-hold definition admits
   both forms. Durations compare by value, as now.
3. **An unknown shape is unreadable.** A stated shape the mapping does not know, or a
   malformed term, yields unreadable terms naming the term's path. It is never mapped as
   `afterStop`, and nothing is ruled mechanically on it.
4. **Nothing else moves.** The expected end, maximum hold extension and authorities are
   derived as now, and the remedies keep their definitions, which are already stated
   over money still held.
5. **Vectors.** A mapped Agreement stating "after earning"; an Agreement stating an
   unknown shape, unreadable; and a `delivery_end` with cause `payee` on an after-earning
   deal whose penalty is capped by the earnings still held.

Implementation starts once a publication carrying this is vendored under
`kit/arkhai-mediation`: its schema, its vectors and the generated models. Until then no
code of this change lands, since a storefront able to publish the shape would publish
options whose disputes all go to a person. The lane's mediation double then checks the
expected hold for the shapes it knows, so a lane does not rule mechanically where the
authority would not. The gate is external to this repository and is recorded in the
campaign index as one, not as a dependency on a change.

Vendoring is not deployment. Whether the authority a given option names runs the
revision is Q6. This change makes its own live observation of the shape against a hosted
dispute authority that maps it (Q9): Goal 8 waits for this change's closeout, and no
other change verifies a hold shape live.

Rejected:

- Offering the shape on the contract vendored today, with every case on such a deal
  ruled by a person and the buyer told so. It weakens the remedy the post-commitment
  lifecycle rests on.
- Settling only the term now and the rest once the contract moves. The rule the mapping
  must learn is part of this design; written later, it would be written without it.
- Teaching only the lane double. A lane would then show a mechanical ruling the
  authority does not make.

### D6 — The payments kit's contract note states the derivation the kit has

`kit/arkhai-payments/schema/SOURCE.md` says the kit derives a maximum hold extension of
`P0D` and that its buyer policy refuses any other, null included. The derivation takes
the cap from the option's `case_hold_max_seconds` and keeps null where the terms leave
it unbounded, and the kit's tests and `settlement-servicing`'s "Mandate holds and
approval follow the option's timing" say the same. The note is corrected to the
derivation, and the unused `IMMEDIATE` constant in `mandates.py`, whose comment says a
hold is never extended, is removed. This change rewrites the kit's hold derivation and
the documents that describe it, so the correction belongs with it.

## Open Questions

Each is decided in this change's design session. Q1 and Q6 shape what D5 asks of the
mediation contract, so they are settled first.

### Q1 — How the stated shape is spelled

An on-demand option as the quickstart's clause publishes it today, abbreviated:

```json
"lifecycle": {
  "adjudication": {"version": 1,
                   "dispute": {"interface": "arkhai.mediation.v1", "origin": "https://mediation.example",
                               "account": "33333333-3333-4333-8333-333333333333",
                               "record_key": "example-public-record-key", "params": {}},
                   "dispute_window_seconds": 1296000, "case_hold_max_seconds": null},
  "early_termination": {"version": 1,
                        "entitlements": {"payer": {"notice_seconds": 0, "settles_through": "started_period"}},
                        "settles_through": "last_boundary", "premature_stop_penalty": "24000000"},
  "delivery_deadline_seconds": 1800
}
```

Each alternative shows the first shape, then how a later shape with a parameter would
read, to test that it adds a case and edits nothing.

- (a) A top-level term holding a versioned object discriminated by shape:

  ```json
  "payout_hold": {"version": 1, "shape": "after_earning"}
  "payout_hold": {"version": 1, "shape": "capped", "amount": "24000000"}
  ```

- (b) The same object with no version, the shape's name being the only unit of change:

  ```json
  "payout_hold": {"shape": "after_earning"}
  "payout_hold": {"shape": "capped", "amount": "24000000"}
  ```

- (c) A bare string. A shape with a parameter then needs a second key or a new format:

  ```json
  "payout_hold": "after_earning"
  "payout_hold": "capped", "payout_hold_amount": "24000000"
  ```

- (d) One key per shape, relying on the codec's refusal of unknown keys in place of a
  discriminator. Two shapes could then be stated at once, so it needs a rule that at
  most one is:

  ```json
  "hold_after_earning": {}
  "hold_capped": {"amount": "24000000"}
  ```

- (e) Inside `adjudication`, beside the window the first shape uses. `adjudication`
  carries `version: 1`, and a versioned contract is never changed in place
  (`docs/guidance/engineering/versioning.md`), so it becomes version 2, which every
  released reader and the mediation mapping refuse for every option that states it:

  ```json
  "adjudication": {"version": 2, "dispute": {"...": "..."}, "dispute_window_seconds": 1296000,
                   "case_hold_max_seconds": null, "hold": {"shape": "after_earning"}}
  ```

What an older reader does is the same under (a) to (d): a buyer or registry of
`marketplace-v0.4.0` refuses the unknown top-level key, so the buyer drops the option
and the registry matches it for no lifecycle filter; the mediation contract vendored
today ignores the key and reports the hold as a mismatch.

Open beside the form:

- **The term's name.** `payout_hold` says what the seller waits for and stays apart from
  `case_hold_max_seconds`, which bounds a case's extension. `hold` is the payments
  contract's word.
- **The first shape's name.** `after_earning` follows the contract's description of
  `for`.
- **Whether today's hold has a spelling.** If an option could also state the unstated
  hold by name, one meaning would have two encodings and two option IDs.

Recommended: (a), named `payout_hold`, the first shape `after_earning`, and no spelling
for the unstated hold. A discriminated object gives each shape its own parameters
without a second key, and a top-level term follows `delivery_deadline_seconds`, the last
term added. The version follows `early_termination` and `bond`, each a versioned object,
and `deal-lifecycle`'s "Malformed terms are refused" already says what an unknown
version does. Under D2 it stays 1 as shapes are added, which is the argument for (b): a
number that never moves says nothing. It would change to (b) if the design session
holds that the codec's per-term versions are not a precedent worth following here.

### Q2 — Which parts the first shape applies to

A rate option's mandate has a rate part and, where the seller prices one, a setup `once`
part. A once-only option's mandate has one prepaid `once` part. Under the payments
contract a `for` hold on a `once` part runs from approval.

- (a) The rate part only. A setup part keeps `afterStop`, and an option with no rate
  part cannot state the shape: publication refuses it, as it refuses `early_termination`
  on an option with no stoppable part.
- (b) The rate part and the setup part. Setup would be collectable the dispute window
  after approval, which for a deal starting later can be before its delivery deadline
  has run. `deal-lifecycle`'s "Dispute timing terms are bounded" exists so that "no
  `once` part pays out before non-delivery can be established and filed on", and
  `settlement-servicing`'s "The payments mandate is derived exactly from the Agreement"
  refuses to "replace the stop-relative hold with a duration from acceptance".
- (c) Every part, once-only options included. A prepaid seller would be paid the whole
  price the dispute window after approval while service runs to the term's end.

Recommended: (a). The shape is defined per period, and only a rate part has periods. A
seller of long prepaid leases who needs earlier payment is asking for a different shape,
one that releases a prepaid amount as the term is served, which the payments contract
cannot express today.

### Q3 — What the option may say about a penalty the hold cannot back

Under "after earning" the penalty is collectible from at most the earnings of the
trailing window. With hourly periods and a fifteen-day window that is 360 periods, far
above the default 24. With a period longer than the window it is at most one period's
price, and nothing for the rest of each period: a monthly period under a fifteen-day
window holds the last month's charge for fifteen days and then nothing until the next
month ends.

- (a) The display states the bound (Q5) and nothing else changes. The penalty is
  already a ceiling: under today's hold nothing backs it in a deal's first period.
- (b) (a), and publication reports to the seller an option whose stated shape can never
  hold its penalty in full, as it reports each term a default buyer refuses.
- (c) (a), and publication refuses such an option.
- (d) The default buyer's penalty refusal reads what the hold can back, not the stated
  penalty.

Recommended: (b). A refusal would be the storefront's opinion on a trade the seller may
make knowingly and the buyer is shown; `deal-lifecycle`'s "Premature-stop penalties
consume only held earnings" already forbids promising more than held money, which (a)
keeps. The rule is per shape (D3): it is stated for "after earning", and a later shape
brings its own. It would move to (c) if the design session holds that a penalty the
terms can never back should not be published.

### Q4 — Whether the default buyer refuses an option stating a shape

The default buyer refuses what a buyer should not accept unknowingly, each refusal with
its own waiver.

- (a) Shown, not refused. Under "after earning" the buyer keeps the authority's full
  window on every period.
- (b) A fifth default refusal with its own waiver, for any option stating a shape.
- (c) Decided per shape: each shape's case says whether the default buyer refuses it,
  and "after earning" is not refused.

Recommended: (c). It is (a) for the shape this change builds and leaves a later shape,
which may release far more, to answer for itself, as D3 has every consumer do. A buyer
that wants only the unstated hold says so with a settlement clause on Q7's projection.

### Q5 — What the buyer is told

The display is one row set per shape (D3). For "after earning":

- (a) A "Payout hold" row stating until when each period's charge stays reversible and
  that a case protects only what is still held; the "Premature-stop penalty" and "Cases
  and holds" rows state their bounds for this shape in place of "what the deal has
  earned so far" and "holds last through stop plus the dispute window". An option
  stating none keeps today's rows.
- (b) (a), and the row labels the option as giving reduced protection.
- (c) (b), and the row says when the seller is paid.

Recommended: (a), with one sentence of comparison: under an option stating no hold
shape every charge stays reversible until the deal stops plus the window. The facts say
what a label would, in terms the buyer can act on. The seller's payout date is not the
buyer's concern, and it depends on a delay that is the payments service's own.

### Q6 — How SCM knows an option's dispute authority maps a shape

D2 has publication refuse a shape the option's authority does not map, and a buyer
should not approve one either. An option names its own authority, and vendoring a
contract does not show which authorities run it.

- (a) The authority's advertisement names the hold shapes its mapping reads. A seller's
  and a buyer's `[[Dispute]]` entry copies it, as it copies the payment mechanisms and
  the minimum windows, and the mediation adapter reads it from the copy, which already
  keeps interface-owned fields. An entry written before the field exists names none, so
  only the unstated hold is offered or accepted against it:

  ```toml
  [Dispute.advertisement]
  mechanisms = ["arkhai.payments.v1"]
  minimum_dispute_window_seconds = 1209600
  payout_hold_shapes = ["after_earning"]
  ```

- (b) The vendored contract alone: every `arkhai.mediation.v1` authority is taken to run
  the vendored revision or later. No advertisement field.
- (c) (a) for publication and acceptance, and (b) as what the kit can frame.

Recommended: (a). It is per authority, a later shape adds a value, and an authority
that has not taken the revision is refused before a deal, not found out in a dispute.
It adds one item to what D5 asks of the mediation contract: the advertisement field.

### Q7 — The query projection

`cli-query-language`'s "Common settlement fields include the lifecycle projections"
lists the fields a clause and a registry filter may name. The projection of the stated
shape joins them.

- (a) One string field projecting the shape's name, with a fixed value for an option
  with lifecycle terms that states none, so a buyer can ask for either. The fixed value
  is the query's word only; the option still states nothing (Q1):

  ```text
  --settlement 'payout_hold=after_stop'       only options stating no shape
  --settlement 'payout_hold=after_earning'    only that shape
  ```

  A later shape adds a value. A clause written for the unstated hold goes on excluding
  every shape added later.
- (b) One boolean per shape, absent projecting false. A buyer wanting only the unstated
  hold must negate every shape, and a clause written today admits a shape added later.
- (c) One boolean for "states any shape", with (a) beside it.

Recommended: (a). It needs no value type or operator the filter grammar lacks, so a
released buyer's other queries keep working against a registry serving the added filter.
An option with no lifecycle terms projects nothing, as it projects no delivery deadline.
`discover-open-ended-compute-listings` modifies the same requirement; whichever change
lands second writes its delta against the other's text.

### Q8 — Where the seller states the shape

- (a) In the payments publication clause's `mechanism_input`, beside
  `dispute_window_seconds`, from which `adjudication` is built for both the once and the
  recurring option builders:

  ```toml
  [pricing.settlements.mechanism_input]
  payee_account = "<YOUR_PAYEE_ACCOUNT>"
  asset = "USD/6"
  approval_window = "PT10M"
  delivery_deadline_seconds = 1800
  dispute_window_seconds = 1296000
  payout_hold = "after_earning"
  ```

- (b) On the clause's `recurring` preset, beside the penalty and the notices:

  ```toml
  recurring = { period = "PT1H", reserve_ahead_seconds = 3600, payout_hold = "after_earning" }
  ```

Recommended: (a). The term is derived with the window it uses, one input model serves
every option builder of the mechanism, and a later shape for prepaid parts would have no
`recurring` preset to sit on. (b) fits if Q2 settles that a hold shape is a property of
rate options for good. Either way the key takes the option term's form once a shape has
parameters.

### Q9 — Provisional answers

Each follows from something settled or from the nearest precedent, and is confirmed or
moved in the design session.

- **The capability check.** The installed payment contract's hold shapes reach the
  codec through `TermContext`, as its partial-period treatments do, and `validate_terms`
  refuses a stated shape outside them, at publication and for the buyer.
- **The hold recorded in settlement evidence.** The VM storefront records
  `hold_until_utc` as approval plus the duration for any part with a `for` hold
  (`domains/vms/storefront/src/market_storefront/settlement_stages.py`), which is wrong
  for a rate part. It is corrected here, the code being this change's.
- **Compatibility.** No path is owed to `marketplace-v0.4.0`: its readers fail closed on
  the term, and `docs/guidance/repository/package-versions.md`, "Compatibility is owed
  to what a release has shipped", owes a released buyer nothing against a later
  storefront. An Agreement accepted under that release states no shape and derives the
  mandate it always did. No stored record changes form.
- **Vendoring.** Refreshing the mediation kit's schema, vectors and models is this
  change's first step where no other change has done it by then.
- **Which specification states what.** `deal-lifecycle` states the term, the open set
  and what an unknown shape does; `settlement-servicing` the derivation per shape;
  `settlement-configuration` the seller's key and, under Q6 (a), the advertisement
  field; `buyer-orchestration` the display; `cli-query-language` the projection;
  `test-compatibility` the lane row, its live verification twin and the double's
  mapping check.
- **Documents a seller or buyer reads.** `docs/seller-quickstart.md`, "Payout", and
  `docs/buyer-quickstart.md`, on the penalty and on disputes, state today's hold and
  gain the shape; `kit/arkhai-payments/README.md` describes the derivation.
- **Test levels.** The codec, the derivation, the exact check and the projection are
  unit tests in their kits. The mapping's expected hold is the mediation kit's vector
  replay. One VM lane scenario on lane time runs an after-earning deal past the window,
  shows an early period released and a seller's filing whose penalty is capped by what
  is still held, as lane-double evidence. One live verification scenario is that
  scenario's twin: it gives a hosted dispute authority that maps the shape the seller's
  filing on an after-earning deal and compares the ruling through the lane scenario's
  assertion, on wall time and mock provisioning, with its topology requirements stated
  in `e2e-tests/README.md` (`test-compatibility`'s "Each live verification scenario
  states its topology requirements"). It needs the deployed authority to run the
  revision of D5, which is the capability this change waits on.

### Q10 — Implementation cadence

Recommended: one round, once the mediation contract of D5 is vendored. First the kits:
the codec term and capability, the derivation, the publication input, the projection and
the registry's filter rows, one session. Then the readers: the display, the mediation
double's mapping check, the lane scenario and the quickstarts, one session.

## Requirements this change modifies

No delta is written yet: each depends on Q1, Q2 or both. The design session writes them
against these, by title.

- `deal-lifecycle`: "A settlement option states price, settlement and lifecycle" (the
  list of lifecycle terms); "Malformed terms are refused" (an unknown shape); "Builders
  emit terms only where they bind" (a shape only where a part can take it); "The dispute
  window sets the earliest payout", which today requires that every amount pay out no
  earlier than its part's end plus the window; "Dispute timing terms are bounded" where
  Q2 touches a `once` part. Its companion's "Parts and terms" and "External
  authorities".
- `settlement-servicing`: "Mandate holds and approval follow the option's timing", which
  today says every rate hold is `{afterStop: dispute_window}`; the scenarios of "The
  payments mandate is derived exactly from the Agreement" and "Hosted rate mandates are
  derived from the selected option" that fix `afterStop`. Its companion's paragraph on
  rate mandates.
- `settlement-configuration`: "Hosted rate parameters are explicit and unit-safe" for
  the seller's key, and "Dispute authorities are configured as preferences" under Q6
  (a). Its configuration companion.
- `buyer-orchestration`: "Buyers approve explicit compute price and end terms"; "The
  buyer is shown the penalty's collectible bound and why a funding stop is final"; the
  scenario "The full policy is enforced" of "Default acceptance requires an on-demand
  seller penalty"; "Each default refusal has its own waiver" under Q4 (b).
- `cli-query-language`: "Common settlement fields include the lifecycle projections".
- `storefront-publication`: "Recurring presets expose the premature-stop penalty" under
  Q3 (b) or (c).
- `test-compatibility`: "Lanes run a mediation double that answers from programmed
  rules", "The in-lane payments double mirrors the service and proves its engine's
  surface" and, for the live twin, "Rate deals and dispute filings are verified live
  against a prepared topology".
