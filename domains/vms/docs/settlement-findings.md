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

## Established reference conflict (review F5)

Evidence reuse raises `VmSettlementEvidenceConflict`, distinct from missing
accepted state. The Alkahest seller entry maps it to HTTP 409, preserving the
original evidence and leaving delivery untouched.

Proving test: `test_settlement_reference_conflict.py` drives the settlement
controller through real repository rejection of a second escrow UID for the
same negotiation. Missing-state ValueErrors still retain their existing 404.

```sh
cd domains/vms/storefront
ENABLE_EVENT_QUEUE=true AGENT_WALLET_ADDRESS='' .venv/bin/python -m pytest \
  tests/unit/test_settlement_reference_conflict.py \
  tests/unit/test_settlement_start_authority.py \
  tests/unit/test_settlement_composition.py -q
```

Focused suite: **17 passed** (one existing agent-ID configuration warning).

## Neutral introducing migration (review F6, VM)

Migration `20261001_011_vm_settlement_records` names the evidence/delivery
schema it creates. The introducing migration was edited in place; there is no
adoption or compatibility migration. Existing databases require the campaign's
explicit disposable-database reset.

```sh
cd domains/vms/storefront
.venv/bin/python -m pytest tests/unit/test_migrations.py -q
```

Fresh bootstrap, rerun and restart suite: **7 passed** (one existing agent-ID
configuration warning).

## Standalone buyer stage dispatch (verify F2)

`market negotiate` resolves the declared buyer stage once, then uses its
selection, accepted-entry, negotiation-price/prerequisite and proposal hooks.
The Alkahest stage owns escrow parsing, buyer-policy compatibility, chain and
wallet guards, and explicit token-price scaling. Advertised prices are not
scaled again. The payment stage supplies payer selection without wallet or
chain effects. The CLI only projects the resulting proposal into its wire
carrier; it never branches on a mechanism config key or escrow absence.

Replay/proving entry: fresh `CliRunner` invocation for both supported entries,
explicit and derived prices, and wallet refusal in
`test_negotiate_stage_dispatch.py`. It uses owned temporary run logs,
synthetic Ed25519 identity, controlled registry/config/token input, and a
capturing negotiation boundary; no payment/chain mutation is performed.

```sh
cd domains/vms/buyer
.venv/bin/python -m pytest tests/test_negotiate_stage_dispatch.py \
  tests/test_buy_resume_cli.py tests/test_policy_cli_injection.py \
  tests/test_buy_pricing_and_filters.py -q
```

Focused suite: **36 passed**. Inspection of `negotiate_cli.py` found no remaining
`config_key`, payment payer helper, Alkahest token resolver or wallet resolver.

Two first-use blockers were fixed separately: registry publisher pins are
parsed as JSON arrays, not Python tuples (`e97d81bf`); payment payer enrichment
accepts selection `params=None` as empty. Both are covered by the fresh CLI
replay above.
