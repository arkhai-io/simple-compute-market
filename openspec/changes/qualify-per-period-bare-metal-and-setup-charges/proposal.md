# Qualify per-period bare metal and setup charges

## Why

On-demand and spot VM are a supported seller configuration, released in marketplace
0.4.0: a shipped chart example, seller, buyer and operator documents, and live evidence
that the hosted payment and dispute authorities emit what the lanes' doubles emit
(`docs/attachments/switch-on-hosted-per-period-vm/live-verification.md`). Three things
Goal 8 promises are not yet in that state.

**Per-period bare metal.** Both compute storefronts deliver and service a rate deal, and
the bare-metal lane runs the recurring purchase, the rate rows and the buyer's watchdog.
Nothing a seller, buyer or operator reads says so. The bare-metal chart's production
example settles through Alkahest only
(`helm/charts/bare-metal-storefront/examples/production-values.yaml`),
`docs/bare-metal-seller-quickstart.md` has no recurring section, the buyer quickstart
speaks of a VM by the period, the operator handbook's "Serving rate deals" speaks of a
VM storefront, and no live scenario runs the bare-metal buyer's commands against a
hosted authority.

**A setup charge.** The payments kit derives a setup part beside the rate, and a
bare-metal seller is recommended to price one, since provisioning a host costs the
seller whatever the deal's length. `deal-lifecycle`'s "Setup returns by delivered for
either cause" keeps setup-bearing presets disabled "until a hosted dispute authority is
qualified on the vendored delivery_end revision". No lane declares a setup charge, no
example prices one, and no live observation involves a setup part.

**Live observations still unmade.** An operator's ruling of a buyer's contested case has
never been observed live: the topology of the VM run applied no ruling policy. A case
over money already paid out, a stop replayed under its key, and whatever rows
`converge-ongoing-compute-leases` adds that reach an authority have no live twin.

Nothing here is switched on. A seller can declare per-period bare metal and a setup
charge on marketplace 0.4.0 today, since the declaration is the seller's own table and
nothing restricts it by domain. What is missing is the repository saying these are
supported, and the evidence for saying it.

## What Changes

- **Per-period bare metal becomes a supported seller configuration** (design D1): the
  bare-metal chart's production example offers on-demand and spot, rendered and checked
  as the VM example is; the bare-metal seller quickstart gains a section on offering
  them; the buyer quickstart and the operator handbook speak of both domains.
- **A setup charge becomes a supported seller configuration** (D1): the requirement
  that keeps setup-bearing presets disabled is reworded to what a setup-bearing option
  requires, and the documents say how a seller prices one and what a buyer is returned.
- **The live observations Goal 8 still lacks are made**, each as a live verification
  scenario extending a lane row, against a topology the deployment prepares (D2), on
  mock provisioning (D3). Which rows get a twin is the design session's, once
  `converge-ongoing-compute-leases` has landed its rows (D4, D5).
- **An operator's ruling of a buyer's contested case is observed live**, and this
  change does not close out without it (D6).
- **The roadmap states Goal 8's remaining acceptance criteria and what blocks each**
  (D4, D6, D7): the closeouts the goal waits for, the contested case, and mechanical
  remedies, which wait on a capability the hosted dispute authority owes.
- **No code gate is added, no switch is flipped and no default changes.** The servicing
  declaration gains no further role (D8).

What the design leaves open is in its "Open Questions": what bare-metal live evidence is
enough, how a setup charge becomes supported, which of converge's rows get a live twin,
what shows the mechanical-remedy criterion met, the bare-metal example's shape,
`prorated`, whether VM's observations are made again, and an unbuilt claim about an
advisory time to rule.

## Capabilities

### Modified Capabilities

- `deployment-state`: the bare-metal storefront chart's production example offering
  on-demand and spot.
- `deal-lifecycle`: "Setup returns by delivered for either cause", its sentence keeping
  setup-bearing presets disabled.
- `test-compatibility`: "Rate deals and dispute filings are verified live against a
  prepared topology", for the scenarios this change adds and the contested case's
  ruling.

`.openspec.yaml` sets `skip_specs` until the design session settles the open questions;
the design names the requirements to be modified.

### New Capabilities

None.

## Non-Goals

- A gate keyed to what a hosted authority has been shown to do, a default declaration,
  or anything declared in production (D1).
- Naming or preparing a hosted target. The deployment prepares a topology from the
  stated requirements (D2).
- A real bare-metal host. Real-host qualification is
  `complete-real-provisioning-qualification`'s (D3).
- Live verification of a payout hold's shape, which
  `offer-a-seller-chosen-payout-hold` makes itself (D4).
- Live observations a hosted authority cannot be made to produce: a storefront stopped,
  a payment authority out of reach, a funded instant it cannot confirm. Those are lane
  rows (D5).
- The dispute authority's policy and procedures, and any statement of how or when it
  provides a capability (D5, D7).
- Retiring the servicing declaration, tabled under Goal 8's unowned work (D8).
- Product terms, servicing, the mandate codec and payment arithmetic. A difference
  between a hosted authority's output and a lane twin's fails the observation and
  returns to the change that owns the code.

## Dependencies and Related Changes

- **`converge-ongoing-compute-leases` gates this change's design** (D4). The design is
  the list of which of its landed lane rows get a live verification twin, and whether a
  setup-bearing row exists to extend.
- No other change gates this one. Goal 8 waits for
  `discover-open-ended-compute-listings`, `filter-listings-by-capacity-bounds`,
  `enforce-delivery-deadlines-at-the-site`, `end-delivery-when-funding-runs-out` and
  `offer-a-seller-chosen-payout-hold` as closeouts the roadmap's "Done when" names, not
  through this change.
- `complete-real-provisioning-qualification` states the same rule for when a real-host
  run is owed (its design, D1) and rewrites the validation runbook's candidate rule to
  it. Whichever of the two lands first writes the rule to
  `docs/guidance/repository/qualification-evidence.md`; the other confirms the text and
  adds nothing.
- **External needs, at live verification, not at design** (D2, D6): a topology with
  Arkhai payments in test mode, a hosted mediation authority serving the vendored
  contract, this repository's services on mock provisioning, and a ruling policy for
  the buyer's contested case.
- **Builds on**, all archived: `switch-on-hosted-per-period-vm` (the live verification
  form, the VM scenarios and their shared assertions, the VM example),
  `serve-running-rate-deals` (rate servicing in both compute storefronts and the lane
  rows), `spot-deals-through-arkhai-payments` (the setup part and the recommendation
  that bare-metal sellers price one), `negotiate-open-ended-compute-terms` (the
  servicing declaration and its three doors), `agreed-evidence-and-early-termination`
  (the `delivery_end` claim and setup's return by delivery) and
  `add-arkhai-payments-lane-double` (both doubles).
- This change was `activate-per-period-compute-servicing` until 2026-11-26.

## Impact

`helm/charts/bare-metal-storefront` (the production example and its render test),
`e2e-tests` (live verification modules, their shared assertions' unit tests, and the
README's topology requirements), `docs/bare-metal-seller-quickstart.md`,
`docs/buyer-quickstart.md`, `docs/operator-handbook.md`, `docs/development/TESTING.md`,
and the companions of `settlement-configuration`, `deal-lifecycle` and
`test-compatibility`. No service code is expected to change.

Compatibility is owed to `marketplace-v0.4.0`, the newest release tag, which carries
every form this change touches as it stands on the development branch.

- **Configuration.** No key is added, removed or given a new meaning. A 0.4.0
  storefront accepts the configuration the bare-metal example will state.
- **Wire and persistence.** Nothing changes form.
- **Behaviour.** None changes. A requirement's wording about setup-bearing presets
  changes to match what a 0.4.0 storefront already admits.

## Permanent documentation impact

- [ ] `docs/development/ARCHITECTURE.md`
- [x] Existing subsystem specification: the capabilities above.
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

- D1: `docs/bare-metal-seller-quickstart.md`, `docs/buyer-quickstart.md` and
  `docs/operator-handbook.md`, "Serving rate deals", for the supported configurations;
  `openspec/specs/settlement-configuration/configuration.md`, "Settlement consumer
  configuration and cutover"; `openspec/specs/deployment-state/spec.md` for the
  bare-metal example.
- D2: `e2e-tests/README.md`, "Live verification", and `docs/development/TESTING.md`,
  "Live verification", for the scenarios and their topology requirements;
  `openspec/specs/test-compatibility/spec.md`.
- D3: `docs/guidance/repository/qualification-evidence.md`, for when a real-host run is
  owed.
- D4: `docs/development/ROADMAP.md`, Goal 8's "Done when", which carries the goal's
  order.
- D5: `openspec/specs/test-compatibility/architecture.md`, "Payment evidence
  ownership", for which observations are live and which are lane rows.
- D6: `docs/development/ROADMAP.md`, Goal 8; `openspec/specs/test-compatibility/spec.md`,
  for the contested case's ruling.
- D7: `docs/development/ROADMAP.md`, Goal 8; `openspec/specs/deal-lifecycle/architecture.md`,
  "External authorities" and "Current limits".
- D8: `docs/development/ROADMAP.md`, Goal 8's unowned work, where the row is recorded
  now.
