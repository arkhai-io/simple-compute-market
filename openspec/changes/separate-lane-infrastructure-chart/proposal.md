## Why

The umbrella chart, `arkhai-node-operator` ("Arkhai node operator cloud stack"), is
the chart an operator installs, and it carries the end-to-end lanes' collaborators as
subcharts beside the product services: `dev-env` (the Anvil chain, the Alkahest
address book and Mailpit), `payments-lane-double`, and, once
`add-arkhai-payments-lane-double` lands, `mediation-lane-double`. Each is disabled by
default and enabled only by `helm/local-values.yaml`.

The collaborators have grown into a stack of their own. The doubles expose control
routes that move an authority's perceived clock, inject rulings and fund accounts,
and those belong in no chart an operator installs, even disabled. They also share a
lifecycle the product services do not: the chain and both doubles hold state the
product's volumes refer to, so `make helm-topology-up` must never restart them, a
rule that is today written down rather than structural.

## What Changes

- A lane-infrastructure chart holding `dev-env` and both lane doubles, with the lane
  CA ConfigMap, installed as its own release in a namespace before the product
  release. Service names stay as they are, so no product configuration changes.
- The umbrella chart keeps the product services only.
- Every target and tool that treats a namespace as one release learns two:
  `helm/Makefile`'s deploy, topology, resume and teardown targets,
  `scripts/validate_slice.py`'s upgrade-from-zero and scale-to-zero, the capacity
  figure in `helm/validation-capacity.toml`, `check-local-secrets`, the image-overlay
  and release-topology render tests, and `docs/development/DEPLOYMENT_AND_CONFIG.md`.
- State: **proposed; design not started.**

## Capabilities

### New Capabilities

None.

### Modified Capabilities

Likely `deployment-state`, whose requirements name the umbrella chart's lane-double
subcharts and the local release. `.openspec.yaml` sets `skip_specs` until design
confirms it, adds the delta and clears it.

## Non-Goals

- Running the payment scenarios in Helm validation, which `helm-e2e-pipeline-parity`
  owns.
- Changing the doubles, their controls or the Compose lanes.

## Open questions

- Whether the `e2e-tests` runner and `validate-contracts` subcharts, also test-only,
  move too. They run as the product release's `helm test` pods today.
- Whether the `payments-ca-bundle` ConfigMap is renamed for the lane CA it now holds
  for both doubles.
- Whether a lane release is recreated, rather than upgraded, by each validation, as
  a clean chain, ledger, case store and clock.

## Dependencies and Related Changes

- Opened by `add-arkhai-payments-lane-double`'s design review (15 F2), which extends
  the subchart pattern with the mediation double rather than moving the
  collaborators itself; this change moves that subchart with the rest, so it follows
  that change.
- Related to `helm-e2e-pipeline-parity`, which grows what Helm validation runs.

## Impact

`helm/` charts, values, scripts and `Makefile`; `scripts/validate_slice.py`; Helm
render tests; `docs/development/DEPLOYMENT_AND_CONFIG.md`. No service code changes.
