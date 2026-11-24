## Why

Every Arkhai payments part holds the seller's earnings until the part stops and the
dispute window passes: the mandate's hold is always `{afterStop: <dispute window>}`
(`kit/arkhai-payments/src/market_arkhai_payments/mandates.py`), and the payments
service then pays out a fixed seven days after release. A seller on a long on-demand
deal is therefore paid nothing until the stop, plus the dispute window, plus seven
days. A seller who would accept less buyer protection for faster payment cannot offer
it, and a buyer cannot see what protection an option's hold gives.

The hold also bounds the on-demand premature-stop penalty. A penalty is collectible
only from the seller's earnings still held: under `afterStop` holds that is everything
the deal has earned so far, and nothing in its first period without a setup charge
(`openspec/specs/deal-lifecycle/architecture.md`). A shorter hold pays the seller
sooner and shrinks what a penalty can reach by the same amount; at the limit the
penalty is a number in the terms with nothing behind it, and on-demand is spot at a
higher price. The hold and the penalty's collectibility are therefore decided
together.

This change is one of Goal 8's later changes; the MVP keeps the `afterStop` hold.

## What Changes

- **The payout hold as an option term.** A seller chooses each option's payout hold;
  it is a codec-owned lifecycle term, part of the option ID, and filterable in the
  registry. The default is the foundation's hold, until the stop plus the dispute
  window. Holds are not uniform across a market: each option states its own.
- **Derivation.** The payments kit derives the part's hold from the term — `afterStop`
  for the default, `for` a stated duration otherwise, both shapes the vendored contract
  publishes (`kit/arkhai-payments/schema/payments.schema.json`) — and the buyer's exact
  check compares it like every other mandate field.
- **Buyer display.** A hold shorter than the stop plus the dispute window is shown as
  reduced protection, with when the seller is paid. It is never refused by default.
- **The penalty's collectibility.** One rule states what an on-demand option's
  premature-stop penalty can actually reach under its hold, chosen in design from:
  a ceiling stated as a function of the hold; a floor of held funds equal to the
  penalty for a seller choosing a short hold; or operator enforcement beyond what is
  held. The buyer display and the default buyer's penalty refusal follow that rule.

## Capabilities

### Modified Capabilities

- `deal-lifecycle`: the payout hold term in the codec, and the penalty's collectibility rule.
- `settlement-configuration`: seller configuration of the hold, and the mandate's hold derived from it.
- `buyer-orchestration`: the hold and reduced-protection display, the exact check, and any change to the default penalty refusal.
- `registry-discovery`: filtering options by their hold.

### New Capabilities

None.

## Non-Goals

- A seller-funded bond, the codec's reserved `bond` term, which needs a payments
  contract and approval design first.
- Changing the payments service's fixed payout delay after release.
- A uniform hold across a market or a domain.

## Dependencies and Related Changes

- `serve-running-rate-deals` (a Goal 8 MVP change) shows the on-demand penalty with its
  bound — collectible only from the seller's earnings still held — under the
  `afterStop` hold; this change's display replaces that wording with the hold-aware
  rule. It needs nothing else from the MVP changes and may be designed in parallel.
- `switch-on-hosted-per-period-vm` gives operators the procedure for ruling a seller's
  unentitled end with the penalty up to what is held; this change's rule informs it.
- `discover-open-ended-compute-listings` owns the class filters this change's hold
  filter sits beside.

## Impact

The lifecycle codec, `kit/arkhai-payments` mandate derivation and seller
configuration, both compute buyers' display and exact check, and the registry's filter
specification. A new term changes the IDs of options that state it; options under the
default hold are unchanged.

## Permanent documentation impact

- [ ] `docs/development/ARCHITECTURE.md`
- [x] Existing subsystem specification: `deal-lifecycle`, `settlement-configuration`, `buyer-orchestration`, `registry-discovery`
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

- The hold term and the penalty's collectibility rule: `deal-lifecycle`'s spec and its
  architecture companion's external-authorities section.
- The derivation and seller configuration: `settlement-configuration`'s spec.
- The display and exact check: `buyer-orchestration`'s spec.
- The hold filter: `registry-discovery`'s spec.
