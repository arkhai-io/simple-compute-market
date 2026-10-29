# In-lane payment and dispute authority doubles

## Why

The end-to-end lanes have no default payments target, so their payment scenarios
skip. The payments kit's in-process fake supplies a receipt and a placeholder
snapshot proof, not a service that can exercise authority records, transport
failures, rate stops, or case holds. A buyer's protection must rest on its own stop,
held money and kept signed bytes, including when the storefront fails or misbehaves.
Those paths need independently controllable payment and dispute authorities in the
lane, not a cooperative storefront masquerading as an authority.

## What Changes

- Own both runnable HTTP boundary doubles: `arkhai.payments.v1` and
  `arkhai.mediation.v1`, in one lane-only tooling image with separate services,
  identities, records and availability controls. Production adapters, contract
  vendoring and signing/verification primitives remain in their owning kits.
- Preserve two explicit contract modes, `published` and `proposed`. Published mode
  implements the exact vendored publication; proposed mode implements a pinned,
  labelled candidate where that publication lacks the target revision. The payments
  target is per-part authorities, payee-only rate start, pending stops with notice,
  term/exhaustion stops, `{afterStop: dispute_window}` holds and `extend`/`lift`.
  There is no backdated stop or released-funds refund extension.
- Add the dispute authority's file, append and read/watch boundary with signed
  per-agreement records. It extends holds as the authority, mechanically rules a
  sufficient seller self-penalty and an acknowledged `buyer_end(at)`, and sends
  everything else to controllable triage. Only the authority double applies a
  ruling's effects at the payment double.
- Keep mid-scenario control routes through a tooling-owned typed client: exhaustion,
  snapshot sequence/provenance faults, delay/drop/refusal, independent outages,
  signing-identity rotation and triage/effect retry. Lane services use wall time
  and due-work barriers; isolated tooling tests use injectable deterministic time.
- Use explicit lane-only HTTPS origins, a public development CA and fixture bearer
  auth; keep published clients' production transport/auth checks intact. Production
  composition refuses lane settings and identities. Add the double's own timer,
  classifier, retry and isolation suites as required work, not deferred approval.
- Wire lane-scoped targets, accounts, credentials and authority advertisements into
  the existing VM, bare-metal and API-credit lanes. Existing bare-metal and credits
  payment scenarios stop skipping; later compute lifecycle scenarios reuse the same
  services. API-credit dispute servicing is not added here.
- Attribute each run as qualification against the published contract, qualification
  against a proposed contract, or live evidence. Neither double can produce live
  evidence or `livemode: true`.

## Capabilities

### Modified Capabilities

- `test-compatibility`: runnable boundary doubles, authority separation, controls,
  contract provenance, lane readiness and evidence attribution.

### New Capabilities

None. These are test collaborators, not new production authorities.

## Dependencies and Related Changes

- `agreed-evidence-and-early-termination` owns the lifecycle interfaces, payment and
  dispute adapters, evidence stores, contract vendoring, and shared signed-frame
  primitives. Its schema/model work gates this change's corresponding published
  mode, not design. A pinned draft permits proposed-only qualification until then.
- This change alone owns the executable payment and mediation doubles and their
  controls. Kits keep vector-generated in-process contract fakes for unit and
  library-integration tests; they never depend on the tool. Its own tests exercise
  real clients, while lanes consume the runnable services. Foundation section 12
  does not build another executable double. Design D7 gives the section-level gates.
- `spot-deals-through-arkhai-payments` consumes both doubles for compute lane
  scenarios, retaining kit contract fakes for rate-part client integration; it owns production rate arithmetic and adapters.
- `activate-per-period-compute-servicing` compares the doubles with the vendored
  publication and qualifies the ready hosted deployment before claiming live
  servicing. Producer snapshot/start/reversal vectors also gate published
  qualification; until available, affected scenarios report proposed qualification.
  Hosted deployment is not a gate on building or using lane doubles.

## Non-Goals

Production payment/dispute services, production derivation or cryptographic
verification changes (the lane-only configuration refusal guard is in scope),
new payment primitives, bonds before the contract supports them, automated decisions
beyond the mediation contract's two mechanical classes, and live provider or ledger
qualification. Seller site deadlines and churn/pricing policy are not protocol
requirements and are not simulated as authority guarantees.

## Impact

A new tooling distribution and image under `tools/authority-lane-doubles`, a shared
lane overlay, root and e2e build/run targets, lane payment/dispute profiles and public
development identities, and existing payment scenario setup/reporting. The kits
remain independently scoped; only test tooling composes both interfaces.

## Permanent documentation impact

- [ ] `docs/development/ARCHITECTURE.md` (no new production layer or authority)
- [x] Existing subsystem specification: `test-compatibility`
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

- Double ownership, contracts, controls and evidence boundaries:
  `openspec/specs/test-compatibility/spec.md` and its architecture companion.
- How to run, configure and interpret lane qualification:
  `docs/development/TESTING.md`, "Payment Receipts in Tests" and "Private Service
  Dependencies", plus `e2e-tests/README.md`.
- Build and lock conventions are followed, not changed. The external authority
  contract itself remains documented by the foundation change, not by a test double.
