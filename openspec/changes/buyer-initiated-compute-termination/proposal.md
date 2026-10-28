## Why

A buyer who has taken delivery of a VM cannot end the lease. The VM storefront's
`terminate_vm_lease` (`domains/vms/storefront/src/market_storefront/services/fulfillment_service.py`)
reaches the site's terminate route, but no storefront route, typed-client method, or
buyer CLI verb calls it; after delivery a VM buyer can heartbeat, read settle status,
and reclaim an Alkahest escrow after expiry, and nothing else. Bare metal has the
capability — `POST /api/v1/fulfillments/{negotiation_id}/teardown`, authenticated as the
accepted buyer, and `market bare-metal teardown` — but as a domain route with its own
transport, outside the canonical storefront client. Neither domain records why a deal
ended: the lease's release reason is a string at the site, and the storefront learns
of the end only through the capacity-released callback, after teardown is proven.

This is the first change of the roadmap goal that sells compute by the period until
either party stops ([`ROADMAP.md`, Goal 8](../../../docs/development/ROADMAP.md#goal-8--sell-compute-by-the-period-until-either-party-stops)).
It needs no settlement change, so it lands first and on reserved deals as they are
today: the buyer's right to stop is universal, and what stopping costs is the selected
mechanism's own — a prepaid `once` part is forfeited, a refund stays seller-initiated
(`openspec/specs/settlement-servicing/spec.md`, "Only the seller reverses a held
payment"), and a per-period part, once one exists, stops at the effective time.

## What Changes

- One buyer-authenticated end-deal route in both compute storefronts, keyed by the
  negotiation ID and authorized to the accepted thread's buyer principal, as bare
  metal's teardown route is today. Bare metal's route folds into it; VM gains it over
  `terminate_vm_lease`. It terminates the lease at the site at once through the site's
  terminate route — the path the expiry watchdog runs, without waiting for a cycle —
  never by truncation, and answers with durable progress, never claiming capacity
  released while teardown is only queued. A repeat finds the same end.
- An **append-only log of requests to end a deal** and one **effective decision** per
  deal, keyed by negotiation ID: every request — buyer, seller, site, administrator,
  the storefront on a verified funding end — is appended with its principal, cause,
  requested instant, and evidence; the decision is a deterministic fold (earliest
  lawful effective instant wins, deterministic ties, final once passed or physically
  begun), with its financial and physical convergence tracked independently and every
  external call keyed by the decision. The log is retained for a seller-configured
  window at least the dispute horizon. This change records the buyer, site, and
  administrator request kinds and the physical convergence; the later changes add the
  seller's and the storefront's, and the financial half.
- An **administrative override**, a request kind with its own authority and audit,
  so an emergency never has to be dressed as a preemption.
- The site's **lease-ended event**: a durable, typed record — stable identity,
  effective instant, cause, source state — written in the same transaction as every
  transition that ends a lease, delivered through an outbox keyed by event identity,
  signed with the site's service identity, received idempotently by both compute
  storefronts and kept as evidence, with the lease read as the pull recovery path.
  Today the site sends only `capacity_released`, after teardown is proven, from an
  outbox keyed by reservation; that callback stays as it is. This is its own
  acceptance boundary within the change.
- The canonical storefront client gains the end-deal method, and both buyer CLIs a
  verb for it (`market vms` gains one; `market bare-metal teardown` is kept as the
  verb over the shared route). A deal whose fulfillment has not begun is ended too,
  by release where nothing was dispatched; bare metal's refusal of that case is
  retired.

## Capabilities

### Modified Capabilities

Expected: `vm-storefront-fulfillment` (the buyer-facing termination flow its
requirement says is deliberately absent), `physical-provisioning` (the lease-ended
report beside the capacity-released callback), `storefront-publication` or
`market-composition` (the stop intent and the shared route), `buyer-orchestration`
(the CLI verb). `.openspec.yaml` sets `skip_specs` until design adds the deltas.

### New Capabilities

None expected.

## Non-Goals

- Issuing any payment stop: a reserved deal's prepaid part is unaffected by the buyer
  ending the lease, and the payer stop for a per-period deal belongs to
  [`converge-ongoing-compute-leases`](../converge-ongoing-compute-leases/), which
  also makes the buyer's CLI stop the transaction before calling this route.
- Any refund or cancellation term for a buyer leaving a reserved deal early. The
  consequence is the mechanism's; a stated cancellation term is recorded as a revisit
  trigger in `design.md`.
- Seller-initiated ends: [`publish-and-preempt-spot-compute`](../publish-and-preempt-spot-compute/).
- The Alkahest-only admin interrupt route, which is left to Alkahest's owners.

## Dependencies and Related Changes

- Depends on nothing. The site's terminate route and release path exist
  (`openspec/specs/physical-provisioning/spec.md`, early termination uses the
  expiry release path).
- First of the goal's five changes; `converge-ongoing-compute-leases` builds on its
  stop intent and lease-ended report, and `publish-and-preempt-spot-compute` on its
  route shape.
- The lease-ended event's outbox is the shape `replace-polling-with-authenticated-push`
  plans for every site event; that change adopts it rather than building a second.
  Should it be designed first, this change depends on it for the transport.
- `resolve-compute-family-findings` removes the VM storefront's senderless callback
  routes; this change adds a route with a sender.
- `buyers-use-the-storefront-client` owns moving production buyers onto the typed
  client generally; this change adds its one method and verb without waiting on it.

## Impact

Both compute storefronts' route tables and fulfillment services, the storefront
client and its settlement route contracts, `core/storefront`'s persistence for the
stop intent, the provisioning service's deal-event sink and the site's outbox, both
buyer CLIs, the bare-metal buyer transport, and the end-to-end deal scenarios
(bare metal's second-deal buyer teardown stages move onto the shared route; VM gains
a buyer-cancel stage).

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md` — the stop intent and the lease-ended
  report under "Release" and "Fulfillment status and results"
- [x] Existing subsystem specification: `vm-storefront-fulfillment`,
  `physical-provisioning`, `buyer-orchestration`, and the storefront capability that
  owns the shared route
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

- The buyer may end any compute deal; the consequence is the selected mechanism's —
  `settlement-servicing` architecture companion.
- A deal's end is an append-only log of requests folded into one effective decision,
  with independent financial and physical convergence keyed by the decision —
  `ARCHITECTURE.md`, "Release".
- The site records a lease's end as a durable event with the ending transition and
  reports it to the storefront only — `physical-provisioning` and `site-capacity`
  specs, `ARCHITECTURE.md`.
- Ending a deal terminates; truncation is for moving an end the watchdog will act on
  later — `site-capacity` architecture companion.
