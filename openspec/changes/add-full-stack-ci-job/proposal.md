## Why

No CI job runs a branch's whole local validation before review. `tests.yml` runs
the Python suites only for pushes and pull requests to `staging` and `dev`; the
end-to-end lanes in `e2e.yml` run on a schedule or by dispatch; and root
`make test` does not include the Helm render tests, which only CI's
`release-deployment` job runs, without any service environment.

One consequence is concrete. `helm/charts/storefront/tests/test_render.py` loads a
chart-rendered `storefront.json` with the storefront's own configuration loader —
the check that catches the chart and the loader disagreeing about a value's type,
which is how 160-bit EVM addresses were once read back as integers. It runs only
where the storefront environment exists and reports a skip otherwise, so in CI it
never runs. `pass-through-storefront-config` recorded this as its finding 9 and
left it out of scope.

## What Changes

- Add a workflow, with make targets to drive it, that runs `make test`,
  `make build-dev`, and the Helm render tests together on one runner, so the
  checks that need both Helm and a service environment run.
- Under CI, a render test that needs the storefront environment fails rather than
  skips when that environment is missing, so the check cannot quietly stop running.
- State: **proposed; design not started.**

## Capabilities

### New Capabilities

None.

### Modified Capabilities

None expected; this is CI and build tooling, so `.openspec.yaml` sets
`skip_specs`. Design confirms whether `deployment-state`'s packaging or validation
requirements change, and adds a delta and clears `skip_specs` if they do.

## Non-Goals

- Do not change the end-to-end lanes in `e2e.yml` or deploy to a cluster.
- Do not change what `make test` or the render tests check; this change runs them.

## Open questions

- Which events trigger the job: every pull request, or the same branches as
  `tests.yml`.
- Whether it replaces `tests.yml`'s per-project matrix or runs beside it.
- The runner it needs: `make build-dev` needs a container runtime, and the job needs
  Helm and the Python environments; and the duration budget that implies.

## Dependencies and Related Changes

- Follows `pass-through-storefront-config` (archived), whose finding 9 this owns:
  `openspec/changes/archive/2026-10-02-pass-through-storefront-config/design.md`.

## Impact

`.github/workflows/`, the root `Makefile`, and `helm/scripts/test-render.sh`'s
handling of the storefront interpreter. No runtime behaviour changes.

## Permanent documentation impact

- [ ] `docs/development/ARCHITECTURE.md`
- [x] Existing subsystem specification — to be confirmed in design
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

- Which CI job runs each test tier, and that it runs the chart-to-loader check —
  `docs/development/TESTING.md`.
