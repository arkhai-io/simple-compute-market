# Core settlement dispatch — implementation evidence

Code revision: `1fd0a4cd`, with carrier contract in `1472158d`. Scope is section 1 of `route-settlement-by-mechanism`; these are implementation self-checks, not independent acceptance or live payment/hardware qualification.

## Setup and replay

Required/prepared target: checkout-local library composition, owned by the `core-dispatch` worktree. Internal dependencies are rebuilt wheels, not editable sibling sources. Tests use deterministic synthetic marketplace signers, opaque domain stages and temporary run-log directories; no external credentials, database seed or service deployment is needed. Wheel installation and import checks completed successfully. No servers or external resources remain running.

From the repository root, this command prepares and opens the dispatch/recovery surface:

```sh
make dist-core dist-arkhai-core-buyer dist-arkhai-core-storefront dist-registry-client dist-kits && make -C core/buyer reinit && make -C core/storefront reinit && (cd core/buyer && uv run --no-sync pytest tests/unit/test_orchestrator.py tests/unit/test_identity_recovery.py -q)
```

The consuming `reinit` targets currently rewrite unrelated lock resolution; restore `core/buyer/uv.lock` and `core/storefront/uv.lock` after the check, without discarding fresh local installs. Tracked friction: [#257](https://github.com/arkhai-io/simple-compute-market/issues/257).

## Observed boundaries

- Agreement dispatch receives the identical accepted outcome, both without a proposal and with a stray escrow field. Missing declared support fails before invoking domain effects. Evidence persists independently of escrow identity.
- Fresh selection excludes an installed/enabled mechanism with no buyer stage before clause ordering and compatibility effects.
- Entry acceptance validation receives the exact outcome before accepted-round observation. Generic Agreement, party, amount and option checks remain in core.
- Real run-log replay preserves negotiation, mechanism and established reference; changed evidence identity is refused. No payment escrow is required.
- Storefront fulfillment retains accepted negotiation, settlement reference and site. Retargeted results fail at the common boundary. Opaque stages pass domain-contract/registry composition with no universal verify/build-plan interface.

## Validation

Final focused commands used freshly rebuilt/reinstalled wheels:

- `cd core && uv run --no-sync pytest tests/unit/test_carrier_purity.py tests/unit/test_domain_contract.py tests/unit/test_domain_boundaries.py -q`: **15 passed**.
- `cd core/buyer && uv run --no-sync pytest tests/unit/test_orchestrator.py tests/unit/test_settlement_acceptance.py tests/unit/test_settlement_policy.py tests/unit/test_priceless_options.py tests/unit/test_identity_recovery.py -q`: **52 passed**.
- `cd core/storefront && uv run --no-sync pytest tests/unit/test_domain_registry.py tests/unit/test_domain_lifecycle.py tests/unit/test_publication_plugins.py -q`: **24 passed**.
- `make -C core typecheck-core`: passed, 6 source files. A separate typed consumer with non-callable `SettlementStageTable[Stage]` entries and the public evidence export also passed mypy. `make check-comment-hygiene` and strict OpenSpec validation passed.
- Wheel/import inspection: `arkhai-core` contains `market_core/settlement.py`, both public exports and `market_core/py.typed`; buyer/storefront modules import against the installed carrier. Role wheels have no pre-existing typing marker or declared static target.
- Production scan found no concrete-mechanism or proposal-presence dispatch in core. Existing escrow wire coercion/backfill and opaque carrier projections remain deliberately in scope of their later changes.

The initial dispatch fixture used a noncanonical option ID; correcting its canonical derivation made that run pass. Final runs have no failures. Core pytest emits the existing unused `asyncio_mode` warning ([#258](https://github.com/arkhai-io/simple-compute-market/issues/258)); buyer migration fixtures also emit an existing Pydantic enum-serialization warning.

Concrete VM, bare-metal and API-credit consumer wiring/suites wait for sections 2–5. No complete-deal or live payment lane was run. The table/evidence API and adapter obligations are recorded in the change's design and permanent market-composition/buyer-orchestration architecture. No screenshots are applicable to this library boundary.
