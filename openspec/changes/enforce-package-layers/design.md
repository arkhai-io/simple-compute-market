# Design — one architecture check over every package

## Context

See `proposal.md` for why eighteen per-package tests are not enforcement and why
an audit precedes a gate. This document records the model the check encodes, the
decisions taken about how a script reads it from the tree, the conventions and
budgets this change owns until they are shown to hold, and the questions planning
must settle. The principles — four layers, scope as a set of permitted knowledge,
the subset rule, any import counting — are permanent and already in
`docs/development/ARCHITECTURE.md`.

## Decisions

### Scope is permission read from the path, never inferred from imports

A check that inferred a package's scope from its imports and then checked its
imports against that scope would authorize any dependency by the act of adding it.
Scope is therefore declared independently, and the declaration is the package's
place in the tree, because a path is the hardest thing to change without a signal
review sees. Four readings cover every package:

- A package under `kit/` has scope `{}`, unless it is the kit the rules file names
  for a mechanism, in which case its scope is `{m}`.
- A package under `domains/<family>/` has scope `{family}`.
- A package under `domains/<domain>/` has scope `{family, domain}`.
- A specialization that knows a mechanism carries it in its name:
  `domains/vms/settlement-alkahest` has scope `{compute, vms, alkahest}`. A
  specialization whose name carries no mechanism may import no mechanism kit.

Compositions differ in one respect. A composition composes whatever mechanisms it
installs, and that is not knowledge it can be wrong about, so its mechanisms are
the mechanism kits it imports. Its domain is still its path: a composition under
`domains/<domain>/` composes that domain alone, so `domains/vms/storefront`
importing a bare-metal package fails. A composition under `domains/<family>/`
composes that family's domains by rule — `domains/compute/provisioning-service` is a
family composition root because it lives at the family, not because a label says
so.

### Layer and kind are read from the path and name

| Path | Layer | Kind |
|---|---|---|
| `core/<name>` | core | carrier |
| `kit/<name>` | kit | library |
| `kit/<name>-<kind>` | kit | the suffix |
| `roles/<name>` | composition | executable |
| `domains/<scope>/…/<last>` | by kind | the last segment if it names a kind, else a `-<kind>` suffix, else library |

Kinds are five: `library`, `executable`, `contracts`, `client`, `plugin`. A last
segment or suffix naming an executable role (`storefront`, `buyer`, `service`,
`app`) yields `executable`; `adapter`, `vocabulary`, `listings`, `negotiation`,
and `settlement` are descriptive segments that yield `library` — what a VM
specialization is about is not a kind. A project declaring any entry-point group
other than `console_scripts` is a `plugin` whatever its name says. Where the
current tree does not match these readings, an **override row** states the
attributes and names the change that will move the project; the row fails once
the path conforms.

### What each layer's scope may contain

| Layer | Scope may contain |
|---|---|
| core | nothing |
| kit | nothing, or exactly one mechanism — and only the kit that *is* that mechanism holds it |
| specialization | at least one family or domain, plus any mechanisms its name carries |
| composition | the domain or family it lives under, plus the mechanisms it composes |

This table is what makes the subset rule bite on kits and compositions; without
it a kit could be placed under `kit/` with a mechanism in its name and legally
import anything. It is held here rather than in `ARCHITECTURE.md` until the audit
shows the tree can meet it.

### Every import node is an edge

The scan is an `ast.walk` over every `Import` and `ImportFrom` node in every module
under `src/`, excluding `tests/`. The enclosing context — module level, inside a
function, under `if TYPE_CHECKING:`, inside `try` — is recorded for the report and
ignored by every rule. Most of the violations the review found were function-local
imports whose comments argued they were not dependencies.

### Declared dependencies: one direction fails, the other warns

An imported distribution that is not declared is a defect; the environment that
happens to resolve it transitively is the next one to break. The reverse is not a
defect: a distribution may be declared for an entry point, a database driver,
form handling, or an optional extra with no static import. So a declared internal
distribution that is never imported is a warning that asks for a reason, and a
declared external distribution is not examined. The scan on 2026-10-11 found six
projects with undeclared direct internal imports — `arkhai-core-storefront`,
`arkhai-apicredits-buyer`, `arkhai-bare-metal-storefront`, `arkhai-kit-alkahest`,
`arkhai-kit-policy`, and `arkhai-kit-storefront` (`arkhai-core` and
`arkhai-kit-identity`, reached today only through `arkhai-core-storefront`) — and
two stale internal declarations, both on the VM storefront.

### Rules are independent and each names a file and line

| Rule | Fails when | Mode at gate |
|---|---|---|
| layer | `layer(dst)` is above `layer(src)` | fail |
| cycle | a same-layer strongly connected component has more than one package | fail |
| scope subset | `scope(dst) ⊄ scope(src)` | fail |
| layer/scope | a scope violates its layer's bounds, or a kit holds `{m}` without being `m`'s kit | fail |
| undeclared import | an imported distribution is not declared | fail |
| unused declaration | a declared internal distribution is never imported | warn |
| kind budget | a `contracts`, `client`, or `plugin` package exceeds its budget (below) | fail once the audit shows the kind clean |
| plugin in-degree | any package imports a `plugin` | fail |
| vocabulary | a package's string literals contain a scope element's token outside its scope | warn; fail at core and kit after one cycle |
| exception expiry | an `[[exceptions]]` row names an edge or token that no longer exists | fail |
| override expiry | an `[overrides]` row names a path that now classifies without it | fail |

Kind budgets: `contracts` may depend on core, foundation kits, and its own
family's vocabulary; `client` on its contracts, core, the identity kit, and an
HTTP library; `plugin` on anything, but nothing depends on it. These are the
reviewed refinement of the first draft, which allowed a client no core carriers
and a family contract no family vocabulary; both were wrong for packages that
exist today.

### Audit before gate

The library and rules file land first with every rule in report mode, and the
report over the whole tree is classified in this change's design before any rule
fails a build: each finding is a defect with an owning change, an accepted case
with a stated reason, or a rule error. The exceptions table is seeded from the
defects. This is the order because the first draft of this change promised to
seed every known exception and pass on day one, and a single scan showed the known
set was five short. A gate turned on against an unaudited tree becomes an
exercise in loosening rules or adding exceptions after the fact.

### Exceptions are owned and expire

Every row carries the owning change and the date. A row is deleted by the change
that owns it at closeout; a row whose edge is already gone fails the check, so a
change cannot fix the code and forget the row, and a change cannot re-add the edge
without the check naming it. `--strict` ignores the table and shows the full set.
Once the gate exists, the table is the authoritative list of divergences and
`ARCHITECTURE.md`'s paragraph points at it.

### The check joins `make check-packaging`

`planning-governance` already requires every closeout to run the packaging check
and resolve every failure. Adding `check-architecture` to that target puts
architecture on every closeout with no new process step.

### Per-package tests are subsumed, not deleted in bulk

Each of the eighteen tests is retired in its own commit, after the repository check
has been shown to fail on the synthetic violation that test fails on, and after the
owning change for any edge the local test guarded has closed, so no local guard is
removed while the global check still excuses its edge. Several assert things the
repository rules express directly (`kit/fulfillment` forbids
`compute_provisioning`: a layer rule; `domains/bare_metal/storefront` forbids every
VM package: a scope rule). `core/tests/unit/test_domain_boundaries.py` already
scans for `CONCRETE_IDENTITIES` literals and becomes the three domains' `tokens`.
`kit/settlement-runtime`'s test forbids external packages (`fastapi`, `httpx`,
`eth_account`), which becomes an `external_budget` on its row. The provisioning
service's test allowlists two adapter entrypoints the repository check cannot
model and is kept.

## What the rules deliberately do not catch

So that no one expects them to: the VM storefront importing `kit/site`'s matching
predicate passes layer and scope and is an ownership judgement; `kit/alkahest`
reading a user configuration file is a content rule; the provisioning service is a
family composition and which of its modules may name an adapter is a wiring
judgement. Each is owned elsewhere. The ownership question in `ARCHITECTURE.md` is
the review's, by design.

## Open questions

- **Rules file home.** `ARCHITECTURE.toml` under `docs/development`, beside the
  prose it encodes, or at the repository root beside `Makefile` where tooling
  configuration usually sits. The prose links to it either way.
- **Mechanism-in-name for existing specializations.** Today `arkhai_vms_settlement`,
  `arkhai_vms_listings`, `arkhai_vms_negotiation`, and `arkhai_apicredits` import
  `kit/alkahest` without a mechanism in their names. `move-escrow-into-alkahest`
  is expected to remove the listings and negotiation imports; the settlement codec
  legitimately keeps its. Whether the surviving packages are renamed
  (`settlement-alkahest`) or carry override rows until `align-package-paths-with-layers`
  moves them is decided by the audit's classification.
- **Vocabulary projects at a scope root.** `domains/compute`, `domains/bare_metal`,
  and `domains/apicredits` each hold the vocabulary project at the scope directory's
  root; `domains/vms/domain` is a subdirectory whose name is the scope word. Either a
  scope root that is itself a project is the vocabulary, which needs no move, or every
  vocabulary project moves to `domains/<scope>/vocabulary`. Decide with
  `align-package-paths-with-layers`.
- **Nested paths.** `domains/apicredits/middleware/python` has a segment the
  convention does not read. An override row covers it; whether the move change
  flattens it is that change's question.
- **External dependency budgets.** Whether `external_budget` is a general attribute
  every kit declares or exists only to carry the one per-package test that asserts
  it today.
- **Virtual and tooling projects.** `e2e-tests`, `dev-env`, `tools/*`, and `scripts`
  are skipped. `domains/apicredits/sample-app` is an executable composition; confirm
  it is checked rather than skipped as a demonstration.
