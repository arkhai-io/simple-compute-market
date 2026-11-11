# Design

## Context

Verified against the tree at planning time; re-verify before implementing.

- Negotiation is a kit lifecycle. `kit/negotiation-runtime` owns the round state
  machine; the VM storefront injects `NegotiationDomainHooks` from
  `domains/vms/storefront/src/market_storefront/negotiation_runtime.py`:
  `validate_opening`, `validate_continuation`, `evaluate_round`,
  `reference_amount`, `amount_from_proposal`, `proposal_from_amount`,
  `agreement_terms`, `build_artifacts`, `place_hold`.
- Continue and advance requests carry a typed `proposal`. The kit stores the
  negotiated amount as an exact integer parsed through `Decimal(str(value))`,
  never a float and never a 64-bit column.
- Round 0 carries shape data in `provision_terms.compute_resource` (the flat
  `ComputeResource`). `_validate_vm_opening` refuses an opening whose shape
  differs from the listing's on any dimension the listing declares
  (`OfferUnfulfillableError`, `resource_shape_not_negotiable`); an opening that
  omits `compute_resource` proceeds. No later round can carry a shape.
- Both storefronts ship `capacity.hold_ttl_seconds = 0`: `_place_capacity_hold`
  returns immediately, and the reservation is created at settlement from the
  settlement order, which `build_vm_accepted_artifacts` derives from the
  listing record at acceptance. The committed reservation's dimensions and
  `claim_attributes` are authoritative through scheduling and dispatch.
- `kit/site`'s `resize_reservation` supersedes a reservation with a new shape
  under the same negotiation. It has no caller. *Since 2026-10-05
  (`bare-metal-mock-provisioned-deal` 5B.8.B.3), the supersede passes the site's
  release guard, as every capacity release does. The guard frees the superseded
  reservation only when its fulfillment proves nothing was dispatched (no aggregate,
  or one still `assigned`, which it abandons), so a resize of a reservation whose
  fulfillment has begun is refused and changes nothing. A negotiation-time resize
  precedes fulfillment and passes; design for the refusal anyway.*
- `kit/capability-shape` and `VM_CAPABILITY_SCHEMA` define the family-grouped
  capability shape and the VM vocabulary. `capacity-shape-pricing` lets a seller
  state per-family rates; a shape-priced listing records its resolved rates on the
  storefront's listing record, and since `store-registry-listings-as-published`
  publishes them to the registry at the listing's `pricing.rate_structure`. Its
  aggregator evaluates the rates for any shape exactly. A flat-priced listing — one
  whose GPU family states no rates — has a clause rate for its own shape and no
  family rates, so it cannot price a revised shape and is shape-fixed by
  construction. `capacity-shape-envelope` supplies an admissibility predicate and
  `negotiation-capacity-feasibility-probe` a non-consuming authoritative probe,
  where a domain composes them.
- Reverified 2026-11-06: `NegotiateContinueRequest` and `AdvanceRequest` now
  carry top-level `extra="forbid"`; their `proposal` remains a dictionary, not a
  typed revised-terms carrier. The Section 1 revert remains historical; this
  section does not undo the later request-model strictness. Nested content still
  needs the domain codec that understands it.

## Goals / Non-Goals

**Goals:** a round after the first can carry a revised capacity shape; the seller
evaluates and prices it; concessions stay comparable across a shape change; the
agreed shape is what gets reserved and built.

**Non-Goals:** pricing a shape (`capacity-shape-pricing`); deciding which shapes a
seller will consider (`capacity-shape-envelope`) or whether the site can serve
one now (`negotiation-capacity-feasibility-probe`); calling `resize_reservation`
(`negotiation-time-capacity-hold`, the change that first holds capacity before
the shape is final); round 0 adopting the family form
(`settle-capacity-claim-vocabulary`).

## Decisions

Section 2's implementation-time decisions were settled with the owner in a design
discussion standing in for a design review (workflow log seq 2), and recorded here
by the implementation round's triage; the owner record's point for each is named
in its heading's note.

### D1 — The revised shape is a child of `proposal`, typed as the `ProvisionTerms` envelope, in the family-grouped form

*Owner record R7, R8.*

A revised-terms field is a child of `proposal`, not a sibling: it is part of
what a round proposes. It reuses the existing opaque `ProvisionTerms` envelope
rather than introducing a core-level concept, so core stays schema-opaque and
the VM codec decodes the payload as a family-grouped capability shape validated
by `VM_CAPABILITY_SCHEMA`. Round 0 keeps `compute_resource`; whether it adopts
the family form is another change's question.

The wire child is `proposal.provision_terms`; its envelope payload is the whole
family-grouped shape, not a patch. The VM decoder preserves the opening's duration,
start and delivery credentials and replaces only `compute_resource` in the effective
terms used by the existing VM codecs. Those full effective terms are recorded beside
each scalar message (core migration `20261106_001_negotiation_message_terms`).
Continuation resumes the latest seller-quoted terms, not the immutable opening's
shape or an unquoted buyer proposal. Domains that do not compose a revision decoder
refuse a revised envelope. Revisit this boundary if non-shape delivery terms become
negotiable; they need explicit domain validation, not arbitrary replacement of the
opening's payload.

The kit's hooks widen accordingly: `decode_revised_terms` decodes a revision against
the previous terms, `RoundRequest.revised_terms` exposes it, and
`RoundEvaluation.agreed_terms` supplies the seller's effective terms to
`agreement_terms` and acceptance; only a counter may revise. Round 0's flat partial
form inherits the listing's omitted dimensions once, and the complete effective shape
is recorded with the seller's quote; a later grouped revision is a whole shape and
never inherits omitted families. The two forms coexist until
`settle-capacity-claim-vocabulary` settles round 0's vocabulary.

The payload is limited to what seller policy can price. A nested field that
passes through unexamined is an unpriced giveaway surface: a buyer could claim
disk or RAM the seller never agreed to give away because nothing checked it.

### D2 — The negotiated variable becomes a rate multiplier

This is the change's central decision and the one that is easy to get wrong.

With shape fixed, negotiating an absolute total works: each round moves one number
toward or away from a bound, and "who conceded" is well defined. With shape variable,
a total stops being comparable between rounds — a buyer who asks for less RAM and more
disk and quotes a different total has not obviously conceded, and `bisection_middleware`
has no axis to bisect.

Three models were considered:

- **Negotiate the absolute total, re-anchoring bounds whenever shape changes.**
  Rejected: every shape change resets the concession history, so a buyer can escape an
  unfavorable position by perturbing the shape. It also makes convergence
  non-terminating in the general case.
- **Fix the rates and let the buyer choose the shape.** Rejected: price becomes
  derived and there is nothing left to negotiate — this is configure-and-quote, not a
  market, and it discards the existing policy machinery entirely.
- **Accepted: negotiate a multiplier over the listing's minimum rate structure.** The
  listing advertises minimum rates; the quote for a shape is those rates evaluated
  against it; the negotiated scalar is the multiplier applied to that structure. Shape
  and price vary independently, the multiplier remains a single monotone axis, and
  `bisection_middleware` keeps working with its reference quantity reinterpreted rather
  than replaced.

A consequence worth stating: a seller's floor is expressed once, as the multiplier's
lower bound, and applies to every shape automatically (D4). Under absolute-total
negotiation, a floor has to be recomputed per shape, which is where a
shape-perturbation attack would have entered.

### D3 — The multiplier is an integer in basis points, and every amount stays exact

*Owner record R1, R8.*

A multiplier is a ratio; the kit's negotiated amount is an integer. The
multiplier is carried as basis points over the advertised minimum rate
structure: 10,000 means 1.0×. The kit's `reference_amount`,
`amount_from_proposal`, and `proposal_from_amount` hooks keep their integer
contract, `bisection_middleware` converges on it unchanged, and the seller's
floor is one integer bound.

**The ratio rule.** The quote for a shape is the selected settlement option's
advertised rate, scaled by the ratio of the requested shape's composed price to the
advertised shape's, both evaluated through `price_vm_shape` in the selected option's
asset; the family rates set only that ratio. Scaling the option's already
materialized rate reuses its base-unit scale without a token metadata read or an
inferred decimal precision. Both composed prices must be positive, and a selected
asset with no matching family rates refuses as `shape_price_unavailable`, never
falling back to another asset's rates.

Amount arithmetic follows the rule the kit already applies: exact integers
(Python `int`), `Fraction` or `Decimal`, never `float`, and never a database
`INTEGER` column — an asset's base units exceed 64 bits routinely, and a wei amount
that has been through a float is a different number. The shared quote helper
(`arkhai_vms_negotiation.amounts.quote_from_multiplier`) applies the ratio, the
duration and the multiplier exactly and rounds upward once, after the complete
product, so a quote is never below what the multiplier promises the seller. A quote
that would not fit uint256 is refused as `shape_price_overflow`, not truncated.

**Wire.** The round carries the multiplier and, when it changes, the shape; the
quote is derived by both sides from the listing's advertised rate structure,
which is authoritative for both. It is not carried per round. At opening the
seller pins the rate-structure digest; a changed structure refuses a later round
or acceptance distinctly, requiring the buyer to reopen (D9).

### D4 — The seller's multiplier floor

*Owner record R2, R12.*

One storefront-wide `negotiation.multiplier_floor_bps`, default 10,000, plays three
roles: the seller's bound, its opening, and the clamp that turns a sub-floor policy
counter or accept into a counter at the floor. Acceptance below it is refused.
Bisection itself is unchanged; its five percent convergence tolerance is not
permission to undercut the floor. A buyer can accept the floor; repeated sub-floor
counters end under the existing stale-round rule rather than re-anchoring on each
shape.

A floor above 10,000 is refused at configuration load, so the advertised rates are
always a minimum: a seller wanting more advertises higher rates. A seller may lower
the floor explicitly to clear idle capacity; "minimum rate structure" then reads as
the advertised reference structure, and the floor is still expressed once. A
per-pool floor is a future extension, not built.

The VM storefront keeps its own `SellerRoundHook` protocol, as bare metal does, and
applies the floor there. The policy kit's proposal-amount helpers it needs are public
exports of `kit/policy` (`amount_from_proposal`, `set_proposal_amount`), shared by the
VM and API-credit domains.

### D5 — The buyer's amount codec

*Owner record R3; owner's notes 13 O1.*

The core buyer owns an optional, schema-opaque amount codec; the VM buyer supplies
the listing-aware one. Transcripts stay scalar, `NegotiationOutcome.agreed_amount`
stays monetary for aggregation, confirmation and settlement, and
`negotiated_scalar` records the policy quantity separately. Resume records retain
the listing's rate carrier and exact integer prices, never floats.

The buyer's public per-hour price surface remains monetary. The VM codec converts
those bounds to basis points against the buyer's effective opening shape — what its
opening asks for, partial dimensions inheriting the listing's — rounding down so
quantization cannot exceed the caller's monetary bound; the anchor does not move
when a later round revises the shape. The buyer refuses an acceptance whose derived
payment exceeds its monetary ceiling. The seller's advertised-shape cap (D10) makes
overspend impossible today; converting against the opening shape and checking the
ceiling keep it impossible once the cap lifts, and with the buyer's round-0 shape
option, which asks for a different shape than the listing advertises. The ceiling
admits the quote's one upward rounding, so a deal at exactly the buyer's ceiling is
not refused for a fraction of a base unit.

The VM buyer's `buy` and `negotiate` commands take `--shape`, comma-separated
quantities (`gpu_count=1,vcpu_count=8,ram_gb=64`) filling the opening's
`compute_resource`; an omitted quantity is the listing's. The buyer refuses a shape
exceeding the listing on any quantity, as the seller would (D10) — `buy` skips such
a match — and a resumed run reuses the shape its negotiation opened with.

*Owner's notes 13 O1.* Prices the buyer does not state are derived for the shape it
opens with. Derivation reads a candidate's advertised rate, which prices the whole
advertised shape; against a smaller opening shape that would make derived defaults a
multiplier above 1.0× of what the buyer asks for — the whole listing's price for the
smaller machine. With `--shape`, each candidate's pricing copy states only its
selected option's rate, scaled by the composed-price ratio of its effective opening
shape to the advertised one (the ratio rule, D3) and rounded up to a whole base unit;
derivation reads rates as exact integers, never through a float, so a derived ceiling
never converts below 10,000 bps. `buy` then anchors on the cheapest scaled candidate as
before, skipping one whose selected asset cannot price the shape, as the seller would
refuse it. The scaling lives in the VM buyer (`priced_at_opening_shape`), so core's
derivation stays shape-blind; explicit `--initial-price` and `--max-price` keep their
stated values.
Rejected: keeping whole-listing defaults, which silently overpays by the inverse of
the shape ratio, and refusing `--shape` without explicit prices, which leaves the
buyer to price a shape nothing shows it. Revisit if derivation moves into the buyer
policy surface.

Revisit the public-price adapter if the buyer gains explicit multiplier flags.

### D6 — Legacy and payment paths

*Owner record R8.*

Shape-priced scalar negotiations use the multiplier; flat-priced and hidden-reserve
paths keep their exact absolute-amount and truncation behavior, and a flat-priced
listing is shape-fixed. This is the "where a domain's offering carries a resolvable
rate structure" boundary, not a conversion of every market or of an amountless
selection into multiplier bargaining; `core/tests/unit/test_rate_helpers.py`'s
generic `compute_rate_total` still serves legacy and other-domain consumers.

The derived uint256 payment, not the scalar, enters the VM settlement build context,
the escrow or hosted obligation, and the Agreement. A materialized escrow proposal
must not overwrite the scalar `proposal` in the terminal round response; its monetary
form remains in `accepted_escrow_proposal`. A buyer revision instruction is not
echoed as an instruction to revise again when the buyer accepts a seller counter.

### D7 — Registry carrier and seller authority (D-a, D-b, D-c)

*Decided by the webapp owner 2026-11-06; kept by the owner (owner record R4).*

- **D-a — keep what the schema admits.** `store-registry-listings-as-published`
  stores and serves each accepted listing as published. Listing-level terms need
  not accumulate inside `listing_resource`; the schema describes the whole
  accepted listing. Revisit if the registry's admitted schema becomes deliberately
  narrower. Registry storage and verification are owned by that change, not here.
- **D-b — listing-level rates.** Rates are listing-level sale terms for many shapes,
  not the advertised resource's shape. As landed, the registry carries them at the
  listing's `pricing.rate_structure`, beside `pricing.asking_rate`. Revisit if the
  published pricing vocabulary changes.
- **D-c — seller authority.** The registry retains the publisher's signed request
  bytes and signature beside its own signed response. A buyer verifies the seller's
  commitment, rather than treating the registry's copy as seller authority.
  Revisit if the signed-listing proof contract changes.

### D8 — The buyer reads rates from the registry, verified by the seller's proof (D-d)

*Decided by the webapp owner 2026-11-06; kept by the owner (owner record R4).*

A buyer derives quotes from D-b's registry carrier, verified with D-c's retained
seller signature under D-a. This avoids an unsigned storefront read or an
additional negotiation commitment carrier. The buyer lifts `pricing.rate_structure`
into its domain listing record's `rate_structure` once, at its registry boundary
(`negotiate_cli.py`, `settlement_composition.accepted_listing_record`); everything
downstream stays keyed on the domain record. Verification of the retained proof
lives in the buyer's pricing-record verifier, which
`negotiate-open-ended-compute-terms` delivers. Rates are as trustworthy as the
registry's publisher key set — the same trust root that authenticates negotiation
replies and Agreements; that root's gaps are `store-registry-listings-as-published`'s,
not this change's. Revisit if discovery no longer supplies the seller-authenticated
rate structure.

### D9 — A rate structure is pinned for the negotiation, from what the seller last published (D-e)

*Decided by the webapp owner 2026-11-06; amended by the owner (owner record R5).*

The seller pins and prices from its most recent successful registry publication,
not from its stored listing record: that is what the buyer read. Core's
`publications` table keeps each registry's last successful payload in an additive
column (`published_payload_json`, migration
`20261111_001_publication_published_payload`) written only by a successful
publish, so a failed republication, or a status update, loses nothing. Only
currently configured registries are read: a registry dropped from the
configuration is one publication neither reaches nor repairs. The VM runtime overlays the published rate structure onto the listing
record once, where it resolves the listing, and pricing, the opening's pin and
continuation's check all read that one record.

At opening, the seller persists the digest of that rate structure — `pricing.rate_structure`
only, through `market_identity`'s `canonical_json`, computed by
`arkhai_vms_negotiation.amounts`. On a later round or either acceptance (buyer or
administrative) it refuses distinctly as `rate_structure_changed_reopen` if the
current structure differs, even if the advertised shape's composed total and the
settlement option's identity are unchanged. A missing pin on a shape-priced thread
fails closed, so in-flight absolute-amount negotiations drain at upgrade (D15). Exit
performs no validation and no reference pricing, so withdrawn or unpriceable terms
never trap a buyer in a thread.

The pin over-refuses: a change to any family's or any asset's rates refuses every
open thread on the listing, including one whose shape and asset the change does not
touch. A narrower pin would need per-thread price derivation at each check; the
over-refusal is accepted while sellers rarely reprice live listings.

Registries whose last successful payloads disagree fail closed
(`rate_structure_divergent`), and the existing targeted resend repairs them; a
partially failed republication therefore refuses every thread on the listing until
it converges. A buyer-named digest, letting the buyer say which publication it
read, is deferred until multi-registry sellers lose deals to it. A shape-priced
listing with no successful publication recorded — one carried across the upgrade —
takes no opening until its first successful refresh (`rate_structure_unpublished`).
For a shape-priced listing, a configured registry with a publication row of it but
no retained accepted payload counts as divergent while another registry's is known
(27 F1): after the upgrade, a refresh one registry accepts and another refuses
would otherwise price from the new rates while the other still serves the old. A
registry with no publication row of the listing serves none and is ignored. The
cost is over-refusal in two cases: a newly configured registry whose first publish
keeps failing stops negotiation on the listing until it accepts, and a registry
whose last pre-upgrade publish succeeded, beside one convergence repaired, is not
resent the listing until the listing next changes, since convergence resends only
to a registry whose last publish failed. A flat-priced listing negotiates from its
stored record as before the pin existed, with nothing published or with a
registry's payload unseen, since its quote reads no rate structure. Continuation resolves the listing without
refusing, so a buyer can always exit; every validated round and acceptance refuses.
The
settlement-option repricing lag predates this change and is a recorded gap, not
fixed here: the selected option's rate, which the ratio rule scales (D3), and the
`pinned_option_withdrawn` refusal still read the stored listing, which a failed
republication can leave ahead of what was published.

Honoring the old snapshot would bind the seller to withdrawn rates, a new pricing
commitment; explicit repricing would change the wire. Neither is implicit in a
multiplier. Revisit condition: sellers needing to reprice live negotiations.

### Carrier alternatives considered before D7 and D8

The quote for a revised shape is derived from the listing's rate structure, so a
buyer must be able to read that structure with the authority the quote needs. Three
carriers were possible:

- the storefront's listing read, which exists but is unsigned, with the structure —
  or its digest — bound into a signed negotiation response so both parties derive
  the quote from the same committed rates;
- `listing_resource`, following `asking_rate`'s precedent, which the registry
  stored and could filter;
- a listing-level field at the registry, which the registry then discarded.

The third depended on `store-registry-listings-as-published`, whose accepted carrier
policy bore on the second as well. D7 and D8 select the listing-level registry
carrier, available at discovery.

### D10 — The seller's evaluation order, and the advertised-shape cap

*Owner record R6, R8, R14.*

For a round carrying a shape, the VM composition runs, in order: policy resolution,
admissibility, authoritative feasibility, the seller's commercial feasibility guard,
then pricing. Each is a distinct refusal reason on the wire, because each leads to a
different counter: change the ask, retry later, or accept the seller's counter.

Policy resolution reads the requested shape's quantitative predicate from the
listing's durable site/pool binding and the held pool projection, then the stored VM
override and the parsed configured default through the existing listing-shape
resolver; the override replaces the hint's shape list whole, and only the advertised
base shape's constraints apply. Missing or unreadable policy refuses as
`shape_policy_unavailable`, never as an unconstrained fallback. Admissibility refuses
as `shape_inadmissible`.

Authoritative feasibility is not composed: `negotiation-capacity-feasibility-probe`
supplies it. Existing listing-source confirmation concerns the advertised shape
alone and is not evidence that a requested shape fits. Until the probe is composed,
the seller caps a requested shape at the advertised shape on every quantity and
refuses a larger one with a distinct reason (`shape_exceeds_advertised`, naming each
quantity requested and advertised), in the feasibility check's place after
admissibility and before the commercial guard: the advertised shape is one the site
was found able to serve, and a smaller one fits wherever it does. Lifting the cap —
negotiating a shape larger than the advertised one — is what the probe is the
prerequisite for; buyers will want to negotiate up, but not in this release.

The commercial feasibility guard takes a requested shape and the listing's
categorical commitments — GPU model and region compared by equality — so a shape
the seller does not sell is declined before it is quoted (`shape_commercially_infeasible`).
Its quantitative counterpart is admissibility, composed first; the guard does not
re-check ranges. It moved here from `capacity-shape-pricing`, whose planning-time
Section 5 held both halves, because this composition is where a requested shape
first exists. A domain that composes neither admissibility nor feasibility
negotiates shapes on price alone and says so in its composition rather than
silently.

A listing is shape-fixed by its own construction, with no separate declaration:
flat pricing cannot price another shape, and an envelope admitting a single shape
admits no other. A seller policy that refuses every revised shape covers the rest.

Round 0 is evaluated by the same composition as any later round, so the round-0
shape guard `_validate_vm_opening` once applied — refusing a differing round-0
shape because nothing could price it — is retired with its regression tests. It was
never promoted to a permanent requirement because it was temporary by design.

### D11 — The agreed shape reaches the claim through the accepted artifacts

*Owner record R8.*

The VM acceptance composition writes the agreed order into the settlement plan's
`service_terms["vm.v1"].order` after the selected mechanism materializes its
artifacts. One shared builder (`agreed_vm_order`) replaces the listing resource's
whole quantitative and GPU shape with the accepted shape; omitted families do not
inherit the advertised quantities. Capacity identity and sale terms remain unchanged,
and the published listing is not mutated. `compute_capacity_claim_from_order` is
unchanged.

Holds, escrow and hosted-payment settlement, and the administrator's settlement
preview read that snapshot for delivery facts through `settlement_vm_order`; legacy
plans without an order derive one from the accepted provision terms. The fulfillment
planner reads those facts; the provider already sizes from the committed
reservation. `encode_compute_lease` encodes the supplied order's GPU terms and needs
no new sizing authority. `_place_capacity_hold` derives its claim through the same
builder, so a deployment with a non-zero `hold_ttl_seconds` holds the agreed shape.
No reservation is resized here.

### D12 — `resize_reservation` is not wired here

No reservation exists while the shape is still negotiated, so there is none to
resize. A deployment with a positive `hold_ttl_seconds` places a TTL soft hold at
acceptance, before settlement, but only once the shape is final, and that hold
claims the agreed shape (D11); with no hold, the claim built at settlement from
the agreed shape is reserved fresh. A resize is needed only when a hold was placed
*before* the shape was final, and the change that introduces such a hold is
`negotiation-time-capacity-hold` (one superseded reservation per negotiation,
resized per differing-terms proposal). That change is the first caller. This
change's title names the mechanism the model described; its scope is that the
capacity shape is negotiated.

### D13 — The storefront's negotiated quantity is named `negotiated_scalar`

*Owner record R9.*

The storefront's negotiated quantity is a basis-point multiplier on a shape-priced
listing and an amount only on legacy paths, so `agreed_price` and `agreed_amount`
mislead every reader who takes it for money. It is renamed `negotiated_scalar`
everywhere it is the policy quantity: the `negotiation_threads` column (core
migration `20261111_002_negotiation_negotiated_scalar` renames it), the storefront's negotiation detail and summary wire,
`storefront_client.models`, the kit runtime's `Acceptance` and records, and every
domain consumer. No alias is kept; no external reader is known. The buyer's
`NegotiationOutcome.agreed_amount` stays monetary and keeps its name.

### D14 — Settlement reads money only from the Agreement

*Owner record R10.*

Hosted-payment settlement no longer compares the Agreement's amount with the
negotiated scalar: the payments kit already verifies that the exact Agreement
derives its stored mandate. Settlement reads money only from the Agreement and its
bound mandate, never from a negotiated scalar.

### D15 — The release is one-way for storefront state; drain before upgrading

*Owner record R11.*

The negotiated quantity's meaning and column name change, and migrations are
forward-only, so storefront state crosses the release one way. The forward drain
enforces itself through the pin: a thread opened before the upgrade has none and is
refused on its next round. Operators pause trading, let open threads end, settle
accepted deals, and take the backup before upgrading; rollback is only by restoring
that backup with the earlier image (`docs/operator-handbook.md`, "What the upgrade
from v0.3.0 changes").

### D16 — The VM domain's import guard follows the package layers

*Owner record R8.*

VM concept modules may import `market_core` carriers, as `ARCHITECTURE.md`'s
"Package and dependency layers" permits, but not role packages; the VM domain's
import guard is aligned to that rule.

### D17 — Content validation lives in the domain codec

*Owner record R15.*

Both shared request models carry top-level `extra="forbid"`, which rejects an
unknown top-level key. That does not protect against the real risk, an unexamined
nested field, and core cannot check nested content without knowing the domain. The
VM codec's schema validation of the revised shape is that check.

## Risks / Trade-offs

- **The multiplier is unintuitive to sellers who think in currency** → a
  presentation concern; the quoted price for a concrete shape is what both
  parties see. The multiplier is the internal negotiated quantity.
- **`bisection_middleware`'s reference quantity changes meaning** → contained
  in the middleware, which bisects a scalar regardless of units. The risk is
  every consumer that assumed the scalar was an amount in base units, audited in
  task 2.8 and named for what it is by D13.
- **In-flight negotiations at deployment** carry an absolute amount → drained
  before the upgrade (D15).
- **The pin over-refuses on any rate change** (D9) → accepted while live
  repricing is rare.

## Findings during implementation

Kept from the task notes, which closeout compressed; each review's findings and
dispositions are in its triage record under `reviews/`.

- **Consumers of the scalar.** Driving the real buyer against the served storefront
  found two consumers that read the scalar as money: a materialized escrow proposal
  overwrote the scalar `proposal` in the terminal response, and hosted-payment
  settlement compared the Agreement's amount with the basis-point scalar (D6, D14).
  Accepting a revised counter found the buyer echoing its revision instruction
  (D6). These are why task 2.8 was an audit of consumers rather than a rename.
- **A registry record is not a storefront listing.** A shape-priced `market buy`
  failed before reaching the seller because the buyer validated its registry record
  as a storefront `Listing`, which requires `seller_principal`, a field a registry's
  discovery record never carries (validation 07 V2). The quote now reads the
  selected option's rate directly, and the buyer's test fixture is registry-shaped.
- **A stale wheel cache.** API-credit wheel-install tests installed a wheel uv had
  cached weeks earlier under the same find-links path and filename; installs now
  pass `--refresh` (validation 07 V1).
- **The release guard keeps delivered reservations.** Stage 08b's restated shape
  was judged against available capacity and found none, because releasing the
  holds of delivered deals frees nothing: the site's release guard frees only a
  torn-down or undispatched reservation. The scenario declares a third GPU instead
  (validation 21 V1).
- **Partial first refresh after the upgrade.** With no retained payload backfilled,
  a refresh one registry accepted and another refused let the seller price from the
  accepting registry alone; a registry with a publication row and no retained
  payload now counts as divergent (27 F1, D9).
- **Local compose.** No stack started locally during implementation: Docker was
  absent and Podman Compose resolved included environment-file paths against the
  wrong directory. The deployed evidence comes from the pipeline (task 2.15, 3.8);
  the local Podman failure is out of this change's scope.

## Migration Plan

1. Revised-terms field, kit hook widening, evaluation order, guard retirement.
2. Multiplier reinterpretation and the consumer audit. Deployment boundary.
3. Agreed shape into the accepted artifacts and the hold's claim.

Storefront state crosses the release one way (D15): drain before upgrading, and
roll back only by restoring the pre-upgrade backup with the earlier image.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| A buyer-requested round-0 VM shape differing from the listing is rejected outright until a round can carry a shape | Temporary; lifted by Section 2 (D10). Never promoted |
| D1: revised terms are a child of `proposal`; core reuses `ProvisionTerms`; durable seller-quoted terms survive continuation and acceptance | `openspec/specs/negotiation-protocol/spec.md#requirement-a-round-may-revise-the-capacity-shape` (archive merge); rationale in `openspec/specs/negotiation-protocol/architecture.md#negotiating-a-shape`; `docs/development/ARCHITECTURE.md#discovery-and-negotiation` |
| D2, D3: the negotiated quantity is a multiplier in basis points; the ratio rule; amounts stay exact and round up once | `openspec/specs/negotiation-protocol/spec.md#requirement-rate-multiplier-negotiation` (archive merge); why, and the rejected models, in `openspec/specs/negotiation-protocol/architecture.md#why-the-negotiated-quantity-is-a-multiplier`; `docs/development/ARCHITECTURE.md#discovery-and-negotiation` |
| D4: the seller's multiplier floor, at most 10,000 | `openspec/specs/negotiation-protocol/spec.md#requirement-rate-multiplier-negotiation`; `openspec/specs/negotiation-protocol/architecture.md#why-the-negotiated-quantity-is-a-multiplier` |
| D5: a schema-opaque buyer amount codec keeps transcript scalars separate from monetary outcomes; bounds against the opening shape; the ceiling check; derived prices for the opening shape | `docs/development/ARCHITECTURE.md#discovery-and-negotiation`; `openspec/specs/negotiation-protocol/spec.md#requirement-rate-multiplier-negotiation`; `openspec/specs/negotiation-protocol/architecture.md#why-the-negotiated-quantity-is-a-multiplier` |
| D6: legacy flat and hidden-reserve paths; the payment, not the scalar, enters settlement | `openspec/specs/negotiation-protocol/spec.md#requirement-rate-multiplier-negotiation`; `docs/development/ARCHITECTURE.md#discovery-and-negotiation` |
| D7, D8: registry listing-level rate carrier, the buyer's lift, and the retained seller proof | `openspec/specs/negotiation-protocol/spec.md#requirement-rate-multiplier-negotiation`; registry storage and proof are `registry-discovery`'s, landed with `store-registry-listings-as-published` |
| D9: the pin, from the seller's last successful publication; divergence; the over-refusal trade-off | `openspec/specs/negotiation-protocol/spec.md#requirement-rate-multiplier-negotiation`; `openspec/specs/storefront-publication/spec.md#requirement-the-storefront-keeps-each-registrys-last-successful-publication` (archive merges); `openspec/specs/negotiation-protocol/architecture.md#the-rates-a-negotiation-is-held-to`; `openspec/specs/storefront-publication/architecture.md` (shape-resolvable rates paragraph) |
| D10: evaluation order, distinct refusals, the advertised-shape cap, shape-fixed listings | `openspec/specs/negotiation-protocol/spec.md#requirement-seller-feasibility-precedes-pricing` and `#requirement-a-round-may-revise-the-capacity-shape`; `openspec/specs/negotiation-protocol/architecture.md#evaluation-order` |
| D11: the agreed shape is what the claim reserves | `openspec/specs/vm-storefront-fulfillment/spec.md#requirement-the-agreed-shape-is-reserved` (archive merge); `docs/development/ARCHITECTURE.md#discovery-and-negotiation` |
| D12: `resize_reservation` is not wired here | `docs/development/ARCHITECTURE.md#capacity-reservation`; `docs/development/ROADMAP.md#goal-2--negotiate-full-compute-capability-not-gpu-count-alone`; `negotiation-time-capacity-hold` owns its first call |
| D13: the negotiated quantity is `negotiated_scalar` | `openspec/specs/negotiation-protocol/spec.md#requirement-rate-multiplier-negotiation`; `openspec/specs/negotiation-protocol/architecture.md#why-the-negotiated-quantity-is-a-multiplier` |
| D14: settlement reads money only from the Agreement and its mandate | `openspec/specs/negotiation-protocol/spec.md#requirement-rate-multiplier-negotiation` |
| D15: one-way release; drain before upgrading | `docs/operator-handbook.md#what-the-upgrade-from-v030-changes` |
| D16: VM import guard follows the package layers | `docs/development/ARCHITECTURE.md#package-and-dependency-layers` (already states the rule) |
| D17: content validation lives in the domain codec | `openspec/specs/negotiation-protocol/architecture.md#negotiating-a-shape` |
| Current limits: the advertised-shape cap, the settlement-option repricing lag, no buyer-named digest | `openspec/specs/negotiation-protocol/architecture.md#current-limits`; the two unowned gaps in `docs/development/ROADMAP.md` Goal 2 and `openspec/changes/README.md` |
| Roadmap currency: Goal 2's current state now describes shape negotiation; this change's gap row is removed, the probe's row names the larger-shape limit, and the two unowned gaps are added | `docs/development/ROADMAP.md#goal-2--negotiate-full-compute-capability-not-gpu-count-alone` |
| Campaign index currency: the row is `in closeout`, its Notes rewritten and its link pointing at the archive; the campaign graphs are unchanged | `openspec/changes/README.md#roadmap-goal--negotiate-full-compute-capability-not-gpu-count-alone` |
