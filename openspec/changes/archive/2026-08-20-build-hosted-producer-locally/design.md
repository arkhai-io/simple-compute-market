## Context

See proposal.md — Why. The relevant current state:

`prepare-hosted-compose.py` renders one non-secret Compose environment with an exact
key set, and both halves of the stack contribute keys to it. The consumer half already
has a local mode, and its shape is the precedent this change follows:

```python
#: The marketplace coordinates a locally built consumer has no released source
#: for. Rendered empty rather than omitted: the environment's reader requires
#: the exact key set, and a development run reads an empty value as "local".
#: The image is not among them -- Compose refuses to start a service without
#: one -- so a local environment names the image it actually runs.
_LOCAL_MARKETPLACE_COORDINATES = (...)
```

The producer half has no equivalent. Its keys divide cleanly into two groups that the
current code does not distinguish, because until now they always arrived together from
one signed manifest:

- **Provenance** — manifest digest and sha256, client wheel sha256, source commit,
  repository, workflow ref, authority id/scheme/address, and the five artifact digests.
  These describe *who published this and from what*. A local build has no answer.
- **Contract** — release version, API version, schema version, funding profiles,
  capabilities. These describe *what the service serves*. A local build answers all of
  them, because `hosted-settlement-artifacts` writes them into `conformance-v<version>.json`
  as `api_version`, `schema_version`, `funding_profiles`, and `identity_contract.capabilities`.

`gates.py::_require_hosted_half` then re-asserts the contract group against literals in
its own source — `"0.2.1"`, `"5"`, `_FUNDING_PROFILES`, `_CAPABILITIES` — rather than
against what the run bound. Its docstring states the current intent plainly: "A
development run still consumes the signed hosted release -- only the marketplace half
is locally built -- so nothing here relaxes."

## Goals / Non-Goals

**Goals:**

- One local path per half, of the same shape, composable in any of the four combinations.
- Contract assertions survive a producer version bump without a harness edit.
- A local producer is as loud about a missing input as an attested one is about a bad
  signature.

**Non-Goals:**

- Signing anything locally, or producing a manifest that resembles a signed one. A local
  build has no provenance and the environment records that as absence, never as a value.
- Teaching the harness to build the producer. It consumes a build; the producer repository
  owns how one is made.
- Any change to what an attested run asserts or how it fails.

## Decisions

**D1 — Empty provenance, not synthetic provenance.** The local producer keys render as
empty strings in the exact same key set, mirroring `_LOCAL_MARKETPLACE_COORDINATES`.

Considered and rejected: computing a digest over the local image and writing it into the
provenance keys. It would populate every field and produce an environment indistinguishable
from an attested one by inspection, which is precisely the property the release-mode work
exists to prevent. Absence must be visible in the artifact, not only in a mode flag.

**D2 — The contract comes from the conformance artifact, in both modes.** `prepare-hosted-compose.py`
reads the contract group from `conformance-v<version>.json` for a local producer and from
the signed manifest for a released one, and `gates.py` compares the rendered environment
against the coordinates the run bound rather than against module constants.

Considered and rejected: keeping the literals and adding a second set for 0.3.0. That is the
status quo with more branches, and it means every producer release requires a consumer edit
before it can be tested — the same coupling this change removes one layer up.

Note this decision stands alone. The literals break on 0.3.0 whether or not a local producer
path is ever built, so it is not contingent on the rest of the change landing.

**D3 — The image is named, not digest-pinned, when local.** `_IMAGE` requires
`name@sha256:...`. A locally built image has an image ID, not a registry digest, and inventing
one would violate D1. The local branch accepts a bare reference and asserts only that the
environment names the image the run was told to use — the same relaxation the consumer half
already takes for `arkhai:storefront`.

**D4 — Safety gates are not touched, and that is the invariant to preserve under review.**
Test-mode-only credentials, refusal of live objects, loopback-only webhook delivery,
connected-account readiness, and browser availability are asserted on a path with no mode
branch at all. This change adds branches only below the provenance/contract split. A review
of it should be able to confirm that no safety assertion acquired a mode parameter.

**D5 — Any local half makes the whole run a development run.** The release mode is computed
from what was bound, not passed in. Naming a local producer image is sufficient to make the
run non-qualifying, with no separate flag and no way to combine a local producer with an
attested claim.

## Risks / Trade-offs

- **A local producer image drifts from the artifacts describing it** — an operator rebuilds
  the image, forgets `make artifacts`, and the run asserts a stale contract. → The image
  reports its own version through the existing `image-check` entry points, and preparation
  fails closed if the composed authority disagrees with the bound conformance file. This is
  the spec's "composed authority does not serve the bound contract" scenario.
- **The four-combination matrix grows the paths under test** → Prefer table-driven coverage
  over four near-duplicate tests, and keep the attested/attested path byte-for-byte
  comparable to today's so a regression there is obvious.
- **Reading the contract from the bound release weakens a real check if the source is
  attacker-controlled** → For an attested run the conformance file is covered by the signed
  manifest, so the trust root is unchanged. For a local run there is no trust root and none
  is claimed. The check that remains meaningful in both — that the composed authority serves
  what was bound — is the one being kept.
- **Two repositories must be checked out to run locally** → Already true in practice for
  anyone changing the producer, and the alternative is publishing a release per iteration,
  which is the problem being solved.

## Migration Plan

Additive. Existing invocations of `prepare-hosted-compose`, `prepare-hosted-compose-local`,
`hosted-stripe-test`, and `hosted-stripe-test-local` keep working with unchanged arguments:
omitting `--local-hosted-image` selects the released producer path exactly as today. The
protected workflow's thirteen dispatch inputs are untouched.

Rollback is deletion of the local branch; no persisted state, schema, or wire format is
involved.

The first real use is the direct-setup work: build hosted-settlement-service 0.3.0 locally,
bind it, and run a `saved_instrument` lane without a browser. That lane is the acceptance
evidence for this change being useful, though as a development run it qualifies nothing in
the protected matrix.
