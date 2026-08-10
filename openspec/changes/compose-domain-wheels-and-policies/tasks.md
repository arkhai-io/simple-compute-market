# Tasks

Staged as two commits, reviewed and merged as one change. Commit 1 must be
independently green: policies compose and resolve with the wheel layout
unchanged. Commit 2 removes the layout that only import-order resolution made
necessary.

## Commit 1 — Composed negotiation policy catalogue

### 1. Kit source protocol and loaders

- [ ] 1.1 Add `NegotiationPolicySource` to `market_policy` with `describe()`
  and `load() -> Mapping[str, NegotiationMiddleware]`. Implementations return
  mappings and mutate nothing. Kit references no domain, domain contract, or
  capability type.
- [ ] 1.2 Add `InlinePolicySource` for policies known at build time.
- [ ] 1.3 Add `EntryPointPolicySource` for the existing
  `market_policy.negotiation_middlewares` group, loading without catching
  per-entry exceptions.
- [ ] 1.4 Add `DirectoryPolicySource`, carrying the behaviour currently in
  `_discover_file_policies` and `_register_file_policy`. No domain registers
  it in this change; it remains available for a domain or external team that
  opts in.
- [ ] 1.5 Add `scalar_escrow_policies()` returning kit's own set — the
  generic escrow vocabulary currently registered by decorator in
  `scalar_policies`. Kit's built-ins are one source among several, with no
  special case in the catalogue.

### 2. Catalogue and builder

- [ ] 2.1 Add a builder accumulating loaders via `add_loader`, and a `build()`
  producing a frozen catalogue. Builder mutability is unconstrained; the built
  catalogue MUST be immutable.
- [ ] 2.2 `build()` loads every source and raises on source failure, naming
  the source via `describe()`. A declared-but-unsuppliable policy is a broken
  install, never a skipped policy.
- [ ] 2.3 `build()` validates that every offered value is callable and raises
  naming the source and the offending name and type.
- [ ] 2.4 `build()` rejects a name offered by two sources, naming both
  providers. No override mechanism is provided.
- [ ] 2.5 Catalogue lookup raises on an unknown name, listing what is
  available and naming no package the reader must import.
- [ ] 2.6 Retain provenance per name so every error message can attribute a
  policy to the source that offered it.

### 3. Core capability

- [ ] 3.1 Add `DomainCapability.NEGOTIATION`, a `NegotiationCapability`
  protocol whose hook is `policy_sources`, and its immutable dataclass,
  following the existing capability pattern. `market_core` gains no import.
- [ ] 3.2 Register the required hook in `_CAPABILITY_HOOKS` so
  `validate_domain_contract` rejects a declaration missing the hook.
- [ ] 3.3 Confirm the capability is optional and that absence requires no
  placeholder, per `market-composition`'s existing requirement.

### 4. Domain and role composition

- [ ] 4.1 VM: expose its two guards as an inline source and declare
  `NEGOTIATION`. Its default chain becomes an ordered tuple of names
  interleaving kit and VM policies, replacing `_DEFAULT_GUARDS`.
- [ ] 4.2 API-credit: same, for its four guards — the three seller-side and
  the buyer-side key responder. Verify after composition that it resolves no
  name it does not own and no name VM provides.
- [ ] 4.3 Bare-metal: declare no `NEGOTIATION` capability. Record in the
  design-promotion record that this is correct, not an omission.
- [ ] 4.4 Compose one catalogue per role at the composition root from kit's
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
- [ ] 4.6 Make `core_buyer.plugins` domain loading fatal on load failure,
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
  to any of them remain in the repository. The decorator is not retained as a
  marker: the source mappings are the declaration, and two ways to declare one
  policy is worse than either.
- [x] 5.1a Convert every test that resolved through the registry to compose its
  own catalogue: the kit strategy suite, both VM storefront suites, the VM buyer
  client suite, and the API-credit buyer negotiation flow. Delete the VM buyer
  conftest's global `rl` alias — a test that needs a policy now offers it to its
  own catalogue instead of mutating state every other test inherits.
- [x] 5.1b Pass the resolver at the two remaining escrow-kind dispatch call
  sites in tests. All five call sites across production and tests now supply it.
- [ ] 5.2 Delete `_backfill_market_policy_compat_exports` and its call. No
  caller reads the attributes it sets on `market_policy.negotiation_middleware`.
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
- [ ] 5.5 Make `listings/strategy.determine_strategy_from_resources` and
  `listings/pricing.resource_is_compute` private and remove them from the
  `listings` facade. Each has one caller, in its own module, and was reachable
  publicly only through the facade; they are over-exported, not dead, so
  deletion would break their callers.

### 6. Commit 1 verification

- [ ] 6.1 Duplicate name across two sources fails at `build()` naming both.
- [ ] 6.2 A raising source fails at `build()` naming the source.
- [ ] 6.3 A non-callable offered value fails at `build()` naming the value.
- [ ] 6.4 An unavailable configured name fails with the available set and no
  package-import instruction.
- [ ] 6.5 Buyer and storefront catalogues compose independently in one
  process.
- [ ] 6.6 VM and API-credit storefront negotiation suites pass with the wheel
  layout unchanged.
- [ ] 6.7 `market --help` renders under a `buyer.toml` naming an unknown
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

- [ ] 7.1 Move storefront-only modules from
  `domains/vms/{listings,negotiation,settlement}` into `market_storefront`,
  confirming each has no other production consumer at move time.
- [ ] 7.2 Move the buyer's formatting helpers — the six symbols it imports
  from `listings/buyer_cli` — into `domains/vms/buyer`.
- [ ] 7.3 Move genuinely shared modules, `listings/models` and its transitive
  needs, into `arkhai_vms`. Move the RL strategy and its model checkpoints
  with the `[rl]` extra and the PyTorch CPU index intact.
- [ ] 7.4 Inline or relocate `settlement/proposals`, a pass-through
  re-exporting from `market_alkahest`.
- [ ] 7.5 Rewrite every affected import to the owning distribution. Remove the
  eager cross-package facades; nothing re-exports across a package boundary
  after the split.

### 8. Remove the assembly mechanisms

- [ ] 8.1 Remove `[tool.hatch.build.targets.wheel.force-include]` from
  `domains/vms/buyer/pyproject.toml`.
- [ ] 8.2 Remove `COPY domains/ ./domains/` from the VM storefront Dockerfile
  and the reliance on `PYTHONPATH=/app` for domain resolution. Update
  `compose.yml` where it assumes the copied tree.
- [ ] 8.3 Add a repository check rejecting a Python package under `domains/`
  that no `pyproject.toml` owns, so an unowned namespace cannot reappear.
- [ ] 8.4 Bring `domains/apicredits` to the same ownership rule: split
  `listings`, `negotiation`, and `settlement` by consumer, remove the
  `force-include` table from `domains/apicredits/pyproject.toml`, and remove
  any reliance on an interpreter path for domain resolution. Its manifest
  audited complete at proposal time; a complete hand-maintained manifest is
  what `vms/buyer` had before the POOLS work.
- [ ] 8.5 Confirm the repository check from 8.3 covers `domains/apicredits`
  and that no package under either domain tree is unowned.
- [ ] 8.6 Record, rather than fix here, that a manifest audit is a static check
  and cannot detect a stale installed artifact. A built wheel whose contents
  predate a source change produces the same class of failure as a drifted
  manifest — a symptom several modules from its cause. Build-and-import
  validation across every domain wheel and its advertised entry points is
  tracked separately; it needs a build step in CI and is not scoped here.

### 9. Commit 2 verification

- [ ] 9.1 Build `arkhai-vms-buyer` and assert every `domains`/`arkhai_vms`
  import in its shipped code resolves inside the wheel.
- [ ] 9.2 Assert no shipped file originates outside its own project directory.
- [ ] 9.3 Start the VM storefront from an image built without `COPY domains/`
  and assert its configured chain resolves.
- [ ] 9.4 Run the E2E buyer CLI scenario that currently fails at stage B4 and
  record the resulting failure count and skip count. A reduced skip count
  indicates tests previously skipped because the domain was unloadable.
- [ ] 9.5 Record which remaining E2E failures belong to
  `publish-multidimensional-listing-shape` rather than this change.

## 10. Closeout

- [ ] 10.1 Comment hygiene: run `make check-comment-hygiene`, resolve every
  match, and read the changed Python directly for references to the review or
  migration that produced it.
- [ ] 10.2 Import placement: confirm every import added is at module level,
  and that none was placed locally without a circular-import or documented
  lazy-load reason. This change removes deferred imports; it must not add
  them.
- [ ] 10.3 Documentation compliance: re-check accepted decisions against
  `openspec/README.md`'s placement rules, including
  `docs/development/ARCHITECTURE.md` for the wheel ownership rule and
  `docs/development/TESTING.md` for the composition test conventions.
- [ ] 10.4 Narrative compression: keep completed-task notes at final
  behaviour, material validation evidence, and permanent destinations; hold
  rejected alternatives in `design.md` only.
- [ ] 10.5 Roadmap currency: determine whether any `docs/development/ROADMAP.md`
  goal's current state or gap mapping changes, and record the disposition in
  the design-promotion record either way. Note the relationship to
  `remove-relative-uv-sources` and to the kit-composition goals.
- [ ] 10.6 Promotion: complete the design-promotion record.
