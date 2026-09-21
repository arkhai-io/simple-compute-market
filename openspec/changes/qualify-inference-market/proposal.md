## Why

One deal on one model at one seller proves the plumbing. A market has several
sellers serving overlapping models, buyers holding several keys, streams that
are cancelled, requests that arrive concurrently against one balance, keys that
are rotated or revoked mid-session, and usage that arrives late or not at all.
`test-compatibility` requires a release-qualified per-domain deal path and a
deterministic buyer-profile matrix across domains; this change delivers both for
inference and broadens the evidence to the cases that break real markets.

## What Changes

- **Multi-seller discovery.** Two storefronts publishing the same `model_id` at
  different rate cards; the buyer filters and ranks by rate and asset
  client-side; each seller's listings, keys, and balances stay isolated.
- **Concurrency.** Many concurrent requests against one key whose balance
  covers only some of them: holds serialize admission, no overdraft, no
  double-charge, and the refused requests receive `402` with the purchase
  pointer.
- **Streaming and cancellation.** Cancelled streams are charged for produced
  tokens only; a client that disconnects before the first token is charged the
  request floor only; the gate drains upstream in every case.
- **Credential lifecycle.** Rotation of an unused newly issued key, revocation
  mid-stream (the current request completes and settles; the next is `403`),
  and top-up of an existing key while requests are in flight.
- **Missing and late usage.** An upstream that returns no `usage` block is
  settled from the pre-flight estimate with outcome recorded; a hold whose
  settle never arrives is reclaimed by the sweeper and the reclaim is
  observable.
- **Retry safety.** Repeated `settle` with one idempotency key charges once;
  repeated issuance for one obligation issues once; a lost settle
  acknowledgement is recovered by identity.
- **Buyer-profile matrix.** The inference plugin runs the same selected-primary
  and retained-recovery profile matrix VM and API credits run, with secret
  canaries absent from every artifact.
- **Cross-language conformance.** The metered conformance fixture is replayed
  by whichever of the TypeScript and Rust gates
  `sign-multi-language-credits-middleware` has brought forward; the others are
  recorded as blocked, not skipped silently.
- **Release qualification.** `e2e_inference_deal` and its extensions are
  release-qualified on the nightly pipeline with the evidence the closeout
  requirement names.

## Capabilities

### Modified Capabilities

- `inference`: multi-seller, concurrency, cancellation, lifecycle, and
  late-usage behavior is normative.
- `test-compatibility`: the inference domain satisfies the per-domain deal
  path and buyer-profile matrix requirements.

## Non-Goals

- No new features. Every case here exercises behavior a prior change in the
  campaign defined.
- No hosted fiat evidence; that route is owned outside this workstream.
- No performance or load qualification beyond correctness under concurrency.

## Dependencies and Related Changes

- **Depends on** `meter-inference-usage` and `package-inference-seller`.
- `sign-multi-language-credits-middleware` governs which non-Python gates can
  be qualified.
- `repair-multi-storefront-scenario` owns the provisioning-side fix that lets
  two storefronts share one development stack; inference's two-seller case
  needs the registry and settlement halves of that, not the provisioning half,
  and should not wait on it unless inspection shows otherwise.

## Impact

- Touched: the e2e scenario package, development identities for a second
  inference seller, the conformance fixture, `TESTING.md`.
- Wire: none. Database: none. Deployment: a second inference storefront in the
  development stack.

## Permanent documentation impact

- [x] Existing subsystem specification — `inference`, `test-compatibility`.
- [x] `docs/development/TESTING.md` — the inference lane and its blocked
      non-Python gates.
- [x] `docs/development/ROADMAP.md` — Goal 8's completion test.

## Status

Design phase. `tasks.md` is authored when `meter-inference-usage` and
`package-inference-seller` are accepted.
