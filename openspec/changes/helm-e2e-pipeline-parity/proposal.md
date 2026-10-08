## Why

Pre-review validation runs the end-to-end pipeline's scenarios twice: in the
pipeline, against the compose stacks `e2e-tests/Makefile` brings up, and locally
against the Helm charts deployed to a development cluster, because the images and
charts are what is deployed. The Helm run reads the same marker lists the pipeline
does (`E2E_MODULE` and `E2E_BARE_METAL_MODULE`), so the two cannot drift.

The charts do not deploy everything the compose stacks do. With the default
`helm/values.yaml` there is one storefront and one registry; the API-credits
service, storefront, and registry, a second storefront, and the bare-metal
storefront and its registry are absent or disabled; and `make -C helm forward`
forwards Anvil, the registry, one storefront, and provisioning, not Mailpit. The
scenarios that need those services are therefore excluded from the Helm run by an
explicit list in `scripts/validate_slice.py` and reported as not run against Helm.
Each excluded scenario is deployment behaviour the charts are never shown to
support.

The pipeline proves a topology that passes these scenarios exists: its compose
configuration already assembles it. That configuration is the source for what the
charts lack.

## What Changes

- Give the charts and their values what the excluded scenarios need, taking the
  topology and configuration from the pipeline's compose stacks.
- Extend `make -C helm forward` and `make -C helm unforward` to the services those
  scenarios reach.
- Empty the Helm exclusion list in `scripts/validate_slice.py` as each scenario
  passes against the charts; a scenario that cannot be served is kept with its
  reason.
- State: **proposed; design not started.**

## Capabilities

### New Capabilities

None.

### Modified Capabilities

None expected; this is deployment configuration and validation tooling, so
`.openspec.yaml` sets `skip_specs`. Design confirms whether a deployment
specification changes, and adds a delta and clears `skip_specs` if it does.

## Non-Goals

- Do not change the scenarios or the compose stacks the pipeline runs.
- Do not change the pipeline to deploy to a cluster.

## Open questions

- Whether the bare-metal lane, which the pipeline runs as a separate stack, is
  served by the same release with the bare-metal storefront enabled or by a second
  release.
- Whether the added services belong in the default `helm/values.yaml` or in a
  values overlay used for validation.
- How the buyer-CLI scenarios reach the storefront from outside the cluster, since
  the pipeline runs them from inside the compose network.

## Dependencies and Related Changes

- Follows `agent-driven-change-workflow`, whose pre-review validation introduced
  the Helm run and its exclusion list.
- Related to the unowned item in this campaign about converging compose
  configuration onto one source shared with the Helm charts; design decides
  whether this change takes it on.

## Impact

`helm/` charts, values, and `Makefile`; `scripts/validate_slice.py`'s exclusion
list. No service code changes.
