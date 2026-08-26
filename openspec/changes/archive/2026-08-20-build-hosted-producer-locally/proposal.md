## Why

`separate-protected-run-release-gate` established that provenance gates classify
a run's evidence rather than decide whether the body may execute, and it made a
development run possible against a locally built stack. It implemented that on
one side only. The marketplace consumer half honours it — `prepare-hosted-compose.py`
takes `--local-marketplace-image` and renders a `local` release mode from an image
the operator built. The hosted producer half does not: every mode still requires
the committed trust manifest, the downloaded `release-manifest.json`, the released
client wheel, and an image pinned by published digest.

So the settlement service can only ever be a published release, and the spec that
says a development run "MUST NOT require an attested release artifact, a published
image digest, a credential-broker service, or a self-hosted runner" is satisfied for
the consumer and unsatisfied for the producer.

The cost is now concrete. Hosted-settlement-service 0.3.0 introduces
`payer-direct-instrument-setup.v1`, the capability that lets a saved-instrument lane
run without a browser and therefore without the hCaptcha throttle that currently
bounds the protected matrix. It has no published image. Until one exists there is no
end-to-end path to exercise it at all — not protected, not local. The "release first
to test" loop that change removed on the consumer side is still intact on the producer
side, and it is blocking the work most likely to unblock the matrix.

## What Changes

- `prepare-hosted-compose.py` gains `--local-hosted-image`, the symmetric counterpart
  to `--local-marketplace-image`. In `local` release mode it sources the
  `HOSTED_SETTLEMENT_VERIFIED_*` Compose inputs from a locally built producer's own
  generated artifacts — the OpenAPI, conformance, and migration manifests that
  `hosted-settlement-artifacts` already emits — instead of from a signed release
  manifest and a published digest.
- `gates.py::_require_hosted_half` gains the matching local branch. Its safety
  assertions are unchanged; its provenance assertions become mode-dependent exactly
  as the marketplace half's already are.
- The expected hosted contract stops being source literals. `gates.py` currently
  hardcodes `"0.2.1"`, schema `"5"`, and a literal capability tuple, and compares
  the rendered Compose environment against them. That comparison is re-pointed at
  the release the run actually bound. **This breaks on 0.3.0 whether or not the rest
  of this change happens**, so it is in scope here rather than deferred.
- A Makefile target builds the producer image and artifacts from a sibling
  hosted-settlement-service checkout, so a local run has something to bind.
- `docs/development/TESTING.md` documents the producer-local recipe next to the
  existing consumer-local one.

Explicit non-goals:

- **No weakening of protected evidence.** A protected run keeps every gate it has
  today, fail-closed, before any mutation, and its dispatch inputs are unchanged.
- **No new release mode.** This extends the existing `local` mode, which already
  stamps `release_mode: local` and already qualifies nothing. A locally built
  producer cannot make a run attested by any flag.
- **No relaxation of safety gates.** Test-mode-only credentials, refusal of live
  provider objects, loopback-only webhook delivery, connected-account readiness,
  and browser availability continue to hold in every mode.
- **No consumption of `payer-direct-instrument-setup.v1`.** Passing a payer-supplied
  instrument through the marketplace payer facade is a separate change that depends
  on this one for its test path.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `deployment-state`: extends "A development run needs no release infrastructure"
  to the producer half of the stack, which it names but does not currently reach,
  and adds a requirement that the contract a run asserts is read from the release
  it bound rather than fixed in harness source.

## Impact

- `scripts/prepare-hosted-compose.py` — a local producer path alongside the local
  consumer path.
- `e2e-tests/src/hosted_real_stripe/gates.py` — `_require_hosted_half` becomes
  mode-aware; `_CAPABILITIES`, `_FUNDING_PROFILES`, and the release/API/schema
  literals stop being module constants used as expectations.
- `Makefile` — `HOSTED_LOCAL_HOSTED_IMAGE` and a producer build target;
  `prepare-hosted-compose-local` and `hosted-stripe-test-local` stop requiring the
  six `HOSTED_PRODUCTION_*` identities when a local producer is named.
- `docs/development/TESTING.md` — the producer-local recipe.
- No change to `.github/workflows/hosted-stripe-test.yml`, its thirteen dispatch
  inputs, or the attested path through `prepare-hosted-compose`.
- No wire, database, deployment, or packaging break. Contributor workflow changes
  additively: existing invocations keep working unchanged.
