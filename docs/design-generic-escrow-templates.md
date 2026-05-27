# Generic escrow templates — design proposal

Status: design only, not yet implemented. Captures the locked-in shape
from a design conversation so whoever picks this up has the conclusions
without having to re-derive them.

## Problem

Today's listing publish pipeline is hardwired to a single escrow shape:

```python
escrow_address = get_erc20_escrow_obligation_nontierable(chain.name, ...)
accepted_escrows.append({
    "chain_name": chain.name,
    "escrow_address": escrow_address.lower(),
    "fields": {"token": token_address},
    "price_per_hour": advertised_amount,
})
```

Three things baked in:

1. The escrow contract is always the ERC-20 non-tierable one.
2. `fields` is always `{"token": addr}` — ERC-20 specific.
3. `price_per_hour` is a single scalar — fine for ERC-20, useless for
   anything with multiple amounts (TokenBundle) or non-amount variables
   (ERC-721 tokenId).

Alkahest's non-tierable escrow contracts have heterogeneous shapes:

| Contract           | Fixed-by-operator                                        | Scales per unit time         |
|--------------------|----------------------------------------------------------|------------------------------|
| ERC20              | `token`                                                  | `amount`                     |
| ERC721             | `token`, `tokenId`                                       | —                            |
| ERC1155            | `token`, `tokenId`                                       | `amount`                     |
| NativeToken        | —                                                        | `amount`                     |
| TokenBundle        | `erc20Tokens[]`, `erc721Tokens[]`, `erc721TokenIds[]`,   | `nativeAmount`,              |
|                    | `erc1155Tokens[]`, `erc1155TokenIds[]`                   | `erc20Amounts[]`,            |
|                    |                                                          | `erc1155Amounts[]`           |
| Attestation/2      | `attestationUid` / `attestation`                         | —                            |

## Locked-in design

### Wire format generalization

`accepted_escrows[].price_per_hour` is a wart — it bakes in single-rate
ERC-20. Replace with a per-field rate list:

```json
{
  "chain_name": "anvil",
  "escrow_address": "0x...",
  "literal_fields": {"token": "0x..."},
  "rates": [{"field": "amount", "per": "hour", "value": "150"}]
}
```

The buyer takes its negotiated duration, computes
`field_value = rate × duration` per entry in `rates`, builds the
obligation data from `literal_fields ∪ computed_fields`. Negotiation
pressure points at the rate values; literal fields are non-negotiable.

### Storefront-side: templates declare structure, CSV supplies rate values

The escrow contract address is the natural identity that fixes the
field shape. The template captures that shape once; CSV rows reference
templates by name and supply per-resource rate values.

```toml
[escrow_templates.usdc_anvil]
chain = "anvil"
escrow_address = "auto:erc20_nontierable"
literal.token = "0x9fe4..."

  [escrow_templates.usdc_anvil.rates.amount]
  field = "amount"
  per   = "hour"

[escrow_templates.compute_bundle_anvil]
chain = "anvil"
escrow_address = "auto:token_bundle"
# Index correspondence (USDC → index 0, CREDITS → index 1) is set
# ONCE here in the template; CSV never sees array indices.
literal.erc20Tokens     = ["0xUSDC...", "0xCREDITS..."]
literal.erc721Tokens    = []
literal.erc1155Tokens   = []
literal.erc1155TokenIds = []

  [escrow_templates.compute_bundle_anvil.rates.usdc]
  field = "erc20Amounts[0]"
  per   = "hour"
  [escrow_templates.compute_bundle_anvil.rates.credits]
  field = "erc20Amounts[1]"
  per   = "hour"
  [escrow_templates.compute_bundle_anvil.rates.eth]
  field = "nativeAmount"
  per   = "hour"
```

### CSV: named slots, not positional

CSV cell encodes a list of `template:slot=value,slot=value` entries
separated by `;`:

```csv
resource_id,...,accepted_escrows
compute-001,...,"usdc_anvil:amount=150"
gpu-prem-001,...,"usdc_anvil:amount=200; compute_bundle_anvil:usdc=180,credits=10,eth=0"
```

Named slots over positional because:

- Positional silently breaks when a template gains or reorders a rate
  slot. Named slots fail loudly: "unknown slot `creditz`".
- The CSV stays decoupled from contract field paths. Operator writes
  `usdc`; only the template knows that maps to `erc20Amounts[0]`.

### Single-slot ergonomic sugar

When a template has exactly one rate slot, the slot name can be
dropped:

```csv
compute-001,...,"usdc_anvil=150"
```

This degrades cleanly: as soon as the template gains a second rate
slot, the bare-number form errors out — no silent breakage.

### `auto:` indirection

`escrow_address = "auto:erc20_nontierable"` resolves at config-load
time via alkahest's per-chain address config (the same JSON the
storefront already loads). Literal `0x...` addresses always work as
an escape hatch for custom deployments. Available `auto:` keys mirror
alkahest's obligation-kind names:

- `auto:erc20_nontierable`, `auto:erc721_nontierable`,
  `auto:erc1155_nontierable`, `auto:native_token_nontierable`,
  `auto:token_bundle_nontierable`, `auto:attestation_nontierable`,
  `auto:attestation2_nontierable`

(Tierable variants get `_tierable` suffixes.)

### Rendering order

TOML preserves table key order, so the `rates` sub-table is an ordered
dict. `market listings show` and any interactive rate-entry prompt use
that order. Operators get named-slot resilience and stable display
order for free.

## What stays the same

- The `accepted_escrows` wire shape on the listing is still a list of
  per-(chain, escrow) entries. The change is **inside** each entry:
  `fields` becomes `literal_fields`, `price_per_hour` becomes `rates`.
- The buyer's intersection logic (configured chains ∩ listing chains)
  is unaffected — chain selection happens at the entry level, same as
  before.
- The seller-side identity registration, heartbeat, and on-chain
  dispatch all happen per chain; that's orthogonal to the field-shape
  change inside each accepted_escrows entry.

## Migration path

1. Add `[escrow_templates.<name>]` parsing in `service/config_loader.py`,
   sibling to `[chains.<name>]`. Each template gets a typed
   `EscrowTemplate` dataclass exposing `chain`, `escrow_address` (with
   `auto:` resolution), `literal_fields: dict[str, Any]`,
   `rate_slots: dict[str, RateSlot]`.
2. Wire-format change in `service.schemas.AcceptedEscrow`:
   `price_per_hour: str | None` → `rates: list[RateValue]`,
   `fields` → `literal_fields`. No backwards-compat shim (consistent
   with the multi-chain refactor's stance).
3. CSV parser learns the `template:slot=value,...` DSL in
   `resource_csv_importer.py`. Single-slot sugar handled by checking
   the template's rate-slot count at parse time.
4. `cli_publish._publish_round` stops calling
   `get_erc20_escrow_obligation_nontierable`; iterates the resource's
   referenced templates instead, materializing one `accepted_escrows`
   entry per template.
5. Buyer-side `make_buyer_payment_escrow_terms_fn` switches from
   "look at `fields.token` and `price_per_hour`" to "evaluate
   `literal_fields` + (rate × duration) per rate". `escrow_client`
   gains per-obligation-kind builders (alkahest_py already exposes
   them; just need the dispatch on escrow_address).
6. Storefront seller verification (`verify_escrow_for_settlement`)
   reads the chain-side obligation data and reconciles against the
   negotiated `literal_fields` + computed rate values.

## Open questions / deferred

- **Multi-rate negotiation**. Today's bisection negotiates a single
  scalar. With multiple rates, the negotiation space becomes a vector.
  Simplest first step: pick one "primary" rate per template (the
  largest-value one) and negotiate that; treat others as fixed by the
  template-declared value. Vector negotiation can come later.
- **Non-time rate units**. The `per` field is extensible — `per = "request"`,
  `per = "kWh"`, etc. — but adding non-time units means the buyer's
  demand needs to carry the corresponding quantities. The negotiation
  thread already has `agreed_duration_seconds`; would gain
  `agreed_request_count` or similar per rate dimension. Out of scope
  for the initial generic-escrow change.
- **TokenBundle in CSV is genuinely awkward.** The literal arrays in
  the template absorb most of it, but a row referencing a 5-token
  bundle still has 5 rate values to set. Acceptable for now; if it
  becomes painful, the escape hatch is a TOML resource catalog
  (`resources.toml` alongside `resources.csv`, picked up by the same
  auto-discovery) where the nested structure renders more naturally.
- **Attestation escrows are one-shot, not rate-bearing**. Templates
  for `AttestationEscrowObligation*` will have empty `rates` and a
  literal `attestationUid`. The single-slot sugar doesn't apply (zero
  slots). Operator references such templates by name with no value
  payload: `accepted_escrows = "service_attestation"`.
- **Template name collisions across operators.** Templates are local
  to a single storefront, so collisions only matter intra-config;
  config-load validates uniqueness. The wire format records the
  resolved `escrow_address` literally, so buyers never see template
  names.
