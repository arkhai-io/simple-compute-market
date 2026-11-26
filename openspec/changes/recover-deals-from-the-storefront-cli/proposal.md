# Recover deals from the storefront CLI

## Why

A seller whose storefront is not running cannot act on a deal at either authority. Two
acts can fall due while it is down: filing `delivery_end(cause=payee)` for a deal the
seller failed to deliver, and sending a spot seller's notice. Both are sent only by the
running storefront: the seller half's `submit`, and the filing dispatch of its servicing
cycle (`kit/deal-servicing/src/market_deal_servicing/seller.py`).

Nothing serves the stopped case today.

- Each storefront CLI's `deals` group holds `preempt` alone, which calls the running
  storefront (`domains/vms/storefront/src/market_storefront/groups/deals.py`,
  `domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/deals_cli.py`). The
  typed seller client offers `notice`, `read` and `list`
  (`kit/deal-lifecycle-client/src/market_deal_lifecycle_client/seller.py`).
- No route exports a deal's kept evidence, and no command reads one.
- The operator handbook's answer is to end the lease at the site and let the restarted
  storefront file: it classifies the site's termination as the seller's own withdrawal
  and files then (`docs/operator-handbook.md`, "Leases the storefront has not
  delivered").

A buyer's protection does not wait on any of this: it is the buyer's own stop at the
payment authority and a case over held money. What a seller loses while its storefront
is down is time. A filing made late leaves the buyer to file first, and a notice not
sent runs no clock.

## What Changes

- A storefront CLI command exports a deal's evidence from a running storefront: the
  exact Agreement, the commitment and mandate, the authority bindings, the original
  filing identities, the signed evidence and the known case and effect references,
  with no private key. The export is read-only and authenticated as the seller.
- A storefront CLI command acts on an exported deal with the storefront stopped,
  through the same payment and dispute adapters the storefront composes, from the
  storefront's own configuration, as `check-payments` and `check-mediation` reach the
  authorities today. A seller failure is filed through the dispute adapter only, and an
  entitled notice is sent through the payment adapter only.
- Before any request the command writes a durable envelope of the operation: its key,
  kind, time and payload, the commitment and authority binding, the operator and the
  reason, the evidence digests, and the exact adapter requests. A rerun reads first and
  repeats the same requests; it never allocates another key. Results are written apart
  from the envelope.
- The command never opens the storefront's database. A restarted storefront finds the
  operator's case and effects through its watch and adopts them.

### Decided by the owner

- **D1: a change of its own, as a storefront CLI command.** Operator recovery left
  `converge-ongoing-compute-leases` (its design, D2).
- **D2: deferred.** No work starts until the activation condition in the change index
  holds.

### Open for design, not decided here

- **Who takes the export, and when.** It can be taken only while the storefront runs,
  so a seller needs it before the outage it prepares for. Nobody is named to take it:
  an operator by hand, a scheduled job, or the storefront writing one as a deal
  commits.
- **Where the envelope and the export live**, given the command may not write the
  storefront's database, and how long they are kept.
- **A filing that overlaps the restarted storefront's.** The mediation adapter reserves
  one original `delivery_end` writer in the caller's operation store, which is the
  storefront's database
  (`kit/arkhai-mediation/src/market_arkhai_mediation/adapter.py`); given no store it
  answers pending. The command needs a store of its own, and the design must show that
  the command and the storefront filing the same claim resolve to one case, and what
  happens when their claims differ. The adapter adopts an equivalent filed claim and
  answers a differing one repair required.
- **What the export route is to a released client.** A new seller route and its wire
  models are a step of `kit/deal-lifecycle-contracts`.
- **Which acts it covers.** The seller's filing and notice, or also reading the
  authorities for a deal's state.

## Capabilities

### Modified Capabilities

Provisional; settled in design.

- `deal-lifecycle`: the seller's evidence export, and recovery through the adapters
  without the storefront's persistence.

### New Capabilities

None.

## Non-Goals

- Clearing a deal's pending release: an operator does that at the site
  (`docs/operator-handbook.md`, "A deal ending on a pending release").
- A second writer of the storefront's database, or a second implementation of either
  authority's operations.
- Recovering a storefront's database. The command acts on what was exported.
- A stop or reverse sent by the seller in place of a filing.

## Impact

- Provisionally: `kit/deal-servicing` (the export's route service and the recovery runner),
  `kit/deal-lifecycle-contracts` and `kit/deal-lifecycle-client` (the export).
- Both compute storefronts' CLIs and their composition of the adapters outside the
  running application.
- `docs/operator-handbook.md`.

## Dependencies and Related Changes

- None.
- `converge-ongoing-compute-leases` makes a revised `delivery_end` reach the dispute
  authority; the command would file through the same mapping.

## Permanent documentation impact

- [ ] `docs/development/ARCHITECTURE.md`
- [x] Existing subsystem specification: `deal-lifecycle`
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

To be determined at design completion. Expected destinations: the `deal-lifecycle`
specification and its architecture companion, and the operator handbook's storefront
runbooks.
