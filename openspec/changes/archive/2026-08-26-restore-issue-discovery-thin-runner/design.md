# Design

## Grounding

Audited against `origin/dev` at `e91767a3b074b20168bbcb87a8418d8287e5f8a6`.
Re-pin before implementing; the audit's conclusions are about a tree, not about
the branch.

### What is inherited

`tools/issue-discovery` reached `dev` through
`94db0aac Merge origin/feat/issue-discovery-harness into dev`, an ordinary
reviewed merge. What `dev` inherited is what that merge contributed — 4,277
lines — and not the branch, which has since grown to roughly fourteen times
that. Nothing added to either harness branch after its merge point is inherited,
whatever its quality.

The inherited tool:

| Area | Contents |
|---|---|
| Source | 12 modules — `artifacts`, `clean_room`, `cli`, `collectors`, `commands`, `config`, `issues`, `phases`, `redaction`, `runner`, `workarounds`, `__init__` |
| Tests | 9 modules, 1,901 lines |
| Schemas | 6 — `clean-room`, `collectors`, `phases`, `profiles`, `redactions`, `workarounds` |
| Configuration | `collectors`, `profiles`, `redactions`, `workarounds`, three phase files, one clean-room file |
| Entry | `scripts/issue-discovery` |

Its capability is a phase pipeline with `strict` and
`continue --with <workaround>` modes, recorded workarounds that mark skipped
dependencies `assumed_passed`, docker and health collectors, run artifacts under
`.scm-local/`, issue candidates as JSONL plus Markdown, and `issue create` with
a redaction check, an open-title duplicate search, and a `ready_to_file` gate. A
`local-vm` clean-room sequence stacks strict plus known continuations inside a
disposable Multipass VM.

There is no actor in it. Phases invoke repository commands directly. That is
correct for a build-and-environment smoke harness and is not a defect to repair
here.

### Entry-point drift

Every `make` invocation in `config/phases/local.yaml` resolved against the
Makefile in its declared `workdir`. Seventeen invocations, six directories:

| Workdir | Phases | State |
|---|---|---|
| `core/storefront-client` | `storefront_client_tests` | resolves |
| `domains/vms/provisioning/iac` | `iac_contract_tests` | resolves |
| `e2e-tests` | `e2e_marker_tests`, `full_integration_sweep`, `integration_harness_unit_tests` | resolves |
| `buyer` | `buyer_tests` | **absent** |
| `policy` | `policy_tests` | **absent** |
| `service` | `shared_service_tests` | **absent** |

`buyer` resolves cleanly to `domains/vms/buyer`, which carries all three targets
the phase names — `reinit`, `test`, `smoke-test`.

`policy` resolves to `kit/policy`, which carries `test` but not `reinit`.

`reinit` is not a harness affordance. It maintains a project's `.venv`
dependencies and is the target a developer runs after changing an internal
dependency. A project that has a virtual environment and no way to refresh it is
missing a standard target, so the repair is to add `reinit` to
`kit/policy/Makefile` — not to drop the phase command.

That is a correction to the product, but not the harness bending the product to
suit itself: the target is owed to `kit/policy`'s own developers whether or not
the harness ever calls it.

**Wider finding, not resolved here.** 16 of 33 projects with a `pyproject.toml`
have no `reinit` target: `core`, `core/registry-client`,
`core/storefront-client`, `domains/apicredits/middleware/python`,
`domains/vms/provisioning/iac`, and six of the eight `kit/*` packages have
Makefiles without one; `domains/bare_metal/provisioning/adapter`,
`domains/vms/domain`, `domains/vms/provisioning/client`, `provisioning/compute`,
and `tools/issue-discovery` have no Makefile at all.

It is not a kit-versus-domains convention — `kit/config` and `kit/fulfillment`
do have `reinit` while their six siblings do not. Some absences are probably
correct: `tools/issue-discovery` is deliberately isolated behind
`uv --no-config`, and several of the Makefile-less projects may be wheel-only
libraries with no environment to maintain. Deciding which of the sixteen owe a
target is a separate change; this one fixes the single package it needs and
records the rest.

`service` does not resolve from the configuration alone, and this change does
not resolve it either. See "Open questions".

### Disposition of the 20-path review manifest

The manifest frozen at merge `d00b0641` / second parent `a6682051` is a review
envelope, not an inventory of any branch's current contents. Against
`e91767a3`:

| Manifest paths | Disposition |
|---|---|
| `config/phases/local.yaml`, `src/issue_discovery/{cli,issues,runner}.py`, `tests/test_{bootstrap,cli,issues,runner}.py`, `README.md`, `docs/development/ISSUE_DISCOVERY.md` | Present on `dev`. Inherited. In scope for this change where drift requires it. |
| Every `config/capacity/*` path, both capacity schemas, `capacity.py`, `test_capacity.py` | On no branch `dev` contains. Excluded. Not seeded from any branch; re-derived by a later change if wanted at all. |
| G2 fixtures | Inert regardless. |

Recorded here so a later session classifies rather than rediscovers.

## Decisions

### The harness section in TESTING.md is rewritten, not deleted

Two options, and the choice matters more than it looks.

Deleting the section removes the incorrect citations immediately and leaves
`TESTING.md` silent about where the harness sits. That silence is a real loss:
the document's central rule is "put a test at the lowest level that can
meaningfully prove the behavior", and a reader who finds `tools/issue-discovery`
with no guidance has a plausible fifth level in front of them and no statement
that it isn't one.

Rewriting keeps the part that is true today — the harness is outside the
jurisdiction table, product behaviour belongs at the level that owns it, the
harness earns a test only when the behaviour is the harness's own — and drops
the capacity-specific claims and both dangling citations.

Rewriting is chosen. The deleted paragraphs return with the change that makes
them true, which is the ordinary promotion path rather than a special case.

Note one factual error worth not reproducing: the existing text says the harness
"performs no market, wallet, cloud, host, provisioning, VM, or GPU action." The
tool that exists starts a compose stack in mock provisioning mode and registers
a mock host. That claim describes an intended future component, and repeating it
about the current tool would be false in a permanent document.

### Configuration validation resolves entry points by invocation

Every entry point a phase declares is resolved by asking the build system,
not by pattern-matching the Makefile:

- a `make <target>` command resolves by running `make -n <target>` in the
  declared working directory;
- any other command resolves by locating its executable on `PATH`.

`make -n` prints what would run and executes no recipe, so the check has no side
effects. It is materially stronger than parsing: it resolves `include`
directives, variable expansion, pattern rules, `.PHONY` declarations, and the
whole prerequisite chain, so a target that exists but depends on one that does
not is caught. Parsing `^target:` sees none of that.

Rejected: parsing target definitions out of the Makefile. The premise for
parsing is that the environment might lack the tools a Makefile references,
making invocation flaky. That premise does not hold here: the harness runs in a
pinned image. Environment completeness is a controlled
property of that image, not an uncertainty to design around. A phase command
whose tooling is missing is a defect in the image, and the correct response is
to add the tool to the image, not to weaken the check so it survives the
omission.

Rejected: validating during the run, just before each command. It catches the
same drift, but only for phases the run reaches, and only after the earlier
phases have spent their time. A configuration defect should not require a
partial run to discover.

Rejected: invoking the targets for real. That is running the harness, not
validating it.

**Known limit.** `make -n` does not expand recursive make inside a recipe. A
target whose recipe is `cd core/registry && make reinit && make test` prints the
line; it does not resolve `reinit` in `core/registry`. Nested entry points
therefore remain unvalidated, and the check must not be described as proving
more than it does.

**Where it runs.** As a load-time check in the harness, and — once the harness
image exists — as a step inside that image, so that entry-point resolution and
image completeness are established together against the same environment the
harness will actually use. The image-side step belongs to the image change, not
this one.

### Entry points are Make targets, and there are two

An external caller needs something stable to name. Two targets, because
running the harness and validating the harness are different acts with different
audiences:

- `make issue-discovery` — the runner, delegating to `./scripts/issue-discovery`
  and passing arguments through.
- `make issue-discovery-test` — the locked suite, in the tool's own `uv`
  environment.

Rejected: one target with a mode argument. The two have different failure
meanings — a red suite is a defect in the harness, a red run is a finding about
the product — and a shared exit code makes an external caller disambiguate by
parsing output.

Rejected: adding the suite to the repository's Tests workflow. `TESTING.md`
already records why it is excluded — the bootstrap tests inspect the host — and
this change does not revisit that. The consequence is that the suite's green
state remains an unenforced claim; that is a known gap and belongs to whichever
change is willing to make the bootstrap tests hermetic.

## Alternatives rejected

**Rebuild the runner instead of repairing it.** The tool is 4,277 lines of
working, tested, inherited code whose only demonstrated defect is stale
configuration. Rebuilding would discard the collectors, the workaround
mechanism, the redaction check, and the duplicate-detection behaviour to fix
three directory names.

**Repoint the configuration from the harness branches.** Both branches have
newer phase configurations. Both are excluded provenance, and the newer
configuration is entangled with a capacity layer this change deliberately does
not import. The three destinations are resolvable from the current tree, which
is the only source the cutoff rule permits.

**Defer the `TESTING.md` correction to the capacity change.** That leaves a
permanent document citing two nonexistent references for however long the
capacity work takes, and makes the eventual correction look like part of a
feature rather than the removal of an error. It also leaves the incorrect
non-execution claim in place while the harness demonstrably executes a compose
stack.

## Open questions

### What was the `service` workdir?

The `shared_service_tests` phase declares `workdir: service`, runs `make reinit`
then `make test`, and is named "Shared service package tests". No `service`
directory exists on `e91767a3`.

Three current packages define `reinit` and could be the successor: `kit/config`,
`kit/fulfillment`, and `core/storefront`. Nothing in the configuration
distinguishes them. The phase's position is weak evidence — it runs after
`build` and before the storefront-client and integration phases — and name
similarity is not evidence at all.

Two things would answer it and neither is available from the tree: history on
the directory across the POOLS and kit reorganisation, or someone who remembers
what the phase covered.

This change removes the phase rather than guessing. Removal keeps the
configuration loadable and leaves the question intact; it is not an answer to
it. Whoever answers restores the phase against the right package, which is a
small edit. Repointing it now at a plausible directory would be worse than
removing it: the phase would run, pass or fail, and attribute its result to a
package nobody chose.


---

## Disposition

**Archived 2026-08-26.** Superseded by `correct-testing-documentation` here. The runner half is retired without a successor, not implemented.

**What carried forward.** The `TESTING.md` correction stays: this repository documents a subsystem that has never existed on `dev`, and that is a defect independent of any harness. The runner repair, phase-configuration repointing, and Make targets are dropped. The `reinit` coverage gap is already owned by `remove-relative-uv-sources` task 2.5 and needs no new home.

**Referenced, not duplicated.** `design.md`'s inventory of the inherited tool — what exists, what its configuration points at, and what no longer resolves — is the record of why repair was not attempted. Removing `tools/issue-discovery` is deferred until a working replacement exists.
