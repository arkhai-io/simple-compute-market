# Design — the tree says what each package is

## Context

See `proposal.md` for the ten nonconforming paths and why the move is mechanical.
This document records the decisions taken about where things go and the two naming
questions still open.

## Decisions

### Scope-first directories, kind in the name

The alternative was layer-first: `kit/`, `specialization/<scope>/`,
`composition/<scope>/`. It was rejected because it scatters each domain across two
trees to save a label, and because "everything about VMs is one directory" is how
the repository is navigated and how its documentation contexts
(`docs/agents/domain.md`) are drawn. The tree stays scope-first — `core/`, `kit/`,
`domains/<scope>/`, plus one directory for repository-wide compositions — and the
kind rides in the project name, which is the convention `kit/site-client`,
`kit/resource-pools-contracts`, and `domains/vms/storefront` already follow.

### The family kit lives under its family

`provisioning/compute/*` becomes `domains/compute/provisioning*`. The family-kit
section of `ARCHITECTURE.md` already says the family kit is the compute family's;
its own README has said since it was created that the top-level directory was
transitional. The five distributions become siblings under `domains/compute/` rather
than nesting, because a project directory containing other project directories
(`provisioning/compute/` holding `service/`) is what the `domains/<scope>/<path>`
convention reads badly, and because `provisioning-contracts` beside
`provisioning-client` reads the kind the same way `resource-pools-contracts` does.

### Names and import roots are untouched

Only directories move. `arkhai-compute-provisioning-service` keeps its name and
`compute_provisioning_service` its import root, so no lock, wheel, image, or
consumer changes content. Renaming packages whose names now say the wrong layer
(`core_storefront`, `market_storefront`, `core_buyer`) is real work with real
consumers — `kit-owned-storefront-shell` already owns the VM storefront's rename —
and bundling it here would turn a mechanical move into a migration.

### One commit per move, plumbing included

Each of the three moves (`provisioning/compute`, the three roles, the two clients)
lands as one commit that moves the directories and updates every reference to
them, with `make check-packaging` and an unscoped `make check-doc-citations` green
at each. A move whose references are updated in a following commit leaves the tree
unbuildable between the two.

## Open questions

- **`core/storefront` after the carve-out.** What moves to the roles directory is
  the composition that remains once `kit-owned-storefront-auth-and-persistence` has
  extracted the hook shapes and models into `kit/storefront-contracts` and the
  persistence and assembly into `kit/storefront`. If that extraction leaves nothing
  but an entry point, the move is a deletion; decide once that change's inventory
  exists.
- **The roles directory's name.** `core/buyer`, `core/storefront`, and
  `core/registry` need a home for repository-wide compositions. `roles/` matches
  the architecture document's own word for the buyer and storefront
  ("role implementations"), though the registry is a service rather than a role.
  `platform/` matches `docs/agents/domain.md`'s "platform context" but that context
  also contains `core/` and `kit/`. `services/` describes the registry and not the
  buyer. `roles/` is the working assumption; decide before the second move.
- **Vocabulary placement.** Three vocabulary projects sit at their scope directory's
  root (`domains/compute`, `domains/bare_metal`, `domains/apicredits`); the VM
  vocabulary is `domains/vms/domain`. Either rule works for the check — "a scope
  root that is itself a project is its vocabulary" needs no move but leaves a
  project directory containing other project directories, and the VM one still has
  to move to its root; `domains/<scope>/vocabulary` needs four moves and reads the
  kind in the path like every other package. Decide with the first move so the
  `domains/compute/` directory is shaped once.
- **The nested middleware path.** `domains/apicredits/middleware/python` carries a
  language segment because the same directory holds the Rust and TypeScript
  middlewares. Flattening to `domains/apicredits/middleware-python` conforms;
  leaving it under an override row costs one row forever. Decide with the
  vocabulary question, since both are about what `domains/<scope>/` may contain
  besides projects.
- **`CONTEXT.md` and the platform context.** `docs/agents/domain.md` draws the
  platform context as `core/`, `kit/`, and `provisioning/`. After the moves the
  compute family kit is under `domains/compute/` but is still platform-context
  material by that document's own rule ("code that serves a single domain belongs
  to that domain's subcontext wherever it sits on disk" — and the family kit serves
  two). Whether the context's membership is restated by layer and scope rather than
  by directory is a documentation question for the move, not a design question here.
