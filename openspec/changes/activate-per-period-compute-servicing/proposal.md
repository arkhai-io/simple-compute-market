## Why

Goal 8's MVP changes land before this one. `switch-on-hosted-per-period-vm`, the
last of them, declares rate servicing in the VM production composition for the
treatments the shipped presets use, `[charged, returned]`, makes Arkhai operators
the dispute authority under a published policy with operator runbooks, records live
evidence of VM deals — including a preemption and a term end returning the
unstarted remainder, the `chosen` dispute stop and reversal — and prepares the
hosted target and its readiness check. It owns reduced, VM-only forms of this
change's tasks 1.1, 1.2, 2.3–2.4 and 3.1–3.4 and of 1.3a's policy; each task below
keeps only the residual work and builds on what that change leaves. Turning the MVP
on does not complete Goal 8; this change's closeout does.

What remains is the full product: bare metal switched on; setup charges; the
mediation `delivery_end` revision and its mechanical rulings replacing the operator
procedures where they apply, with case extension and lifting on rate parts; and the
consolidated matrix of `serve-running-rate-deals` and
`converge-ongoing-compute-leases` run against the hosted authorities in both domains.

The hosted payments service documents every `partialPeriod` treatment as executed,
and runs the vendored revision on every deployment
(`kit/arkhai-payments/schema/SOURCE.md`); `switch-on-hosted-per-period-vm`
qualifies the treatments the presets use. Its external gates are now two: the hosted
mediation service running the vendored `delivery_end` revision
(`kit/arkhai-mediation/schema/SOURCE.md`) on the hosted targets, which mechanical
remedies, case extension and lifting, and setup returns need; and a qualified real
bare-metal host. A published schema alone is not deployment evidence. Unsupported
terms fail closed: each composition's servicing declaration lists the treatments it
has qualified, and publication, acceptance and materialization read that list. The
payment authority computes every partial period, never a storefront corrective
refund. No minimum spend or backdated payee stop is requested or awaited.

## What Changes

- Confirm that the hosted targets run mediation on the vendored `delivery_end`
  revision, and qualify on them what the MVP did not use: case extension and
  lifting on rate parts, setup parts, and `prorated` if a preset offers it.
- Requalify the in-lane doubles and the rate and dispute adapters against the
  vendored revision for the terms beyond the MVP, then verify the hosted target
  implements them.
- Declare servicing in the bare-metal production composition, and extend the VM
  composition's declared treatments to `prorated` only if a preset offers it, only
  after the deployment and consumer checks pass. Publication, acceptance and materialization
  stay fail-closed for any treatment a composition has not declared.
- Re-run the consolidated rate-servicing matrix in both double-backed lanes, and run the residual payment and dispute flows against the hosted target
  with its agreed dispute authority. Lane-double evidence and live evidence stay
  separate.
- Extend the MVP's published dispute-authority policy to mechanical rulings, and
  replace the operator runbooks the mechanical remedies supersede.
- Record activation and rollback operations and update Goal 8 and the campaign
  index at closeout. No existing deal is silently reinterpreted or moved to a new
  authority.

## Capabilities

### Modified Capabilities

- `settlement-configuration`: deployment-qualified production declaration.
- `test-compatibility`: hosted-deployment evidence distinct from double qualification.

### New Capabilities

None.

## Dependencies and scope

Internal readiness gates: `switch-on-hosted-per-period-vm` (the VM declaration,
the operators' policy and runbooks, the prepared hosted target, and the VM live
evidence, which builds on `serve-running-rate-deals`' servicing in both domains),
`converge-ongoing-compute-leases` (the remaining rate rows against the lane doubles
and three servicing fixes; it builds no funding timer and no operator recovery
command), `discover-open-ended-compute-listings` (discovery),
`renewable-compute-lease-deadlines` (the pool's delivery deadline, which the full
product publishes and the site enforces in place of the MVP's storefront-enforced
clause deadline) and `offer-a-seller-chosen-payout-hold` (the seller-chosen payout
hold and the penalty's collectibility rule; this change qualifies hosted whatever
hold that change offers, such as a `for` hold shorter than the stop plus the dispute
window). The foundation (`agreed-evidence-and-early-termination`), the payment and
mediation doubles (`add-arkhai-payments-lane-double`), unified delivery
(`unify-compute-delivery-path`), the terms (`negotiate-open-ended-compute-terms`)
and the rate mechanics, presets, seller notice and buyer end
(`spot-deals-through-arkhai-payments`) have landed. Identity re-anchoring across a
receipt key change is not a gate: the archived spot change made a key change a
drained cutover, and re-anchoring is unowned in Goal 8 of
`docs/development/ROADMAP.md`.

Internal dispute-adapter and mediation readiness includes `delivery_end` filings and
the sole qualifying mechanical payee self-penalty, not seller-direct correction.
Seller stop entries are only entitlements such as spot notice; spot emergency
files `delivery_end`. No seller restitution entry or several-stop-entries gate
remains. `end_delivery` supplies receipt evidence only; the buyer half owns the
payment stop, same-key outage retry and optional payee-signed `delivery_end` or
human triage. Schema and vector checks, credentials, target readiness and live
execution verify or use the gate; they do not introduce extra payment primitives.
This change does not redesign product terms, servicing, adjudication or site policy.
Any contract divergence requiring a product decision blocks activation and returns
to the owning change rather than weakening the declared guarantees.

## Impact

The vendored schema, vectors and SOURCE provenance, double conformance, both
compute compositions' production profiles and generated configuration, lane and
hosted evidence, the operator handbook, and permanent rollout documentation. This
is a design-stage change; it does not turn on any current deployment.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md` — production servicing and authority boundary
- [x] Existing subsystem specification: `settlement-configuration`, `test-compatibility`
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

The hosted-revision gate and the per-composition declared treatments, with their
coordinated extension and rollback, go to settlement-configuration's spec and
architecture companion and `docs/development/DEPLOYMENT_AND_CONFIG.md`. Evidence
provenance goes to test-compatibility's spec and architecture companion. The
mechanical rulings that replace operator procedures go to
`docs/operator-handbook.md` and `deal-lifecycle/architecture.md`. Goal 8 describes
held-money recovery and buyer stops; its completion record cites actual
hosted-deployment evidence. Reconciled servicing diagrams are promoted by the
servicing change, not copied a second time here.
