---
tags: [repository, architecture, dependencies]
---

# Package layers

The rules that place this repository's packages: their layer, scope, and kind, the
check holding them, and how the tree's divergences are recorded. What the layers,
the families, and the kit areas are is
[`ARCHITECTURE.md`, "Package and dependency layers"](../../development/ARCHITECTURE.md#package-and-dependency-layers).

Three independent questions decide whether a package is in the right place — direction, knowledge, and ownership ([`dependencies.md`, "Three questions place a package"](../engineering/dependencies.md#three-questions-place-a-package)). Here:

- **Direction** is the **layer** question: a reusable capability must not depend on an application or on a concrete market.
- **Knowledge** is the **scope** question: may this package know about that family, domain, or mechanism? Market-neutral code must not learn a market by accident.
- **Ownership** is review's: a storefront that imports an authority's matching predicate, a kit that reads a user's configuration file, a composition root whose non-root modules name a contribution — each passes the first two questions.

The first two are stated below as rules a check can hold; the third is stated as placement tests, [`family-kits.md`](family-kits.md#placement-tests)'s among them. A package's **kind** names what it defines and, for a few kinds that exist to be light, bounds what it may depend on. `make check-architecture` holds the layer, scope, and kind rules over every project, reading what no one package owns from [`ARCHITECTURE.toml`](../../development/ARCHITECTURE.toml) beside the architecture document and what a package owns about itself from its own `pyproject.toml`; it runs in CI and in `make check-packaging`, so it is part of every change's closeout. The rules file encodes this file's rules and nothing more, and records every divergence the check can see with the change that owns it.

## Layers

The four layers — core, kit, specialization, and composition — are
[`ARCHITECTURE.md`, "Repository layers"](../../development/ARCHITECTURE.md#repository-layers).
A package depends only on its own layer or a lower one, and dependencies within one layer are acyclic. Every layer shares one definition of "depends on": every import form ([`dependencies-python.md`, "Every import form counts"](../engineering/dependencies-python.md#every-import-form-counts)), and every declaration in the package's `pyproject.toml` ([`dependencies.md`, "Declare what you import"](../engineering/dependencies.md#declare-what-you-import)). A distribution only a project's tests import belongs in its `dev` dependency group, which is not a runtime dependency and which the check does not read, so a runtime declaration is removed only once neither the source nor the tests import it. The check reads import statements: a package loaded by name through `importlib` or `__import__` is an edge it cannot see, and no internal package is loaded that way.

Core carrier packages must not import domain vocabulary or concrete mechanism implementations. `market_core.settlement` ships the dependency-light `SettlementStageTable[StageT]` and `SettlementEvidence` exports with `py.typed`. Kits and domains may depend downward on these carriers; core does not require callable stages, shared stage methods or a kit lifecycle adapter. Domain packages may implement core hook shapes but should not make core depend on a concrete market. Composition roots own wiring and may depend on all lower layers.

## Scope

A package's scope is the set of specific things it is permitted to know: nothing, a market family, a domain, a settlement mechanism, a dispute interface, or permitted combinations of these. Scope is a set rather than a position, because one package may know a domain and a mechanism at once — a VM Alkahest codec does — and a storefront knows its domain and every mechanism it composes. A domain that belongs to a family implies the family; a domain with no shared vocabulary beneath it has no family and implies nothing.

One rule follows: **a package may depend only on packages whose scope is a subset of its own.** A package that knows nothing specific depends on nothing specific; a family package never depends on one of its domains; sibling domains never import each other; a mechanism-neutral kit never imports a mechanism kit; a domain codec may import its mechanism's kit because its scope names the mechanism. A dependency is an import or a declaration: a package that declares another in its `pyproject.toml` to have it installed knows that package as surely as one that imports it, so a storefront that installs a sibling domain's contribution composes that domain.

Scope is permission, declared independently of the imports it governs, and the declaration is the package's place in the tree: a package under a domain's directory is scoped to that domain, a package under a family's directory to that family, a kit to nothing — or to the one mechanism or dispute interface it *is* — and a specialization that knows a mechanism carries the mechanism in its name. A composition is scoped to the domain it lives under and composes only that domain; a composition under a family directory composes that family's domains, which is what makes it a family composition root rather than a label making it one. The one knowledge a package does not declare is which mechanisms a composition installs: a storefront's mechanisms are whatever mechanism kits it composes, bounded to the domain it lives under.

Placing a package is therefore the same act as declaring its scope. A package that serves one domain goes under that domain; one that several domains of a family share goes under the family, whose directory `ARCHITECTURE.toml` names — `domains/api` for the api family, `domains/compute` for the compute family; one that knows no market goes directly under `kit/`, which holds no specialization; one that composes goes with the domain or family it composes. A contracts or client package carries that kind in its name. Nothing elsewhere — a label in `pyproject.toml`, a comment at an import — may widen what the path grants.

Each layer bounds the scope a package in it may hold:

| Layer | Scope may contain |
|---|---|
| core | nothing |
| kit | nothing, exactly one mechanism, or exactly one dispute interface — only its owning kit holds that scope, never both |
| specialization | at least one family or domain, plus any mechanisms its name carries and dispute interfaces it composes |
| composition | the domain or family it lives under, plus the mechanisms and dispute interfaces it composes |

What a composition composes is not knowledge its dependents gain: depending on a composition is a layer violation in its own right, and the scope rule compares only the scope a package's place grants it.

Consequences worth stating: a kit that comes to know a family is a specialization in the wrong directory; a kit that comes to know two mechanisms cannot exist, because the knowledge is either a mechanism-neutral abstraction or composition logic; a specialization that knows nothing specific is a kit in the wrong directory; a composition under one domain that imports a sibling domain is composing something it does not live with. The placement tests of [`family-kits.md`](family-kits.md) are the scope rule applied to a market family.

Scope extends to what a package's tooling writes. A domain's tooling never writes another domain's artifact, even where every import its generator makes is permitted: the VM storefront's values-schema generator writes the VM storefront chart's schema and the umbrella chart's definition of its `storefront` subchart, which is VM's chart, and the bare-metal storefront's generator writes only the bare-metal chart's. Sharing between them goes through a kit, as the generator itself does. This is guidance no check enforces; review holds it.

## Kind

Kind names what a package defines. Most packages are a **library** of mechanisms, vocabulary, codecs, or policies, and their kind adds no rule beyond their layer. An **executable** is a composition's entry point. Two kinds exist to be light, and their constraint is that they stay so:

- **contracts** define an API — wire models, route declarations, versions — and depend on nothing heavier than core, foundation kits, and their own family's vocabulary. A contract's scope is that of its widest consumer, so a contract the compute family's storefronts all call is a family contract even when one service serves it; cross-scope use is the signal to widen the contract, not to import across.
- **client** wraps one API and depends on its contracts, core carriers, the identity kit, and an HTTP library.

Being a **plugin** is a property a package of any kind may have, not a kind: a package that registers into one of the entry-point groups a host discovers at startup — a buyer domain, a storefront contribution, a delivery sink other than the built-in ones — is imported by nobody. A buyer is an executable that is a plugin; a delivery sink is a kit library that is one. A host declares a plugin to have it installed, which is composition, and never names it in an import. Registering into an extension point that libraries contribute to, such as a domain's vocabulary registering its storefront domain, does not make a package a plugin.

The tree carries layer, scope, and kind in a package's path and name, and the check reads them this way:

| Path | Layer | Kind |
|---|---|---|
| `core/<name>` | core | library |
| `kit/<name>` | kit | library, or the kind word after its last hyphen |
| `domains/<scope>/…/<last>` | composition for an executable, else specialization | the kind or role word that is `<last>` or follows its last hyphen, else library |

The kind words are `contracts` and `client`; the role words `storefront`, `buyer`, `service`, and `app` make an executable. A word is read only when it is one of these, so `kit/capability-shape` is a library, and role words are not read under `kit/`, because a kit composes nothing: `kit/storefront` is a library. The scope directory names a family or a domain, a domain bringing its family when it has one, and a mechanism's name in `<last>` adds that mechanism. A project at a scope directory's root, or under a nested path such as `domains/vms/provisioning/adapter`, reads the same way. Tooling projects — `e2e-tests`, `tools/`, `scripts`, and `dev-env` — and virtual projects are outside the architecture.

A **standalone component** under `tools/` is outside it too, but stricter than any layer: it depends on no internal package at all, only on third-party distributions and the standard library, and names no market concept, so it can be lifted into a repository of its own as it stands. Because `make check-architecture` does not read `tools/`, each one holds that boundary in a structure test of its own, and its tests join `make test` through a root target ([`tools/README.md`](../../../tools/README.md#standalone-infrastructure-components)). The frps admission plugin, [`tools/frp-grant-admission`](../../../tools/frp-grant-admission/README.md), is one ([capability](../../../openspec/specs/frp-grant-admission/architecture.md)), as are the process time source, [`tools/injected-time`](../../../tools/injected-time/README.md) ([capability](../../../openspec/specs/injected-time/architecture.md)), and the eventing system, [`tools/eventing`](../../../tools/eventing/README.md) ([capability](../../../openspec/specs/eventing/architecture.md)).

Infrastructure that is not specific to the market, built here, is such a standalone `tools/` component, ready to lift into a repository of its own, never part of a market package — neither a kit nor a family package, however few packages use it ([`implementation.md`, "Generic infrastructure is a standalone component"](../engineering/implementation.md#generic-infrastructure-is-a-standalone-component)).

Two allowlists bound what a package may depend on. A **kind allowlist**, one per light kind in the rules file, names what a package of that kind may depend on: a **contracts** package on core, the identity, capability-shape, and capability-admissibility foundation kits, and its own family's vocabulary; a **client** on contracts, core, and the identity kit. A **package allowlist** belongs to one package whose lightness is part of its contract — the shape, pricing, and admissibility kits, which import only the standard library and the shape kit, the identity kit, the settlement runtime, the migration engine kit, and the thin contracts and clients — and is stated in its own `pyproject.toml`, as `allowed-dependencies` under `[tool.arkhai.architecture]`: every distribution, internal or third-party, it may declare or import beyond the standard library. Such a package must also declare every third-party distribution it imports. A third-party import matches the distribution of the same normalized name, or one an `import-roots` entry names; that alias is taken as the package states it, because checking it would need installed metadata. Outside packages with an allowlist, whether third-party declarations are complete rests on each project's own environment and tests, and removing a package's allowlist removes its constraint, which is a visible edit to that package. The table may only narrow or annotate its package; it cannot state a layer, kind, or scope, so nothing a package declares about itself widens what its path grants. The plugin entry-point groups are `market.buyer_domains`, `market.storefront_contributions`, and `market.delivery_sinks`, whose owner `kit/delivery` registers its built-in sinks without becoming a plugin.

A project whose path does not yet say what it is carries an **override** row stating the layer, kind, and scope the path should yield and the change that will move or rename it. The row fails once the path yields the same, or once a mechanism it grants is known by none of the project's dependencies.

## Where the current tree diverges

The rules above are the contract, and the tree does not yet meet all of it. [`ARCHITECTURE.toml`](../../development/ARCHITECTURE.toml) is the authoritative list of every divergence the check can see, in two tables. An **override** row records a package whose place in the tree says the wrong thing: its path does not yield the layer, kind, or scope it has, and the row fails once the path does. An **exception** row records an edge that breaks a rule: it names the rule it excuses, and it fails once it excuses nothing. Each row names the change that owns the remedy and the date, so neither list can outlive its causes, and a change may not be archived while it owns a row (`make check-architecture-change CHANGE=<name>`). An internal distribution a package declares without importing carries its runtime reason in that package's `pyproject.toml`, under `[tool.arkhai.architecture.runtime-dependencies]`, unless it is a plugin the declaration installs. None of these is a sanctioned edge, and no new dependency of the same shape should be added while one stands.

Divergences the layer and scope rules cannot see stay with review and with the owning kit's own boundary test: `kit/alkahest` reads a user configuration file, a content judgement, owned by a change in the [change index](../../../openspec/changes/README.md).

A kit-to-kit edge the kit-area order forbids ([`ARCHITECTURE.md`, "Kit areas"](../../development/ARCHITECTURE.md#kit-areas)) — one two kits of empty scope may form under the layer and scope rules — is removed, by moving the code it reaches for to where both sides may depend on it or by injecting a port the lower kit defines ([`dependencies.md`, "A port is satisfied structurally"](../engineering/dependencies.md#a-port-is-satisfied-structurally)), rather than sanctioned by amending the order. Amending it retires the order's rule for every kit, not for the one edge. Once removed, each kit's boundary test forbids the edge in its own direction, since no check holds the order and acyclicity fails only once both directions exist: `kit/site` and `kit/resource-pools` each forbid the other.

## A boundary change

A contract moved or renamed at a package boundary is validated as
[`boundary-changes.md`](../engineering/boundary-changes.md) lists. Here the
dependency direction, `TYPE_CHECKING` imports included, is held by
`make check-architecture` ("Layers" above).
