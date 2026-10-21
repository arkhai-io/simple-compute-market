## 1. Refresh the payments wire contract

- [x] 1.1 Vendor the current payments schema and conformance vectors, record their hashes in `kit/arkhai-payments/schema/SOURCE.md`, and regenerate `models.py`.
- [x] 1.2 Add the required expected `livemode` to `verify_receipt`, supply it from `ArkhaiPaymentsConfig.livemode` (default `false`) in the buyer and seller stages, and cover matching and mismatched modes in `tests/test_receipts.py`.
- [x] 1.3 Sign `livemode` in the receipt and snapshot fixtures, pass the expected mode in `examples/local_e2e.py`, and show the setting in the kit README and the seller quickstart.
- [x] 1.4 Bump `arkhai-kit-arkhai-payments` to `0.3.0` and relock every dependent.

Landed in `064d8365`. `examples/local_e2e.py` passed against a development-mode payments service at the vendored contract.

## 2. Merge the development branch

- [x] 2.1 Merge `dev`, resolving dependency pins to `dev`'s with this change's payments requirement, and relock the conflicted projects against freshly built wheels.
- [x] 2.2 Regenerate the storefront Helm values schemas so they carry `livemode`.

Landed in `9983720a` and `01b1f6de`. Conflicts were confined to pins and locks; after relocking, the locks differ from `dev` only in the payments kit version, and `check-locks` passed repository-wide. `check-architecture` passed. Unit and integration suites: `test-arkhai-payments`, `test-apicredits`, `test-vms-buyer`, and `e2e-tests` unit passed; `test-bare-metal` passed once the values schemas were regenerated; `test-storefront` passed except `tests/integration/test_alkahest.py`'s two tests, which need a local Alkahest test chain (Node.js, Rust, Foundry) absent from the environment that ran them. The end-to-end pipeline has not run.

## 3. Prove the configured mode reaches verification

- [ ] 3.1 Give `FakePaymentsClient` a `livemode` option, default `False`, that the receipts it signs carry, so existing tests are unchanged (01 F2).
- [ ] 3.2 In the kit's `tests/test_seller.py` and `tests/test_buyer.py`, add for each stage: configured for live mode, it accepts a live receipt; configured for live mode, it refuses a test-mode receipt and produces no verified evidence. Live-service qualification stays with the payments service's own end-to-end tests (01 F2).
- [ ] 3.3 Correct the kit README's provenance sentence: the schema and vectors are vendored from the payments service's published wire contract and identified by the content hashes in `schema/SOURCE.md`, which records no upstream commit (01 F4).

## 4. Closeout

The full closeout task is planning's. Accepted in the design review's triage:

- [ ] 4.x Promotion writes `livemode` into `docs/development/DEPLOYMENT_AND_CONFIG.md`'s Arkhai payments settings: it must be set to `true` on upgrade for a live service; its `false` default refuses live receipts; and switching mode, origin, or identity is a cutover that drains or refunds open payment deals first (01 F3).
