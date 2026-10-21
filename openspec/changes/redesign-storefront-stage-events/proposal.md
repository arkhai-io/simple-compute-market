## Why

A storefront records structured **stage events**: `core_storefront.stage_log.stage_event(stage,
event, **fields)` writes a JSON log line and, best-effort, a row in the storefront's
`stage_events` table (`ts`, `stage`, `event`, `negotiation_id`, `listing_id`, `escrow_uid`,
`data`). Kits and domains emit events wherever they choose, and the storefront kit's
stage-event read route, bound by all three storefronts, serves them to administrators.

The mechanism serves two purposes with no contract for either:

- **An operator's audit trail of a deal's stages.** VM's `logs` CLI and deal-status view read
  the table directly; bare metal and API credits have no equivalent. The negotiation detail
  read embeds a negotiation's events.
- **The end-to-end synchronisation and evidence seam.** `docs/development/TESTING.md` directs
  end-to-end tests to "stage/event APIs over HTTP". Scenarios wait on or read
  `negotiation/round_decided`, `provision/job_submitted`, the `claims` stage, a lease's
  released event, and `fulfillment/capacity_released`.

What was found while designing `unbacked-bare-metal-listings` (its open question 11.3):

- **Identity columns are filled by guesswork.** The `listing_id` column takes
  `listing_id`, else `our_listing_id`, else the **negotiation ID**, so events naming no
  listing record a negotiation as one. The negotiation watchdog and VM's
  `discovery/order_published` pass the listing as `order_id`, which the fallback ignores;
  the kit negotiation runtime's `round_decided`, `accepted`, and `exited` events, VM's
  capacity and claim events, and bare metal's `fulfillment/capacity_released` have the
  listing in scope and pass the negotiation only.
- **No vocabulary.** Event names and fields are free-form keywords; nothing defines what an
  event means, which fields it carries, or who owns its definition.
- **Best-effort writes.** The insert swallows every error, so a scenario waiting on an event
  whose write failed times out rather than reporting the cause.
- **No retention.** Nothing prunes the table.
- **One domain's operator read.** Only VM has a CLI over the log.

No reader filters `listing_id` by a negotiation ID today, and the one end-to-end read by
listing passes the listing correctly, so the mislabelled column misleads a human reading rows
or a future reader rather than a current one.

## What Changes

Proposed; design not started. The design decides:

- whether the audit trail and the synchronisation seam remain one mechanism, and in
  particular whether end-to-end scenarios wait on events or on typed state reads that already
  exist (a fulfillment's status, a lease's state);
- who owns each event's definition — the core, the kit that emits it, or the domain — and
  how its fields and identity columns are declared and validated at the call;
- whether an event is written in the same transaction as the state change it reports;
- what `negotiation_id`, `listing_id`, and `escrow_uid` mean, and what an event that has none
  records;
- retention;
- what the operator read is across domains.

It covers every emitter and reader listed above, `TESTING.md`'s guidance on the seam, and
`market-composition`'s stage-event read requirement.

## Capabilities

### New Capabilities

None expected.

### Modified Capabilities

Expected: `market-composition` (the stage-event read and the events' contract) and
`test-compatibility` (the end-to-end seam). `.openspec.yaml` sets `skip_specs` until design
adds the deltas.

## Non-Goals

- Cross-service event delivery, which is `replace-polling-with-authenticated-push`'s. Its
  acceptance boundary refactors scenarios to await events; this change's design decides
  whether either depends on the other.

## Dependencies and Related Changes

- Opened by `unbacked-bare-metal-listings`, which handed it this defect (its design's
  decision 24) and changes nothing in stage events.
- Related to `replace-polling-with-authenticated-push` in the same lesser goal.

## Impact

`core/storefront`'s stage log and stage-event persistence; `kit/storefront`'s stage-event
read route and negotiation watchdog; `kit/negotiation-runtime`'s emitters; every storefront's
emitters; VM's logs CLI; `core/storefront-client`'s event reads; end-to-end scenarios that
wait on events.
