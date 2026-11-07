# VM physical end and admission checkpoint

Nonvisual implementer first-use evidence, not independent acceptance.

## Prepared target and runnable surface

This checkout's VM storefront uses fresh internal wheels, an invocation-owned
SQLite database, signed in-process HTTP, the payments kit's vector-derived
authority fixture and controlled VM delivery/teardown. The mediation contract
supplies the accepted authority and delivery-end signature format; no mediation
remedy is computed by the example. Buyer and seller are deterministic public
development identities, never public-network credentials.

No secret, inherited deployment selector, resident service or remote target is
required. From repository root:

```sh
unset ALL_PROXY all_proxy
export NO_PROXY=localhost,127.0.0.1 no_proxy=localhost,127.0.0.1
make dist
make -C domains/vms/storefront reinit
uv run --project domains/vms/storefront --locked --find-links .dist \
  python domains/vms/storefront/examples/payment_smoke.py
```

The command opens the actual mounted settlement and lifecycle routes. Normal
approval reaches provisioning and then ready with one delivery and no escrow
row. A second invocation-local deal verifies payment commitment, obtains a
buyer-authenticated end receipt before delivery starts, and observes released
undispatched delivery. The receipt includes a seller-signed delivery-end claim.
Later settlement reports ended with zero dispatches and no delivery row.

## Implemented boundary

- VM delivery insertion, reservation/dispatch/activation checkpoints and
  credential authorization share a SQLite write transaction with end admission.
  Recovery traverses those same checkpoints. A due final request prevents
  further dispatch and disclosure; the terminal checkpoint and deadline/end
  writes survive the refused operation.
- Refund completion records its final request atomically with the refunded
  evidence. Physical failure does not turn a confirmed financial refund into
  an unknown financial answer; its journal remains recoverable.
- Terminal uncollected settlement journals its end before physical effects.
  Physical lookup uses the accepted site and negotiation, not an escrow ID.
  The port releases undispatched holds and invokes immediate VM termination
  for delivered leases; it does not truncate to now and wait for a watchdog.
  Future truncations preserve seconds.
- A missing reservation does not acknowledge an in-flight allocation as
  released. Future ends without a reservation remain pending. Teardown requests
  retain their operation key until capacity return is observed.
- The existing lifecycle cycle drives physical intents independently of
  authority availability, and drives newly observed ends in the same cycle.
  Non-payment deals can use the same journal without parsing payment data.
- The mounted buyer surrender path supplies receipt claims without authority
  I/O. Claim creation uses read-only snapshots inside the ingress transaction,
  avoiding a second SQLite writer lock.

The existing refund-during-provisioning assertion now requires ended delivery
and no credentials rather than completing delivery after the refund. The
terminal-settlement assertion requires immediate termination and no truncation.
Existing low-level fixtures supply the lifecycle admission boundary explicitly;
full delivery fixtures retain an accepted Agreement with a current lease window.
No permanent test function was added or kept acceptance assertion weakened.

## Validation

- The VM storefront's 1,690 existing unit/application-integration cases pass,
  with the existing optional Torch-dependent collection skip.
- The mounted first-use entry point above passes both normal commitment/delivery
  and end-before-delivery. It creates and deletes its own state.
- Fresh wheels, architecture, packaging, locks, comment hygiene and pinned
  OpenSpec 1.14.0 strict validation pass. No dependency or configuration model
  changed, so no lock regeneration or Helm schema regeneration is required.
- The first full aggregate passed the package suites and stopped at release
  tooling: the inherited bare-metal storefront release-table row omitted its
  three declared lifecycle dependencies. The separate documentation repair
  `edd52a728` lists each dependency once; all 1,858 release-tooling cases
  pass after it. No sibling-domain source was changed.
- Scoped documentation citations report exactly the three known future
  lifecycle destinations in #325; no additional citation failure is present.
- Full `make test` passes with both all-proxy variables unset, both no-proxy
  variables set to loopback and the shell-local Podman shim. The final pipeline
  (fresh wheels, repository checks, first use and aggregate) completed in 7m42s,
  including release tooling and Helm render/structural assertions.

## Remaining boundaries

Administrator entitlement dispatch, authenticated site-report HTTP ingress,
callback-driven release progress, failure-source classification/correlation,
buyer lifecycle-stage composition and the VM buyer end command remain the next
tasks. The local site-proof verifier is available to that ingress composition;
this packet does not claim a mounted site callback or pull-recovery journey.

The fresh branch-built VM end-to-end stack, real local payment/mediation
qualification, and end/report e2e stages are unrun. No hosted or rate-part
qualification is claimed. Permanent documentation promotion remains reviewed
closeout. No sibling-domain or shared package source was changed.
