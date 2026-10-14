# API-credit settlement repair evidence

Base: `49b9fff3`; checkout-owned branch `fix-apicredits`. Hacking self-checks for the assigned code-review findings, not independent acceptance or live payment qualification. Production changes are under `domains/apicredits/`; permanent specification promotion is recorded in `openspec/changes/archive/2026-10-09-route-settlement-by-mechanism`.

## Setup

Required and prepared target: installed internal wheels, in-process seller settlement and credits HTTP authority, fresh temporary SQLite databases. No inherited deployment selector, external credential, shared database, server or browser is used. Synthetic buyer/seller/payment-service Ed25519 identities and an ephemeral operator key exercise the controlled boundary. The existing first-use script seeds 100 units of `svc-quota`, checks credits `/health=200`, and cleans its databases and authority engine.

```sh
make dist
make -C domains/apicredits/storefront reinit
make -C domains/apicredits/service reinit
(cd domains/apicredits/service && PYTHONPATH=src uv run --project . --find-links ../../../.dist --with arkhai-apicredits-storefront --reinstall-package arkhai-apicredits-storefront --reinstall-package arkhai-apicredits-domain python ../../../docs/attachments/apicredits-dispatch/first_use.py)
```

## Review F1 — immutable verified evidence and receipt-based recovery

`SettlementRepository.store` rejects status or payload changes once evidence is verified; exact retries remain valid. Payment settlement revalidates the stored receipt and its exact Agreement/mandate/reference instead of overwriting it with pending evidence or re-polling. Receipts are persisted with wire aliases so the real verifier can read them after reopen.

Production-surface tests: `storefront/tests/integration/test_payment_recovery.py` uses the real seller stage, receipt verifier and SQLite repository. It proves lost-ack recovery with payment polling unavailable, one grant, unchanged verified evidence; transactional refusal of status/source changes; and no issuance or payment I/O for a tampered stored signature.

```sh
(cd domains/apicredits/storefront && uv run --no-sync pytest tests/integration/test_payment_recovery.py tests/unit/test_settlement_fulfillment.py tests/unit/test_issuance_evidence_repository.py -q)
```

Observed after `make dist` and consuming reinit: **18 passed** (4 new recovery/storage checks, 14 existing). The initial run exposed non-wire receipt serialization; the final run includes its repair. The committed existing first-use replay passed: pending grants 0, lost-ack grants 1, final grants 2, balance 5, payment escrows 0, payment polls 3 (cached receipt recovery needs no new poll), private owner-only retrieval held, temporary databases removed. Comment hygiene and `git diff --check` passed.

No API-credit verify finding was assigned from the independent verification packet; its shared controlled API-credit first-use replay is rerun here. The bare-metal and VM diagnostics remain with their assigned workers.

## Review F2 — consume prepared verified evidence without another chain read

`AlkahestSellerStage.deliver_prepared` loads the evidence saved by preparation, requires verified delivery facts and the matching Agreement/reference, and then issues/attests. It does not call preparation again inside the exception-to-failed block. Preparation remains the chain-verification boundary before a delivery job is reserved.

Production coordinator test: `storefront/tests/unit/test_settlement_fulfillment.py::test_verified_prepare_delivers_when_further_chain_reads_are_unavailable` makes the first chain verification succeed and every further verification raise a transport error. Observed: verified evidence, one issuance, ready progress and ready genuine Alkahest row. The existing coordinator test now expects one verification instead of two; its grant/credential/obligation-servicing assertions remain intact.

After rebuilding wheels and storefront reinit, the same focused command above passed **19 checks** (13 fulfillment/coordinator, 4 payment recovery, 2 issuance/private repository). No separate API-credit verification diagnostic exists in the closeout packet; this coordinator replay is the F2 reproduction surface.

## Review F6 — neutral issuance/failure/rollback references

Common issuance results and stage events, failure-policy kwargs/context, and `CreditsServiceClient.rollback_issuance` now use `settlement_ref`. Failure context also carries `negotiation_id`; capacity release uses that accepted identity in `deal_ref`, matching VM failure actions, while retaining the exact held reservation ID. Genuine Alkahest verification/rows, the site ledger's existing correlation API and unchanged public settlement wire DTOs retain their escrow names.

Production fulfillment test: `storefront/tests/unit/test_settlement_fulfillment.py::test_payment_refusal_releases_hold_using_negotiation_not_transaction` drives the real fulfillment/failure-policy composition with SQLite and controlled credits/capacity I/O. It observes refusal, exact hold release under the negotiation ID rather than the distinct transaction reference, neutral failure-event correlation, listing-reopen dispatch, and hold cleanup. Existing client HTTP rollback tests retain adjust/revoke ordering and use the renamed parameter. No compatibility alias was added. Touched capacity/publication imports are module-level; real consumer suites found no import cycle.

Final validation after `make dist`, buyer/storefront/service reinit and domain `uv sync --dev --find-links ../../.dist --reinstall`:

| Scope | Passed |
|---|---:|
| Storefront seven existing focused files plus payment recovery integration | 64 |
| Domain typed credits client/HTTP/issuance evidence | 25 |
| Buyer five focused composition/credential/negotiation/listing/plugin files | 17 |
| Credits authority real typed-client HTTP `src/tests/unit/test_api.py` | 3 |

**109 passing checks.** Commands use the focused file sets in `docs/attachments/apicredits-dispatch/index.md`, adding `storefront/tests/integration/test_payment_recovery.py`. F1 adds 4 checks, F2 adds 1 coordinator check, F6 adds 1 failure-recovery check. Final first-use replay on all three repairs again observed credits `/health=200`, pending grants 0, lost-ack grants 1, final grants 2, balance 5, payment escrows 0, payment polls 3, private owner-only retrieval, and temporary database cleanup. Final comment hygiene and `git diff --check` passed.

## Tooling and limits

Reinit lock churn is already owned by [#257](https://github.com/arkhai-io/simple-compute-market/issues/257); only generated lock changes are restored, not tested environments. Existing Pydantic schema-shadowing warnings remain owned by [#259](https://github.com/arkhai-io/simple-compute-market/issues/259). These packages declare no static typing target. Live payment-ledger qualification is not represented by synthetic receipt I/O. Visual: false; screenshots: none. No external resources remain.
