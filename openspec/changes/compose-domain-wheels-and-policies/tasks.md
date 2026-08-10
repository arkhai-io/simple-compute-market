# Tasks

Staged as two commits, reviewed and merged as one change. Commit 1 must be
independently green: policies compose and resolve with the wheel layout
unchanged. Commit 2 removes the layout that only import-order resolution made
necessary.

## Commit 1 — Composed negotiation policy catalogue

### 1. Kit source protocol and loaders

- [x] 1.1 Add `CatalogueSource` to `market_policy` with `describe()`
  and `load() -> Mapping[str, NegotiationMiddleware]`. Implementations return
  mappings and mutate nothing. Kit references no domain, domain contract, or
  capability type.
- [x] 1.2 Add `InlineSource` for items known at build time.
- [x] 1.3 Add `EntryPointSource` for the existing
  `market_policy.negotiation_middlewares` group, loading without catching
  per-entry exceptions.
- [x] 1.4 Add `DirectorySource`, carrying the behaviour currently in
  `_discover_file_policies` and `_register_file_policy`. No domain registers
  it in this change; it remains available for a domain or external team that
  opts in.
- [x] 1.5 Add `scalar_escrow_policies()` returning kit's own set — the
  generic escrow vocabulary currently registered by decorator in
  `scalar_policies`. Kit's built-ins are one source among several, with no
  special case in the catalogue.

### 2. Catalogue and builder

- [x] 2.1 Add a builder accumulating loaders via `add_loader`, and a `build()`
  producing a frozen catalogue. Builder mutability is unconstrained; the built
  catalogue MUST be immutable.
- [x] 2.2 `build()` loads every source and raises on source failure, naming
  the source via `describe()`. A declared-but-unsuppliable policy is a broken
  install, never a skipped policy.
- [x] 2.3 `build()` validates that every offered value is callable and raises
  naming the source and the offending name and type.
- [x] 2.4 `build()` rejects a name offered by two sources, naming both
  providers. No override mechanism is provided.
- [x] 2.5 Catalogue lookup raises on an unknown name, listing what is
  available and naming no package the reader must import.
- [x] 2.6 Retain provenance per name so every error message can attribute a
  policy to the source that offered it.

### 3. Core capability

- [x] 3.1 Add `DomainCapability.NEGOTIATION`, a `NegotiationCapability`
  protocol whose hook is `policy_sources`, and its immutable dataclass,
  following the existing capability pattern. `market_core` gains no import.
- [x] 3.2 Register the required hook in `_CAPABILITY_HOOKS` so
  `validate_domain_contract` rejects a declaration missing the hook.
- [x] 3.3 Confirm the capability is optional and that absence requires no
  placeholder, per `market-composition`'s existing requirement.

### 4. Domain and role composition

- [x] 4.1 VM: expose its two guards as an inline source and declare
  `NEGOTIATION`. Its default chain becomes an ordered tuple of names
  interleaving kit and VM policies, replacing `_DEFAULT_GUARDS`.
- [x] 4.2 API-credit: same, for its four guards — the three seller-side and
  the buyer-side key responder. Verify after composition that it resolves no
  name it does not own and no name VM provides.
- [x] 4.3 Bare-metal: declare no `NEGOTIATION` capability. Record in the
  design-promotion record that this is correct, not an omission.
- [x] 4.4 Compose one catalogue per role at the composition root from kit's
  set plus each discovered domain's sources.
- [x] 4.5 Inject the catalogue into `default_seller_round_hook` and remove
  `extra_policy_paths` from its signature; source selection moves to
  composition. Both storefronts compose per hook rather than at import, so a
  catalogue is never built before configuration resolves. The escrow-kind
  dispatch middleware takes the resolver too — a required argument, not a
  default, so a per-kind chain cannot reach a name the role did not authorize.
- [x] 4.7 Remove the storefront-round file-discovery and lazy RL-registration
  helpers. Both were mechanisms triggered from inside chain resolution; they are
  now sources a role authorizes at composition. Tombstone the test file whose
  subject was the removed private helper; its coverage moved to the directory
  source and role-authorization suites.
- [x] 4.6 Make `core_buyer.plugins` domain loading fatal on load failure,
  matching `core_storefront.publication_plugins`, so a broken install fails
  instead of reporting that no domain is installed.

### 4b. Buyer-role composition

- [x] 4b.1 Compose the buyer's catalogue in `core_buyer`. The buyer role owns
  its own composition rather than sharing the storefront's: composition is where
  a role decides which mechanisms may contribute, and the buyer's answer differs.
  Kit cannot own it either, because composition reads market-domain contracts.
- [x] 4b.2 The buyer authorizes no filesystem or entry-point mechanism, so
  nothing in `buyer.toml` can cause a policy to be loaded from disk.
- [x] 4b.3 Offer the VM torch strategy to both roles and its inventory guards to
  the storefront only. A buyer resolving an inventory guard would name a policy
  about inventory it does not own; both sides of a negotiation may run the
  strategy.
- [x] 4b.4 Remove the buyer's RL registrar hook — a module-level callable a
  domain installed by import side effect, then invoked from inside chain
  resolution. The domain capability supersedes it.
- [x] 4b.5 Compose per invocation rather than caching at module scope. The buyer
  CLI is short-lived and a cached catalogue would be built before the
  configuration selecting its policies is read.

### 5. Remove the superseded mechanisms

- [x] 5.1 Remove the module-level negotiation `_REGISTRY`, the decorator itself,
  `load_negotiation_chain`, `list_negotiation_middlewares`, the entry-point cache
  write during resolution, and the stub file-discovery trigger. Remove the error
  message instructing the operator to import a domain package. Zero references
  remain in production or test code. The decorator is not retained as a
  marker: the source mappings are the declaration, and two ways to declare one
  policy is worse than either.
- [x] 5.1a Convert every test that resolved through the registry to compose its
  own catalogue: the kit strategy suite, both VM storefront suites, the VM buyer
  client suite, and the API-credit buyer negotiation flow. Delete the VM buyer
  conftest's global `rl` alias — a test that needs a policy now offers it to its
  own catalogue instead of mutating state every other test inherits.
- [x] 5.1b Pass the resolver at the two remaining escrow-kind dispatch call
  sites in tests. All five call sites across production and tests now supply it.
- [x] 5.2 Delete `_backfill_market_policy_compat_exports` and its call from
  **both** modules that carried one — the VM policies module and
  `market_policy.scalar_policies`. Each patched its `__all__` onto
  `market_policy.negotiation_middleware` at import, so that module's contents
  depended on what had been imported. No caller reads those attributes.
- [x] 5.3 Reduce the VM negotiation policies module to the two guards it
  defines. The compatibility block re-exported 36 names; nine files imported
  eleven of them through that path and now import
  `market_policy.scalar_policies` directly, which is where they live. Five
  names the module body itself uses are retained as a real import rather than a
  re-export. `__all__` drops from 15 entries to the 2 the module defines.
- [x] 5.4 Convert `market_policy.buyer_policy`'s registry to the same composed
  form: a builder validating `BuyerPolicy` rather than callability, composed by
  `core_buyer` which is its only offering package. Both modes of
  `configured_buyer_policy` are preserved — tolerant when rendering
  `market --help`, strict when loading a chain — because silently negotiating
  under a policy the user never chose is worse than failing.
- [x] 5.4a Duplicate buyer policy names now fail composition. The superseded
  registry documented last-write-wins registration, so a second offering of one
  name silently replaced the first.
- [x] 5.4b Remove the lookup failure's guess that the reader should check
  whether a domain plugin is installed. No domain offers a buyer policy; the
  message named a cause it could not know, from inside the generic layer.
- [x] 5.5 Verified: both helpers are private in their owning modules and absent
  from the `listings` facade's imports and `__all__`. Make
  `listings/strategy.determine_strategy_from_resources` and
  `listings/pricing.resource_is_compute` private and remove them from the
  `listings` facade. Each has one caller, in its own module, and was reachable
  publicly only through the facade; they are over-exported, not dead, so
  deletion would break their callers.

### 6. Commit 1 verification

- [x] 6.1 Duplicate name across two sources fails at `build()` naming both.
- [x] 6.2 A raising source fails at `build()` naming the source.
- [x] 6.3 A non-callable offered value fails at `build()` naming the value.
- [x] 6.4 An unavailable configured name fails with the available set and no
  package-import instruction.
- [x] 6.5 Buyer and storefront catalogues compose independently in one
  process.
- [x] 6.6 VM and API-credit storefront negotiation suites pass with the wheel
  layout unchanged.
- [x] 6.7 `market --help` renders under a `buyer.toml` naming an unknown
  policy; chain loading under the same config fails.

### 6a. Validation jurisdiction for this slice

Recorded so the suite is not over-credited. Every test added by commit 1 is
**unit level** under `docs/development/TESTING.md`'s definition: pure
composition and transformation, a real local filesystem boundary for the
directory source, and a mocked entry-point boundary. None uses the real
application stack or a typed client, so none is integration coverage.

- [x] 6a.1 Confirm every added test sits under a path its package's
  `testpaths` collects. Three files were initially placed at `tests/` root
  where `make test` does not reach them.
- [ ] 6a.2 Add one storefront application integration test once a role
  resolves a configured policy through the composed catalogue in a real
  request: real in-process application, real DI and configuration, the
  negotiation endpoint driven through the canonical storefront typed client.
  If that client lacks the method, extend the client rather than building the
  payload by hand.
- [ ] 6a.3 Do not add an end-to-end case to prove catalogue merging. One is
  owed only if this change alters the policy names a buyer sends into a real
  storefront negotiation, which is a cross-service compatibility question and
  belongs to system tests.

## Commit 2 — Wheel-owned domain code

### 7. Split by consumer

Consumer sets re-derived after section 5, which moved many imports to their real
owners. Of the modules remaining under `domains/vms/{listings,negotiation,settlement}`:
fifteen have no consumer outside the storefront; one, `negotiation/policy_sources`,
is reached by both roles; the rest are facades and helpers reached through them.

The buyer-reachable subset is narrow and its boundary is what determines the
split: `policy_sources` needs `negotiation/policies` directly and
`negotiation/rl/*` lazily, and `rl/arkhai_common` needs one enum from
`listings/models`. So the shared set is the negotiation tree plus the VM domain
models — which is what `arkhai_vms` already describes itself as owning — and
everything else is storefront-local.

- [x] 7.1 Move the twelve storefront-only modules into `market_storefront` as
  `listings/`, `settlement/`, and `negotiation/`, each confirmed to have no
  consumer outside the storefront at move time.
- [x] 7.2 Move the buyer's formatting helpers into `domains/vms/buyer` as
  `listing_helpers.py`. The module is presentation only — filter-parameter
  construction and the row formatting the `listing` and `buy` verbs print — so
  it belongs to the package that renders it rather than to a listings module the
  storefront also imports. Removed from the `listings` facade and from the
  buyer's wheel manifest's `../listings/` group; added under its own directory.
- [x] 7.3a Move `listings/models` into `arkhai_vms` as `listing_models`. It is
  shared VM-domain vocabulary — the listing shape, its resources, and the GPU
  enum — and depends only on stdlib, pydantic, and `market_alkahest`, so it moves
  into the distribution both roles already declare. 19 import sites rewritten;
  the `listings` facade stops re-exporting its eleven names. The buyer needs it
  because `rl/arkhai_common` reads `GPUModel`.
- [x] 7.3b Move the negotiation tree — `policies`, `policy_sources`, `rl/*`, and
  the two checkpoints — into `arkhai_vms`. It is the buyer-reachable subset, and
  it needs nothing outside `market_policy` and `arkhai_vms.listing_models`. The
  storefront keeps `storefront_round`, which reads storefront-local listing and
  settlement state; the `domains.vms.negotiation` facade narrows to that. The
  policy-source suite moves to the package that now owns it.
- [x] 7.3c Carry the `[rl]` extra, the PyTorch CPU index, and the checkpoint
  `artifacts` entry onto `arkhai_vms`. The checkpoints are data rather than
  modules, so package discovery does not find them and the extra would otherwise
  install a strategy with no weights. The buyer's own `[rl]` extra now defers to
  `arkhai-vms[rl]` instead of restating the torch pin.
- [x] 7.3d Test that the strategy module does not import torch at module scope.
  `arkhai_common` reads `GPUModel` at module scope and the strategy imports
  `arkhai_common` only inside its functions; that chain is what keeps torch out of
  a process that merely composes a catalogue, and hoisting the import fails the
  test.
- [x] 7.4 Delete `settlement/proposals`. It re-exported four names from
  `market_alkahest.proposals` and its own docstring called itself a
  compatibility shim; seven consumers across the buyer, the storefront, and the
  settlement facade now import the owner directly.
- [x] 7.5 Rewrite every affected import to the owning distribution: 49 files.
  `domains/vms/{listings,negotiation,settlement}` is tombstoned in full,
  facades included — after the split nothing re-exports across a package
  boundary, so a facade whose only purpose was to be imported from outside has
  no purpose. `grep` for `domains.vms.{listings,settlement,negotiation}` returns
  zero.

### 8. Remove the assembly mechanisms

- [x] 8.1 Reduce the buyer's manifest from 38 entries to 23. Every entry
  reaching into another project directory is gone except the two namespace
  anchors the flat `domains.vms.buyer` import path needs. The table is retained
  rather than removed because the buyer's own layout still puts its modules at
  the project root; converting it to package discovery is a layout change
  outside this section.
- [x] 8.2a Remove `_add_checkout_root_to_path()` from `market_storefront`'s
  package initializer; the storefront imports no `domains.*` module. Rationale in
  `design.md`.
- [x] 8.2 Remove `COPY domains/ ./domains/` and `ENV PYTHONPATH=/app` from the
  VM storefront Dockerfile, and drop `/app` from both storefront services'
  `PYTHONPATH` in `compose.yml`. The image no longer resolves any module from a
  source tree on the interpreter path.
- [x] 8.3 Add a repository check rejecting a Python package under `domains/`
  that no distribution owns. A directory whose only live module is its
  `__init__.py` is a namespace anchor rather than a package, and is owned when
  some project's manifest ships that file — so the check distinguishes the two
  and both branches are exercised.
- [x] 8.3b Extract the tombstone predicate into `scripts/tombstones.py`, shared by
  the manifest audit and the prune utility. Rationale in `design.md`.
- [x] 8.3c Add `scripts/tests/` and `make test-scripts` — 34 tests across the
  predicate, the manifest and ownership audits, and the prune utility. Every
  branch the earlier tasks claimed was "exercised" by a one-off run now has
  durable coverage, including the ones that must *not* fire.
- [x] 8.3d Scope the prune utility's vacancy sweep to the source roots.
- [x] 8.3a Teach `check_wheel_manifests.py` about tombstones. A file whose
  contents are a tombstone comment is a pending deletion, not a module: it must
  not be added to a manifest, and a manifest still listing it is stale. Both
  branches are exercised — the check caught a stale entry left by this section's
  own tombstones.
- [x] 8.4 Re-scoped on measurement: `domains/apicredits` does not carry the
  ownership defect. Its `pyproject.toml` sits at the domain root, so `listings`,
  `negotiation`, and `settlement` are inside its own project directory — zero
  manifest entries reach outside it, and the ownership check reports no findings.
  The VM tree was different because its wheel lived at `domains/vms/buyer` and
  reached up two levels. A consumer-split remains available inside that one owned
  distribution — `settlement` has only a storefront consumer — but that is
  tidiness within a distribution rather than the ownership violation this change
  addresses, and the domain does not yet ship. Recorded for whoever completes it.
- [x] 8.5 Confirm the repository check from 8.3 covers `domains/apicredits`: the
  ownership audit walks every `__init__.py` under `domains/` and reports no
  unowned package in either domain tree.
- [x] 8.6 Record that a manifest audit is a static check and cannot detect a
  stale installed artifact. A built wheel whose contents
  predate a source change produces the same class of failure as a drifted
  manifest — a symptom several modules from its cause. Build-and-import
  validation across every domain wheel and its advertised entry points is
  tracked separately; it needs a build step in CI and is not scoped here.

### 9. Commit 2 verification

One obsolete test was found by auditing what a static import rewrite could not
see. `domains/vms/buyer/tests/test_no_resource_pools_dependency.py` guarded a
shared listings package the buyer could reach; the rewrite pointed it at
`market_storefront.listings`, which the buyer does not depend on, so it would
have raised `ModuleNotFoundError` in a real buyer environment while passing in
one where every package is installed. The guarantee it asserted is now
structural — the buyer cannot reach that package at all — so it is tombstoned
rather than repaired.

- [x] 9.1a Build every internal wheel into one clean virtual environment with no
  repository source tree and no `PYTHONPATH`, then import every module each
  ships: `arkhai-vms-storefront` 77 modules, `arkhai-vms-buyer` 21, `arkhai-vms`
  13, zero failures. Also ran the scenario the original CI failure came from —
  buyer domain discovery returns `compute.v1` and the composed catalogue resolves
  `rl`, entirely from installed wheels. This proves the assembled set is
  consistent; it cannot prove any single wheel is self-describing.
- [x] 9.1b Add `scripts/check_wheel_closure.py` and `make check-wheel-closure`.
  Rationale in `design.md`; jurisdiction recorded in
  `docs/development/TESTING.md` under Packaging Validation.
- [x] 9.1c Declare `arkhai-kit-alkahest` and `arkhai-kit-policy` as runtime
  dependencies of `arkhai-vms`. The moved listing models read Alkahest escrow
  shapes and the moved policies are middlewares in the policy kit's vocabulary,
  both at module scope. `core_storefront` stays under the `[storefront]` extra,
  which is correct, and the closure check records that exemption with its reason.
- [x] 9.2 Assert that no shipped **implementation module** originates outside its
  owning project directory, and that the only files which may is an explicitly
  validated namespace-anchor `__init__.py`. Two remain, both required by the flat
  `domains.vms.buyer` import path; `8.3`'s check validates that each is shipped by
  some manifest and distinguishes it from an unowned package.
- [ ] 9.3 Start the VM storefront from an image built without `COPY domains/`
  and assert its configured chain resolves. The import half is covered by `9.1`
  — every module in the storefront wheel imports with no source tree present —
  so what remains unproven is the image build and container startup themselves,
  which need a Docker daemon.
- [ ] 9.4 Run the E2E buyer CLI scenario that currently fails at stage B4 and
  record the resulting failure count and skip count. A reduced skip count
  indicates tests previously skipped because the domain was unloadable.
- [ ] 9.5 Record which remaining E2E failures belong to
  `publish-multidimensional-listing-shape` rather than this change.

### 9b. Image publication defect found during verification

Pre-existing and unrelated to the ownership split, but it blocks `push-images`
and so blocks the end-to-end verification this change is meant to unblock.

- [x] 9b.1 Define `GIT_SUFFIX` in `provisioning/compute/service/Makefile` and tag
  the built image with it, as the registry and storefront Makefiles already do.
  The push target tags by commit; without the local tag it fails on a missing
  image rather than on anything wrong with the build.
- [x] 9b.2 Correct `push-images` to name the tag the build produces. The remote
  name is `provisioning` and the local tag is `compute-provisioning`; the
  `push_image` macro already takes both, and the call passed `provisioning` twice.
- [x] 9b.3 Confirm no other consumer breaks: `compose/seller.yml` and
  `domains/vms/compose.yml` reference the unsuffixed `arkhai:compute-provisioning`,
  which the build still produces. Only this one service was affected — the
  registry and storefront Makefiles both already defined `GIT_SUFFIX`.

## 10. Closeout

- [x] 10.1 Comment hygiene: run `make check-comment-hygiene`, resolve every
  match, and read the changed Python directly for references to the review or
  migration that produced it.
- [x] 10.2 Import placement: of the six modules this change adds, five have zero
  function-scope imports. The one exception, `TorchStrategySource.load`, is a
  documented lazy load — deferring the strategy module is the property the design
  depends on, and a test fails if the import is hoisted.
- [x] 10.3 Documentation compliance: re-check accepted decisions against
  `openspec/README.md`'s placement rules, including
  `docs/development/ARCHITECTURE.md` for the wheel ownership rule and
  `docs/development/TESTING.md` for the composition test conventions.
- [x] 10.4 Narrative compression: keep completed-task notes at final
  behaviour, material validation evidence, and permanent destinations; hold
  rejected alternatives in `design.md` only.
- [x] 10.5 Roadmap currency: Goal 4's registry gap row is rewritten. Two of the
  four named-item registries are now composed catalogues, so the row names what
  remains — the buyer's aggregation policies, whose lookup also writes to the
  registry it reads, and the identity verifiers — and names
  `market_policy.catalogue` as the primitive they migrate onto.
  `remove-relative-uv-sources` is unaffected: it targets parent-path
  `tool.uv.sources` entries, a different mechanism, and remains unstarted.
- [x] 10.6 Promotion: complete the design-promotion record.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| Every shipped module is owned by one distribution; no project enumerates another's files; no role obtains code by source-tree copy | `docs/development/ARCHITECTURE.md#build-packaging-and-initialization` |
| A distribution declares every dependency its shipped modules import at module scope, verified per wheel rather than in aggregate | `docs/development/ARCHITECTURE.md#build-packaging-and-initialization` |
| Neither a package initializer nor an image restores a source tree to the interpreter path | `docs/development/ARCHITECTURE.md#build-packaging-and-initialization` |
| Configurable names resolve against a catalogue composed once at startup and immutable thereafter, never process-global state populated by import order | `docs/development/ARCHITECTURE.md#package-and-dependency-layers` |
| Composition is role-owned: the role authorizes mechanisms, the domain contributes only its own items through a narrow typed request | `docs/development/ARCHITECTURE.md#package-and-dependency-layers` |
| Strict conflict with no precedence rule; load failure and malformed items fail at startup | `docs/development/ARCHITECTURE.md#package-and-dependency-layers` |
| `Wheel-owned domain code`, `Fatal domain plugin load failure`, and the optional-capability clause for negotiation | `openspec/specs/market-composition/spec.md` |
| `Composed negotiation policy catalogue` and `Domain-chosen policy discovery` | `openspec/specs/negotiation-protocol/spec.md` |
| Packaging validation is a distinct jurisdiction from the four test levels; per-wheel closure is not substitutable by an aggregate install | `docs/development/TESTING.md#packaging-validation` |
| Operator-facing policy configuration: domain-offered policies, startup conflict failure, the `middleware` file contract, and the buyer authorizing no filesystem mechanism | `docs/configuration.md` |
| Two named-item registries remain unconverted — the buyer's aggregation policies and the identity verifiers — with `market_policy.catalogue` as the primitive they migrate onto | `docs/development/ROADMAP.md` Goal 4 gap table |
| The generic catalogue primitive eventually belongs in a zero-dependency kit package, since `market_identity` and `core_buyer` cannot depend on `arkhai-kit-policy` | Deferred; recorded in `design.md` and owned by `kit-storefront-composition-seam` |
| Directory-level `force-include`, lazy facades, singleton catalogues, precedence overrides, and carrying policies on the domain contract | Rejected; retained in `design.md` only |
| The RL strategy's laziness is the strategy module and its dependency graph, not torch itself — torch is already function-scoped | Corrected mid-change; recorded in `design.md` and guarded by a test |
