# Proposal

## Why

No end-to-end lane can run a purchase settled in `arkhai.payments.v1`. With no
payments target configured, every payment scenario reports a blocked skip
(`e2e-tests/tests/e2e/roles/helpers/payments.py`), so the payment path is verified only
against an external deployment. The kit's `FakePaymentsClient` is in-process: it cannot
serve a buyer CLI subprocess or a storefront container.

The payments service lives outside this repository, so it has no mock mode the way
provisioning does. Its locally verifiable stand-in has to be a double of its public HTTP
contract that runs in the lane. `add-arkhai-payments-lane-double` designs such a double,
together with a mediation double, the per-part rate revision, contract modes, fault
controls and evidence classes for Goal 8. That scope is gated surface by surface on
contract publication, and none of it is needed for a once-only purchase.

`qualify-real-provisioning-by-scenario` needs a locally verifiable buyer purchase in the
VM and bare-metal lanes, which its external-topology qualification scenarios then extend.
That purchase uses only the once-only surface. This change delivers that surface first,
as the minimum `add-arkhai-payments-lane-double` later builds on.

## What Changes

- **R1. A once-only payments HTTP double.** A lane-only tooling service wraps the
  payments kit's existing clock-injected `PaymentsAuthority` engine, the engine
  `FakePaymentsClient` uses, so there is no second ledger. It serves approval, exact
  Agreement attachment, signed receipts, transaction snapshots and seller reverse,
  with per-account authentication and idempotency, through the kit's real
  `PaymentsClient`. It refuses every operation outside that set. It always signs
  `livemode: false`.
- **R2. A lane-only HTTPS origin under a development CA.** Lane storefronts and the
  buyer trust that CA explicitly through `SSL_CERT_FILE`. Production transport checks
  are unchanged: HTTPS outside loopback, no verification bypass.
- **R3. Deterministic fixture accounts.** Buyer, seller and dispute-authority accounts
  and their keys are visibly public development values, never to be used on a public
  network, and production configuration refuses them. The double seeds the buyer's
  balance. In the local tier this stands in for the funding a deployment performs as
  topology.
- **R4. VM and bare-metal lane wiring.** Each lane's stack runs the double and sets its
  `PAYMENTS` settings, so payment scenarios run rather than skip. A double that is not
  ready fails lane setup by name.
- **R5. A pinned dispute authority nobody answers.** The lane storefronts and the
  buyer accept a fixture dispute-authority identity whose account exists at the double.
  No service answers at its origin, matching a hosted deployment with no controllable
  dispute authority.
- **R6. The payer's balance read.** The kit's `PaymentsClient` gains a call for the
  payer's own balance, using a route the payments service already serves, and the
  double serves it.
- **R7. The harness readiness probe trusts an explicit CA.** The e2e payments helper
  checks a target's readiness with TLS verification built from `SSL_CERT_FILE` when it
  is set, keeping environment proxies disabled.

First consumers:
- `qualify-real-provisioning-by-scenario`'s locally verifiable buyer purchases in the
  VM and bare-metal lanes;
- the existing bare-metal payment scenario, which stops skipping.

No mediation double, rate part, stop or hold, contract mode selector, fault control or
evidence class is introduced; those remain `add-arkhai-payments-lane-double`'s.

## Capabilities

### New Capabilities

None. The double is a test collaborator, not a production authority.

### Modified Capabilities

- `test-compatibility`: lanes run payment scenarios against an in-lane once-only
  payments double.

## Impact

- New lane-only tooling project for the double, with its image built from the
  repository wheelhouse and lock.
- `kit/arkhai-payments`: the balance call and its tests.
- `e2e-tests`: lane Compose stacks, lane configuration, and the payments helper's
  readiness probe.
- `add-arkhai-payments-lane-double`: its D1 (tooling ownership) and D7 (one owner of the
  doubles) are revised at its design reverification, to extend this double rather than
  own the whole tool.

## Permanent documentation impact

- [ ] `docs/development/ARCHITECTURE.md`
- [x] Existing subsystem specification
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

- The in-lane payments double and what it does not claim (no hosted-ledger or live
  evidence): `openspec/specs/test-compatibility/spec.md` and `architecture.md`.
- Lane setup and the payments settings each lane supplies: `docs/development/TESTING.md`
  and `e2e-tests/README.md`.
