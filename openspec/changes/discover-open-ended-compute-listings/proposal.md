## Why

A compute listing offers reserved, on-demand and spot options, and a buyer has no way to
ask for one by name. The VM buyer finds an on-demand or spot option by a settlement clause
written by hand: the buyer quickstart's recipe is
`arkhai_payments.billing_kind=per_period early_termination.payee=false`
(`docs/buyer-quickstart.md`, "7. On-demand and spot"). No recipe covers reserved, no test
evaluates a clause on `arkhai_payments.billing_kind`, and the recipe matches only Arkhai
payments options, because a mechanism's clause field matches only that mechanism's options
(`kit/settlement-runtime/src/market_settlement_runtime/clauses.py`).

The bare-metal buyer cannot ask at all. `market bare-metal list` takes a resource query and
prints the registry's response, and `market bare-metal buy` takes a listing and an exact
`--option-id` (`domains/bare_metal/buyer/src/arkhai_bare_metal_buyer/cli.py`): it has no
settlement clauses, no selection and no explanation mode, though `buyer-orchestration`'s
"Buyer normal path consumes two DSLs" and `cli-query-language`'s "Explanation is
deterministic and sanitized" ask them of every domain's commands. The API-credit buyer
lacks settlement clauses and explanation too.

Each buyer also chooses its settlement option by its own code. The VM buyer chooses across
the whole discovered set through `BuyerSettlementPolicy`
(`core/buyer/src/core_buyer/settlement.py`); the API-credit buyer chooses per listing and
stops at its match limit (`domains/apicredits/buyer/src/arkhai_apicredits_buyer/buy_cli.py`);
the bare-metal buyer looks its option up by ID. The VM and API-credit buyers carry the
choice by rewriting a copy of the advertised listing. A shorthand added to three selections
would be written three times.

The product class itself is defined by billing where it is defined at all. The permanent
documents and the buyer's display call an option billed once reserved
(`docs/development/ARCHITECTURE.md`, "Discovery and negotiation";
`kit/settlement-runtime/src/market_settlement_runtime/buyer_terms.py`). What distinguishes
the products is who may end the lease early, which the option's early-termination
entitlements state for every mechanism.

## What Changes

- A compute option's class is read from its early-termination entitlements alone: neither
  party entitled is reserved, the payer alone is on-demand, the payer and the payee is
  spot, and the payee alone is committed spot, a lease the seller may end while the buyer
  is committed for the term. The buyer's display and the permanent definition follow that
  reading (design D1).
- Both compute buyers take a class shorthand on their discovery and purchase commands. It
  expands to predicates on the common `early_termination.payer` and
  `early_termination.payee` fields, conjoined with every explicit settlement clause, and
  the explanation shows the expansion (D2). The quickstart's recipes are rewritten to the
  same predicates, with a reserved recipe beside them.
- One shared selection chooses, caches and resolves the advertised option for the VM,
  bare-metal and API-credit buyers, and carries its choice beside the listing as
  advertised (D4). This takes the unowned item "Buyer settlement selection is implemented
  per domain and belongs in kit", which `fix-credits-payment-opening-amount` recorded.
- The bare-metal buyer's listing and purchase commands take the settlement clauses,
  selection and explanation the VM buyer's take (D5).
- The class predicates, and the rule that an unstated entitlement projects false and an
  unstated notice projects as missing, are tested as clause predicates.

## Capabilities

### Modified Capabilities

- `buyer-orchestration`: the class read from the entitlements and its shorthand; one
  selection shared by the three buyers, keeping the listing as advertised.
- `cli-query-language`: the class shorthand's expansion; what an option that states no
  entitlement or notice projects.

### New Capabilities

None.

## Non-Goals

- Filtering listings by `max_duration_seconds` or `available_until_utc`:
  `filter-listings-by-capacity-bounds` (D6).
- A release projection or lifecycle terms for Alkahest options. An interruptible Alkahest
  option reads as reserved; the roadmap tables the gap under Goal 8's unowned work (D3).
- A stored class, a common billing field, or a class field under a mechanism's namespace.
- Pushing settlement clauses to the registry. A buyer may already write the lifecycle
  projections in a resource query, where the registry filters them.
- Changing which mechanisms a buyer can purchase with: the bare-metal buyer still buys
  hosted options only.
- Moving buyers onto the typed storefront client: `buyers-use-the-storefront-client`.

## Dependencies and Related Changes

- Nothing gates this change.
- `filter-listings-by-capacity-bounds` owns the registry's bound filters. The two changes
  share no code.
- `buyers-use-the-storefront-client` edits the same buyer packages to replace their
  storefront transports. Whichever lands second reverifies against the other.
- `offer-a-seller-chosen-payout-hold` adds a hold term a buyer may filter on beside the
  class predicates.

## Impact

`kit/settlement-runtime` (selection, clause compilation, the class display in
`buyer_terms.py`), `core/buyer` (`BuyerSettlementPolicy`, orchestration's option
resolution, the explanation payload), `kit/policy` (`selected_settlement_artifact`), the
VM, bare-metal and API-credit buyer packages, `docs/buyer-quickstart.md`, and the
compute lanes' purchase drivers. No wire format, registry schema or stored record changes.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md`
- [x] Existing subsystem specification
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

- D1: the class definition in `docs/development/ARCHITECTURE.md`, "Discovery and
  negotiation"; `openspec/specs/storefront-publication/architecture.md`, "Compute terms of
  sale"; `openspec/specs/buyer-orchestration/spec.md` and its companion.
- D2: `openspec/specs/cli-query-language/spec.md`; the recipes in
  `docs/buyer-quickstart.md`.
- D3: no permanent destination — the gap is a row of Goal 8's unowned work in
  `docs/development/ROADMAP.md`.
- D4: `openspec/specs/buyer-orchestration/spec.md` and its companion.
- D5: `openspec/specs/buyer-orchestration/architecture.md`; the bare-metal buyer's command
  help.
- D6: no permanent destination — a boundary between two changes.
