# Generic escrow templates — implementation handoff

Companion to [`design-generic-escrow-templates.md`](./design-generic-escrow-templates.md).
The design doc captures the locked-in shape; this doc captures
implementation state and the staging plan worked out across two
sessions.

## What's landed

- `5033148` — Phase 1: `EscrowTemplate` + `RateSlot` dataclasses,
  `escrow_templates_from_config()` in `service/config_loader.py`, with
  `auto:<obligation-kind>` resolution through the existing alkahest
  address machinery (`_AUTO_ESCROW_LOOKUP`). 7 new tests in
  `service/tests/unit/test_config_loader.py`. Additive — no consumers
  wired up.
- `ae3e1c6` — Phase 2a: `RateValue` Pydantic model in
  `service/src/service/schemas.py`, plus `literal_fields` and `rates`
  as forward-looking optional siblings on `AcceptedEscrow` (alongside
  the legacy `fields` / `price_per_hour` pair). Canonical readers:

  ```python
  from service.schemas import (
      primary_rate_value,        # rates[0].value (or None)
      accepted_token_address,    # literal_fields["token"] (or None)
      compute_rate_total,        # rate.value * duration // PER_UNIT_SECONDS[per]
      PER_UNIT_SECONDS,          # {"hour": 3600} for now
  )
  ```

  Both helpers accept either a Pydantic model or a plain dict. Their
  point is to give consumers a single line to change per call site
  rather than coupling them to wire-format details.

## Why staged as siblings, not a rename

The original design says "fields becomes literal_fields, price_per_hour
becomes rates" — that's the end state, not the route. ~68 files
reference `accepted_escrows` directly today, and the negotiation
engine in `market-policy` operates on a scalar price throughout. A
single-commit rename would either break the branch for the duration
of the migration or force a 1000+ LOC commit covering production
code + 40+ test files + negotiation engine in lockstep — high risk
for one sitting.

Sibling fields let consumers migrate one at a time. The last commit
in the staging plan drops the legacy fields cleanly once every reader
is on the helpers.

## What's left (staging plan)

### Phase 2b — Emit the new shape (small, isolated)

`cli_publish.py:_publish_round` builds `accepted_escrows` entries
directly. Change it to populate both shapes:

```python
accepted_escrows.append({
    "chain_name": chain.name,
    "escrow_address": escrow_address.lower(),
    "fields": {"token": token_address},           # legacy reader
    "price_per_hour": advertised_amount,          # legacy reader
    "literal_fields": {"token": token_address},   # new
    "rates": [{"field": "amount", "per": "hour", "value": advertised_amount}],
})
```

Test surface: `test_accepted_escrows_synthesis.py`, `test_cli_publish_helpers.py`,
`test_publications_wiring.py`, `test_listing_token_extraction.py`,
`test_extract_initial_price.py`. Add assertions on the new fields;
leave the legacy assertions in place.

### Phase 2c — Migrate readers to helpers (medium, mechanical)

Every place that reads `escrow.price_per_hour` or
`escrow.fields.get("token")` swaps to the helper:

- `storefront/src/market_storefront/utils/action_executor.py:373-413,566`
  — `_extract_initial_price_from_order`, `_token_resource_from_accepted_escrow`.
- `storefront/src/market_storefront/utils/refund.py:161-185` — refund
  amount derivation.
- `storefront/src/market_storefront/utils/sync_negotiation.py:386` —
  `_seller_reference_amount` (already calls `_extract_initial_price_from_order`
  internally, so changes flow through once the latter migrates).
- `storefront/src/market_storefront/cli_publish.py:500` — display only.
- `storefront/src/market_storefront/groups/escrow.py:152` — CLI default
  computation.
- `storefront/src/market_storefront/utils/escrow_verification.py` —
  check `fields.token` reads.
- `storefront/src/market_storefront/utils/sqlite_client.py:96` —
  storage/retrieval shape.

Pattern:

```python
# before
amount = escrow.get("price_per_hour")
token = (escrow.get("fields") or {}).get("token")

# after
from service.schemas import primary_rate_value, accepted_token_address
amount = primary_rate_value(escrow)
token = accepted_token_address(escrow)
```

Tests at this stage: production code reads land cleanly because the
emitter still populates legacy fields. No test rewrites needed yet.

### Phase 3 — CSV DSL

`storefront/src/market_storefront/utils/resource_csv_importer.py`
(or whichever importer owns the `accepted_escrows` column today)
learns the `template:slot=value,slot=value;template2:...` DSL with
single-slot ergonomic sugar (bare `template=value`) and zero-slot
attestation form (bare `template`).

Touches the CSV examples in `storefront/storefront.{bob,alice}.toml`
provisioning paths and the test fixtures in
`integration-tests/tests/e2e/roles/`.

### Phase 4 — `cli_publish` switches to template iteration

Once templates are parsed and CSV rows reference them, `_publish_round`
stops calling `get_erc20_escrow_obligation_nontierable` directly and
materializes one `accepted_escrows` entry per (template referenced by
row) × (slot values from CSV).

This is the commit that justifies the templates' existence. After
this, ERC20 still flows end-to-end; other obligation kinds become
addable via TOML alone (provided buyer/seller dispatch supports
them — see phase 5/6).

### Phase 5 — Buyer dispatch

`buyer/market_buyer/escrow_client.py:make_buyer_payment_escrow_terms_fn`
swaps "look at `fields.token` + `price_per_hour`" for "evaluate
`literal_fields` + (rate × duration) per rate, build obligation_data".

For ERC20 only, dispatch stays on `alkahest_py.erc20_escrow.do_obligation`.
Other obligation kinds raise NotImplementedError loudly with the
escrow_address in the message — design doc's "deferred" pattern.

The negotiation engine in `market-policy` does NOT need to change.
Per-round message bodies still carry absolute `fields.amount`; the
rate ↔ amount conversion happens at the listing/proposal boundaries
only. See "Negotiation invariant" below.

### Phase 6 — Seller verify

`storefront/src/market_storefront/utils/escrow_verification.py:verify_escrow_for_settlement`
reads on-chain obligation data per kind (`alkahest_py.erc20_escrow.get_obligation`
etc.) and reconciles against the negotiated `literal_fields` plus
computed rate values. Same ERC20-only dispatch as Phase 5.

### Phase 7 — Drop legacy fields

Once every reader is on helpers AND every emitter populates the new
shape, delete `fields` and `price_per_hour` from `AcceptedEscrow`,
make `literal_fields` non-optional, and rename `rates: list | None`
to `rates: list`. Update tests in bulk. Single commit, clean diff.

## Negotiation invariant (don't break)

The per-round negotiation message body carries an **absolute** amount,
not a rate. That's because both sides have agreed the duration is
fixed before negotiation begins, so the per-round counter is a single
scalar in base units — no ambiguity between "you offered $50/hr for
5h = $250" vs "you offered $250 total". Keeping this shape avoids
touching the negotiation engine.

Conversion happens only at the boundaries:

- Listing → per-round reference amount:
  `primary_rate_value(accepted) * duration_seconds // 3600`
  (already done inline in `_seller_reference_amount`).
- Final accept → rate.value on the agreed proposal:
  `agreed_amount * 3600 // duration_seconds` (forward calc; the
  agreed proposal echoes the listing's `rates[i].field`/`per`).

Multi-rate templates (TokenBundle) at this point would still
negotiate a single scalar against the *primary* rate (the largest-value
one — design doc's "open questions" simplification). The other rates
are template-fixed.

## Open questions deferred (still)

The design doc's "Open questions / deferred" section stands as-is:

- Multi-rate vector negotiation
- Non-time rate units (`per = "request"`, `per = "kWh"`)
- TokenBundle CSV awkwardness past 5 tokens
- Attestation one-shot template ergonomics

None of these block the staging above. They become tractable once the
generic infrastructure is in place.

## File map (pointers for the next session)

```
service/src/service/config_loader.py        Phase 1 — done
service/src/service/schemas.py              Phase 2a — done; Phase 7 finishes
service/tests/unit/test_config_loader.py    Phase 1 tests — done

storefront/src/market_storefront/cli_publish.py
  ├── _publish_round        Phase 2b emit; Phase 4 template iteration
  └── _print_publish_table  Phase 2c reader migration (cosmetic)
storefront/src/market_storefront/utils/action_executor.py
  ├── _extract_initial_price_from_order  Phase 2c
  └── _token_resource_from_accepted_escrow  Phase 2c
storefront/src/market_storefront/utils/refund.py        Phase 2c
storefront/src/market_storefront/utils/sync_negotiation.py:386   Phase 2c (transitively)
storefront/src/market_storefront/utils/escrow_verification.py  Phase 6 (per-kind decode)
storefront/src/market_storefront/utils/sqlite_client.py:96   Phase 2c

storefront/tests/unit/test_cli_publish_helpers.py       Phase 2b assertions
storefront/tests/unit/test_accepted_escrows_synthesis.py  Phase 2b assertions
storefront/tests/unit/test_listing_token_extraction.py    Phase 2c (helpers handle dict)
storefront/tests/unit/test_extract_initial_price.py       Phase 2c
storefront/tests/unit/test_escrow_fields_policy.py        Phase 7 (cleanup)
storefront/tests/unit/test_publications_wiring.py         Phase 2b/7
storefront/tests/unit/test_refund.py                      Phase 2c
storefront/tests/unit/test_escrow_verification.py         Phase 6/7
storefront/tests/unit/test_rl_middleware.py               Phase 7
storefront/tests/unit/test_order_pause_state.py           Phase 7
storefront/tests/integration/test_listings_api.py         Phase 7
storefront/tests/integration/test_negotiate_controller.py Phase 7
storefront/tests/integration/test_settle_controller.py    Phase 7
storefront/tests/integration/test_negotiations_api.py     Phase 7
storefront/tests/integration/test_registry_client_contract.py  Phase 7
storefront/tests/integration/test_storefront_client.py    Phase 7
registry-service/tests/integration/test_listings.py       Phase 7
registry-service/tests/integration/conftest.py            Phase 7

buyer/market_buyer/escrow_client.py
  └── make_buyer_payment_escrow_terms_fn   Phase 5

resource_csv_importer (find via grep)   Phase 3
integration-tests/tests/e2e/roles/       Phase 3/4 (CSV fixtures)
```

## Estimated session count

- Phase 2b: 1 session (small, isolated).
- Phase 2c: 1 session (mechanical migration of ~6 production files + spot test updates).
- Phase 3 + 4: 1 session (CSV DSL + cli_publish refactor land together because they need the same templates wired in).
- Phase 5 + 6: 1 session (buyer/seller dispatch + verify; ERC20-only path).
- Phase 7: 1 session (drop legacy fields + bulk test rewrites).

So ~5 sessions to fully land. Each is committable independently and
keeps the branch green.
