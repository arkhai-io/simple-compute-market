## Why

The per-period compute product may be qualified against in-lane doubles before
production can use its required payment semantics. Its external gate is the
**hosted deployment of the payments contract revision adding per-part authorities
and hold extensions**, including afterStop holds and partial reversals after stop,
and support for the stop terms actually offered. Unsupported started-period terms fail closed; the
payment authority computes them, never a storefront corrective refund. A supported
charged/charged subset may ship before the hosted deployment supports returned only with explicit
buyer-policy opt-in for payee and charged term ends, and only if every required
term is supported. On-demand always returns the partial period through the dispute
authority's qualifying mechanical self-penalty ruling.
A published schema alone is not deployment evidence. No
minimum spend or backdated payee stop is requested or awaited.

## What Changes

- Verify the revision and vectors through `kit/arkhai-payments/schema/SOURCE.md`,
  reusing the foundation's vendoring if already current; do not fork a contract.
- Requalify the in-lane double and rate-part adapters against the published
  revision, then verify the intended hosted target actually implements it.
- Enable the published-contract servicing declaration in both compute production
  compositions only after the deployment and consumer checks pass. Publication,
  acceptance and materialization remain fail-closed before this gate.
- Re-run convergence's consolidated rate-product matrix (including prepared spot
  entry points, distinct integration restart evidence and coherent real-time lanes)
  in both double-backed lanes and run the payment/dispute flows against the intended hosted test deployment with its
  agreed dispute authority. Keep qualification and live evidence separate.
- Record activation/rollback operations and update Goal 8 and the campaign index
  at closeout. No existing deal is silently reinterpreted or moved to a new authority.

## Capabilities

### Modified Capabilities

- `settlement-configuration`: deployment-qualified production declaration.
- `test-compatibility`: hosted-deployment evidence distinct from double qualification.

### New Capabilities

None.

## Dependencies and scope

Internal readiness gates: `agreed-evidence-and-early-termination` (per-part lifecycle,
holds and mediation), `spot-deals-through-arkhai-payments` (rate mechanics, presets,
publication and notice), `converge-ongoing-compute-leases` (servicing), and
`discover-open-ended-compute-listings` (discovery). The payment and mediation double
is supplied by `add-arkhai-payments-lane-double`; unified delivery is a transitive
servicing dependency. No dependency remains on the superseded settle or publish/
preempt changes.

The external payments capability gate is hosted deployment of that revision.
Internal dispute-adapter/mediation readiness includes exceptional_end filings and
the sole qualifying mechanical payee self-penalty, not seller-direct correction.
Seller stop entries are only entitlements such as spot notice; spot emergency
files exceptional_end. No seller restitution entry or several-stop-entries gate
remains. end_delivery supplies receipt evidence only; buyer half owns payment stop,
same-key outage retry and optional human-triaged buyer_end. Schema/vector checks,
credentials, target readiness and live execution verify/use the gate; they do not
introduce extra payment primitives.
This change does not redesign product terms, servicing, adjudication or site policy.
Any contract divergence requiring a product decision blocks activation and returns
to the owning change rather than weakening the declared guarantees.

## Impact

The existing vendored schema/vectors and SOURCE provenance, double conformance,
both compute compositions' production profiles and generated configuration,
lane/hosted evidence, and permanent rollout documentation. This is a design-stage
change; it does not turn on any current deployment.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md` — production servicing and authority boundary
- [x] Existing subsystem specification: `settlement-configuration`, `test-compatibility`
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

The hosted-revision gate and coordinated declaration/rollback go to
settlement-configuration's spec and architecture companion and
`docs/development/DEPLOYMENT_AND_CONFIG.md`. Evidence provenance goes to
test-compatibility's spec/architecture companion. Goal 8 describes held-money
recovery and buyer stops; its completion record cites actual
hosted-deployment evidence. Reconciled servicing diagrams are promoted by the
servicing change, not copied a second time here.
