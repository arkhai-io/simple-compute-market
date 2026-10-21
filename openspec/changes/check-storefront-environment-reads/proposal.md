## Why

`docs/development/DEPLOYMENT_AND_CONFIG.md` requires application configuration to travel
through mounted files, with environment variables only as the configuration loader's
last-resort override layer. Nothing checks it. The bare-metal storefront drifted to reading
about twenty-six application settings directly from its environment, and its chart to passing
them as pod `env` entries, without any check noticing; `share-site-projection-state` corrects
that drift and states the rule normatively in `deployment-state` ("A storefront reads no
application settings from its environment").

A rule review alone enforces is how the drift happened. This change makes it a mechanical check,
as `make check-architecture` makes the package layers one.

## What Changes

- Add a check, run in CI and from `make check-packaging`, that scans each storefront package for
  reads of the process environment and refuses any read not declared as allowed.
- Allow, by declaration in the reading package's own `pyproject.toml` with a stated reason, only
  reads that are not application settings: the signing credential, platform metadata, an
  environment passed whole to a subprocess, and configuration-migration diagnostics that name
  legacy variable names. Reads through the configuration loader's documented override layer are
  not direct reads.
- Name the check as the enforcement of the `deployment-state` requirement.

## Capabilities

### Modified Capabilities

- `deployment-state`: the environment-read rule is held by a mechanical check.

### New Capabilities

None.

## Non-Goals

- Changing any storefront's configuration loading; `share-site-projection-state` brings bare
  metal into compliance first.
- Services other than storefronts, unless the design decides the check's scope should include
  them.

## Impact

- A check script and its unit tests under `scripts/`, a root `Makefile` target, and its wiring
  into `make check-packaging` and CI.
- One declaration table in each storefront package's `pyproject.toml` that has an allowed read.
- `docs/development/DEPLOYMENT_AND_CONFIG.md` and `docs/development/BUILD_AND_PACKAGING.md`
  name the check.

## Permanent documentation impact

- [ ] `docs/development/ARCHITECTURE.md`
- [x] Existing subsystem specification — `openspec/specs/deployment-state/spec.md`.
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

- The environment-read rule is enforced mechanically, with allowed reads declared per package —
  `openspec/specs/deployment-state/spec.md`, `DEPLOYMENT_AND_CONFIG.md`, and
  `BUILD_AND_PACKAGING.md`'s table of checks.

## Dependencies

- **Depends on `share-site-projection-state`** for implementation: until it lands, the bare-metal
  storefront's environment reads would fail the check. Design may proceed now.
