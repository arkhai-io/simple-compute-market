## Why

The harness's purpose is to declare a finite set of capacity scenarios, run
them outside this repository, and evaluate the recorded results. Nothing in the
repository declares what a scenario is. Without that, every result is evaluated
against whatever the evaluator happened to assume, and a scenario cannot be
reviewed before it runs.

This change adds the declaration and its validation. It executes nothing.

Three findings from grounding against `e91767a3` shape the contract, and each
would silently corrupt results if the schema ignored it.

**The scarcity signature is not a closed vocabulary.** The intended assertion is
HTTP 409 with `error=offer_unfulfillable` and `reason=no_matching_inventory`.
`error` is stable. `reason` is not: it arrives from four raise sites in
`sync_negotiation.py`, and two interpolate.

| Raised as | Shape |
|---|---|
| `f"resource_shape_not_negotiable: {mismatched}"` | interpolated |
| `f"listing_not_open (status={listing_status!r})"` | interpolated |
| `"no_floor_price"` | stable |
| `decision.reason or "rejected"` | policy-supplied, or a generic fallback |

`no_matching_inventory` reaches the response through the last of those — it is a
negotiation policy's reject reason passed through, not a distinct code path. The
same channel also carries `compute_duration_invalid:...` and
`missing_amount:...`, both interpolated. A scenario that asserts equality on
`reason` is asserting on a string the product does not promise to keep stable.

**Expected scarcity depends on deployed configuration, not only on code.**
`capacity.hold_ttl_seconds` ships as `0` — no capacity is held before escrow
settles, so exclusivity arises only from a settled deal. The local compose
profile deliberately overrides it to `900` to keep the two-phase reserve path
under e2e coverage. The dev cluster runs the shipped posture.

So the same scenario, at the same product revision, has different correct
outcomes in the two environments: with a hold, a losing concurrent buyer is
refused at negotiation; without one, it may settle and then find the capacity
gone. A scenario that does not declare the posture it assumes is not evaluable.

**A losing buyer that never saw the listing is indistinguishable from a losing
buyer that lost.** Buyer discovery is a union across configured registries, and
the fan-in client logs and swallows per-registry failures. A buyer whose
registry was unreachable finds nothing and fails differently from one that
contended and lost — an environment outcome that would be recorded as scarcity
or as a product defect.

## What Changes

- A scenario schema declaring, for one scenario: deal type, GPU topology, actor
  counts by role, arrival mode, the pinned buyer and seller quickstart
  references, expected successes, expected refusals with their signatures, retry
  prohibition, and cleanup expectations.
- A scenario declares the **capacity hold posture** it assumes. Validation
  refuses a scenario whose declared posture is absent, and evaluation of a
  result against a target with a different posture is a contract violation
  rather than a failed assertion.
- A refusal expectation names a **status code, a stable error code, and a reason
  match mode** — exact for reasons the product emits verbatim, prefix for the
  interpolated ones. A scenario may not assert equality against an interpolated
  reason.
- A scenario declares a **discovery receipt requirement** per buyer: the buyer
  proved it observed its assigned listing before the arrival barrier released.
  A result missing a receipt is inadmissible, not a failure.
- The finite set is declared as fixtures: a single-buyer qualification, a
  controller-driven reference row, the buyer-contention rows, a fan-in
  completeness row, and the fan-out multi-market contention rows. Rows requiring
  topologies the product does not support are not declared — see Impact.
- Validation runs at load: schema shape, closed vocabularies, internal
  consistency between declared counts and declared expectations, and refusal of
  anything outside the finite set.

Not in scope, deliberately: any actor, any runner, any execution, any adapter,
any result evaluation against a live system, and any finding schema. This change
declares what a scenario is and proves the declarations are admissible. Nothing
in it runs a scenario.

## Impact

- Affected specs: `test-compatibility`
- Affected code: `tools/issue-discovery/schemas/`,
  `tools/issue-discovery/config/capacity/scenarios/`,
  `tools/issue-discovery/src/issue_discovery/`, `tools/issue-discovery/tests/`
- Depends on `restore-issue-discovery-thin-runner`: the scenario loader uses the
  entry-point resolution that change introduces, and both touch the tool's
  configuration layer.
- **Seller-process contention rows are not declared.** One storefront serves one
  site, and the fulfillment callback binds to one storefront — the provisioning
  service holds a single storefront URL and admin key — so a second seller can
  negotiate and can never fulfil. `domains/vms/storefront/storefront.alice.toml`
  records this already, and the many-to-many storefront-to-authority axis was
  removed from `market-platform-compute-40-multi-domain-proof`'s scope
  deliberately. That constraint is unchanged by this change.
- **"Seller service" is reinterpreted as the market a resource is listed on.**
  Approved by product authority 2026-08-13, on the grounds that the
  storefront-to-registry layer is what carries the anti-vendor-lock claim.
  Registry and storefront are N:N in both directions. This is a
  reinterpretation, not a clarification: the phrase originally meant seller
  processes, and the substitution does not prove several sellers competing,
  cross-storefront arbitration, or per-seller fulfillment isolation. Fixture
  identifiers name the market axis `m` and leave `s` unused so the two readings
  cannot be confused.
- **Whole-GPU assignment is not assertable yet.** The accepted VM shape does not
  reach the provisioning request (`fix-vm-fulfillment-capacity-boundary`, one
  task open), so no scenario can currently assert that the GPU reserved is the
  GPU received. Scenarios declare the expectation; a result claiming it is
  inadmissible until that change lands. Recorded rather than deferred, so the
  contract does not have to be reopened.
- Behaviour change to record: none. This change adds declarations and a
  validator and alters no product behaviour.
- Product gap surfaced, not fixed here: `reason` in the unfulfillable response
  is an open string set, two members interpolated, one a generic fallback. A
  closed reason vocabulary would let a scenario assert exactly. That is a
  product change with its own consumers — the buyer CLI and the e2e suite read
  the same field — and does not belong to the harness.

## Permanent documentation impact

- [ ] `docs/development/TESTING.md` — what a declared scenario is and what the
  harness validates about it, extending the section
  `restore-issue-discovery-thin-runner` rewrites
- [ ] Existing subsystem specification — `test-compatibility`
- [ ] `docs/development/ARCHITECTURE.md` — none owed
- [ ] New subsystem specification — none owed
- [ ] `docs/development/ROADMAP.md` — none owed; the harness holds no goal row

### Knowledge to promote

See the design-promotion record in `tasks.md`.
