# Permanent compute-domain lifecycle qualification

Nonvisual implementer qualification of O-F1's sections 14/15, starting at
`e118120be`. These encounters use invocation-owned SQLite and signed in-process
HTTP, not a deployed hosted VM or independent acceptance.

## Required and prepared setup

The target is this checkout's installed VM and bare-metal storefronts composing
the real lifecycle services and the payments kit's vector-derived fixture.
Mediation filing uses the kit's installed contract peer. The entitled admin
case injects a future stop adapter to prove dispatch ordering, not current
once-only rate execution. All personas are public deterministic development
fixtures, never identities for a public network. No secret, inherited deployment
selector or persistent seed state is required.

From repository root, prepare and directly open the stories:

```sh
unset ALL_PROXY all_proxy
export NO_PROXY=localhost,127.0.0.1 no_proxy=localhost,127.0.0.1
make dist
make -C domains/vms/storefront reinit
(cd domains/vms/storefront && uv run --no-sync pytest -q \
  tests/unit/test_lease_end_precision.py tests/unit/test_interrupt_deal_admin.py \
  tests/integration/test_lifecycle_acceptance.py \
  tests/integration/test_lifecycle_admission.py \
  tests/integration/test_lifecycle_admin.py \
  tests/integration/test_lifecycle_failures.py \
  tests/integration/test_lifecycle_ends.py \
  tests/integration/test_payment_settlement.py \
  tests/integration/test_lifecycle_cycle.py \
  tests/integration/test_servicing_composition.py)
make -C domains/bare_metal/storefront reinit
(cd domains/bare_metal/storefront && uv run --no-sync pytest -q \
  tests/integration/test_lifecycle_dispatch.py \
  tests/integration/test_lifecycle_ends.py \
  tests/integration/test_buyer_lifecycle_recovery.py)
```

The tests clean their own databases and clients. Readiness here is successful
installation and signed application composition, not a deployed-service probe.
VM unit/integration and bare-metal discovery already run in root `make test`;
`test-storefront` and `test-bare-metal` in `.github/workflows/tests.yml` run those
same targets. No new optional first-use target substitutes for those suites.

## Permanent coverage map

Paths below are under the named storefront's `tests/` directory.

| Task | Lowest meaningful retained coverage |
| --- | --- |
| 14.1 | VM `integration/test_lifecycle_acceptance.py` negotiates hosted terms and checks the original buyer envelope, exact signed seller acceptance and expiry. Existing `test_payment_settlement.py::test_settlement_is_pending_until_a_verified_receipt_then_delivers_once` checks the authenticated lifecycle list and exact transaction reference. |
| 14.2 | VM `integration/test_lifecycle_admission.py` covers surrender/ruling before dispatch, independent coordinator reconstruction, in-flight surrender and no credential disclosure. Existing payment tests retain refund-before/after-start, terminal/restart and exactly-once delivery. `test_lifecycle_failures.py` covers delayed lawful correlation, signed unentitled withdrawal and direct hardware-failure dispatch with a payee filing. |
| 14.3 | VM `unit/test_lease_end_precision.py` covers seconds, offsets and historical minute reads. `integration/test_lifecycle_admission.py` sends a mid-minute future end through the real capacity client and checks the site's retained instant. Existing admin unit cases retain second-precision assertions. |
| 14.4 | VM `integration/test_lifecycle_admin.py` drives signed admin HTTP on both branches: authority-effective notice ordering, or attributed unentitled teardown independent of filing loss, same-key recovery to one case and changed-content refusal. |
| 14.5 | VM `integration/test_lifecycle_ends.py` composes the actual buyer half and canonical client for hosted commit/end: wrong buyer/site, forged inner proof, duplicate push, signed typed pull, exact bytes/headers, earlier-end ordering, payee filing through the installed mediation peer without a local reversal, buyer evidence and callback-only capacity progress. Admission cases cover pre-provisioning and in-flight ends. Existing e2e end/report stages remain; these tests do not substitute for O-F18. |
| 15.1 | Bare metal `integration/test_lifecycle_dispatch.py` and existing `test_lifecycle_ends.py` cover lawful teardown without a payment reversal, before-dispatch refusal, reconstructed reconciliation and create adoption. Existing payment integration retains terminal/refund admission and restart. |
| 15.2 | Bare metal `integration/test_lifecycle_dispatch.py` covers wrong buyer/site, end returning during blocked create, one adopted termination, repeated teardown, exact signed push/retry/pull and separate capacity-release callback. Existing `test_buyer_lifecycle_recovery.py` retains canonical buyer-half recovery after policy rotation. |

The VM payment example now asserts pending/provisioning/ready rather than
merely printing. Admin and site examples follow credential-independent adapter
composition and earlier-end behavior without relaxing proof/dispatch assertions.

## Defect found by the permanent encounter

Off-loop seller journal preparation exposed a VM admin interruption race:
`asyncio.gather(submit, drive_physical)` could run physical lookup before the
local end existed. Physical driving then returned without acting. An authority
gated on teardown could never answer; retry was the first chance to dispatch.

The seller now exposes local end recording independently of submission. VM
awaits that immutable record before independently driving teardown and filing.
No authority I/O precedes teardown and no money remedy is computed locally.
The unentitled admin case fails under the original ordering and passes with
the repair. Its authority waits on a deterministic event, not a sleep.

## Preparation corrections

The hosted negotiation fixture initially omitted the scalar amount required
by its priced option and the runtime's explicit agreement-settlement dispatch
entry. Supplying both opens the actual hosted acceptance path; no server rule
was relaxed. The admin peer also needs the domain credential-availability
seam, not only the seller service's predicate. The retained test supplies that
seam and keeps the authority behind the teardown event.

The old payment example expected a never-delivered surrender claim with
`delivered=false`; the accepted receipt contract requires `delivered=true`
when surrender is selected. The example and permanent pre-delivery test now
assert that contract. Earlier seller ends still suppress an automatic payer
claim, as the signed-site/buyer encounter verifies.

## Validation and continuation

- Final focused re-drive: VM **50 passed**; bare metal **7 passed**.
- Servicing **48 passed**, with typing clean across all 11 source files.
- Architecture, fresh-wheelhouse packaging, locks, comment hygiene and pinned
  OpenSpec 1.14.0 strict change validation pass. No dependency or lock changed.
- The required focused/check/aggregate chain completes in **8m44s**, including
  a passing shim-backed full `make test`: VM storefront **1,196 unit passed**
  (one existing optional collection skip) and **520 integration passed**;
  bare-metal storefront **538 passed**; VM buyer **213**; bare-metal buyer
  **16**; e2e harness **316**; release tooling and Helm structural/render
  checks. Final test-only refinements were re-driven in the focused command.
- All four VM first-use scripts and all three modes of the bare-metal example
  pass their assertions. The bare-metal fixture logs its intentionally
  unconfigured publication loop; no lifecycle assertion fails.
- The build process leak reproduced the existing
  [#326](https://github.com/arkhai-io/simple-compute-market/issues/326); evidence
  was added there. The exact owned native child was stopped through the
  supervisor, without signaling unrelated processes.

O-F18 remains owed: extend VM e2e with hosted commit, servicing and an end with
its case; readiness-gate a fresh owned branch-built stack on payment/mediation
health and signed dispute-bearing publication, run its stages and tear it down.
Early shim-backed images were built before the admin-ordering repair; they
must be rebuilt from the committed branch. An image build is not deployment
readiness or a monetary case result. No deployment or authority service was started.
The build's leftover local development-chain process was explicitly stopped.

Permanent promotion remains reviewed section 16 closeout in the existing
lifecycle, VM fulfillment and compute/site authority destinations. This repair
restores already-required local-before-effect ordering, not a new authority or
an accepted remedy policy change.
