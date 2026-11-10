## Why

Goal 8's MVP changes land before this one. `switch-on-hosted-per-period-vm`, the
last of them, declares per-period servicing in the VM production composition for
the `charged` treatment only, makes Arkhai operators the dispute authority under a
published policy with operator runbooks, records live evidence of the MVP's rows,
and prepares the hosted target and its readiness check. It owns reduced, VM-only
forms of this change's tasks 1.1–1.3, 2.3–2.4 and 3.1–3.4; each task below keeps
only the residual work and builds on what that change leaves. Turning the MVP on
does not complete Goal 8; this change's closeout does.

What remains is the full product: bare metal switched on; the `returned` and
`prorated` treatments executed live, so a seller's preemption returns the unstarted
remainder; the mediation `delivery_end` revision and its mechanical rulings
replacing the operator procedures where they apply; and convergence's consolidated
matrix run against the hosted authorities in both domains.

Its external gate is the hosted payments deployment executing what the MVP does not
use: `returned` and `prorated` on every stop entry and the term end, the dispute
authority's stop entry with `chosen` treatment, hold extension and lifting on rate
parts, and partial reversal after a stop; and the hosted mediation service running
the vendored `delivery_end` revision. The contracts themselves are published and
vendored (`kit/arkhai-payments/schema/SOURCE.md`,
`kit/arkhai-mediation/schema/SOURCE.md`); a published schema alone is not
deployment evidence. Unsupported terms fail closed: each composition's servicing
declaration lists the treatments it has qualified, and publication, acceptance and
materialization read that list. The payment authority computes every partial
period, never a storefront corrective refund. No minimum spend or backdated payee
stop is requested or awaited.

## What Changes

- Confirm, with the payments service's maintainers, that the hosted target
  executes the residual gate above, extending the answers the MVP obtained.
- Requalify the in-lane doubles and the rate and dispute adapters against the
  vendored revision for the terms beyond the MVP, then verify the hosted target
  implements them.
- Extend the VM composition's declared treatments to `returned` and `prorated`,
  and declare servicing in the bare-metal production composition, only after the
  deployment and consumer checks pass. Publication, acceptance and materialization
  stay fail-closed for any treatment a composition has not declared.
- Re-run convergence's consolidated rate-servicing matrix in both double-backed
  lanes, and run the residual payment and dispute flows against the hosted target
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
the operators' policy and runbooks, the prepared hosted target),
`spot-deals-through-arkhai-payments` (rate mechanics beyond `charged`, setup parts,
presets, notice and identity re-anchoring), `converge-ongoing-compute-leases`
(servicing and its consolidated matrix), `discover-open-ended-compute-listings`
(discovery) and `renewable-compute-lease-deadlines` (the pool's delivery deadline,
which the full product publishes and the site enforces). The foundation
(`agreed-evidence-and-early-termination`), the payment and mediation doubles
(`add-arkhai-payments-lane-double`) and unified delivery
(`unify-compute-delivery-path`) have landed.

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
