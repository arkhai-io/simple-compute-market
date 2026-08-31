## Why

`tests.yml` runs on every push and pull request to `staging` and `dev`, and its own
header states what it is: every package's unit and integration suite, with integration
mocked at the boundary and no external services. The heavy end-to-end suite and the
protected Stripe lane are deliberately elsewhere, on schedules.

It nevertheless requires a signed hosted release. Two jobs download the release assets
for the version the trust configuration names and run `make verify-hosted-release`
before their suites. That happens not because a dev-pace unit suite has any business
verifying a release, but because a release was the only place the client wheel existed —
`arkhai-hosted-settlement-client` is not published to any public index.

`consume-direct-instrument-setup` moved the pin to `0.3.0`, which has no release. Those
two jobs now download `0.2.1` and then fail to satisfy lockfiles that ask for `0.3.0`.
The release-first loop that change set out to remove is still intact in CI, and this is
where it bites.

The same workflow also still spells the version it is binding. Four values are already
derived from the trust configuration; the OpenAPI, conformance, and migration asset
patterns, and the path of the trust configuration itself, are written out. That is the
literal defect `build-hosted-producer-locally` and `consume-direct-instrument-setup`
removed everywhere else and did not carry into CI.

## What Changes

- The dev-pace workflow obtains the client from the producer's private package index
  when the pinned version has no signed release, and keeps downloading and verifying the
  signed release when it does. Which path runs follows from comparing the pinned version
  with the version the trust configuration names — neither is stated twice.
- The remaining literals in that workflow — asset patterns and the trust configuration
  path — are derived from the pinned version.
- **BREAKING (CI).** The two hosted jobs gain a registry credential requirement when the
  pinned version is unreleased. Absence is reported as an unavailable prerequisite
  naming the version and the channel, not as a resolution failure.
- The release-pace workflow that publishes packages keeps verifying the signed release,
  unchanged.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `test-compatibility`: what a dev-pace check may depend on to obtain a producer
  artifact, and what remains reserved to checks that verify a release.

## Impact

- **CI**: `.github/workflows/tests.yml` only. `publish-pypi.yml`, `hosted-stripe-test.yml`,
  and `e2e.yml` are untouched.
- **Lockfiles**: unchanged. The wheel still lands in `.dist` and still resolves by path,
  so local development needs no credential and no new mechanism.
- **Externally blocked.** The workflow cannot authenticate to the private index until a
  GitHub-to-Google federation exists: an identity pool and provider for this repository,
  a service account with read access to the Python repository, and the repository
  variables naming them. None of that exists yet, and none of it can be created from
  here. Until it does, the two hosted jobs remain unable to resolve an unreleased client
  — which is what they already cannot do, reported better.

### Non-Goals

- No change to what the protected lane requires. Signed release inputs stay signed
  release inputs.
- No migration of the other internal wheels from `--find-links` to an index. That is the
  documented direction and a separate change; this moves one wheel because CI cannot
  build it from source.
- No public publication of the client.
