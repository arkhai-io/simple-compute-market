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
- [x] 4.5a Compose each storefront's catalogue during lifespan startup and hold
  it on the container, not at the point of consumption. It was first composed per
  hook, which is per negotiation request: a broken operator policy directory, a
  duplicate source, or a malformed middleware would have failed the first
  negotiation that reached it rather than startup, and filesystem discovery could
  observe changes mid-process. Both contradicted the permanent contract that
  composition failures surface before the role serves requests.
  `container.policy_catalogue()` raises rather than composing on demand, so the
  lifecycle cannot silently regress, and
  `test_policy_catalogue_lifecycle.py` asserts the negotiation path composes
  nothing. An autouse conftest fixture populates the container for suites that
  exercise negotiation without running the lifespan — one place rather than
  every suite.
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
- [x] 9.4 Run on `ci-discovered-bug-fixes` (`c710057d`): **6 failed, 52 passed,
  42 skipped**, against a 5/53/42 baseline. Skip count unchanged, so nothing was
  skipping because the domain was unloadable — the plugin failure aborted the
  buy rather than suppressing tests.

  The packaging defect is resolved. Stage B4's failure mode changed from
  `skipping buyer domain 'vms': No module named 'domains.vms.listings.listing_mode'`
  followed by "none is installed", to `discover 1 match(es)` →
  `negotiate → bob-storefront` → `HTTP 409 no_matching_inventory`. The buyer now
  loads its domain, discovers a listing, and negotiates; it is blocked downstream.

  One new failure was this change's own defect, described in 9.4a.
- [x] 9.4b Re-run after the 9.4a fix (`633fcc63`): **5 failed, 53 passed, 42
  skipped**, against the 5/53/42 baseline. `test_credits_full_deal` passes. No
  `UnknownCatalogueEntryError`, no `ModuleNotFoundError`, no
  "skipping buyer domain", and no "none is installed" anywhere in the run.

  Same failure count as baseline, different composition: the baseline's one
  packaging failure is resolved, and the count holds because stage B4 is now
  blocked by the pre-existing filter defect it was previously unable to reach.
- [x] 9.4a `market credits buy` failed with
  `UnknownCatalogueEntryError: unknown negotiation policy: answer_key_challenge`.
  The API-credit buyer contract declared no negotiation capability, so the buyer
  role composed a catalogue without the domain's buyer-side responder. Identical
  to the defect found in the VM buyer contract earlier in this change, in the
  other domain, and flagged as outstanding at the time without being fixed.

  Fixed, and `domains/apicredits/buyer/tests/test_real_domain_composition.py`
  guards it — the counterpart of the VM suite added for the same defect. Both
  domains' published buyer contracts are now covered.

  Worth recording why component tests missed it twice: the domain offered the
  policy, the role forwarded the request, and the catalogue resolved names, each
  verified. Only the published contract's capability set was wrong, and nothing
  asserted on the real contract until a test was written against it.
- [x] 9.5 All five remaining failures are one pre-existing defect, none in this
  change's scope:

  | Scenario | Signature |
  |---|---|
  | `test_b4_market_buy_reaches_ready` | `HTTP 409 no_matching_inventory` |
  | `test_02_admin_reserve_2x_closes_oversized_listings` | `No available compute VM matched required attributes` |
  | `test_02_reserve_2x_keeps_large_slices_open` | same |
  | `test_05a_evaluate_negotiate_would_not_exit` (×2) | `has_matching_inventory_guard` returns `reject` / `no_matching_inventory` |

  Each is the registry's dimension and form-factor filters failing closed on
  missing fields, owned by `publish-multidimensional-listing-shape`. The
  negotiation-side symptom is `arkhai_vms.negotiation.policies`'
  `has_matching_inventory_guard` rejecting because the inventory query returns
  nothing — the guard is behaving correctly on an empty result.

  No `UnknownCatalogueEntryError`, no plugin load failure, and no import error
  appears anywhere in the run apart from 9.4a's.

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

`Applied` rows are already in the named document. `At archival` rows are spec
deltas that `openspec archive` synchronizes into `openspec/specs/` at workflow
step 7; writing them into the permanent specs by hand now would duplicate the
tool and leave the two copies to drift. The change is between steps 6 and 7 —
`9.3` and `6a.2` are open — so those rows are named, not yet applied.

| Accepted decision | Permanent location | State |
|---|---|---|
| Every shipped module is owned by one distribution; no project enumerates another's files; no role obtains code by source-tree copy | `docs/development/ARCHITECTURE.md#build-packaging-and-initialization` | Applied |
| A distribution declares every dependency its shipped modules import at module scope, verified per wheel rather than in aggregate | `docs/development/ARCHITECTURE.md#build-packaging-and-initialization` | Applied |
| Neither a package initializer nor an image restores a source tree to the interpreter path | `docs/development/ARCHITECTURE.md#build-packaging-and-initialization` | Applied |
| Configurable names resolve against a catalogue composed once at startup and immutable thereafter, never process-global state populated by import order | `docs/development/ARCHITECTURE.md#package-and-dependency-layers` | Applied |
| Composition is role-owned: the role authorizes mechanisms, the domain contributes only its own items through a narrow typed request | `docs/development/ARCHITECTURE.md#package-and-dependency-layers` | Applied |
| Strict conflict with no precedence rule; load failure and malformed items fail at startup | `docs/development/ARCHITECTURE.md#package-and-dependency-layers` | Applied |
| `Wheel-owned domain code`, `Fatal domain plugin load failure`, and the optional-capability clause for negotiation | `openspec/specs/market-composition/spec.md` | At archival |
| `Composed negotiation policy catalogue` and `Domain-chosen policy discovery` | `openspec/specs/negotiation-protocol/spec.md` | At archival |
| Configurable catalogues are composed during application startup and injected, so a broken source fails before the role serves traffic | `docs/development/ARCHITECTURE.md#package-and-dependency-layers` | Applied |
| Packaging validation is a distinct jurisdiction from the four test levels; per-wheel closure is not substitutable by an aggregate install | `docs/development/TESTING.md#packaging-validation` | Applied |
| Operator-facing policy configuration: domain-offered policies, startup conflict failure, the `middleware` file contract, and the buyer authorizing no filesystem mechanism | `docs/configuration.md` | Applied |
| Two named-item registries remain unconverted — the buyer's aggregation policies and the identity verifiers — with `market_policy.catalogue` as the primitive they migrate onto | `docs/development/ROADMAP.md` Goal 4 gap table | Applied |
| The generic catalogue primitive eventually belongs in a zero-dependency kit package, since `market_identity` and `core_buyer` cannot depend on `arkhai-kit-policy` | Deferred; recorded in `design.md` and owned by `kit-storefront-composition-seam` | Deferred |
| Directory-level `force-include`, lazy facades, singleton catalogues, precedence overrides, and carrying policies on the domain contract | Rejected; retained in `design.md` only | Rejected |
| The RL strategy's laziness is the strategy module and its dependency graph, not torch itself — torch is already function-scoped | Corrected mid-change; recorded in `design.md` and guarded by a test | Applied |
| A fungible pool is several executors with one capacity declaration each, never several declarations on one executor; the bucket projection's `resource_count` is what makes it fungible | Owned by `capacity-resource-administration` §4b's spec delta; encoded here only as scenario setup | At archival |
| The negotiation inventory guard reads the bucket snapshot, not either projection — recorded as a correction in `e2e-inventory-findings.md` | Change history only; the permanent contract is `openspec/specs/site-capacity/spec.md`'s existing accounting boundary | Applied |
| A test double must answer every question the service it substitutes answers, and answer it identically where the answer is a validation decision | Enforced by a parity test in `provisioning/compute/service/tests/unit/services/test_programmable_mock.py`; the general principle is already in `docs/development/TESTING.md`'s client-parity rule | Applied |

## 11. E2E capacity setup

Added 2026-08-11. Section 9's verification is blocked by scenario setup rather than by
anything this change's packaging or catalogue work owns, and `e2e-inventory-findings.md`'s
correction section records why. This is test-only: no production file changes here. The
production hardening that keeps the same mistake from recurring is planned as
`capacity-resource-administration` §4b, and the admin reserve path's 500 as
`fix-vm-fulfillment-capacity-boundary` §10 — both are prerequisites for a green run, and
neither belongs in this change.

Scope note: this section is scenario setup for a change whose acceptance boundary is
wheel-owned domain code and composed policy catalogues. It is here because the e2e run is
this change's own verification gate and the diagnosis lives in this directory, not because
capacity setup belongs to it. If it grows past the tasks below, that is the signal to split
it into its own change rather than widen this one.

### 11a. Setup model

- [x] 11a.1 Confirm by inspection before writing anything: `_find_candidate` reads
      `CapacityBucket` only; `register_resource` is the only thing that creates one; the
      resource-pool projection is host-row-shaped and the capacity-bucket projection is the
      fungible source; and a pool's `listing_mode` policy tag selects between them with a
      structural default of `specific_resource` at one member. Record any drift rather than
      working around it. **Done.** All four confirmed against the tree; no drift.
- [x] 11a.2 Give each scenario its own executor host, and stop sharing `kvm1`. Every VM
      scenario currently seeds `attribute.vm_host=kvm1`, so under one-declaration-per-executor
      they cannot coexist — and the shared host is already what let one scenario's GPU count
      break another (see this change's `host_registry.py` docstring). Host names belong to the
      scenario that registers them. **Done.** Seven scenario-owned hosts replace the shared `kvm1`.
- [x] 11a.3 Keep a declaration's own id distinct from its executor's name, correlated by the
      executor attribute. A specific-resource listing's `offer_resource.resource_id` becomes
      the claim's pinned `resource_id` via `compute_capacity_claim_from_order`, so the
      declaration must carry the commercial id the listing names, not the host alias. One
      declaration per executor is still satisfied — one declaration claims one host. **Done.** Declarations keep the commercial resource id; `vm_host` carries the correlation.
- [x] 11a.4 Declare pool membership in the `pool_id` field, never in `attributes`. The
      attribute spelling is read by nothing and is refused by
      `capacity-resource-administration` §4b.4.
 **Done.** Passed as the field everywhere; no scenario sets it as an attribute.
### 11b. Shared helpers

- [x] 11b.1 Rework `e2e-tests/tests/e2e/roles/scenarios/vms/host_registry.py`: add a pool
      helper over `create_pool`/`get_pool` carrying the scenario's `listing_mode` policy tag,
      make the host helper take a name and `pool_id` (both already on `HostCreate`/`HostUpdate`),
      and rename the capacity helper to say it declares sellable capacity rather than
      registering a resource. `SiteCapacityAdminClient.register_resource` already accepts
      `pool_id`; nothing new is needed on any client. **Done.** `register_e2e_pool`, `register_e2e_host(name, pool_id)`, `declare_e2e_capacity`, and `provision_e2e_executor` composing the three in dependency order. No client change was needed.
- [x] 11b.2 Rewrite that module's header docstring. It states the site authority projects
      capacity by iterating host rows and that an unregistered host yields an empty
      projection — true of the resource-pool projection and irrelevant to the buckets every
      claim actually matches against, which is the misreading that cost a debugging loop. **Done.** Rewritten to lead with the three-store distinction and why the host-derived projection is not what claims match.
- [x] 11b.3 Keep `refresh_storefront_projections` as it is. Its refusal to treat
      `unavailable`/`invalid` as an authoritative empty is what surfaced the poisoned
      projection at its cause instead of three layers downstream.
 **Done.** Unchanged.
### 11c. Per-scenario setup

- [x] 11c.1 `test_compute_dynamic_listings.py`, fungible class: one pool tagged
      `listing_mode: fungible`, two executor hosts of four GPUs each, one declaration per
      host with `pool_id` set on the field. Confirm the existing 2× and 4× assertions still
      hold and why: slices are generated to `max_member_available_gpu_count`, not to the pool
      sum, so a 2× reserve on the first host leaves the ceiling at four, and a 4× reserve then
      lands on the second and drops it to two, closing 3× and 4×. Today those assertions pass
      only because two declarations on one host double-count that host's GPUs. **Done.** Two executors, one declaration each, `listing_mode: fungible`. The existing 2×/4× assertions hold for the right reason now — previously they passed only because two declarations double-counted one host's GPUs.
- [x] 11c.2 `test_compute_dynamic_listings.py`, dynamic class: its own executor host and one
      declaration, single-member pool, so the structural default resolves to
      `specific_resource`. **Done.** Own host, single-member pool, `specific_resource`.
- [x] 11c.3 `test_full_deal.py`, `test_full_deal_buyer_cli.py`, `test_buy_oneshot_buyer_cli.py`,
      `test_multi_registry.py`, `test_non_erc20_settlement.py`: each declares capacity for its
      own host in its existing executor-host stage, carrying the `region` and `gpu_model` its
      listing advertises. Those two are what `has_matching_inventory_guard` compares by
      equality, so a declaration missing either reproduces the failure the stage exists to
      prevent. **Done.** All five, each with its own host and a declaration carrying its listing's `region` and `gpu_model`. `test_multi_registry` needed two — Alice's negotiation asserts `counter`, so her resource needs a declaration in her own region. `test_non_erc20_settlement`'s `kvm{index}` was always `kvm1`, since each parametrized run passes one case; it now derives a host from `case.name`.
- [x] 11c.4 Correct the stage-05a assertion message in `test_full_deal.py` and
      `test_full_deal_buyer_cli.py`. It attributes any non-`counter` decision to
      `BUYER_INITIAL_PRICE` being above the seller floor; the observed decision was `reject`
      from an inventory guard that never evaluated price, and the message sent a debugging
      loop after a pricing problem that did not exist. Distinguish `reject` from `accept`. **Done.** Run 31478292008 confirms the value: the message reported `reject` and pointed at the declaration rather than at `BUYER_INITIAL_PRICE`.
- [x] 11c.5 Confirm mock-mode provisioning tolerates hosts other than `kvm1` — the compose
      profile runs `PROVISIONING_MODE=mock` and hosts are registered through the API, so this
      is expected to be free, but it is an assumption worth one deliberate check rather than
      a surprise mid-run.
 **Done.** Confirmed by run 31478292008 — all seven scenario hosts registered and provisioned under the mock profile.
### 11c-bis. Pool creation requires provider configuration (found in run 31476576548)

The first run of Section 11 failed earlier than any of its own assertions: every
`POST /api/v1/pools/` returned 400 `provider_config.playbook_path is required for
provider='ansible'`, so no pool, host, or declaration was created and all eleven
failures were one cascade. Two facts settle the fix.

- [x] 11c-bis.1 A scenario has no profile-independent `playbook_path` to supply.
      The correct value is `/dev/null` under the mock profile and a container path
      under docker and Helm. Read the system `default` pool's `provider_config`
      instead and pass it through: the migration seeds that pool from the service's
      own active settings, making it the one place a scenario can read a valid value
      for whatever profile the stack is running under. Assert loudly when it carries
      no `playbook_path` rather than substituting a guess. **Done.** Reads the `default` pool's `provider_config` and passes it through, asserting loudly when it carries no `playbook_path`.
- [x] 11c-bis.2 Reconcile an existing pool's `listing_mode` rather than accepting
      it, matching the host helper. A pool surviving an earlier run may carry a
      different mode, and the mode decides how the scenario's listings publish. **Done.** `patch_pool` reconciles a surviving pool's `listing_mode`.
- [x] 11c-bis.3 Pin the contract the helper now depends on where the pool API owns
      it: the default pool exposes a usable `playbook_path`, and a pool created by
      copying its provider configuration is accepted. Added to
      `provisioning/compute/service/tests/integration/test_pools_api.py`. **Done.** Two tests in `test_pools_api.py`.
- [x] 11c-bis.4 Fix the fidelity gap those tests exposed in
      `provisioning/compute/service/tests/integration/conftest.py`: `db_engine`
      seeded the default `ResourcePool` row but not its `AnsiblePoolConfig`, while
      its own comment claimed to mirror the migration's guarantee. A caller reading
      the default pool's `provider_config` saw an empty mapping under test and a
      populated one in every deployment — exactly the divergence class that let the
      reserve-response defect ship.
 **Done.** `db_engine` now seeds the default pool's `AnsiblePoolConfig` as the migration does. Both 11c-bis.3 tests failed until it did — the fixture was a half-mirror of its own stated guarantee.
### 11d. Verification

- [x] 11d.1 Run `make -C e2e-tests test-e2e` — the target the workflow runs, not a
      scenario-by-scenario path, since naming a path overrides the configured `testpaths`. **Done.** Run via the workflow's own `make -C e2e-tests test-e2e`.
- [x] 11d.2 Expect the nine failures to resolve as: five projection-stage failures and the
      fungible 409 from this section; both `05a` and `b4` from this section's declarations;
      `test_02_admin_reserve_2x` only once `fix-vm-fulfillment-capacity-boundary` §10 lands.
      If any scenario fails for a different reason, stop and record it before adjusting setup —
      the last loop's cost came from fixing a symptom whose cause was elsewhere. **Partly done, two runs.** Run 31476576548: all eleven failures were one cascade from my own defect — `PoolCreate` with `provider="ansible"` requires `provider_config.playbook_path` and I supplied none, so no pool, host, or declaration was created. Fixed as 11c-bis. Run 31478292008: `1 failed, 66 passed, 39 skipped`. Every setup stage, both `05a`s, and `test_02_admin_reserve_2x` are green; zero 500s, zero `several capacity resources`, zero `KeyError`, zero `'resource_pool': 'invalid'` in the compose logs. The one remaining failure is `b4`, which now negotiates, escrows, and settles and fails at `begin_fulfillment` — a pre-existing defect this section's work exposed by reaching that call for the first time, tracked as section 12.
- [x] 11d.3 Disclose which suites ran and which did not. A local docker-compose run has been
      unavailable since 2026-07-29 (see `refactor-e2e-fulfillment-lifecycle`), so this
      section's verification may be a CI run rather than a local one, and saying so is part of
      the result.
 **Done.** Disclosed per fileset: no docker-compose run is available in the implementation session, so scenario collection plus the affected unit/integration suites were run locally and the e2e evidence comes from CI runs 31476576548 and 31478292008.
### 11e. Section 11 closeout

Per `openspec/README.md#plan-closeout-requirements`, scoped to this section. Section 10's
closeout is complete and stays as it is.

- [x] 11e.1 **Comment hygiene.** Run `make check-comment-hygiene`. These are test files, so
      the mechanical target is unlikely to fire; read 11b.2's rewritten docstring and each
      scenario's stage docstring directly, since several currently explain the setup in terms
      of the projection rather than the buckets their claims match. **Done.** `make check-comment-hygiene` clean; the rewritten helper docstring and each stage docstring read directly.
- [x] 11e.2 **Import placement.** Confirm no function-level import is added by the helper
      rework, and record the disposition. **Done.** No function-level import added.
- [x] 11e.3 **Documentation compliance.** This section adds no permanent documentation: the
      setup model it encodes is `site-capacity`'s existing accounting boundary, and the two
      new normative requirements belong to `capacity-resource-administration` §4b's spec
      delta. Confirm that remains true rather than assuming it. **Done.** No permanent documentation owed by this section; the two normative requirements remain `capacity-resource-administration` §4b's spec delta.
- [x] 11e.4 **Narrative compression.** Compress these notes to final scenario shape and the
      run evidence once green; the diagnosis stays in `e2e-inventory-findings.md`. **Done.** Notes held at final scenario shape and run evidence; the diagnosis stays in `e2e-inventory-findings.md`.
- [x] 11e.5 **Roadmap currency.** No roadmap goal changes: this is scenario setup, and the
      production gaps it exposed are already owned by rows under Goal 1 and Goal 2. Recorded
      explicitly as a deliberate finding rather than an omitted step. **Done.** No roadmap change: scenario setup, and the production gaps it exposed are already owned by rows under Goal 1 and Goal 2.
- [x] 11e.6 **Promotion.** Add this section's rows to the design-promotion record.
 **Done.** Rows added to the design-promotion record.
## 12. Mock Ansible service diverged from the service it stands in for

Found by run 31478292008, the first run to reach `begin_fulfillment` at all. Pre-existing
and independent of this change's subject; recorded here because Section 11's work is what
exposed it and because leaving it would keep `b4` red.

`AnsibleFulfillmentProvider.prepare_create` validates pool `extra_vars` against
`AnsibleJobService.reserved_var_keys`, which passes through to the Ansible service.
`MockAnsibleService` does not implement it, so under the mock profile the call raised
`AttributeError`, surfaced as a 500 on `POST /api/v1/fulfillment/begin`, and reached the
buyer as `Provisioning failed: Internal Server Error` — four layers from its cause.

- [x] 12.1 Implement `reserved_var_keys` on `MockAnsibleService` by borrowing the real
      implementation rather than reproducing it. The answer is a validation decision, not
      I/O: a mock computing its own set would accept pool configuration production refuses.
      The file already establishes this pattern — `parse_playbook_result` delegates to a
      real instance for exactly the same reason. **Done.**
- [x] 12.2 Add an interface-parity test asserting the mock implements every public method of
      the real service. `MockAnsibleService`'s own docstring promises this and nothing
      checked it, which is why `reserved_var_keys` could be added to one side alone.
      **Done.** It failed immediately on a second, latent divergence — `lookup_public_host`,
      absent from the mock and reachable today only because `parse_playbook_result` routes
      through a real instance. Borrowed the same way.
- [x] 12.3 Assert the two services return the *same* reserved set for the same params, not
      merely that the method exists, plus a concrete floor so parity cannot be satisfied by
      two empty sets. **Done.**
- [x] 12.4 Note why the existing provider unit test could not catch this:
      `test_ansible_fulfillment_provider.py`'s `job_service` fixture injects the real
      `AnsibleService.reserved_var_keys` onto a `MagicMock`, so it exercises the real
      implementation on both sides and never the mock. Left as it is — it tests the
      provider's collision logic correctly; the gap was the absent parity check, now
      12.2. **Done.**

### 13. Declared units must match the scenario's own resource (found in run 31479739305)

`b4` is green: the mock's `reserved_var_keys` fix landed and the buy scenario negotiates,
escrows, settles, and provisions. Two failures remain, and only one is mine.

- [x] 13.1 Declare each scenario's own sellable units instead of defaulting to the host's
      GPU count. Six of the nine seeded resources declare one unit and three declare four;
      the helper declared four for all of them, so `b5`'s 1x listing stayed open after its
      1x reserve — three units remained available. `sellable_units` is now a required
      argument with no default, because it is a value only the scenario knows, and
      `host_gpu_count` stays separate: a host says what hardware exists, a declaration says
      how much is for sale. **Done.**
- [x] 13.2 **Attributed by run 31482372498 — see 15.4.** Neither reading was right: it is not the inline release path racing the subscriber but a reopen acting on an availability view older than the reservation it contradicts. Filed as `monotonic-listing-reconciliation`.
- [x] 13.2a Original note, kept for the reasoning it records:
      `test_04_capacity_release_reopens_oversized_listings` asserts the release response
      reports the listings it reopened and received an empty list. The compose log shows why
      the list was empty: 24ms earlier, at 09:57:09.672, the capacity-delta subscriber
      reopened those exact two listings in response to a delta on `compute-e2e-buy-001` —
      a different resource, while two of the dynamic resource's four units were still held
      and its 3x/4x listings were therefore not servable. Two readings fit, and the logs do
      not separate them: either reopen decisions are not being recomputed per resource
      against current availability, or this is the release-path twin of a race the reserve
      path already handles (`reserve_capacity` unions `closed_listing_ids` with
      `_closed_since_snapshot`, commented "the capacity-delta subscriber can race this
      inline reconciliation"; the release path has no equivalent union). 13.1 changes the
      shape of that delta — the buy resource now declares one unit rather than four — so the
      next run distinguishes them. Do not fix either reading before it does: three loops in
      this campaign were spent fixing a symptom whose cause was elsewhere.

### 14. Lease assertions and a dead stage gate (found in run 31481250887)

`test_04` passes — 13.1's change to the delta's shape was enough, so neither reading of
that race needed a product fix. `b5` fails one line further on, and chasing it found a
second, larger problem in the same file.

- [x] 14.1 Assert the field the reservation contract actually carries. `DealLease.refresh`
      read `row.get("resource_id")` from a reservation payload that has never had that key:
      the initial capacity accounting is private to the site authority, and the physical
      resource a deal lands on is the scheduler's choice, recorded as
      `settlement_resource_id`. Every call returned `None`; the assertion had never run
      before because `b4` failed in every previous run. Surfaced `settlement_resource_id`
      instead, and updated the three assertion sites plus the `reserved_resource_id`
      capture that feeds a later claim. **Done.**
- [x] 14.2 Also assert the lease's executor identity in `b5`. `vm_host` is carried and is
      the observable binding; asserting both distinguishes "bound to the wrong machine"
      from "bound to the right machine under a different resource identity". **Done.**
- [x] 14.3 Word the `settlement_resource_id` mismatch message as a product finding rather
      than a test problem. Scheduling considers every enabled resource at the site and
      re-applies no attribute from the admitted claim, so a mismatch means a deal was placed
      outside the region or hardware it was negotiated for — which is
      `revalidate-deal-requirements-at-scheduling`'s subject, not this scenario's.
      **Done.**
- [x] 14.4 Set `_evaluate_negotiate_passed` at the end of stage 05a in both full-deal
      scenarios. Every stage from 05b onward requires it and nothing ever set it, so the
      entire tail of both scenarios — negotiation, escrow, settlement, provisioning, lease
      registration, teardown — has been skipping, and a skip reports as a pass at the suite
      level. This is why 38 of 106 tests skip and why `09c`, the stage that would have
      caught 14.1 years earlier, has never executed. **Done.**

**Expect the next run to report more failures, not fewer.** 14.4 unblocks roughly two dozen
stages that have never executed in this campaign, several of which assert on paths no run
has exercised. That is the fix working: a scenario that skips its own subject is worth less
than one that fails it. Read the new failures as first-execution findings rather than
regressions, and attribute each before changing anything.

### 15. First-execution findings from the unblocked stages (run 31482372498)

14.4 did what it was meant to: 74 pass where 67 did, skips fell 38 to 28, and the newly
executing stages found three defects plus one already-filed race. None is a regression.

- [x] 15.1 `settlement_resource_id` was null after a scheduling decision that happened.
      `PhysicalSettlementScheduler` called `rebind_capacity` only when the selected
      resource differed from the reservation's existing debit, so the ordinary
      single-candidate case recorded nothing — while `schedule_assignment` durably
      recorded the same fact, leaving the reservation and the settlement record
      disagreeing. The ledger's assignment is already idempotent and takes a cheap path
      on equality (records the marker, moves no debit, emits no event), so the call is
      now unconditional. Two `kit/fulfillment` tests cover both branches and fail
      against the previous code. **Done.**
- [x] 15.2 `SettleStatusResponse` in `storefront-client` declared `fulfillment_uid` and
      omitted `fulfillment_id`, while the server returns both and documents
      `fulfillment_id` as the field a caller should prefer. Stage 08b asked for it and
      got an `AttributeError`; the value had been landing in `extra` all along. Added,
      with a docstring stating that the two identities are not interchangeable.
      **Done.**
- [x] 15.3 `b5`'s lease assertion now passes through 15.1. **Done.**
- [x] 15.4 The dynamic-listing reopen race is reproduced with timings and filed as
      `monotonic-listing-reconciliation`: a reconciliation for capacity version 5
      reopened listings a version-7 reservation had just closed, and a later pass closed
      them again 300ms later. This is the same behaviour 13.2 left open, now with enough
      evidence to attribute — it is not a race in the inline release path but a
      non-monotonic reopen. The scenario polls for the converged state rather than
      sampling once, with the defect named at the assertion; the reserve response's own
      `closed_listing_ids` stays strictly asserted, so the synchronous contract is
      unchanged. **Done.**

### 16. Operator convergence control was never wired (run 31483777656)

79 pass, 24 skip. The two `09a` failures are the first execution of a stage that drives
provisioning to completion, and they found a control that has never worked.

- [x] 16.1 Pass the fulfillment convergence watchdog into `SystemService`. The endpoint,
      the service method, and the watchdog all existed; `_system_service` never passed it,
      so `force_fulfillment_convergence` returned "not initialised" and the operator
      one-cycle control 503'd in every deployment. `ARCHITECTURE.md`'s "Operator lifecycle
      controls" describes this control as available and requires that a manual cycle invoke
      the same production handler — it could not, because it had no handler. **Done.**
- [x] 16.2 Pass it in the provisioning integration fixture too, which built `SystemService`
      directly and omitted it. The fixture looked wired and was not — the fourth instance
      this campaign of a test double diverging from production composition. **Done.**
- [x] 16.3 Integration coverage that one cycle returns a summary rather than an
      initialisation error, and that the summary's shape is stable across repeated cycles.
      Both fail against the previous wiring. **Done.**
- [x] 16.4 A unit test on `_system_service` itself asserting the watchdog reaches the
      runtime factory. A provider that drops an argument fails nowhere at import time; it
      fails at the one call site that needs it, which here was reachable only from an
      end-to-end stage. **Done.**
- [x] 16.5 Poll for convergence at every derived-listing status assertion in the
      dynamic-listing scenario, not only the one that failed first. The fungible pool shows
      the same reopen flap, triggered by a *registration* delta — `register_resource` emits
      a `released`-kind event for a new resource — and one of its reserves reported closing
      listings that a read immediately after observed open. Both observations are recorded
      in `monotonic-listing-reconciliation`, including that the write ordering between the
      subscriber and an inline close is not settled by their log order. **Done.**

### 17. The convergence-polling stopgap is withdrawn

- [x] 17.1 Remove `_await_listing_statuses` and restore single-sample status assertions
      in the dynamic-listing scenario. It polled on a sleep, which
      `docs/development/TESTING.md`'s async discipline forbids, and it was introduced in
      this change rather than designed — the repository's answer to a timer-driven loop is
      an operator control that halts and steps it, not a tolerance in the assertion. The
      four assertions now fail honestly against a known defect instead of passing by
      waiting. **Done.**
- [x] 17.2 State both causes at the assertion: the reopen itself
      (`monotonic-listing-reconciliation`) and the racing that makes observing it
      non-deterministic (`storefront-lifecycle-pause-and-advance`). A reader who finds this
      red should not have to rediscover which is which. **Done.**

### 18. A project that ships its own modules must reinstall itself

Three runs in this campaign were misread because a venv held a wheel older than the
source it shadowed. Folded in here rather than made its own change: it is a Makefile
defect in the same wheel-ownership area this change already owns.

The mechanism: a `force-include` wheel installs its modules into its own virtual
environment, its tests import them from there, and `uv sync` will not replace a wheel
whose version has not changed. A source edit is invisible until something forces a
reinstall, so the suite runs against whatever was installed first. The failure is
plausible rather than obviously wrong — a missing capability and an unexpected keyword
both look exactly like defects in the change under review.

- [x] 18.1 Add the project's own distribution to `reinit` in `domains/apicredits`,
      `domains/apicredits/buyer`, and `domains/vms/buyer` — the three whose wheels
      force-include modules the source tree also carries. The other twelve projects that
      omit themselves use a `src` layout, where installed and source resolve to one
      import path and staleness is benign, so they are deliberately left alone. **Done.**
- [x] 18.2 Add `scripts/tests/test_reinit_self_reinstall.py`, discovering force-include
      projects from `pyproject.toml` rather than a hardcoded list, and failing if the
      discovery matches nothing so the check cannot pass by finding no projects.
      **Done.**
- [x] 18.3 Verify the reported failure was this and not a defect: `make test` in
      `domains/apicredits/buyer` reported the domain contract declaring no negotiation
      capability and `answer_key_challenge` unresolvable, while the source declares both.
      Through its own target with the fix applied: 20 passed. **Done.**
- [ ] 18.4 Run `make test` for `domains/apicredits` and `domains/vms/buyer` against
      rebuilt venvs and record whether either surfaces a defect its suite had been
      shadowing. Not run in this session.
- [x] 18.5 Tombstone `openspec/changes/reinstall-self-owned-wheels/`, which briefly
      existed as a separate change. **Done.**

### 19. Lease-expiry back-date must land inside the watchdog grace (run 31539745808)

- [x] 19.1 Bound the back-date on both sides. `E2E_LEASE_EXPIRY_BACKDATE` is one minute:
      enough for the watchdog to treat the lease as expired, not enough to elapse the 300s
      grace, because `_process_releasing_reservation` marks `release_failed` the moment
      grace passes with `vm_remove` unfinished — and 11a/11b hold `vm_remove` at a mock
      gate on purpose. Two hours put the lease past grace before the release began, so one
      cycle both dispatched and timed out the removal. The constant states both bounds.
      **Done.**
- [x] 19.2 Give the buyer-CLI scenario its own resource id. Both full-deal scenarios
      declared `compute-e2e-deal-001`, so the failed release above starved the second
      scenario's inventory guard and its round-0 evaluation vetoed — a failure that looks
      like a negotiation defect and is not. Same lesson as the shared `kvm1` executor, in a
      different field. **Done.**

### 20. A fleet-wide release fixture now races the lifecycle it substituted for

Found by run 31578351290. Recorded rather than fixed: the remedy is a scoping decision
about a fixture three scenarios depend on, and the evidence supports more than one answer.

`release_reserved_resources` (module-scoped, autouse) calls
`POST /api/v1/admin/portfolio/release-reservations`, releasing **every** held reservation
on the storefront. Its docstring justifies itself by the mock flow never expiring leases.
Section 4c made that false: 10a expires the lease and 10b drives the watchdog through it.

- [x] 20.1 Decide the fixture's future. Three options, and the choice needs the
      scenarios' owner: scope it to reservations the module created (needs a handle it does
      not currently keep); drop it for the full-deal scenarios that now drive expiry and
      keep it for those that do not; or remove it entirely and give any scenario still
      relying on it an explicit expiry stage. The last is most consistent with
      pause-verify-advance, and is also the largest change. **Done — removed entirely**, per the repository owner. The fixture's premise had two halves and both were false: leases now expire on the production path (4c), and every scenario declares its own resource (11c/19.2), so leftover capacity in one cannot starve another. A scenario needing its capacity released asks in a named stage. Confirmed no other reference: `admin_release_reservations` had exactly one caller.
- [x] 20.2 Whichever is chosen, the fixture must not be able to release a reservation
      belonging to another module. Fleet-wide plus autouse is what turned a teardown into a
      cross-scenario failure, and the same shape as the shared `kvm1` executor and the
      shared `compute-e2e-deal-001` resource id before it. **Satisfied by removal.** Nothing in the suite can now release a reservation it did not create. The rationale is recorded where the fixture used to be, including that a sweep for long-lived stacks belongs in that stack's reset rather than in a teardown that reaches across scenarios.
- [x] 20.3 Re-check `09c`'s premise afterwards. It asserts a reservation carrying a
      `lease_end_utc` exists; if a scenario's own teardown may legitimately have released
      it by then, the stage is asserting on a window rather than on a fact.
 **Done, as a diagnostic rather than a relaxation.** `09c`'s premise is sound again now that nothing races it, so the assertion stands. Its message now prints the reservations it actually saw and names the two causes apart: an empty list means none was registered, while entries lacking `lease_end_utc` mean one was and its lease tail was cleared since — a different problem the previous message would have reported identically.
### 21. Lease-view field name, and a stage that asserted before its own advance

- [x] 21.1 Read the release job id from `vm_remove_job_id`, the name `LeaseResponse`
      actually exposes, falling back to the reservation row's `release_job_id`. The ledger
      writes both columns but only the vm-flavoured one is on the lease contract, so
      `DealLease.refresh` returned `None` for `fulfillment_id` on every healthy release —
      the fourth field in this campaign read under a name the contract does not use.
      **Done.**
- [x] 21.2 Run the lease cycle before asserting the fulfillment is torn down. Releasing
      the `vm_remove` gate only makes its job succeed; a lease cycle is what polls it and
      finishes the release, and convergence cannot record `torn_down` until it has. The
      stage observed `tearing_down` — the right state, one step early. It passed under the
      old interrupt trigger because teardown had already begun before the stage ran, so the
      stage was relying on an ordering it never stated. **Superseded by 21.3** — the
      reorder was itself one step short in the other direction.
- [x] 21.3 Drive all three advances in 11b and assert only afterwards. `drain` waits on the
      Ansible queue where `vm_remove` runs; the release job the lease cycle polls is a
      fulfillment aggregate, not a queue job. So convergence must notice the Ansible job
      finished, the lease cycle must then observe the release fulfillment succeed and return
      the units, and a second convergence records `torn_down`. Both two-call orderings were
      observed failing one step short, and in both the product was correct a step later.
      **Done.**

### Section 12 closeout

- [x] 12.5 **Comment hygiene.** `make check-comment-hygiene` clean; the borrowed-method
      docstrings state why borrowing is correct rather than convenient. **Done.**
- [x] 12.6 **Import placement.** The added `AnsibleService` import is module level, beside
      the three names the file already imported from that module. **Done.**
- [x] 12.7 **Documentation compliance.** No permanent documentation owed: a test double
      matching the interface it substitutes is a testing convention, and
      `docs/development/TESTING.md`'s sync/async client-parity rule already states the
      general principle this applies to a different pair. **Done.**
- [x] 12.8 **Narrative compression.** Held at final behaviour and evidence. **Done.**
- [x] 12.9 **Roadmap currency.** No roadmap impact — a mock completeness defect changes no
      goal's current state. Recorded explicitly rather than omitted. **Done.**
- [x] 12.10 **Promotion.** Row added to the design-promotion record below. **Done.**
