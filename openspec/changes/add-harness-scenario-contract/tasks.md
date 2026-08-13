# Tasks

One commit. The schema, the fixtures that exercise it, and the validation that
refuses a bad one are a single reviewable unit — a schema without fixtures is
unexercised, and fixtures without validation are a directory of JSON.

Baseline: `origin/dev` at `e91767a3b074b20168bbcb87a8418d8287e5f8a6`. Re-pin
before starting.

Sequenced after `restore-issue-discovery-thin-runner`: the scenario loader
builds on the entry-point resolution that change introduces, and both touch the
tool's configuration layer.

Nothing here executes a scenario. If a task appears to need a runner, an actor,
an adapter, or a live target, the plan premise is wrong — pause for design
review rather than adding one.

## 1. Scenario schema

- [ ] 1.1 Add `tools/issue-discovery/schemas/capacity-scenario.schema.json`
  declaring: scenario identity, deal type, GPU topology, actor counts by role,
  arrival mode, pinned buyer and seller quickstart references, expected
  successes, expected refusals, retry prohibition, and cleanup expectations.
  Every vocabulary is closed and enumerated in the schema; no free-string field
  carries meaning the evaluator will later parse.
- [ ] 1.2 Require `capacity_hold`, one of `held` or `none`. No default. A
  scenario that omits it is inadmissible, because its contention expectations
  are unevaluable without it — see `design.md`, "A scenario declares the hold
  posture it assumes".
- [ ] 1.3 Model a refusal expectation as `status`, `error`, `reason`, and
  `reason_match` of `exact`, `prefix`, or `any`. Enumerate in the schema which
  reasons the product emits verbatim: `no_floor_price`, `no_matching_inventory`,
  and the bare fallback `rejected`.
- [ ] 1.4 Require a per-buyer discovery receipt in any scenario with more than
  one buyer: the market the buyer was assigned, the listing it was assigned, and
  that it observed that listing through that market before the barrier released.
  Both dimensions vary — registry and storefront are N:N — so neither can be
  implied.
- [ ] 1.5 Model market multiplicity: the registries a listing is published to,
  and the storefronts a registry indexes. A fan-out row declares one storefront
  and several registries; a fan-in row declares one registry and several
  storefronts.
- [ ] 1.6 Model a withdrawal expectation: after the successful deal, the sold
  capacity is absent from every registry that carried the listing. Required on
  fan-out contention rows.
- [ ] 1.7 Model the whole-GPU assignment expectation, and mark results claiming
  it inadmissible pending `fix-vm-fulfillment-capacity-boundary`. The accepted
  VM shape does not currently reach the provisioning request, so the claim
  cannot be substantiated. Declaring the field now avoids reopening the contract
  when it can be.

## 2. The finite set

- [ ] 2.1 Declare the single-buyer qualification row under
  `tools/issue-discovery/config/capacity/scenarios/`. One buyer, one seller, one
  physical GPU, one expected success, no contention.
- [ ] 2.2 Declare the controller-driven reference row. Mark its evidence class
  as product-and-environment evidence rather than agent evidence — a
  controller-driven row proves the path works, not that an agent can traverse
  it.
- [ ] 2.3 Declare the buyer-contention rows: several buyers, one seller, one
  physical GPU, common arrival barrier, exactly one expected success, and a
  declared refusal signature for each remaining buyer.
- [ ] 2.4 Declare the fan-out contention rows: one storefront, one physical GPU,
  one listing broadcast to several registries, buyers arriving through different
  registries on a common barrier, exactly one success, a declared refusal
  signature for each remaining buyer, and withdrawal from every registry that
  carried the listing.
- [ ] 2.5 Declare the fan-in completeness row with the qualification rows, not
  the contention set: one registry, several storefronts, separate resources, the
  buyer's union complete and its listings distinct. It declares no scarcity —
  the sellers are not competing — and a fan-in result must not be read as
  evidence about the fence.
- [ ] 2.6 Name the market axis `m` in fixture identifiers and leave `s` unused.
  The archival fixtures used `b<buyers>-s<sellers>-g<gpus>` with `s` counting
  seller processes; reusing it for markets would silently change its referent.
  See `design.md`, "Seller service is reinterpreted".
- [ ] 2.7 Do not declare seller-process contention rows, and do not declare them
  disabled. One storefront serves one site and the fulfillment callback binds to
  one storefront, so a second seller cannot fulfil and the row could not pass.
  The market reinterpretation is the approved substitute and does not make this
  representable.
- [ ] 2.8 Each fixture names the pinned public revision its expectations were
  derived against, so a later reader can tell whether the product moved
  underneath it.

## 3. Validation

- [ ] 3.1 Add scenario loading to
  `tools/issue-discovery/src/issue_discovery/`, validating shape against the
  schema and refusing anything outside the finite set.
- [ ] 3.2 Validate internal consistency, not just shape: declared successes plus
  declared refusals equal the declared buyer count; every buyer in a
  multi-buyer scenario has a discovery receipt requirement naming a declared
  market and a declared listing; an arrival barrier is declared only where there
  is contention to order; a withdrawal expectation names only registries the
  listing was declared as published to.
- [ ] 3.3 Refuse a scenario that declares several storefronts contending for one
  resource. The topology cannot exhibit it, and a fixture that can never pass
  invites making it pass by changing the product to suit the harness.
- [ ] 3.4 Refuse `reason_match: exact` against a reason the schema marks
  interpolated. Name the reason and the permitted modes in the error.
- [ ] 3.5 Refuse a scenario whose deal type, GPU count, or actor topology falls
  outside the finite set, naming which constraint it violated.
- [ ] 3.6 Report every violation from one load rather than the first.

## 4. Tests

- [ ] 4.1 Add `tools/issue-discovery/tests/test_capacity_scenarios.py`: every
  shipped fixture validates; a missing `capacity_hold` is refused; `exact`
  against an interpolated reason is refused; counts that do not reconcile are
  refused; a multi-buyer scenario without discovery receipts is refused; a
  receipt naming an undeclared market is refused; a withdrawal expectation
  naming an unpublished registry is refused; several storefronts contending for
  one resource is refused; an out-of-set topology is refused; several violations
  report together.
- [ ] 4.2 Assert the fixtures are the finite set — a test that fails when a
  fixture is added or removed without the schema's enumeration changing to
  match. The set being finite is the contract, not an accident of the directory
  contents.
- [ ] 4.3 Do not add a test that runs a scenario. There is nothing to run.

## 5. Documentation

- [ ] 5.1 Extend `docs/development/TESTING.md`'s harness section — as rewritten
  by `restore-issue-discovery-thin-runner` — with what a declared scenario is
  and what validation guarantees. Do not restate the schema; state the two
  properties a reader needs: the set is finite, and a declaration is refused
  rather than coerced.
- [ ] 5.2 Record in `docs/development/ISSUE_DISCOVERY.md` how to validate the
  declared set, and that validation executes nothing.
- [ ] 5.3 Verify every path and requirement cited by both documents exists on
  the branch before marking done.

## 6. Closeout

- [ ] 6.1 **Comment hygiene.** Run `make check-comment-hygiene` and resolve every
  match; read touched files for the fuzzier violations the target cannot catch.
- [ ] 6.2 **Import placement.** Migrate local imports added by this change to
  module level where safe, verifying each against the real suite.
- [ ] 6.3 **Documentation compliance.** Re-check accepted decisions against
  `openspec/README.md`'s placement rules, and confirm every citation resolves.
- [ ] 6.4 **Narrative compression.** Reduce task notes to final behaviour,
  validation evidence, unresolved work, and promotion destinations. The reason
  vocabulary analysis and the topology finding belong in `design.md`.
- [ ] 6.5 **Roadmap currency.** `docs/development/ROADMAP.md` owes nothing: the
  harness is not a market capability and holds no goal or gap row. Recorded as a
  deliberate disposition.
- [ ] 6.6 **Promotion.** Complete the design-promotion record below.

## Design promotion record

| Accepted decision | Permanent location | State |
|---|---|---|
| A declared scenario set is finite, and a declaration outside it is refused rather than coerced | `docs/development/TESTING.md` | Pending |
| Validating the declared set executes nothing | `docs/development/ISSUE_DISCOVERY.md` | Pending |
| `Capacity scenarios are finite, declared, and non-executing`, `A scenario declares the capacity hold posture it assumes`, `Refusal expectations name a match mode`, and `Multi-market contention is declared over markets, not seller processes` | `openspec/specs/test-compatibility/spec.md` | At archival |
| "Seller service" in a capacity scenario means the market a resource is listed on, and a multi-market result is not evidence about seller-process competition | `docs/development/TESTING.md` | Pending |
