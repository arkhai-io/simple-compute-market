## Why

`docs/development/ARCHITECTURE.md` makes a package's place in the tree its
declaration of layer and scope. Most of the tree already conforms. Ten projects do
not, and `ARCHITECTURE.md`'s "Where the current tree diverges" names them first
because they are the ones where the directory says something false:

- `provisioning/compute` and its four distributions (`ansible`, `contracts`,
  `client`, `service`) are the compute family kit, which the convention places under
  `domains/compute/`. The top-level `provisioning/` directory exists for one family
  and its README describes the layout as transitional.
- `core/buyer`, `core/storefront`, and `core/registry` are compositions — role
  implementations and a deployed service — under the directory whose name means
  "carriers with no internal dependencies". `core/storefront` alone is 13.7k lines
  with persistence, FastAPI assembly, and an EVM transfer helper, and two kits
  depend on its hook shapes; `kit-owned-storefront-auth-and-persistence` carves
  those shapes out into `kit/storefront-contracts` before what remains moves.
- `core/storefront-client` and `core/registry-client` are repository-wide client
  kits, like `kit/site-client`, under `core/`.
Beside the ten, the four vocabulary packages take one shape: `domains/vms/domain`
sits in a subdirectory whose name is the scope word, while the other three sit at
their scope directory's root. Settling that is a decision this change owns, and
it may move one project or four.

Nothing imports by path. Every internal dependency resolves from a built wheel, no
`pyproject.toml` names a sibling by path, and in-source references to these
directories are comments. What references them is build and deployment plumbing:
the root and aggregate `Makefile`s, two CI workflows, `scripts/resolve-review-scope.py`,
three Dockerfiles and two dockerignores, the registry's Compose and Helm files, the
issue-discovery phase configuration, and the documentation. That is a mechanical
change, and doing it now is cheaper than carrying an overrides table that exists
only to describe these ten paths.

## What Changes

- `provisioning/compute` → `domains/compute/provisioning`;
  `provisioning/compute/ansible` → `domains/compute/provisioning-ansible`;
  `provisioning/compute/contracts` → `domains/compute/provisioning-contracts`;
  `provisioning/compute/client` → `domains/compute/provisioning-client`;
  `provisioning/compute/service` → `domains/compute/provisioning-service`. The
  top-level `provisioning/` directory is removed.
- `core/buyer`, `core/storefront`, `core/registry` → a composition directory for
  repository-wide roles (name decided in `design.md`), leaving `core/` as the
  carrier alone. `core/storefront` moves only after
  `kit-owned-storefront-auth-and-persistence` has carved its hook shapes and
  models out into `kit/storefront-contracts`; moving it whole would put a package
  two kits depend on under a composition directory.
- `core/storefront-client` → `kit/storefront-client`;
  `core/registry-client` → `kit/registry-client`.
- The vocabulary projects take one shape (decided in `design.md`): either every
  scope directory's root is its vocabulary project and `domains/vms/domain` moves to
  `domains/vms`, or every vocabulary project moves to `domains/<scope>/vocabulary`.
- Distribution names and import names do not change. `arkhai-compute-provisioning`
  stays `arkhai-compute-provisioning`; `core_buyer` stays `core_buyer`. A later
  change may rename packages whose names now say the wrong layer (`core_storefront`
  is a composition; `market_storefront` is the VM storefront); this one moves
  directories only.
- Every Makefile target, workflow path, Dockerfile `COPY`, dockerignore pattern,
  Compose build context, Helm values path, review-scope mapping, and documentation
  citation that names a moved path is updated in the same commit as the move.
  The acceptance test for the documentation half is that an unscoped
  `make check-doc-citations` reports no more failures after a move than before it
  (the repository carries fifteen unrelated failures today, which this change does
  not take on); for the build half, `make check-packaging`.
- `enforce-package-layers`'s override rows for the moved projects are deleted; the
  check fails if a row outlives its move.

## Capabilities

### Modified Capabilities

- `deployment-state`: the build and image layout names the new directories.

### New Capabilities

None.

## Non-Goals

- No change to any distribution's contents, name, version, or dependencies.
- No change to `core/storefront`'s role-shaped content; carving its contracts out is
  `kit-owned-storefront-auth-and-persistence`.
- No rename of import packages or distributions. Carrying a mechanism in a
  specialization's name (`domains/vms/settlement-alkahest`) is a directory move
  this change may own once `enforce-package-layers`'s audit says which packages
  legitimately keep a mechanism; see its design.
- No move of `kit/alkahest`, `kit/arkhai-payments`, or `kit/contact-exchange` into
  a mechanism directory. Mechanism scope is inferred from imports, so their paths
  are not wrong; grouping them is a readability choice this change does not make.

## Impact

- Affected files: on the current head, 11 files reference `provisioning/compute`,
  15 reference `core/registry`, 10 reference `core/storefront`, 8 reference
  `core/storefront-client`, 6 reference `core/buyer`, 5 reference
  `core/registry-client`, and 4 reference `domains/vms/domain`, excluding tests,
  locks, and change documents. Most are the root `Makefile`, `core/Makefile`,
  `domains/Makefile`, `.github/workflows/tests.yml`, and
  `.github/workflows/publish-pypi.yml`, which each reference several.
- `docs/agents/domain.md` and `CONTEXT.md` describe the platform context as
  `core/`, `kit/`, and `provisioning/`; the context's membership is unchanged but
  its directories are.
- Wheels, locks, and images are unaffected in content; `make check-packaging`
  re-verifies every lock against the rebuilt wheelhouse because `scripts/uv_project.py`
  reads project paths.

## Dependencies and Related Changes

- `enforce-package-layers`'s audit should land first, so the override rows exist
  to be deleted and the check proves each move conforms. The moves are not blocked
  on it; without it, the acceptance test is the citation and packaging checks alone.
- `kit-owned-storefront-auth-and-persistence`'s contracts carve-out precedes the
  `core/storefront` move; the other two roles and the two clients do not wait.
- Coordinate with any active change touching the moved projects. On the current
  head `resolve-compute-family-findings` (design not started) and
  `kit-owned-storefront-shell` (design phase) are the two most likely to conflict;
  neither has an implementation branch open.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md` — the moved projects leave "Where the
      current tree diverges"; the path conventions gain the roles directory name.
- [x] Existing subsystem specification — `deployment-state` for the image layout.
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

- The directory conventions, including the roles directory and the vocabulary
  placement decided here — `docs/development/ARCHITECTURE.md#package-and-dependency-layers`.
- `docs/development/BUILD_AND_PACKAGING.md` and `docs/agents/domain.md` for the
  new layout.
