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
- `6c8bb5b` — Phase 2b: both `accepted_escrows` emitters
  (`cli_publish._publish_round` and
  `sqlite_client.synthesize_accepted_escrows_from_demand`) now
  populate `literal_fields` + `rates` alongside the legacy fields.
  Hidden-reserve case emits `rates=[]` to preserve the shape.
- `df79caa` — Phase 2c prep: `primary_rate_value` /
  `accepted_token_address` now fall back to the legacy shape when
  the new fields are missing, so individual call sites can migrate
  one at a time without breaking on pre-cutover entries in SQLite
  or on the wire. 20 new helper tests in
  `service/tests/unit/test_rate_helpers.py`.
- `f4b0770` — Phase 2c: 6 production-code reader sites swap from
  inline parsing to the helpers (net −31 LOC, semantics unchanged):
  `_extract_initial_price_from_order`,
  `_token_resource_from_accepted_escrow`, `get_refund_terms`,
  `_extract_listing_token`, `_extract_token_contract_from_listing`,
  `_print_publish_table`. `_seller_reference_amount` migrates
  transitively.
- Phase 3: CSV importer learns the
  `template:slot=value,slot=value;template2:...` DSL via
  `parse_accepted_escrows_cell()` in
  `storefront/src/market_storefront/utils/resource_csv_importer.py`.
  The cell is materialized at import time (not at publish) — each
  entry stored on the row is the same `{chain_name, escrow_address,
  literal_fields, rates}` shape `accepted_escrows` carries on the
  wire. This keeps the row flat and self-contained: cli_publish reads
  the column straight without needing the template catalog at publish
  time. New `accepted_escrows TEXT` column on `resources`, with idempotent
  ALTER-ADD migration. `ESCROW_TEMPLATES` module-level constant in
  `utils/config.py` mirrors `CHAINS`; threaded into the two top-level
  CSV callers (`system_service.seed_resources_if_empty`,
  `admin_controller.import_resources`). Single-slot sugar (`name=value`)
  and zero-slot attestation form (`name`) both validate against the
  template's rate-slot count at parse time. 17 unit tests in
  `tests/unit/test_accepted_escrows_csv_dsl.py` + 3 end-to-end tests
  in `test_resource_csv_importer.py`.
- Phase 4: `_publish_round` branches on the row's materialized
  `accepted_escrows` column. When present, `_scale_template_entries()`
  resolves the entry's chain in `CHAINS`, calls `resolve_token` against
  `literal_fields["token"]`, and scales each `rates[i].value` from raw
  human (slot value as written in CSV) to base units, populating the
  legacy `fields`/`price_per_hour` siblings alongside. The legacy
  CHAINS-broadcast path stays as the fallback for rows without
  templates — backward compat during phases 5/6. Rows with templates
  ignore the row's `min_price`/`token` columns entirely (templates are
  the source of truth). 13 unit tests in
  `tests/unit/test_publish_round_with_templates.py`.
- Phase 5: buyer dispatch in
  `buyer/market_buyer/escrow_client.py:make_buyer_payment_escrow_terms_fn`
  switches the token reader to `service.schemas.accepted_token_address`
  (literal_fields-first, legacy-fields fallback) and gates the build on
  the resolved escrow-kind codec — only `erc20_escrow_obligation_nontierable`
  proceeds; everything else raises `NotImplementedError` with the
  chain + escrow address in the message. `EscrowProposal` gained
  forward-looking `literal_fields` + `rates` optional siblings (mirrors
  the Phase 2a treatment of `AcceptedEscrow`); the proposal builders in
  `buy.py` and `settle.py` now populate `literal_fields={"token": …}`
  alongside the legacy `fields`. 8 new tests in
  `buyer/tests/test_escrow_client_dispatch.py` + 2 schema tests in
  `service/tests/unit/test_escrow_proposal.py`.
- Phase 6: seller verify in
  `storefront/src/market_storefront/utils/escrow_verification.py:verify_escrow_for_settlement`
  applies the same ERC20-only dispatch gate as Phase 5 on the
  proposal-present path. Codec resolution moved from `address_to_slot`
  (slot-name only) to `get_escrow_codec_for` (full codec); the resolved
  codec is also reused for `get_obligation` (no double-lookup). Token
  reader switched to `accepted_token_address` (literal-fields-first,
  legacy-fields fallback); arbiter override now accepts the literal
  sibling on equal footing with the legacy `fields["arbiter"]`. The
  legacy no-proposal path is unchanged. 9 new tests in
  `storefront/tests/unit/test_escrow_verification.py::TestVerifyProposalDispatch`.
- Phase 7: AcceptedEscrow drops the legacy `fields` and `price_per_hour`
  siblings. `literal_fields: dict` and `rates: list[RateValue]` are now
  non-optional (default `{}` / `[]`). The legacy-shape fallbacks in
  `primary_rate_value` and `accepted_token_address` go away — readers
  are exclusively on the new shape. Production emitters
  (`cli_publish._scale_template_entries`, `cli_publish._publish_round`'s
  CHAINS-broadcast fallback, `sqlite_client.synthesize_accepted_escrows_from_demand`)
  stop populating the legacy keys. The seller-side `escrow_shape_guard`
  middleware in `market-policy` now compares against `literal_fields`
  on both sides. Buyer/storefront proposal readers drop the
  `fields["arbiter"]` legacy fallback (Phase 5/6 emitters always populate
  `literal_fields`). Bulk test rewrites across storefront unit +
  integration, buyer, service, registry-service, and e2e fixtures.

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

All seven phases shipped. The generic-escrow template wire format is
now the canonical shape end-to-end. Deferred items remain in
"Open questions" below.

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

- ~~Phase 2b~~ — landed `6c8bb5b`.
- ~~Phase 2c~~ — landed `f4b0770` (helper fallback prep in `df79caa`).
- ~~Phase 3~~ — CSV importer + storage.
- ~~Phase 4~~ — cli_publish reads materialized templates from the row.
- ~~Phase 5~~ — buyer dispatch + ERC20-only NotImplementedError gate.
- ~~Phase 6~~ — seller verify + ERC20-only NotImplementedError gate.
- ~~Phase 7~~ — drop legacy fields + bulk test rewrites.

All landed. Branch is clean.
