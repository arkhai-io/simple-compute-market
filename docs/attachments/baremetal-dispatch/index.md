# Bare-metal settlement dispatch — implementation evidence

Tested code: `355f6de7` on `baremetal-dispatch`, base `1fd0a4cd`. These are implementation self-checks, not independent acceptance or live payment/hardware qualification.

## Setup and first use

Required live target: an owned, ready bare-metal storefront with its selected-site capacity/provisioning authority, payment or chain authority, and revocable hardware access. No such deployment was supplied or prepared here. The live `e2e-tests/tests/e2e/roles/scenarios/bare_metal/test_bare_metal_deal.py` scenario was not run; unavailable hardware is not a passed story.

Prepared target: checkout-local installed wheels, real in-process storefront application and fresh temporary SQLite databases, owned by this worktree. The Alkahest HTTP fixture uses deterministic synthetic EIP-191 principals and the external verification seam. The payment fixture uses Ed25519 buyer/seller/receipt identities with no wallet or chains, real mandate derivation and signed-receipt verification, and a controlled payment-client poll boundary. Site/provisioning collaborators are controlled fixtures, not hardware. No external credentials, durable seed rows, servers or deployments are required or left running.

From the repository root, prepare dependencies:

```sh
make dist && make -C domains/bare_metal/storefront reinit && make -C core/buyer reinit && (cd domains/bare_metal/buyer && uv sync --dev --find-links ../../../.dist --reinstall)
```

The reproducible first-use surface is:

```sh
cd domains/bare_metal/storefront && uv run --no-sync pytest tests/test_http_settlement.py tests/test_http_introductions.py -q
```

This opens the controlled settlement → selected-site delivery/result/restart/teardown and authenticated contact-reveal paths. Each invocation creates fresh temporary databases and cleans them up. Do not reuse an existing storefront database: the introducing evidence migration changed in place, and startup refuses the old receipt-only schema with an explicit reset error. For an operator deployment, select a new owned `BARE_METAL_STOREFRONT_DB_PATH` and republish/re-negotiate; there is no adoption/copy/drop migration.

Environment startup now requires explicit `BARE_METAL_STOREFRONT_SETTLEMENT`. Alkahest's entry alone requests EVM/chain resources; payment and contact do not inherit that requirement. Existing site and identity configuration still applies. No inherited deployment selector was reused or seeded.

## Observed boundaries

- Buyer purchase declares only payment support; selected-entry validation binds the account and accepted mandate before approval. Installed buyer and storefront plugins validate through the core contract, including all six codecs.
- Seller acceptance, registration and settlement share one declared table. Unsupported exact selection fails before acceptance effects. Legacy Alkahest acceptance records an explicit selected Agreement option; verification retains its real escrow and obligation journal.
- Payment pending evidence refuses delivery before reservation/begin. After verification, restart retries the same reservation and fulfillment once, records a redacted result, and needs no escrow row.
- Changed mechanism, Agreement digest, established reference or verified source payload is rejected by the real repository without modifying the original evidence.
- A tampered persisted payment signature is rejected by the selected entry on recovery before any new physical effect. The HTTP fixture also refuses unverified evidence and exercises result/access/teardown on the original site.
- Contact reveal remains authenticated, durable, recipient-delivered and retention-owned by its kit. Its evidence contains only the obligation reference and Agreement digest, no duplicated contact payload or physical delivery input; no physical lifecycle is created.
- Fresh SQL inspection confirms negotiation-keyed evidence, unique opaque reference, status constraint and validated versioned payload storage. Physical progress and private/transient access remain separate.

The escrow-only status fixture now expects missing evidence (404), rather than treating an escrow row as authorization. No kept delivery or privacy assertion was weakened.

## Validation

- The 15 named storefront suites: **76 passed**.
- Buyer `tests/test_buyer_composition.py`: **9 passed**.
- `make dist`, storefront `reinit`, core-buyer `reinit`, and buyer dependency reinstall: passed.
- Installed-wheel inspection: both role entry points and six codecs each conform; fresh schema bootstrap/rerun and explicit drift rejection pass. To reproduce without editable role packages:

```sh
uv pip install --python domains/bare_metal/buyer/.venv/bin/python --reinstall --no-deps .dist/arkhai_bare_metal_buyer-0.1.4-py3-none-any.whl &&
uv pip install --python domains/bare_metal/storefront/.venv/bin/python --reinstall --no-deps .dist/arkhai_bare_metal_storefront-0.2.5-py3-none-any.whl &&
domains/bare_metal/buyer/.venv/bin/python docs/attachments/baremetal-dispatch/inspect_wheels.py buyer &&
domains/bare_metal/storefront/.venv/bin/python docs/attachments/baremetal-dispatch/inspect_wheels.py seller
```

Observed fresh columns: `negotiation_id`, `mechanism`, `agreement_sha256`, `settlement_ref`, `status`, `evidence_json`, `created_at`, `updated_at`. No receipt-only column or payment escrow exists. The diagnostic removes its temporary database.

- Comment hygiene, touched module-import review, undefined/unused import checks and diff whitespace check: passed. Neither role package declares a static typing target or typing marker.
- Initial implementation runs exposed an indentation error and an incorrectly wrapped test provision envelope; both were corrected. The payment first-use path also exposed the existing listing-binding serialization defect, repaired separately in `8d08d32e`. Final runs have no failures.
- Reinit rewrote unrelated core-buyer lock resolution; the generated lock diff was restored without discarding installed wheels. Observation and workaround are recorded in [#257](https://github.com/arkhai-io/simple-compute-market/issues/257).

## Integration and promotion

`BareMetalFulfillmentService` receives `read_verified_evidence` from the settlement boundary. Generic `fulfill_bare_metal` callers supply that transient callable as `context.domain_input["read_verified_evidence"]`; it is never serialized. The hook consumes `context.settlement_evidence`/`settlement_ref` and returns the neutral reference, while existing public DTO and physical-progress coordinates still project it as `escrow_uid`.

Permanent promotion remains pending review: physical-provisioning behavior and its bare-metal/signed-receipt architecture headings, and market-composition table rationale. The active change records these destinations and the reset requirement. No screenshots apply to these backend-only checks; independent drive/review and live complete-deal qualification remain separate.
