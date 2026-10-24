# Design: capacity-event-driven standing VM offers

## Approved execution boundary

Stage 1 was proposal-only and committed before approval. Q10 authorizes retargeting onto `origin/integration/arkhai-payments` (`4881ca816`), not main. Q11 explicitly approves one deterministic integration property covering both listing modes, 8→0→1 capacity, stable identity, failed registry writes, quiet-cycle recovery and restart. No sleeps or live services. Hosted purchase/exhaustion checks and deployment pin changes are prohibited; rollout is description-only in the PR against the approved branch. Do not merge.

## Existing mechanisms to reuse

- `domains/vms/listings/src/arkhai_vms_listings/reconciler.py` owns full-shape fit/candidate selection, exact site/pool/member identity, fungible fragmentation and same-ID recovery.
- VM `services/shape_feasibility.py` supplies the existing reservation-claim/predicate adapter. No new claim vocabulary or feasibility rule.
- `PublicationRuntime` already records closure provenance, protects seller closure, explicitly reopens registry status and converges per-registry failures from durable local intent.
- The VM publication loop already retries every 30 seconds and wakes on pool identity change. The capacity runtime already tails anonymous site ledger events outside reserve/settlement calls.
- Both projection families already have refresh APIs retaining last-good data and reporting failed loads. The event callback currently reads those caches without refreshing them.

## Decisions

### Fresh-known projections before fit

Refresh both existing projection families for the sites being reconciled, then capture their successful values before the existing close/reopen selectors run. A failed family holds that site's listings; loaded-empty remains authoritative. The kit's pre-existing strict all-site snapshot boundary is retained: an unavailable snapshot aborts and retries the pass instead of supplying unknown capacity as empty to another domain's hook. Preserve last-good caches for status, not as proof of a successful new fit decision. Retry on the next capacity cycle, including when the event feed is quiet. No durable projection store.

### One serialized decision boundary

Use the composed capacity runtime's lock for capacity-derived transitions and VM publication cycles, from input acquisition through registry convergence. This prevents a delayed older close from overtaking a later reopen. Events are wakes to inspect current truth, not commands to replay old direction. Preserve cancellation. No separate daemon and no registry calls from settlement.

### Durable delivery convergence

Call the existing convergence operation after the refreshed decision even if there are no transitions. Keep failed or missing per-registry delivery records discoverable against current local status, independent of process cursors or future events. Mark the existing delivery row pending before network I/O, and do not acknowledge a reopen until the same registry accepts both payload publication and open status. This prevents an interruption or lost result write from falsely certifying a closed registry row as published. A later release supersedes a failed earlier close. Reuse the existing tables and registry payload/status operations; no outbox or schema change.

### Existing identity and seller intent

Reload the stored candidate on reopen, preserving ID, binding and terms. Reuse the existing reconciliation-origin guard. Seller-closed/paused listings remain protected. Admission remains authoritative; publication is an asynchronous discovery signal, not a capacity reservation.

## Alternatives

- Settlement-side registry writes couple unrelated failure boundaries and miss external reservations/releases: rejected.
- A GPU-only check or a second claim builder disagrees with existing full-shape feasibility: rejected.
- Waiting only for another event strands quiet exhausted pools; waiting only for the slower publication timer weakens the capacity polling contract: rejected.
- A second retry worker or durable outbox duplicates existing intent and delivery records: rejected.
- Reimplementing the approved base's provenance, full-shape selection or timer adds no capability: rejected.

## Compatibility and rollback

No new public state, endpoint or schema. Rebuild affected wheels and explicitly reinstall them. Rollout uses a rebuilt image digest plus the matching infrastructure source pin, with existing writer/signing configuration. No rollout or live readiness assertion is part of this change. Reverting restores previous asynchronous behavior without altering accepted reservations or settlements.

## Validation

The approved integration scenario drives the real app, SQLite persistence, lifecycle controls and publication runtime with controlled external site/registry boundaries. It observes 8→0 closing, →1 same-ID reopening, per-registry failure during quiet feeds and recovery through reconstructed process-like runtime state over the same database. Existing suites retain jurisdiction over fit edges, fragmentation, seller intent, event transport and registry fan-out.

Stage 1 scoped strict validation passed with OpenSpec 1.14.3. Its former main baseline had 46 unrelated strict failures (SCM #301). The approved branch pins OpenSpec 1.14.0; revalidate using that documented version. Execution evidence is in `docs/attachments/capacity-listing-reconciliation.md`: 584 focused/shared-package tests passed, with two existing core skips; packaging, architecture, comment hygiene and scoped citations passed. Replaying the original VM hook fails the approved property at the eighth reservation; both repaired modes pass. Focused typing retains two reproduced baseline diagnostics (SCM #303). Global strict validation on the approved base retains 16 reproduced failures; scoped validation passes. Hosted qualification and the Docker end-to-end pipeline are unrun; hosted purchases and deployment changes are explicitly prohibited.

## Design promotion record

| Accepted decision | Permanent location | State |
|---|---|---|
| Fresh-known fit and serialized same-ID close/reopen | `openspec/specs/storefront-publication/spec.md`, `openspec/specs/storefront-publication/architecture.md#reconciliation` | Promoted |
| Durable per-registry quiet/restart recovery and seller precedence | Same subsystem spec and architecture, including pending delivery and two-phase reopen acknowledgement | Promoted |
| Event-to-registry work is outside settlement | `docs/development/ARCHITECTURE.md#capacity-publication-and-multi-domain-storefront-composition` | Promoted |
| Existing process, cadence and signer/writer prerequisites | `docs/development/DEPLOYMENT_AND_CONFIG.md#combined-compute-family-storefront` | Promoted |
| Roadmap and campaign index currency | `openspec/changes/README.md` has an independent focused-repair row and no new dependency edges. `docs/development/ROADMAP.md` requires no edit: existing projection ownership and delivered shape semantics remain true; no negotiation, sizing or publication-policy goal is delivered here | Reviewed |
| Approved base, test authorization and rollout-only restriction | This design and [PR #304](https://github.com/arkhai-io/simple-compute-market/pull/304), open against `integration/arkhai-payments` | Temporary |
