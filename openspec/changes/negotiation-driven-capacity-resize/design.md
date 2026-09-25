## Context

See `proposal.md` for the "Why" and current-state findings. This document
records the discuss-phase reasoning and the decisions made so far.

## Section 1: guard against silently dropped top-level fields (resolved, then corrected, 2026-07-29)

### Problem

`NegotiateContinueRequest` and `AdvanceRequest` (`core_storefront/models/
negotiation_models.py`, shared across VM/bare-metal/apicredits) had no
`model_config`, so Pydantic's default `extra="ignore"` behavior applied: a
caller sending a *top-level* field these models don't declare gets that
field silently dropped, not rejected. Confirmed by inspection, not
assumed (`python -c "from pydantic import BaseModel; ..."` confirms `{}`
default config resolves to `extra="ignore"`).

### Resolution

Set `model_config = {"extra": "forbid"}` on both models. Any caller
sending an undeclared top-level field now gets an explicit 422 instead of
silent acceptance-with-data-loss. No controller code change was needed --
FastAPI's dependency-injection body parsing already raises before the
endpoint function runs.

### Correction (2026-07-29, repository-owner review)

The original write-up of this section overclaimed what the guard
achieves. It was framed as protection against a future shape-change
field being silently ignored. That framing assumed such a field would
arrive as a new *sibling* top-level field (mirroring round 0's
`provision_terms`/`proposal` sibling shape) -- which extra="forbid" on
the outer model would indeed catch.

That assumption was wrong on architectural grounds, not just
implementation detail: once a negotiation is already open, a counter is
one offer -- price and any revised terms together, not parallel
top-level signals. The correct home for revised terms is nested inside
`proposal` itself. `proposal` remains an unvalidated `dict[str, Any]` at
every layer this change has touched so far. **Section 1's guard therefore
does not protect against the risk it was originally justified by** --
data nested inside `proposal` (including a future revised-terms field)
is invisible to a top-level `extra="forbid"` check. The guard still has
independent value (rejecting a genuinely unrecognized top-level field,
e.g. a typo or a caller confusing this endpoint's shape with round 0's),
so it is kept, but its docstring and this write-up are corrected to state
that scope honestly rather than imply a protection that isn't real.
Validating `proposal`'s own contents is separate, not-yet-done work --
see the corrected "Section 2+" notes below.

A second correction, on vocabulary rather than mechanics: nothing in
`core_storefront` may define what "revised terms" *means*. Core applies
to every domain this repository could ever host -- VM compute, bare
metal, API credits, and anything not yet built (an electricity market, an
NFT market). `market_core.schemas.ProvisionTerms` already exists to solve
exactly this: an opaque `kind`/`version`/`payload` envelope, with the
payload schema owned entirely by the domain that fills it in
(`VmProvisionTerms` for VM, and so on). A future revised-terms field
belongs typed as that *same* existing envelope, nested inside `proposal`
-- not a new field, not new core-level vocabulary like "shape" or
"requirements" or "compute_resource", and not a domain-flavored name
invented at this layer. If a placeholder concept doesn't already exist in
core for something a change needs, the question to ask is whether the
existing opaque-envelope pattern already covers it before inventing
anything new.



New tests in `core/storefront/tests/unit/test_negotiation_models_extra_fields.py`:
reject-unrecognized-field cases for both models, plus accepts-declared-fields
cases proving the guard didn't break normal construction. Existing
`core/storefront/tests/unit/test_negotiation_sync.py` suite re-run
alongside with no regressions.

### Full revert (repository-owner direction, 2026-07-29)

Section 1 is reverted in full, not merely re-scoped: `model_config` is
removed from both models, and the regression test file is deleted
(tombstone: `core/storefront/tests/unit/test_negotiation_models_extra_fields.py`).
`core_storefront/models/negotiation_models.py` is back to its state
before this change opened. Direction received: no `model_config` guard
belongs in `core` for this. The preceding correction's *reasoning*
(placement as a child of `proposal`; reuse `ProvisionTerms` rather than
inventing core vocabulary) is retained below for Section 2 planning --
only the Section 1 code and tests are gone, not the design conclusion
they led to.

### Section 1 design-promotion record

| Material decision | Permanent location |
|---|---|
| No permanent behavior shipped by Section 1 -- implemented, corrected, then fully reverted same day. Nothing to promote. | N/A |
| The reasoning from the correction (revised terms are a child of `proposal`; core reuses `ProvisionTerms` rather than inventing vocabulary) survives as input to Section 2, despite the code being reverted | See "Section 2+" below |

## Section 2+ (not yet opened)

Open questions, not yet discussed in depth -- listed here so they aren't
lost, not as a commitment to build them. Revised 2026-07-29 after
repository-owner correction; the "sibling field" framing in the original
version of this list is wrong and has been replaced, not merely amended.

1. **Placement (corrected):** a revised-terms field is nested inside
   `proposal`, not a sibling of it. Once a negotiation is open, a counter
   is one offer -- price and any revised terms together. This requires
   `proposal` to stop being a bare `dict[str, Any]` and become a real
   typed model at the continue/advance layer (round 0 already types its
   `proposal` as `EscrowProposal`; continue/advance currently doesn't).
2. **Core vocabulary (corrected):** whatever that nested field is called
   and typed as, it must be the *existing* opaque `ProvisionTerms`
   envelope (`kind`/`version`/`payload`), not a new concept invented in
   `core_storefront`. Core has no way to know what "revised terms" means
   for VM compute vs. a hypothetical electricity or NFT market -- that's
   exactly the problem `ProvisionTerms` already solves by deferring the
   payload schema to the domain. Any core-level change here should be
   checked against "does the opaque-envelope pattern already cover this"
   before adding anything new.
3. **`proposal`'s own validation gap:** once `proposal` is a real typed
   model instead of `dict[str, Any]`, does it get the same
   `extra="forbid"` treatment Section 1 applied one layer up? Very likely
   yes, for the same reason -- but `EscrowProposal.fields: dict[str, Any]`
   itself must stay open (arbitrary escrow-contract-specific payment
   data, legitimately different per contract); only the outer envelope
   around `fields` and any nested `provision_terms` should be strict.
4. Given no negotiation policy will evaluate a revised-terms field yet
   (per repository-owner direction), should the field be added at all
   before policy exists, or does an always-present-but-unenforced
   optional field just recreate a milder version of the Section 1
   problem (caller sends it, gets a 200, but nothing checked it on every
   round)? Still leans toward: don't add the field until policy exists
   to either honor or explicitly reject it with a clear reason.
5. When policy does exist: does `resize_reservation` get called on the
   seller's counter (so the hold reflects what's being offered before
   the buyer accepts), on the buyer's acceptance (cheaper, no reservation
   churn for offers that go nowhere), or does this differ by richer
   negotiation form (per `fix-vm-fulfillment-capacity-boundary`'s
   discussion of hard counters vs. "what can you do for X price")?
6. What happens to `_place_capacity_hold`'s `our_order_dict`-sourced claim
   once shape can differ from the listing? It currently assumes the
   listing's shape is authoritative for the entire negotiation.

None of these are resolved. Planning for Section 2 starts only once
there's a concrete decision to plan against.

## Section 2 resolutions (repository-owner direction, 2026-07-29)

Answering the numbered list above, in order:

1. **Round-0 shape negotiation itself is out of scope.** A buyer should
   eventually be able to ask for a specifically-sized listing at round 0,
   but that requires seller negotiation policy to be able to reason about
   the request -- changing seller policy is explicitly out of scope for
   this change. Accepted fallback: "one size fits all" (the listing's own
   fixed shape) for now. This does no harm and doesn't block later work.
   **Consequence, implemented this session:** since round 0 already
   *carries* real shape data (`provision_terms.compute_resource`) that
   the storefront cannot yet honor, silently ignoring a differing request
   was worse than doing nothing -- a buyer could believe it negotiated a
   smaller/different deal than what actually gets built. `start_sync_negotiation`
   now loudly rejects (`OfferUnfulfillableError`, `resource_shape_not_negotiable`)
   any request naming a shape that disagrees with the listing on a
   dimension the listing declares. A request that omits `compute_resource`
   (the ordinary case) is unaffected. See "Section 0" below for the
   implementation record -- this is real, shipped code, not a discuss-phase
   note, even though the negotiation feature itself (item 1) is deferred.
2. **Placement: confirmed.** A revised-terms field is a child of
   `proposal`, not a sibling.
3. **Core vocabulary: confirmed.** Reuse the existing `ProvisionTerms`
   opaque envelope; no new core-level concept.
4. **`proposal`'s future content must be limited to what seller policy
   can actually reason about, to protect the seller from exploitation.**
   Explicit repository-owner framing: a permissive nested field that
   passes through unexamined risks a buyer claiming resources (disk, RAM,
   etc.) the seller never agreed to give away for free just because
   nothing checked it. This sharpens (not just reaffirms) the earlier
   lean toward "don't add the field until policy exists" -- it's not only
   about avoiding a silently-ignored field, it's specifically about not
   creating an unpriced giveaway surface.
5. **Sequencing block: document it, don't resolve it.** `resize_reservation`
   call-site placement stays open pending policy design. Documented
   explicitly (this section, plus in-code docstrings on the round-0 guard
   and `_place_capacity_hold`) specifically so a future reviewer --
   automated or human -- doesn't have to rediscover this from scratch the
   way the original external review had to reconstruct scattered context.
6. **Confirmed:** `resize_reservation` call-site choice remains open,
   downstream of (5).
7. **Confirmed, with a concrete resolution:** `_place_capacity_hold`'s
   listing-sourced claim is fine as-is *given* (1)'s guard exists --
   nothing can reach it with a differing shape today, since round 0
   already rejects that outright. `_place_capacity_hold`'s docstring is
   updated to state this explicitly (not an oversight; sequenced this
   way; do not thread a negotiated shape through without policy first).

## Section 0: round-0 resource-shape mismatch guard (implemented, 2026-07-29)

Not originally planned as its own section; implemented as the direct
consequence of resolution (1) above, ahead of Section 1/2 numbering
established earlier in this document. Numbered 0 rather than renumbering
the rest of the file.

**What changed:** `start_sync_negotiation`
(`domains/vms/storefront/src/market_storefront/utils/sync_negotiation.py`)
gains `_reject_unsupported_resource_shape_request`, called right after
the listing loads and its status is confirmed live. Compares the buyer's
`provision_terms.compute_resource` (if present) against the listing's own
shape (`extract_compute_from_order`) across the four VM dimension keys
(`arkhai_vms.DIMENSION_KEYS`: `gpu_count`/`vcpu_count`/`ram_gb`/`disk_gb`).
Any dimension the buyer names that disagrees with the listing raises
`OfferUnfulfillableError` (`resource_shape_not_negotiable`, HTTP 409 via
the existing `negotiate_controller.py` mapping -- no controller change
needed). A buyer that omits `compute_resource` entirely is unaffected;
negotiation proceeds exactly as before.

**Where this lives, and why not `core`:** entirely in the VM domain's
storefront utility module, not `core_storefront`. The comparison logic
(which dimension keys matter, what "the listing's shape" means) is
VM-specific; nothing about it belongs in a domain-neutral layer. This is
the corrected shape of the intervention the reverted Section 1 guard was
reaching for -- validating actual negotiable *content* against something
meaningful (the listing), in the domain that understands that content --
rather than generic top-level JSON-key hygiene in `core`.

**Validation:** two new tests in
`domains/vms/storefront/tests/unit/test_sync_negotiation_seller_round_hook.py`:
a mismatched request is rejected before seller policy ever runs (asserted
via a hook that raises if called); a request naming a shape equal to the
listing's own proceeds normally. Full file (7 tests) and three adjacent
negotiation unit-test files (74 tests total) re-run with no regressions.

### Section 0 design-promotion record

| Material decision | Permanent location |
|---|---|
| A buyer-requested VM shape differing from the listing is rejected outright at negotiation creation, not silently admitted or silently ignored | In-code docstrings on `_reject_unsupported_resource_shape_request` and `start_sync_negotiation` (`AGENTS.md`'s "non-obvious invariants" guidance). Not promoted to `openspec/specs` yet -- this is a temporary restriction tied to Section 2's unresolved policy question, not a durable capability contract; promote once Section 2 either lifts or permanently accepts this restriction. *2026-09-25: the guard now lives as `_validate_vm_opening` in the VM storefront's `negotiation_runtime.py`, injected as the kit's `validate_opening` hook, and Section 2 lifts it (task 2.5).* |
| `_place_capacity_hold` intentionally sources capacity only from the listing, not from anything negotiated, until seller policy can reason about a differing shape | In-code docstring on `_place_capacity_hold`, same reasoning. *2026-09-25: the docstring no longer states this; the behavior remains and Section 2 task 2.13 changes it.* |


## Re-grounding (2026-09-25)

Everything above is history. The following is the current basis for Section 2.

### What moved underneath this change

- **Negotiation is a kit lifecycle.** `kit/negotiation-runtime` owns the round state
  machine; the VM storefront injects `NegotiationDomainHooks` from
  `domains/vms/storefront/src/market_storefront/negotiation_runtime.py`. The hooks
  that matter here: `validate_opening` (today `_validate_vm_opening`, the Section 0
  guard), `validate_continuation`, `evaluate_round`, `reference_amount`,
  `amount_from_proposal`, `proposal_from_amount`, `agreement_terms`,
  `build_artifacts`, and `place_hold`. `sync_negotiation.py`,
  `_reject_unsupported_resource_shape_request`, `_resolve_compute_resource`, and
  the two `core/storefront` test files Section 1 named no longer exist.
- **Continue/advance carry a typed `proposal`.** The kit stores the negotiated
  amount as an exact integer parsed through `Decimal(str(value))`, never a float and
  never a 64-bit column, which is what lets an asset's base-unit amounts survive.
- **No hold exists before settlement.** Both storefronts ship
  `capacity.hold_ttl_seconds = 0`; `_place_capacity_hold` returns immediately. The
  reservation is created at settlement from the settlement order, which
  `build_vm_accepted_artifacts` derives from the listing record at acceptance.
- **The committed reservation governs fulfillment.** `fix-vm-fulfillment-capacity-boundary`
  made the reservation's dimensions and `claim_attributes` authoritative through
  scheduling and dispatch.
- **The family-grouped shape exists.** `kit/capability-shape` and
  `VM_CAPABILITY_SCHEMA` define the form and the VM vocabulary; round 0's
  `provision_terms.compute_resource` is still the flat `ComputeResource`.

### Decision: `resize_reservation` is not this change's to wire

With no pre-settlement hold, there is no reservation to resize during negotiation:
the claim built at settlement from the agreed shape is reserved fresh. A resize is
needed only when a hold was placed *before* the shape was final, and the change that
introduces such a hold is `negotiation-time-capacity-hold` (one superseded
reservation per negotiation, resized per differing-terms proposal). That change is
the first caller. This change's deliverable is that the agreed shape is what gets
reserved — through the accepted artifacts and settlement order, not through a
resize.

The title is kept for continuity with the campaign index and the roadmap; the
scope it names is "the capacity shape is negotiated", of which resizing was one
mechanism and is no longer the first.

### The negotiated variable becomes a rate multiplier (moved from `capacity-shape-pricing`, 2026-09-25)

This is the change's central decision and the one that is easy to get wrong. It was designed in `capacity-shape-pricing` on 2026-08-06 and moved here because it is one deployment boundary with the revised-terms field.

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
lower bound, and applies to every shape automatically. Under absolute-total
negotiation, a floor has to be recomputed per shape, which is where a shape-perturbation
attack would have entered.


### Decision: the multiplier is an integer in basis points, and every amount stays exact

A multiplier is a ratio; the kit's negotiated amount is an integer. The multiplier
is carried as **basis points over the advertised minimum rate structure**: 10,000
means 1.0×. The kit's `reference_amount`/`amount_from_proposal`/`proposal_from_amount`
hooks keep their integer contract, `bisection_middleware` converges on it unchanged,
and the seller's floor is one integer bound.

Amount arithmetic follows the rule the kit already applies: exact integers (Python
`int`) or `Decimal`, never `float`, and never a database `INTEGER` column — an
asset's base units exceed 64 bits routinely, and a wei amount that has been through
a float is a different number. The quote for a shape is
`ceil(evaluate(rates, shape, duration) × multiplier_bps / 10_000)` computed in
integers; rounding is upward so a quote is never below what the multiplier promises
the seller. A quote that would not fit the asset's own amount type is refused, not
truncated.

**Floor.** The seller's floor defaults to 10,000 (1.0×, the advertised minimum) and
is a policy bound a seller may lower explicitly for clearing idle capacity. When
lowered, "minimum rate structure" reads as the advertised reference structure; the
floor is still expressed once and applies to every shape. This resolves the first
open question `capacity-shape-pricing` deferred here.

**Wire.** The round carries the multiplier and, when it changes, the shape; the
quote is derived by both sides from the listing's advertised rate structure, which
is authoritative for both. It is not carried per round. If the advertised structure
ever stops being authoritative for both parties (a seller repricing mid-negotiation),
the derivation breaks and the quote would have to travel — that is the revisit
trigger. This resolves the second deferred question.

### Decision: the revised shape rides inside `proposal` as a `ProvisionTerms` envelope, in the family-grouped form

Placement and vocabulary were settled 2026-07-29 (child of `proposal`, the existing
opaque `ProvisionTerms` envelope, no new core concept). What is new: the payload's
shape is the family-grouped capability shape validated by `VM_CAPABILITY_SCHEMA`
through `kit/capability-shape`, not the flat `ComputeResource`. Round 0 keeps
`compute_resource` for now; whether it adopts the family form is
`settle-capacity-claim-vocabulary`'s question, not this change's.

### Decision: evaluation order inside the seller's round

For a round carrying a shape, the VM `evaluate_round` composition runs, in order:
admissibility (`capacity-shape-envelope`, if composed), authoritative feasibility
(`negotiation-capacity-feasibility-probe`, if composed), the seller's commercial
feasibility guard (`capacity-shape-pricing` Section 5), then pricing. Each is a
distinct refusal reason on the wire, because they lead to different counters:
change the ask, retry later, or accept the seller's counter. A domain that composes
none of the first two negotiates shapes on price alone and says so in its
composition, rather than silently.

### Decision: the agreed shape reaches the claim through the accepted artifacts

`build_vm_accepted_artifacts` writes the settlement order from the listing record.
After this change it writes the agreed shape into the order's `listing_resource`
quantities, so `compute_capacity_claim_from_order` — unchanged — builds the claim
from what was agreed. Nothing downstream needs to know a negotiation happened.

### Retiring Section 0's guard

`_validate_vm_opening` rejects a round-0 shape that differs from the listing because
nothing could price it. Once a differing shape is a proposal the seller evaluates,
round 0 is evaluated the same way as any later round. The guard's promotion record
above said "promote once Section 2 either lifts or permanently accepts this
restriction": it lifts it.

### Open questions

- **Should a seller be able to declare a listing shape-fixed** (no revised shape
  accepted), independently of the envelope? A pool with exactly one feasible shape
  is fixed by construction; a seller policy that simply refuses every revised shape
  achieves the rest. Leaning towards no declaration until a seller asks for one.
