## Why

`docs/development/ARCHITECTURE.md` separates three questions about a package's
place — direction, knowledge, and ownership — and states the first two as rules a
check can hold: a layer order and a scope-subset rule, with any import counting.
`openspec/specs/market-composition/spec.md`'s "From-below kit dependencies"
requirement has a scenario named "Architecture boundary tests run". What runs today
is eighteen hand-written per-package tests, each a forbid- or allow-list for one
package, covering nineteen of fifty-one packages. The rules hold where a test
happens to exist and nowhere else.

A repository-wide review on 2026-10-04 found fifteen direction and scope violations,
every one in a package without a test, and most of them function-local imports a
module-level scan would not have seen. Six have since been closed by changes that
happened to touch them. A follow-up scan on 2026-10-11 found six projects importing
an internal distribution they do not declare, of which the review had noticed one.
No one has run a complete audit against the rules, so `ARCHITECTURE.md` can say
which divergences are known and cannot say they are all of them. Nothing makes a
closeout mechanical either: a change can delete the code and leave the divergence
recorded, or fix an edge while another change re-adds it, and no check reports
either.

The structure is decidable from the tree. Layer and scope are read from a package's
path and name, every import is visible to `ast`, and declared dependencies are in
`pyproject.toml`. One check over all of that replaces nineteen partial ones and
reaches the thirty-two packages that have none — once the tree has been audited
against it and every finding classified.

## What Changes

In two phases. The first is a report; nothing gates until the second.

**Audit.**

- One rules file, `ARCHITECTURE.toml`, beside `docs/development/ARCHITECTURE.md`,
  the prose it encodes: the layer order and each layer's permitted scope elements;
  the families, domains, and mechanisms with their directories, owning kits, and
  identifying literals; the path conventions that yield layer, scope, and kind; the
  kind table with its dependency budgets; and an **overrides** table for projects
  whose path does not yet say what they are.
- One stdlib library module, `architecture.py` under `scripts`, that classifies
  every project, walks every import node under `src/` (module-level,
  function-local, `TYPE_CHECKING`, `try`), and exposes one `problems()` per rule:
  layer direction, same-layer cycles, scope subset, layer/scope bounds,
  undeclared imports, declared-but-unimported internal distributions, kind
  budgets, plugin in-degree, scope-vocabulary literals, and the two table-expiry
  rules.
- A report script that runs every rule over the whole tree and writes a classified
  baseline: each finding marked defect (owned by a named change), accepted (with
  its reason), or rule error (the rule is wrong and is revised). The baseline is
  reviewed as a design artifact of this change before anything gates.

**Gate.**

- An **exceptions** table in the rules file, seeded from the baseline's defects,
  each row naming its owning change and date. A row whose edge no longer exists
  fails, and an override row whose path now conforms fails, so neither table
  outlives its cause.
- Four check scripts in `check_project_layout.py`'s shape under
  `make check-architecture`, which `make check-packaging` runs;
  `make check-architecture-change CHANGE=<name>` scopes the checks to one change's
  review scope. The declared-but-unimported rule and the vocabulary-literal rule
  warn rather than fail; the kind budgets fail only for rules the audit showed
  clean or seeded.
- Tests in `scripts/tests/` with a passing and a failing synthetic tree per rule.
- The eighteen per-package boundary tests are retired one package per commit, each
  only after the repository check fails on the same synthetic violation the local
  test fails on. The provisioning service's adapter-entrypoint allowlist, which the
  repository check does not model, stays.

## Capabilities

### Modified Capabilities

- `market-composition`: "From-below kit dependencies" names the layer and scope
  rules and the repository-wide check as their evidence; the "Architecture
  boundary tests run" scenario becomes one scenario per rule.
- `planning-governance`: "Packaging check at change closeout" gains a scenario for
  an architecture exception the change owns.
- `deployment-state`: the packaging-check inventory names the architecture check.

### New Capabilities

None.

## Non-Goals

- No package moves. The overrides table carries the projects whose paths do not
  conform; `align-package-paths-with-layers` moves them and deletes the rows.
- No fix to any finding. Each stays with the change that owns it; this change makes
  the ownership checkable.
- No rule the dependency graph cannot express. A storefront importing `kit/site`'s
  matching predicate, a kit reading a configuration file, and which modules of a
  composition root may name a contribution all pass the graph rules and remain
  review judgements (`negotiation-capacity-feasibility-probe`,
  `move-escrow-into-alkahest`, `resolve-compute-family-findings`).
- No scanning of `tests/` directories.

## Impact

- Affected code: `scripts/` (one library, five scripts, one test module),
  `Makefile` (six targets, one addition to `check-packaging`), the eighteen boundary
  tests (retired), and the new `ARCHITECTURE.toml` beside
  `docs/development/ARCHITECTURE.md`.
- Affected documentation: `docs/development/ARCHITECTURE.md` (the "Where the current
  tree diverges" paragraph becomes a pointer to the exceptions table, and the kind
  conventions and budgets this change owns are promoted once they hold),
  `docs/development/BUILD_AND_PACKAGING.md` (names the check), `AGENTS.md` (the
  interim "enforced by review" sentence is removed).
- Every open change that owns an exception row gains a closeout obligation it
  already had in prose: the row must be gone when the change archives.

## Dependencies and Related Changes

- No blocking dependency. The audit phase lands first so the changes that own
  findings can cite the baseline; the gate follows the baseline's review.
- `align-package-paths-with-layers` deletes the overrides this change seeds.
- `kit-owned-storefront-auth-and-persistence`, `kit-owned-storefront-shell`,
  `move-escrow-into-alkahest`, `inject-site-pool-authority`,
  `deduplicate-dynaconf-bootstrap`, and `type-core-packages` each own findings;
  their designs carry the gating question.
- `shorten-long-requirements` restructures `market-composition`'s requirements;
  the scenario split here should follow its form.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md` — the divergence paragraph points at the
      exceptions table; the kind conventions and budgets move from this change into
      the "Kind" section when the gate lands.
- [x] Existing subsystem specification — `market-composition`,
      `planning-governance`, `deployment-state` as above.
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

- The conventions by which a package's path and name state its layer, scope, and
  kind, and the budgets the light kinds are held to —
  `docs/development/ARCHITECTURE.md#package-and-dependency-layers`.
- The repository-wide check is the evidence for the from-below rule, and an
  exception is owned, dated, and expires with its change —
  `openspec/specs/market-composition/spec.md`.
- `make check-architecture` is part of `make check-packaging` —
  `docs/development/BUILD_AND_PACKAGING.md`.
