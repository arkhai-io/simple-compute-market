## Why

Earlier buyer/registry/storefront projects now consume internal wheels correctly, but five newer domain/provisioning projects encode editable parent-directory sources in `pyproject.toml` and locks. This violates package-layer testing and makes installations depend on repository layout; release documentation also contradicts the wheel-only rule.

## What Changes

- Remove internal path sources from the projects that still carry them.

  **Re-inventoried 2026-08-06; the original list is substantially complete and one entry
  is wrong.** Verified against current code:

  | Project | Internal path sources |
  |---|---|
  | `domains/apicredits` | none remaining |
  | `domains/vms/provisioning/adapter` | none remaining |
  | `provisioning/compute/service` | none remaining |
  | `provisioning/compute/contracts` | **path does not exist** — re-identify the project before planning |
  | `domains/bare_metal/provisioning` | **4 remaining** — the only confirmed target |

  The VM provisioning adapter was cleaned by `fix-vm-fulfillment-capacity-boundary`
  (2026-07-29), six days after this proposal was last revised. That change also
  root-caused a related lockfile defect worth reading before touching the remaining
  project: an absolute `DIST_DIR` propagated from a Make target baked machine-specific
  paths into `uv.lock` on every regeneration. Re-verify this table at implementation
  time rather than trusting it; it moved once already.
- Add or repair local init/reinit targets so changed internal wheels are built into `.dist` and explicitly upgraded/reinstalled.

  **Inventoried 2026-08-13.** 16 of 33 projects with a `pyproject.toml` have no `reinit`
  target, and the absence follows no convention — `kit/config` and `kit/fulfillment`
  define one while their six `kit/*` siblings do not. Task 2.5 carries the list and the
  per-project decision; the count is larger than this bullet previously implied, and some
  absences are correct.
- Regenerate only affected locks against built wheels and preserve unrelated external index sources such as PyTorch CPU selection.
- Add a repository check rejecting parent-directory internal `tool.uv.sources` entries in consumable projects.
- Correct release documentation to match wheel-only internal dependency policy.
- State: **Planned and first in the release-readiness campaign; scope reduced 2026-08-06 to one confirmed project plus one to re-identify.**

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `deployment-state`: Consumable projects resolve internal dependencies from built distributions rather than editable parent paths.

## Dependencies and Related Changes

- Precedes `type-core-packages` packaging verification and `configure-pypi-trusted-publishing`.
- Coordinates with newly extracted packages but does not change their runtime contracts.

## Non-Goals

- Do not remove non-path source/index selectors for external dependencies.
- Do not change dependency versions except where deterministic lock regeneration requires it and the change is reviewed.
- Do not publish packages in this change.

## Impact

Touches the remaining project/lock pairs (see the re-inventory above — one confirmed, one to re-identify, not five), local Make/build orchestration, repository packaging checks, CI, and `docs/development/RELEASING.md`. Runtime APIs are unchanged. The repository check rejecting parent-directory internal sources remains full-scope and is what keeps the already-clean projects clean.
