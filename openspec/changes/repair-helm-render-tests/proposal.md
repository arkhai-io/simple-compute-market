## Why

`make -C helm test-render` fails thirteen chart render tests:

- four in `helm/charts/bare-metal-storefront/tests/test_render.py`;
- seven in `helm/charts/storefront/tests/test_render.py`;
- two in `helm/tests/test_release_topology.py`.

Each fails with `values don't meet the specifications of the schema(s)`, `got
null, want object`, at paths such as `/internalRegistryTrust` and `/agents/bob`.
The failing tests set a value to `None` to remove a chart default; the values
schema validates the `null` rather than the key being dropped from the merged
values. `dev` fails the same step in CI (`.github/workflows/tests.yml`, the
`make -C helm test-render` step).

The suspected cause is the Helm release: the failure was observed under Helm
v4.3.0 locally, and CI installs Helm through `azure/setup-helm@v4` with no version
pinned, so it takes the latest release. This is not verified. Rendering the tests
under a pinned Helm 3 and a pinned Helm 4 would settle it.

Until it is fixed:

- `make test` fails its last suite;
- `make validate-helm` stops at `test-render`, so no Helm scenario runs, and no
  change can produce the Helm part of its validation evidence. This blocks the
  Helm evidence `parallel-change-workflows` owes from its sections 5–7.

## What Changes

- Establish the cause of the `null` validation failures, by rendering the failing
  tests under a pinned Helm 3 and a pinned Helm 4 release.
- Make the render tests pass on the Helm release the repository supports, either
  by changing how a test or chart removes a default so the schema accepts it, by
  changing the values schemas, or by supporting and pinning a Helm release — the
  design decides which.
- Pin the Helm release CI installs, if the cause shows the result depends on it,
  and state the supported release where local development reads it.
- State: **proposed; design not started.**

## Capabilities

### New Capabilities

None.

### Modified Capabilities

None expected; this is chart, test, and CI configuration, so `.openspec.yaml`
sets `skip_specs`. Design confirms whether a deployment specification changes —
for instance, a supported Helm release — and adds a delta and clears `skip_specs`
if it does.

## Non-Goals

- Do not change which scenarios the Helm validation run serves; that is
  `helm-e2e-pipeline-parity`.
- Do not change what the charts deploy, beyond what removing a default under the
  schema requires.

## Open questions

- Whether the cause is the Helm release, and if so which releases fail.
- Whether removing a default by setting it to `null` is a supported idiom the
  charts should keep accepting, or the tests should remove defaults another way.
- Whether a deployed release with an operator values file that nulls one of these
  keys fails the same way, making this a deployment defect and not only a test one.

## Dependencies and Related Changes

- Unblocks the Helm validation evidence of `parallel-change-workflows`, and of
  every change whose validation runs `make validate-helm`.
- Related to `helm-e2e-pipeline-parity` and `add-full-stack-ci-job`, which also
  touch the Helm validation path.
- Opened from the unowned item recorded by `parallel-change-workflows`'
  implementation validation.

## Impact

`helm/` charts, their values schemas, and render tests;
`.github/workflows/tests.yml`'s Helm setup. No service code changes.
