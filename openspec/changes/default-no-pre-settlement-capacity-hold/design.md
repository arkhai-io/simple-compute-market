# Design

## Context

Verified by inspection 2026-08-06.

- `_place_capacity_hold` reads `settings.capacity.hold_ttl_seconds` and returns
  immediately when it is not positive. The apicredits storefront's equivalent does the
  same.
- No funds, escrow, or chain interaction is required anywhere in the negotiation path
  before a hold is placed. Buyer authentication is an EIP-191 signature over operation,
  resource id, and timestamp.
- There is no rate limiting anywhere in the storefront, and no per-buyer concurrency
  limit on negotiations.
- `_commit_or_reserve_fresh` returns `None` when no hold exists or the hold lapsed, and
  settlement reserves fresh. The zero-TTL path is already implemented and exercised.
- The shipped comment describes 0 as "settlement then does the plain atomic reserve,
  racing other deals for the capacity" — a contention trade-off, with no mention of the
  exposure a non-zero value creates.

### Provenance (established from history, 2026-08-06)

Pre-settlement holds are not part of the POOLS work and did not exist for most of the
system's life. The history is specific:

- Before 2026-06-11, capacity was reserved only at settlement. The embedded capacity
  adapter landed 2026-06-10 with `reserve(+TTL)` in its contract but not implemented —
  its own commit records that "TTL soft holds raise until two-phase reserve (II.6)
  lands." Acquiring exclusivity therefore required a verified on-chain escrow, and no
  unfunded party could hold capacity at all.
- On 2026-06-11, "Two-phase reserve: terms acceptance holds, settlement commits"
  introduced the acceptance-time hold, added `hold_expires_at` to `compute_allocations`,
  and set `hold_ttl_seconds` to 900. It was work item II.6 of a pre-OpenSpec design
  document, `design-settlement-lifecycle-and-capacity.md`, which is the "capacity
  design" `_place_capacity_hold`'s docstring still cites and which no longer exists in
  the repository — it predates the migration of planning into OpenSpec. That is why the
  two-phase reserve has no owning change here.
- The POOLS campaign, a month later, moved the ledger from `compute_allocations` into
  `kit/site` and preserved the behavior. It inherited this exposure; it did not create
  it.

The 2026-06-11 change was a deliberate fix for a real problem — it "removes the
hold-lapses-mid-provision race outright," and securing capacity before provisioning is
genuinely the right shape for that race. What it did not weigh was that granting
exclusivity before payment, with no funding requirement and no rate limit, hands an
unfunded party the ability to exclude everyone else. The race was reasoned about; the
exclusivity was not.

Setting the default back to 0 therefore restores the pre-2026-06-11 posture exactly,
rather than inventing a new one: reservation at settlement, behind escrow verification.
The race that change fixed returns with it, which is the accepted cost recorded below.

## Goals / Non-Goals

**Goals:** remove a total-denial vector from the shipped configuration; record why, in
the place an operator will read.

**Non-Goals:** billing, rate limiting, removing the two-phase implementation.

## Decisions

### Zero the default rather than shorten the window

The instinct to lower the TTL treats this as accidental abandonment, where the relevant
quantity is how often acceptance fails to reach settlement. Against an adversary the
quantity is different: the fraction of capacity held is bounded by the attacker's
request rate, not by the hold duration. Holding everything continuously needs
approximately *reservable slices ÷ TTL* requests per second — with 100 slices and a
10-second TTL, ten requests per second. A shorter window raises the required rate
linearly and degrades legitimate settlement at the same time.

Recorded explicitly because "reduce the timeout" is the natural first response and it
does not work.

### Accept the paid-buyer race as the smaller risk

Zeroing reopens the window the two-phase reserve exists to close: a buyer whose escrow
has settled may find capacity taken. That is a genuine regression and it involves money
that has already moved.

It is accepted because the risks are not comparable in kind. The race affects one deal
at a time, occurs only under genuine contention, and has a recovery path — the buyer is
refunded. The vector it replaces denies every buyer simultaneously, costs the attacker
nothing, and has no recovery short of blocking traffic. Trading a rare, bounded,
recoverable failure for the removal of an unbounded one is the right direction.

`negotiation-capacity-feasibility-probe` reduces the residual further by telling a buyer
during negotiation whether the capacity is there, though it cannot remove the race.

### The reasoning belongs in the settings file, not only here

The vulnerable default survived because the comment beside it framed 0 as a performance
choice. An operator tuning for throughput would reasonably raise it, and nothing would
tell them what they were exposing.

The justification therefore goes where the value is set, stating plainly that the
default is a security posture and naming the condition under which it may be raised:
once held capacity is billed. This change's own documents will be archived; the comment
will not.

### Local profiles keep holds on, deliberately

`storefront.bob.toml` and `storefront.credits.toml` are local compose and e2e profiles
with no untrusted buyers. Leaving them at 900 keeps the two-phase reserve path under
end-to-end coverage while production ships safe — otherwise this change would silently
remove test coverage from code that is intended to return.

Both overrides are annotated with why, so a future reader does not "correct" them to
match the default.

## Risks / Trade-offs

- **[A settled buyer loses capacity]** → Accepted above. Needs an operator-visible
  failure path, which settlement's fresh-reserve already surfaces.
- **[An operator raises the value back for throughput]** → Mitigated by the in-file
  justification naming the precondition for raising it.
- **[Test coverage of the two-phase path is lost]** → Prevented by the local profile
  overrides, and by checking rather than assuming that the unit suite parameterizes the
  TTL.
- **[The change reads as abandoning the two-phase design]** → It does not: the
  implementation stays, and `billable-capacity-reservations` restores a non-zero default
  once holding costs the holder something.

## Migration Plan

Configuration only. Deployments carrying their own value are unaffected until they adopt
the new default; operators who have copied the cookbook's `900` should be told to
change it, which the cookbook edit does for new readers.

Rollback is setting the value back, which is exactly what the vulnerability is — so
rollback should not be treated as a routine option.

## Open Questions

- **Should a non-zero value be rejected outright rather than merely defaulted off, until
  billing exists?** A hard refusal removes the footgun entirely but also removes an
  operator's ability to make an informed trade for a trusted deployment, and would break
  the local e2e profiles. Deferrable: the default plus justification addresses the
  shipped-configuration risk, which is the immediate exposure.
