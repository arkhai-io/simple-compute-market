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
| `core/<name>` | core | library |
| `kit/<name>` | kit | library |
| `kit/<name>-<kind>` | kit | the suffix |
| `roles/<name>` | composition | executable |
| `domains/<scope>/…/<last>` | by kind | the last segment if it names a kind, else a `-<kind>` suffix, else library |

Kinds are four: `library`, `executable`, `contracts`, `client`. Being a plugin is
a property, not a kind (below). The words a reading may take are the kind words
`contracts` and `client` and the executable role words `storefront`, `buyer`,
`service`, and `app`; a last segment or `-<word>` suffix is read only when it is
one of them, so `kit/capability-shape` is a library, not a kind "shape", and
`domains/apicredits/sample-app` is an executable through `app`. A role word
yields `executable`. Role words are not read under `kit/`, because a kit composes
nothing: `kit/storefront` is a library. `adapter`, `vocabulary`, `listings`,
`negotiation`, and `settlement` are descriptive segments that yield `library` —
what a VM specialization is about is not a kind. Under `domains/`, an executable
is in the composition layer and every other kind in the specialization layer. The
reading needs no special case for a vocabulary project at a scope directory's
root or for the nested `domains/apicredits/middleware/python`: both classify as
libraries in the right scope. Where the current tree does not match these
readings, an **override row** states the attributes and names the change that
will move or rename the project; the row fails once the path conforms or once a
scope element it grants goes unused.

### A plugin is a registrant in a listed group, and a property rather than a kind

The first draft made any non-console entry point a plugin that nothing may
import. That fails correct code: `arkhai-vms` and `arkhai-bare-metal` register
`market.storefront_domains` and are imported by their own buyers and storefronts,
`kit/alkahest` registers `market.buyer_aggregation_policies` and is imported
everywhere, and `kit/delivery` registers its built-in sinks. The rules file
therefore lists the **plugin groups** — `market.buyer_domains`,
`market.storefront_contributions`, `market.delivery_sinks` — and a package that
registers into one is a plugin. A group may name an **owner**, the package that
discovers the group and may also register into it; `kit/delivery` owns
`market.delivery_sinks`, so its built-in sinks do not make it a plugin and
`kit/delivery-apprise` is one. Every other group is an extension point libraries
contribute to and confers nothing.

The first draft also made plugin a kind, which left a project with a role name
that registers into a plugin group — every buyer, and the VM storefront, which
has console scripts and registers a storefront contribution — with two kinds and
no layer: the `domains/` reading takes its layer from its kind. Plugin is
therefore a property a package of any kind may have. Layer and kind come from the
path and name as for every other package, so a buyer is an executable in the
composition layer that is a plugin, and `kit/delivery-apprise` is a kit library
that is one. The property adds exactly one rule, in-degree, and the rule is about
imports: a host declares a plugin to have it installed, and that declaration is
judged by the scope rule like any other. Nothing imports a plugin on the current
tree; the VM and bare-metal storefronts only declare them.

### Declarations are dependencies

Layer, scope, and cycle rules run over the union of a package's imports and the
internal distributions it declares, optional extras included. A declaration with
no import is still knowledge: the VM storefront declares
`arkhai-bare-metal-storefront` and `arkhai-bare-metal` because it is the
compute-family storefront shell that installs the bare-metal contribution, and a
domain-scoped package installing a sibling domain is the scope rule's own example
of a violation. That finding is owned by `kit-owned-storefront-shell`, which
decides where the shell lives; it is not a stale declaration to delete.

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
form handling, a plugin to install, or an optional extra with no static import.
`ARCHITECTURE.md` requires such a declaration to carry a stated runtime reason and
gives it no home, so the rules file has a **declarations table** — distribution,
dependency, reason — and the warning applies only to a declared internal
distribution with neither an import nor a row, which lets it become a failure
later. External distributions are not examined in either direction: mapping a
third-party import root to its distribution needs installed metadata the
stdlib check does not have, and a project's own environment already fails on an
undeclared third-party import when its tests or type check run. The scan on 2026-10-11
found six projects with undeclared direct internal imports —
`arkhai-core-storefront`, `arkhai-apicredits-buyer`, `arkhai-bare-metal-storefront`,
`arkhai-kit-alkahest`, `arkhai-kit-policy`, and `arkhai-kit-storefront`
(`arkhai-core` and `arkhai-kit-identity`, reached today only through
`arkhai-core-storefront`) — and twelve declared internal dependencies across
seven projects with no import; the audit classifies each as a row or a removal.

### Rules are independent and each names a file and line

| Rule | Fails when | Mode at gate |
|---|---|---|
| layer | `layer(dst)` is above `layer(src)` | fail |
| cycle | a same-layer strongly connected component has more than one package | fail |
| scope subset | `scope(dst) ⊄ scope(src)` | fail |
| layer/scope | a scope violates its layer's bounds, or a kit holds `{m}` without being `m`'s kit | fail |
| undeclared import | an imported internal distribution is not declared | fail |
| unused declaration | a declared internal distribution has neither an import nor a declarations-table row | warn |
| kind budget | a `contracts` or `client` package exceeds its budget (below) | fail once the audit shows the kind clean |
| plugin in-degree | any package imports a plugin; declaring one is permitted | fail |
| vocabulary | a package's string literals contain a scope element's token outside its scope | warn; fail at core and kit once the gate lands (see "Planning decisions") |
| exception expiry | an `[[exceptions]]` row excuses no current finding: its edge or token is gone, or the edge no longer breaks the rule the row names | fail |
| override expiry | an `[overrides]` row names a path that now classifies without it, or grants a scope element that none of the project's edges uses | fail |

Kind budgets: `contracts` may depend on core, foundation kits, and its own
family's vocabulary; `client` on its contracts, core, the identity kit, and an
HTTP library. These are the reviewed refinement of the first draft, which
allowed a client no core carriers and a family contract no family vocabulary;
both were wrong for packages that exist today. A plugin has no budget beyond its
layer and scope; its constraint is the in-degree rule.

### Audit before gate

The library and rules file land first with every rule in report mode, and the
report over the whole tree is classified in this change's design before any rule
fails a build: each finding is a defect with an owning change, an accepted case
with a stated reason, or a rule error. The exceptions table is seeded from the
defects. This is the order because the first draft of this change promised to
seed every known exception and pass on day one, and a single scan showed the known
set was five short. A gate turned on against an unaudited tree becomes an
exercise in loosening rules or adding exceptions after the fact.

A finding is fixed in this change, during the audit, when its remedy is purely
declarative — a missing declaration added, or a declaration with no import and no
runtime reason removed — and changes no edge, no behaviour, and no package's place.
Every other finding is owned by a change and seeded as a row. The exceptions table
exists to park findings whose remedy needs design — a move, a split, a redesigned
seam — with the change that will do the designing; a declaration needs none, and
parking one under a placeholder owner would make the first row that never expires.
A new declaration matches the specifier of the distribution that provided it
transitively, so the lock resolves the same version. The baseline records each
finding resolved this way, so the classification stays complete. The rule does not
reach an undeclared import whose edge another change is removing: declaring
`core/storefront`'s `market_alkahest` would ratify the edge, so it keeps its row.

### Exceptions are owned and expire

Every row carries the owning change, the rule it excuses, and the date. A row is
deleted by the change that owns it at closeout. A row that excuses no current
finding fails the check — whether its edge is gone or the edge no longer breaks
the named rule — so a change cannot fix the code and forget the row, a rule
revision cannot leave a row excusing nothing, and a row cannot be seeded for an
edge the rules do not report. A change cannot re-add the edge without the check
naming it. `--strict` ignores the table and shows the full set. Once the gate
exists, the table is the authoritative list of divergences the check can see and
`ARCHITECTURE.md`'s paragraph points at it.

### Overrides state attributes, exceptions excuse defects

The two tables are not interchangeable. An override asserts what a project truly
is when its path says otherwise: its layer, kind, or scope is right and only its
place in the tree is wrong, so the row is owned by the change that moves or
renames it. An exception excuses an edge that is wrong, so the row is owned by the
change that removes the edge. Using an override for a defect would record a
violation as the package's real scope, and the scope rule would then pass every
later edge of the same shape.

An override expires when its path classifies without it, and also when it grants
a scope element none of the project's edges uses. The second condition is what
makes "the row expires either way" true: a package whose mechanism import is
removed before it is renamed would otherwise keep a grant for knowledge it no
longer has.

### The check joins `make check-packaging`

`planning-governance` already requires every closeout to run the packaging check
and resolve every failure. Adding `check-architecture` to that target puts
architecture on every closeout with no new process step. Closeout is not enough
on its own: about eight of the per-package tests this change retires run in the
CI matrix today, so retiring them against a closeout-only check would weaken
continuous enforcement. `make check-architecture` therefore also runs in the
existing deployment-contracts CI job, which it can, since it needs plain
`python3` and no wheelhouse.

### Per-package tests are subsumed, not deleted in bulk

Each retired test is retired in its own commit, after the repository check
has been shown to fail on the synthetic violation that test fails on, and after the
owning change for any edge the local test guarded has closed, so no local guard is
removed while the global check still excuses its edge. Several assert things the
repository rules express directly (`kit/fulfillment` forbids
`compute_provisioning`: a layer rule; `domains/bare_metal/storefront` forbids every
VM package: a scope rule). `core/tests/unit/test_domain_boundaries.py` already
scans for `CONCRETE_IDENTITIES` literals and becomes the three domains' `tokens`.
`kit/settlement-runtime`'s test forbids external packages (`fastapi`, `httpx`,
`eth_account`), which becomes an `external_budget` on its row.

A test is kept, not retired, when it asserts something the repository check
cannot express. Two are known: the provisioning service's test, which allowlists
two adapter entrypoints, and `kit/site`'s, if `inject-site-pool-authority` keeps
the pool authority repository-wide and adds `market_resource_pools` to the
modules that test forbids — a kit-to-kit edge the layer and scope rules allow and
the kit-area order forbids. Retiring a test is therefore a per-test judgement
against the check's rules, not a count to reach.

### The kit-area order is not encoded

`ARCHITECTURE.md`'s kit areas — foundation, authority, fulfillment, storefront
role composition, with the mechanism kits beside the foundation — are a map of
where a capability lives and what it may build on, not a second ordering inside
the kit layer. Encoding them would reintroduce the per-layer sub-ordering the
layer model deliberately rejected, and would put every kit's area in the rules
file as a classification the path does not carry. The check holds the layer and
scope rules only; an edge between two kits that both allow is a review finding,
guarded where it matters by that kit's own boundary test.

The cost is that the check cannot see `kit/site` → `kit/resource-pools`: both are
kits of empty scope and the edge forms no cycle. That edge is owned by
`inject-site-pool-authority`, and both of its outcomes become visible without new
machinery. If the pool authority becomes a compute family-kit distribution, the
edge is `{}` → `{compute}` and the scope rule fails it. If the authority stays
repository-wide, the port removes the import and `kit/site`'s boundary test
guards against its return. No exception row is seeded for it, nor for
`apicredits_service` → `kit/resource-pools`, which is a composition depending on
a kit and legal until the authority is scoped, at which point the scope rule
reports it; a row for either would excuse nothing and fail exception expiry.

## What the rules deliberately do not catch

So that no one expects them to: the VM storefront importing `kit/site`'s matching
predicate passes layer and scope and is an ownership judgement; `kit/alkahest`
reading a user configuration file is a content rule; the provisioning service is a
family composition and which of its modules may name an adapter is a wiring
judgement; and a kit-to-kit edge the kit-area order forbids but layer and scope
allow, such as `kit/site` → `kit/resource-pools` today, is a placement judgement.
Each is owned elsewhere. The ownership question in `ARCHITECTURE.md` is
the review's, by design.

## Resolved questions

- **Rules file home.** `ARCHITECTURE.toml` under `docs/development`. Forced:
  `make check-comment-hygiene` rejects any `.toml` outside `docs/` and `openspec/`
  that names a change directory, and every exception row names its owning change.
- **Mechanism in the name for existing specializations.** No renames here, and
  the four packages importing a mechanism kit without naming it split by what the
  import is. `arkhai_vms_settlement` and `arkhai_apicredits` (which imports both
  `kit/alkahest` and `kit/arkhai-payments`) legitimately know their mechanisms and
  get override rows owned by `align-package-paths-with-layers`, which renames
  them. `arkhai_vms_listings` and `arkhai_vms_negotiation` import `kit/alkahest`
  as a defect `move-escrow-into-alkahest` removes, and get exception rows owned by
  that change. Every row expires either way: an override once its path conforms or
  its grant goes unused, an exception once its edge is gone.
- **The kit-area order.** Not encoded; see "The kit-area order is not encoded".
  `kit/site` → `kit/resource-pools` is left to `inject-site-pool-authority`, whose
  outcomes the check sees through the scope rule or that kit's own boundary test.
- **Plugin as kind.** Plugin is a property, not a kind; see "A plugin is a
  registrant in a listed group, and a property rather than a kind".
- **Which per-package test retires first.** Not a design decision. The criteria are
  in "Per-package tests are subsumed, not deleted in bulk": a test retires only
  after `check-architecture` runs in CI, after the check fails on that test's
  synthetic violation, and after every owning change for an edge it guarded has
  closed; a test asserting what the check cannot express is kept. The plan orders
  retirements by when those conditions hold.
- **Vocabulary projects at a scope root, and nested paths.** No rule and no
  override: the path reading classifies `domains/vms/domain`, the three root
  vocabulary projects, and `domains/apicredits/middleware/python` as libraries in
  the right scope. Where they live is `align-package-paths-with-layers`'s
  navigability decision, not the check's.
- **External dependency budgets.** An optional table, filled only for the packages
  whose per-package tests assert one today — `settlement-runtime`,
  `capability-shape`, `capability-pricing`, `identity`, and the contracts
  packages — so those tests can retire against it.
- **Tooling projects.** `e2e-tests`, `tools/*`, `scripts`, `dev-env`, and the
  virtual IaC project are skipped; `domains/apicredits/sample-app` is checked as
  an executable composition.
- **A domain with no family.** API credits has no shared vocabulary beneath it and
  no family entry in the rules file; its scope is `{apicredits}`. The
  `domains/<domain>/` reading yields `{family, domain}` only when the rules file
  names a family.
- **Dynamic imports.** No package loads another internal package through
  `importlib` or `__import__`; the few dynamic loads are third-party (`uvicorn`,
  `torch`, `keyring`). Scanning import statements is sufficient.

## Planning decisions

Taken while writing `tasks.md`; each is a default the maintainer may revise.

- **What `check-architecture-change CHANGE=<name>` scopes to.** The rows the named
  change owns, and it fails while any remains. `scripts/resolve-review-scope.py`
  maps projects, manifests, and diffs, not change names, so "a change's review
  scope" had no existing meaning to reuse. The row-ownership meaning is the one
  closeout needs: a change owes the rows it owns, as it owes the citations it
  wrote, and gating it on every other change's rows would let one change block
  another's archive. `planning-governance`'s new scenario and
  `openspec/README.md`'s closeout part 8 use it.
- **How the four check scripts divide the rules.** By the question each answers:
  - `layers`: layer, cycle, layer/scope bounds, and override expiry, since an
    override changes classification;
  - `scope`: scope subset and vocabulary;
  - `dependencies`: undeclared import and unused declaration;
  - `kinds`: kind budgets, external budgets, and plugin in-degree.

  Exception expiry runs in whichever script owns the rule a row names. Each is
  also its own Make target, as each packaging check is.
- **Vocabulary at core and kit fails from the gate.** The rule table said "fail
  at core and kit after one cycle" without defining a cycle. The audit phase is
  that cycle: the baseline classifies every literal finding, defects become
  exception rows like any other, and the gate then fails on new ones. It still
  warns in the specialization and composition layers, where a domain's own tokens
  are expected.
- **The report writes where it is told.** `scripts/architecture_report.py` writes
  to an `OUT` path or standard output, and the baseline is produced by passing the
  change directory on the command line. A script naming a change directory would
  fail `make check-comment-hygiene` and go stale at archive.
- **The test inventory is twenty modules and one function.** That count is from
  the current tree; the proposal's eighteen was an earlier count.
  `domains/vms/buyer/tests/test_no_resource_pools_dependency.py` asserts what an
  import loads at runtime, which no graph rule expresses, so it is kept. The
  disposition of every test is in `tasks.md` 3.1.
- **Retirements this change cannot finish are handed off.** A test whose guarded
  edge is still excused by another change's row at this change's closeout cannot
  retire here without breaking the design's rule. The owning change gains the
  retirement task instead, so archiving this change does not wait on every owner.

## Rule errors the audit found

The audit is where a rule meets the tree; these revisions were made to the rules
in "Rules are independent and each names a file and line" and are what
`scripts/architecture.py` implements.

- **An override's unused-grant expiry covers mechanisms only.** A family or
  domain an override grants is where the project belongs: the compute family's
  provisioning contracts depend on nothing compute-scoped, and a contract's
  scope is its widest consumer's, not its own imports'. A mechanism granted is
  knowledge, and expires once nothing the project depends on knows it.
- **A composition's composed mechanisms do not pass to its dependents.** The
  scope rule compares a dependency's own scope, from its path or override, not
  the mechanisms a composition gains from what it composes. Depending on a
  composition is the layer rule's finding; without this, every package depending
  on `core/storefront` also reported a scope finding for Alkahest.
- **Declaring a plugin needs no declarations row.** Installing a plugin is the
  runtime reason, and the classification already knows the target is one.
- **An unread project is a finding of its own.** `unclassified` reports a project
  whose path yields nothing and that has no override row, rather than defaulting
  it to a layer.
- **A declarations row expires.** `declaration_expiry` fails a row whose
  dependency is no longer declared or is now imported, for the same reason
  exception and override rows expire.
- **An external budget lists internal roots too.** The per-package allowlist
  tests it replaces say what a package may import at all — the shape kit "only
  the standard library", the pool client "only the contracts" — and a budget of
  third-party roots alone would let a light kit grow an internal dependency the
  layer rule allows. A budget is therefore every import root outside the
  standard library and the package itself, internal or third-party.
- **Two planned retirements were not graph rules.** The core buyer's "imports no
  settlement mechanism" test holds the buyer role mechanism-neutral, but a
  composition composes mechanisms by rule; and `kit/config`'s mechanism denylist
  also forbids `stripe` and `web3`, for which `kit/config` has no budget. Both
  tests stay.
- **A declaration can serve a project's tests.** The audit removed a
  declaration when the package source never imported it, but a project's
  tests run in the same environment, and the VM buyer's tests import the VM
  settlement codec. The CI suite caught the removal; the dependency moved to
  the buyer's `dev` dependency group, where a test-only dependency belongs and
  the architecture check, which reads runtime dependencies and extras only,
  does not look. Removing an unexplained declaration therefore also requires
  that the project's tests not import it.
- **A core package's kind is library.** The reading table's `carrier` names the
  layer's content, not a fifth kind.

## Review revisions

Taken after the implementation review, with the maintainer. They correct the
ownership of the rules file's contents and close enforcement gaps; the layer and
scope model, the import scan, and the audit-before-gate order stand.

- **A package's own constraints live in its own `pyproject.toml`.** The rules
  file centralized two kinds of fact a package owns: its external budget, and
  the reason it declares a dependency it never imports. Kept centrally, each
  edit to a package's dependencies was an edit in two places, and the list grew
  with every package. Both move to a `[tool.arkhai.architecture]` table in the
  package's `pyproject.toml`, beside the dependencies they constrain:
  `allowed-dependencies` and `runtime-dependencies`. What stays central is what
  no one package owns: the layer order and scope bounds; the families, domains,
  and mechanisms with their identity literals; the plugin groups; the kind
  budgets; and the overrides and exceptions. Overrides and exceptions are
  migration debt owned by a change, and they must stay under `docs/` anyway,
  because comment hygiene rejects a change name in any other `.toml`. The
  package table may only narrow or annotate a package. The checker rejects any
  other key, so no layer, kind, or scope can be declared there, and a label in
  `pyproject.toml` still cannot widen what the path grants. This supersedes "One
  rules file", the external-budget table, and the declarations table where those
  decisions placed the facts centrally.
- **A budget constrains declarations as well as imports.** A light package could
  declare a heavy third-party dependency without importing it, and the
  import-root budget never saw it. `allowed-dependencies` is one list of
  distribution names, internal and third-party:
  - every declared dependency must be on it;
  - an internal import maps to its distribution through the tree;
  - a third-party import root matches the distribution of the same normalized
    name, `eth_account` matching `eth-account`, with an `import-roots` table for
    the rare root whose distribution is named differently.

  One list rather than separate import and declaration lists, because the two
  would repeat nearly every entry. On the current tree the declaration side
  adds two entries: the identity kit's `keyring`, which it loads through
  `importlib` where the scan cannot see it, and the provisioning client's
  `pydantic`, which it declares for its contracts' models.
- **Discovery fails closed.** A non-virtual project outside the tooling paths
  whose wheel target is not exactly one package is reported as `unclassified`
  rather than skipped, so the check covers every project whether or not
  `make check-project-layout` ran first. No project is affected today; the only
  project without one wheel package is the virtual IaC project. Sharing one
  discovery implementation with `check_project_layout.py` was considered and
  deferred: it refactors a working check for no current finding.
- **The configuration is validated.** A `configuration` rule fails on:
  - a duplicate exception, override, or plugin-group row;
  - a family, domain, or mechanism, or a kind-budget distribution, that names
    nothing in the tree or the rules file;
  - an unknown key in a package's table;
  - an exception or override owner that is not an unarchived change directory
    under `openspec/changes/`.

  The orphaned per-package budget the review raised cannot occur: a budget
  lives in the package it constrains.
- **No per-package conformance test.** A test asserting each package's budget
  would restate the configuration a second time. Discovery failing closed
  covers "every project is checked", the configuration rule covers "every entry
  resolves", and removing a budget is a visible edit to that package's
  `pyproject.toml`.

## Open questions

None.
