# Remaining design work — plan shapes, mechanism vocabulary, multi-domain capacity

Successor to the two retired design docs
(`design-market-core-extraction.md`,
`design-settlement-lifecycle-and-capacity.md`). Everything those docs
planned that has landed is recorded as current state in
`ARCHITECTURE.md` ("Organizing Principle", "Settlement Lifecycle",
"Capacity and the Site Authority"); this doc keeps only what has not,
with the design context needed to pick each item up. `TODO.md` → "Core
Stack" remains the flat aggregation of remaining work and points here
for the architectural items.

Every item below is parked behind an explicit trigger — a second
settlement mechanism, a second executor kind, a second market domain, a
second physical site. Each seam was deliberately left ungeneralized
until its second instance shows what is actually invariant (the same
criterion that gated the core/kit/domain extraction itself).

## 1. Carrier vocabulary generalization

**Trigger:** the first lifecycle policy that needs a second settlement
mechanism, or a plan shape proposed in-band during negotiation.

The settlement-plan carrier is mechanism-neutral
(`market_core.schemas.SettlementObligation`/`SettlementPlan`: lifecycle
universals as typed fields + a `{mechanism, params}` envelope
interpreted by kit codecs), but the *proposal/listing* vocabulary is
not yet: `EscrowProposal`/`AcceptedEscrow` still key on
`(chain_name, escrow_address)`, and a listing's accepted-escrows set
has not generalized to advertising accepted settlement *mechanisms*.
Negotiation vocabulary for proposing/accepting plan shapes (intervals,
bond sizes, oracle choice, mechanism choice) is schema policy, exactly
like price — the buyer-policy surface is the seam it plugs into.

Riding the same wire change, so `/negotiate/*` churns once, not twice:

- **Naming alignment:** the code says `EscrowProposal` /
  `Decision.proposal` where the core's framing says message/terms.
- **The flat legacy shapes leave:** `EscrowTerms` (the alkahest
  `doObligation` call shape) and the flat terms list on the wire
  survive today as marked legacy coercions into the envelope — they
  exit with the client-wheel wire bump.
- **`storefront-client` wire genericization** (TODO.md Core Stack
  item 3): the client wheel still sends the flat legacy
  provision-terms shape and exposes compute-vocabulary parameters.

## 2. Settlement plan shapes

The lifecycle engine, plan carrier, heartbeat channel, and the first
policy (deferring-third-party-oracle single escrow) are landed; the
shapes below are future instantiations of the same machinery.

### Oracle service

The landed oracle-gated policy assumes the oracle `arbitrate()`s true
at end of lease unless a dispute was raised — manual for now via the
kit's `alkahest-oracle` CLI (arbitrate/status). The production
follow-up is an oracle *service* that auto-arbitrates true at lease
end and parks disputes for a human, with the buyer's signed heartbeats
and the seller's persisted evidence informing dispute handling.
Operating an oracle starts as a domain-side tool; kit owns only talking
*to* `TrustedOracleArbiter`.

### True heartbeat-gated collection

Today missing heartbeats ground a *dispute*; making them mechanically
block payment needs one of:

- (a) a heartbeat-verifying **arbiter contract** checking buyer
  signatures on-chain, with the deal split into per-interval escrows so
  a dead buyer costs the seller at most one interval; or
- (b) Alkahest's **splitter contracts** with an off-chain oracle service.

The constraint that shapes both: the oracle must be a party that does
not benefit from the decision (a seller-operated oracle gates nothing;
a buyer-operated one is a unilateral payment hold-up). Party-operated
verification only works where the chain itself checks the evidence —
which is exactly alternative (a).

### Interval escrows and penalty bonds

One negotiated transaction materializing as N escrows (one per service
interval, collected as earned), and seller-posted bonds the buyer can
claim on seller failure (an escrow whose claimant is the counterparty).
Both are plan shapes over the existing carrier. They also carry the
engine's remaining structural gap: the seller-side `ClaimsEngine`
today services claimant-side collection only — `materialize`/`reclaim`
hook driving joins the engine when interval escrows need engine-driven
materialization (until then materialization stays in the settle phase).

### Fiat mechanism codec

The carrier's mechanism envelope exists precisely so fiat support is
additive — a `kit/fiat-<provider>` codec (payment-intent/hold
materialization, provider-API condition checks and terms verification,
capture/payout vs refund primitives) plus a domain policy that
proposes/accepts the mechanism. For mechanisms whose materialization
is not independently derivable (fiat: the provider generates the
object id), determinism covers the agreed terms, and verifying the
materialized object against them is the codec's job. The trust model
shifts (a payment provider is a trusted third party, not a neutral
arbiter), which changes how bonds and heartbeat-gating cash out, but
not the engine's shape. Building a concrete provider integration waits
for a committed customer/provider pairing.

## 3. Capacity: job-kind dispatch and the second market domain

**Trigger:** the second executor kind (formerly lifecycle-doc item
II.7). The site authority, aggregator, two-phase TTL reserve, and
event split are landed; what remains is the proof that the neutral
ledger and job dispatch hold beyond the VM domain.

Open edges left by the site-authority flip, to close with this work:

- **Job-kind queue keyed by `allocation_id`:** job submission still
  goes through the VM-specific `/hosts/{host}/vms` API rather than a
  job-kind queue dispatched by executor plugin. Executor idempotency
  rule when this lands: derive infra names deterministically from
  `allocation_id` so re-delivered creates detect-or-create.
- **Owning storefront from the ledger, not settings:** deal-scoped
  events go to the storefront named in service settings; they should
  route to the `deal_ref` recorded on the allocation at reserve time
  (one site serving multiple storefronts requires it).
- **Multi-site e2e proof:** `AggregateCapacityClient` routing across
  sites is proven at the unit level only; the e2e topology has one
  physical site until a second one joins here.

Then, in order: a second executor kind (inference or other) behind the
job-kind dispatch; a second market-domain storefront sharing the pool
end-to-end (one hardware pool selling through two market schemas — the
original point of the split).

Deployment follow-ons parked on the same milestone: parameterize the
storefront Helm chart for per-domain instances, per-domain Makefile
build targets, and moving the `storefront.bob/alice.toml` instance
configs out of the package data dir into a deploy directory.

## Non-goals / deferred (standing stance)

- **A second resource domain** (storage, bandwidth) — validate with
  heterogeneous *compute* schemas first.
- **Shipping multiple schema plugins from this repo** — the plugin
  mechanism is in place; a second schema package waits for a second
  schema.
- **Generic aggregation beyond the buyer aggregation policy.**
- **Fractional/shared claims and packing** — claims stay coarse
  (whole-GPU, exclusive) until inference packing is concrete; the
  claim schema gets a mode field then, not a general scheduler now.
- **Cross-seller capacity markets** (sites serving storefronts of
  different operators) — the deal/capacity event split already keeps
  deal privacy, but pricing/quota between operators is out of scope.

## References

- `ARCHITECTURE.md` — "Organizing Principle", "Settlement Lifecycle",
  "Capacity and the Site Authority": current state of everything this
  doc builds on
- `TODO.md` → "Core Stack" — the flat aggregation of remaining work
- Alkahest arbiter contracts — `TrustedOracleArbiter.sol`,
  `logical/AllArbiter.sol`, `attestation-properties/RecipientArbiter.sol`
