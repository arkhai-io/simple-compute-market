## Why

The protected Stripe matrix cannot be run. Not "is failing" — cannot be started,
by anyone, today. Its runner label points at a self-hosted machine nobody has
registered, and the credentials it needs come from a credential broker at
`http://127.0.0.1:18082` that exists in one line of one workflow and nowhere
else in the repository: no implementation, no documentation, no way to stand one
up. Three changes have been blocked for weeks on evidence that no available path
produces.

Underneath that operational gap is a design one. The harness fuses two unrelated
concerns into a single entry point: the *mechanical body* that drives real
Stripe test-mode behaviour — compose stack, webhook forwarding, browser
interaction, funding, collection, recovery, lifecycle assertions — and the
*provenance claim* that a run was performed by a released consumer against a
released producer. `require_release_identity` runs as the first statement of
`run()`, and `prepare-hosted-compose` will not render a compose environment
without `gh attestation verify` on an attested marketplace release manifest.

So the only way to exercise the mechanism is to release first. A developer
cannot run the body against their own branch at all: the driver compares
`--observed-marketplace-commit` (the working tree's `git rev-parse HEAD`)
against the trusted release commit and rejects any difference. The cost is
concrete and already paid — `add-bare-metal-hosted-settlement` has been stuck on
a `payer_profile_unavailable` failure whose child exception the sanitized report
discards, and nobody can reproduce it without a release.

The provenance requirement is right and stays. What is wrong is that it gates
execution rather than classifying the result.

## What Changes

- **Safety gates become unconditional; provenance gates become a classifier.**
  The prerequisites that prevent harm — test-mode-only credentials, refusal of
  live objects, loopback-only webhook delivery, connected-account readiness,
  browser availability — MUST hold in every run of the body, in every mode. The
  prerequisites that establish provenance — attested marketplace manifest,
  observed-equals-trusted commit, pinned image and wheel digests, producer
  workflow run identity — decide what a run's evidence may claim.
- A protected run keeps today's behaviour exactly: every gate, fail-closed,
  before any mutation.
- A **development run** of the same body becomes possible against a locally
  built stack and the developer's own branch. Its evidence is stamped as
  non-qualifying and MUST NOT be cited by any verification task.
- Evidence gains an explicit release mode, so a report says which kind it is
  rather than leaving a reader to infer it from which fields are populated.
- **The credential broker is replaced for local use** by an assembler that
  produces the same payload from a local file plus locally generated identity
  credentials — no OIDC, no self-hosted runner. Built to the broker's response
  shape, so implementing the real broker later is a drop-in rather than a
  rewrite.

Explicit non-goals:

- **No weakening of protected evidence.** A development run cannot become
  qualifying evidence by any flag; the qualification tasks in the three blocked
  changes continue to require attested runs.
- **No implementation of the credential broker service**, and no self-hosted
  runner registration. Both stay open; this change removes the need for either
  in order to run the body.
- **No change to what the body does.** Scenarios, funding profiles,
  interactions, and assertions are untouched.
- No live-mode support of any kind, in any mode.

## Capabilities

### Modified Capabilities
- `deployment-state`: separate the fail-closed safety prerequisites of a
  protected hosted run from its release-identity binding, so the same mechanical
  body can run without a release while only attested runs produce qualifying
  evidence, and so every run declares which it is.

## Impact

- **Modified**: `e2e-tests/src/hosted_real_stripe/gates.py` — release identity
  becomes mode-aware; safety gates unchanged and unconditional.
- **Modified**: `e2e-tests/src/hosted_real_stripe/driver.py` — a release-mode
  argument; the body runs identically under both.
- **Modified**: `e2e-tests/src/hosted_real_stripe/evidence.py` — evidence
  records its release mode; schema identity bumped.
- **Modified**: root `Makefile` — `prepare-hosted-compose` splits its attested
  and local paths; a local target with the safety preconditions but not the
  provenance ones.
- **New**: a local credential assembler replacing the broker for development
  runs.
- **Not changed**: `.github/workflows/hosted-stripe-test.yml` keeps invoking the
  attested path, so CI behaviour is identical.
- **Not broken**: no wire, database, or packaging change. Existing attested runs
  produce the same evidence with one added mode field.
