# VM settlement repair replay

Target: checkout-owned VM buyer/storefront wheels and controlled in-process
entry points. No deployed service, inherited deployment selector or external
credential is required. Tests use synthetic canonical principals and fresh
temporary SQLite; no shared database is seeded. These are backend/CLI checks,
not live chain, payment ledger or provider qualification.

Prepare from the repository root:

```sh
make dist
make -C domains/vms/buyer reinit
make -C domains/vms/storefront reinit
```

## Verified evidence validation (verify F3)

`payment_repository.py` validates verified evidence before the first write:
SHA-256 Agreement digest, nonempty authoritative source, supported
`vm.delivery-facts` v1 envelope, and the existing fulfillment planner's
normalized payload. Pending facts remain incomplete; invalid verified writes
cannot replace pending state or freeze a fresh record.

Proving test: `test_vm_evidence_validation.py` drives real SQLite storage with
malformed digest/source/envelope, pending promotion and exact valid retries.
`test_migrations.py` retains restart and immutable delivery identity coverage
with supported verified facts.

```sh
cd domains/vms/storefront
ENABLE_EVENT_QUEUE=true AGENT_WALLET_ADDRESS='' .venv/bin/python -m pytest \
  tests/unit/test_vm_evidence_validation.py tests/unit/test_migrations.py \
  tests/unit/test_vm_fulfillment_planner.py -q
.venv/bin/python ../../../docs/attachments/route-settlement-closeout/inspect_vm_schema.py
```

Focused suite: **22 passed** (one existing Pydantic schema-shadow warning).
Replay refuses the original poisoned record with `ValueError: verified VM
evidence requires a sha256 Agreement digest`; `temporary_database_removed=True`.
