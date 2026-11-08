# In-lane mediation double and controls for both doubles

## Why

Every lane runs a payments double, but no lane runs a dispute authority. The lanes'
registries recommend a fixture authority at a `.invalid` origin that nothing can
answer, so the VM payment scenario's case and refund stages skip and the bare-metal
buyer's delivery-end filing reaches nobody. Nothing in a public run exercises filing,
holds through `extend` and `lift`, rulings and their effects, or the failures a down
or misbehaving authority causes, and the payments double claims only its once-only
surface. Convergence's rate matrix and spot's rotation row have no lane to run in.

## What Changes

- **A mediation double** (`tools/mediation-lane-double`) beside the payments double in
  every lane. It reproduces the dispute authority's API mechanics — authentication,
  idempotency, signed per-agreement records and cursors, the respondent listing, the
  closed-case refusal, extensions at the payments double as its own account, and
  execution of a ruling's effects with stable keys and resume — and takes every
  decision as a scenario-programmed answer, as mock provisioning takes a job's
  outcome. With no rule, nothing is ruled. It duplicates none of the authority's
  decision logic.
- **Controls for both doubles** in a shared package (`tools/lane-double-controls`):
  when→then rules with refusals, filing-answer overrides, rulings and a gate before
  effects; operator decisions and closes; case and rule listings; funding and receipt
  signer rotation at payments; transport faults (unavailable, drop after commit) as
  shared middleware in the doubles; and a perceived clock each double reads, advanced
  by the scenario. The package holds the models, route declarations, typed client and
  middleware; the doubles and the e2e harness import it. Every control is a
  deterministic step.
- **The payments double claims its rate and hold surface**, proven by its own suite
  through the kit's real client over HTTP.
- **Lane wiring:** the mediation double in all three lanes, the lanes' registries
  recommending it in place of the `.invalid` authority, a lane-owned `MEDIATION` runner
  target that fails setup rather than skips, the buyer's mediation credential, and one
  lane CA issuing both doubles' certificates.
- **Mediation trust through configuration:** `[[DisputeCredential]]` gains an optional
  `ca_bundle_path`, which the mediation client uses as its verification context.
- **Scenarios:** the VM case and refund stages and the bare-metal filing run against
  the mediation double, and one VM-lane module on once-only deals proves each control
  kind once.
- **Evidence:** lane runs are labelled *lane doubles*, with the doubles' installed
  contract hashes; only a hosted target yields live evidence.

## Capabilities

### Modified Capabilities

- `test-compatibility`: the mediation double, the doubles' controls and perceived
  clock, the payments double's claimed surface, the lane-owned mediation target, the
  controls scenario, and lane-double evidence.
- `settlement-configuration`: a dispute credential may name the CA bundle its
  mediation client trusts.

### New Capabilities

None. The doubles are test collaborators, not production authorities.

## Dependencies and Related Changes

- `agreed-evidence-and-early-termination` (archived) supplies the lifecycle, the
  mediation kit and both vendored contracts; `add-mvp-payments-lane-double` (archived)
  supplies the payments double and its lane wiring, which this change extends.
- `converge-ongoing-compute-leases`, `spot-deals-through-arkhai-payments` and
  `activate-per-period-compute-servicing` consume the doubles and controls; the
  restatements their designs owe are listed in this change's design ("Effects on other
  changes").
- A lane-wide perceived clock covering storefronts, sites and the buyer half is a new
  change, opened after this one.

## Non-Goals

A rules engine reproducing either authority's decisions; contract modes or a proposed
evidence class; a production guard on fixture identities; storefront- or site-side
clock control; rate scenarios in lanes; a mediation double in the local Helm release;
corruption, delay or race faults; live, hosted-ledger or adjudication evidence.

## Impact

- New `tools/mediation-lane-double` and `tools/lane-double-controls` projects and the
  `arkhai:mediation-lane-double` image; the lane CA generator moves into the controls
  project.
- `tools/payments-lane-double`: the controls, perceived clock and middleware, a token
  for the dispute authority's account, and suite coverage of the rate and hold surface.
- `kit/deal-lifecycle` and `kit/arkhai-mediation`: `DisputeCredential.ca_bundle_path`
  and the client's CA argument; the VM and bare-metal storefronts' and buyers'
  lifecycle compositions pass it.
- Compose: `compose.payments-double.yml` runs the mediation double; lane registry and
  runner profiles, Bob's secret overlay and the buyer configuration writer change.
- `e2e-tests`: the mediation helper and settings, the VM case stages and bare-metal
  filing assertions, a controls module, and a dependency on the controls package.
- `helm`: the local release's registry recommendation and copied dispute credential;
  no new subchart.
- No database migration and no wire change.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md`
- [x] Existing subsystem specification: `test-compatibility`, `settlement-configuration`
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

- D1: `openspec/specs/test-compatibility/spec.md` (delta) and `architecture.md`, a
  section on the in-lane mediation double beside "The in-lane payments double";
  `tools/mediation-lane-double/README.md`; the programmed-decision principle in
  `docs/development/ARCHITECTURE.md`, "Testing strategy", and
  `docs/development/TESTING.md`, "Private Service Dependencies".
- D2: `openspec/specs/test-compatibility/spec.md` (delta); the perceived-clock rule in
  `docs/development/TESTING.md`, "The discipline every scenario follows", and
  `docs/development/ARCHITECTURE.md`, "Testing strategy"; the lane-wide clock as an
  unowned gap in `docs/development/ROADMAP.md`.
- D3: `openspec/specs/test-compatibility/spec.md` (delta);
  `openspec/specs/test-compatibility/architecture.md`, "Payment evidence ownership".
- D4: `openspec/specs/test-compatibility/spec.md` (delta);
  `tools/lane-double-controls/README.md`; `tools/README.md`, "Lane collaborators";
  `docs/development/TESTING.md`, "Private Service Dependencies".
- D5: `openspec/specs/test-compatibility/architecture.md`; `docs/development/ROADMAP.md`,
  the hosted dispute-authority row.
- D6: `openspec/specs/test-compatibility/spec.md` (delta); `e2e-tests/README.md`.
- D7: `tools/mediation-lane-double/README.md`; `tools/lane-double-controls/README.md`;
  `tools/README.md`, "Lane collaborators"; `dev-env/identities/README.md`.
- D8: `openspec/specs/settlement-configuration/spec.md` (delta);
  `docs/development/DEPLOYMENT_AND_CONFIG.md`; `kit/arkhai-mediation/README.md`.
- D9: `openspec/specs/test-compatibility/spec.md` (delta); `docs/development/TESTING.md`,
  "Private Service Dependencies"; `e2e-tests/README.md`.
- D10: `openspec/specs/test-compatibility/spec.md` (delta);
  `tools/payments-lane-double/README.md`.
- D11: `docs/development/TESTING.md`, "Private Service Dependencies", which states the
  local release runs no mediation double.
- D12: no permanent destination — it removes scope from this change's earlier design.
- D13: no permanent destination — an implementation cadence, recorded in the change's
  history.
- Roadmap: Goal 8's row for this change and convergence's row restated, and this
  change's closeout recorded: `docs/development/ROADMAP.md`.
