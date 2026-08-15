## Why

The VM storefront resolves its `MarketDomainContract` from module scope at the points that validate listings, normalize negotiation input, build accepted settlement plans, and fulfill obligations, while the bare-metal storefront already carries one validated contract through its app, runtime, services, and repository. Until the VM root has the same explicit seam, later per-record multi-domain composition would have to guess which domain owns a record or preserve hidden process-global behavior.

## What Changes

- Add a VM storefront application/composition factory that accepts one immutable `MarketDomainContract`, validates its supported contract version and the exact VM storefront capability set before constructing persistence or serving requests, and installs that same object on the FastAPI app and in the lifespan-owned container.
- Thread the validated contract through VM startup, dependency container, SQLite repository factory, listing/publication service, negotiation callbacks, settlement composition, and fulfillment dispatch. Remove runtime calls from those paths to `market_storefront.domain_runtime.get_market_domain_contract`.
- Preserve the current default executable by constructing the existing `compute.v1` contract once at the outermost VM composition root and injecting it. This is a clean internal cutover: no compatibility accessor or second module-global resolution path remains.
- Match the already-parameterized bare-metal shape without changing bare-metal behavior, importing bare-metal code into VM packages, or generalizing either domain's semantics into core.
- Fail closed before startup when the supplied value is not a `MarketDomainContract`, its version is unsupported, its identity does not match the single-domain VM executable, or required codec, storefront, settlement, fulfillment, or compute-provisioning capabilities are absent, incomplete, or undeclared.
- Add focused contract-identity, invalid-version/capability, app/lifespan/container, repository, publication, negotiation, settlement, and package/import-boundary tests proving that one injected object is used end to end and that current VM behavior is unchanged.
- Make no wire, configuration, database-schema, data, deployment, or release migration. Existing persisted listing, negotiation, settlement, fulfillment, and operation identities remain unchanged; rollback is a code-only revert before the dependent multi-domain change begins writing domain discriminators.
- Promote the accepted injection and composition-boundary rules to permanent capability and architecture documents at implementation closeout, and update the roadmap current-state/gap mapping when the prerequisite is complete.

## Capabilities

### New Capabilities

- None.

### Modified Capabilities

- `market-composition`: Require a domain-owned storefront composition root to validate one supplied versioned contract once and inject that immutable contract through role-owned orchestration instead of resolving domain behavior from module state.
- `storefront-publication`: Require listing publication, repository normalization, negotiation, settlement-plan derivation, and fulfillment for one record to use the same startup-selected contract, failing before side effects on a missing or incompatible capability.
- `test-compatibility`: Require focused, package-level evidence that the injected contract reaches every VM storefront boundary, rejects incompatible contracts before startup, preserves observable VM behavior, and does not add an upward or cross-domain dependency.

## Impact

- Expected implementation files: `domains/vms/storefront/src/market_storefront/{domain_runtime.py,server.py,startup.py,container.py,settlement_composition.py}`, `domains/vms/storefront/src/market_storefront/utils/{sqlite_client.py,sync_negotiation.py}`, `domains/vms/storefront/src/market_storefront/services/listing_service.py`, and `domains/vms/storefront/src/market_storefront/controllers/negotiate_controller.py`.
- Expected focused tests: `domains/vms/storefront/tests/unit/{test_domain_runtime_wiring.py,test_server_app_composition.py,test_migrations.py,test_publications_wiring.py,test_sync_negotiation_seller_round_hook.py,test_settlement_composition.py,test_architecture_imports.py}` plus `domains/vms/storefront/tests/integration/{test_listings_api.py,test_negotiations_api.py,test_settle_controller.py}` and the existing standalone publication-command parity tests.
- Reference-only comparison: `domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/{domain_runtime.py,server.py,runtime.py,sqlite_client.py,negotiation_service.py}` and its focused composition tests. These files are not changed by this proposal unless implementation inspection finds an actual shared-core defect; such scope requires an explicit artifact amendment before editing.
- No API, carrier, configuration, database, migration, deployment manifest, package dependency, or released-artifact change is intended.

## Dependencies

- No blocking implementation dependency. The existing core `MarketDomainContract`, `validate_domain_contract`, `build_storefront_app`, and VM/bare-metal composition roots are the baseline.
- `multi-domain-storefront-composition` and `kit-storefront-composition-seam` depend on this clean injection seam and MUST NOT implement a parallel module lookup or domain-local compatibility path while this prerequisite is incomplete.

## Non-Goals

- Selecting among multiple domain contracts in one process or adding a persisted domain/offering-mode discriminator; `multi-domain-storefront-composition` owns that behavior.
- Changing VM, bare-metal, or Alkahest listing, negotiation, settlement, fulfillment, pricing, capacity, identity, or recovery semantics.
- Making the storefront executable core-owned, changing entry-point discovery, extracting a kit-owned storefront runtime, or modifying `MarketDomainContract` vocabulary.
- Adding a configuration key, environment variable, wire field, schema migration, data backfill, compatibility shim, deprecated accessor, or fallback contract.
- Editing production code or permanent specifications as part of this planning change.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md`
- [x] Existing subsystem specification
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

- Injected storefront contract ownership, single validation boundary, dependency direction, and the prohibition on module-global domain resolution to `openspec/specs/market-composition/spec.md` and `docs/development/ARCHITECTURE.md#composition-from-above-and-below`.
- Same-contract use across publication, negotiation, settlement, fulfillment, and repository normalization to `openspec/specs/storefront-publication/spec.md`.
- Focused injection, fail-closed compatibility, behavior-parity, and import-boundary evidence ownership to `openspec/specs/test-compatibility/spec.md` and the applicable current-state testing guidance in `docs/development/TESTING.md`.
- Completion of the prerequisite and the remaining per-record multi-domain gap to `docs/development/ROADMAP.md` under the multi-domain storefront goal.
