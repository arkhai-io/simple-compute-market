> **Archived 2026-08-26 — superseded, not implemented.**
>
> **Superseded by:** `correct-testing-documentation` here. The runner half is retired without a successor.
>
> **Why.** The harness is being built new in a repository of its own rather than repaired here. The tool's phase-pipeline model has no actor in it and does not map onto the harness's execution model, so repairing it would produce something with no consumer.
>
> **What carried forward.** The `TESTING.md` correction stays: this repository documents a subsystem that has never existed on `dev`, and that is a defect independent of any harness. The runner repair, phase-configuration repointing, and Make targets are dropped. The `reinit` coverage gap is already owned by `remove-relative-uv-sources` task 2.5 and needs no new home.
>
> **Where the reasoning lives.** `design.md`'s inventory of the inherited tool — what exists, what its configuration points at, and what no longer resolves — is the record of why repair was not attempted. Removing `tools/issue-discovery` is deferred until a working replacement exists.
>
> Design rationale is referenced rather than duplicated: successors cite this
> change by name and do not restate it, so the two cannot drift under two
> vocabularies.

---

## Why

`tools/issue-discovery` is on `dev` by reviewed merge and is the only inherited
harness code. It runs a phase pipeline — prerequisites, build, code-level tests,
compose stack in mock provisioning mode, readiness, mock host registration,
marker suites, the full integration sweep, teardown — and turns failures into
deduplicated GitHub issue candidates.

It cannot complete a strict pass on current `dev`. Three of the six working
directories its phase configuration declares no longer exist:

| Declared workdir | State on `e91767a3` |
|---|---|
| `buyer` | moved to `domains/vms/buyer` |
| `policy` | moved to `kit/policy`, which has no `reinit` target |
| `service` | destination unresolved; `kit/config`, `kit/fulfillment`, and `core/storefront` each carry `reinit` |

The packages moved during the POOLS and packaging work. Nothing detected the
drift, because a phase whose `workdir` is absent fails the way a broken
environment fails, and the runner's own design treats an unrecognised failure as
a generic phase-and-command candidate rather than a configuration defect. A tool
whose purpose is finding defects reports its own staleness as someone else's
environment problem.

Two further gaps make the tool unreachable and unproven:

**No invocation entry point.** The repository has 79 Make targets and none
invokes the harness. It runs as `./scripts/issue-discovery` plus
`cd tools/issue-discovery && uv --no-config run pytest -q`. Any external caller
must reproduce that sequence, which makes the sequence the contract.

**A permanent document describes a subsystem that does not exist.**
`docs/development/TESTING.md` carries an "Agent-Driven Capacity Harness" section
describing capacity scenario admissibility, reservation and fulfillment
correlation, and expected-scarcity evaluation. None of that is in this
repository. It cites an
`openspec/specs/test-compatibility/spec.md` requirement — "Agent-driven VM
capacity contracts are finite and non-executing" — that has never existed here,
and an `ISSUE_DISCOVERY.md` section that has never existed here. It also
describes the harness as performing no provisioning action, while the tool that
does exist starts a compose stack and registers a mock host.

The section is not wrong about the *intended* capacity harness. It is describing
a different repository's work as though it were this one's, and a reader
checking either citation finds nothing.

## What Changes

- The phase configuration resolves against the current tree. Moved packages are
  repointed, and `kit/policy` gains the `reinit` target it is missing.
- A validation step resolves every entry point a phase declares, by asking the
  build system rather than pattern-matching it: `make -n <target>` in the
  declared directory for `make` commands, `PATH` resolution for the rest.
  `make -n` executes no recipe but resolves includes, variables, pattern rules,
  and the prerequisite chain. Configuration drift becomes a reported defect in
  the harness rather than a runtime failure attributed to the environment.
- The repository gains Make targets for running the harness and its locked
  suite, so an entry point exists to name.
- `docs/development/TESTING.md`'s harness section is rewritten to describe the
  tool that exists: where it sits relative to the four levels, what its
  jurisdiction is, and how it is validated. The capacity-specific claims and
  both unresolvable citations are removed. They return, as accurate statements,
  with the change that builds the capacity contract.
- `test-compatibility` gains two requirements: the harness's position outside
  the level hierarchy, and the entry-point resolution invariant.

Not in scope: any capacity scenario contract, any agent, any actor model, any
finding schema beyond what the tool already produces, and any change to what the
harness is permitted to execute.

## Impact

- Affected specs: `test-compatibility`
- Affected code: `tools/issue-discovery/config/phases/local.yaml`,
  `tools/issue-discovery/src/issue_discovery/config.py`,
  `tools/issue-discovery/tests/`, root `Makefile`, `kit/policy/Makefile`
- Affected documentation: `docs/development/TESTING.md`
- The `service` workdir's destination is not resolvable from the configuration
  alone, and this change does not resolve it. The `shared_service_tests` phase
  is removed so the configuration loads; the question stays open in `design.md`
  and restoring the phase against the right package is a small later edit.
- Behaviour change to record: a phase configuration that names a missing
  directory or target now fails validation before execution. A configuration
  that previously "worked" by failing at runtime and producing a candidate issue
  will now be rejected up front.
- Recorded for a separate change: 16 of 33 projects with a `pyproject.toml`
  have no `reinit` target, and the absence follows no consistent convention —
  two `kit/*` packages define one and six do not. This change fixes only
  `kit/policy`, which a repaired phase needs.
- Related but separate: the capacity scenario contract, the actor model, and the
  finding schema are later changes against this restored base. This change makes
  no claim about them and adds no seam for them.

## Permanent documentation impact

- [ ] `docs/development/TESTING.md` — the harness's position relative to the
  four levels, its actual jurisdiction, and how it is validated
- [ ] Existing subsystem specification — `test-compatibility`
- [ ] `docs/development/ARCHITECTURE.md` — none owed; the harness is a tool, not
  a dependency layer or an authority boundary
- [ ] New subsystem specification — none owed
- [ ] `docs/development/ROADMAP.md` — none owed; the harness is not a market
  capability and holds no goal or gap row

### Knowledge to promote

See the design-promotion record in `tasks.md`.
