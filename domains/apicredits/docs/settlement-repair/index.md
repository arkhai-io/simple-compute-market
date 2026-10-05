# API-credit settlement repair evidence

Base: `49b9fff3`; checkout-owned branch `fix-apicredits`. Hacking self-checks for the assigned code-review findings, not independent acceptance or live payment qualification. All changes and this packet are under `domains/apicredits/`; permanent specification promotion remains with campaign closeout.

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

## Tooling and limits

Reinit lock churn is already owned by [#257](https://github.com/arkhai-io/simple-compute-market/issues/257); only generated lock changes are restored, not tested environments. Existing Pydantic schema-shadowing warnings remain owned by [#259](https://github.com/arkhai-io/simple-compute-market/issues/259). These packages declare no static typing target. Live payment-ledger qualification is not represented by synthetic receipt I/O. Visual: false; screenshots: none. No external resources remain.
