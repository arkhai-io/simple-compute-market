# Design

## Context

Verified 2026-08-06; re-verify before implementing.

- Storefront implementation sizes: `market_storefront` 60 files / 14,408 lines;
  `apicredits_storefront` 33 files / 3,786 lines; `arkhai_bare_metal_storefront` 14
  files / 1,930 lines.
- API credits reimplements eight VM storefront concerns; bare metal has none of them.
- Kit packages carry almost no domain vocabulary already: `kit/policy`, `kit/identity`,
  `kit/fulfillment`, `kit/config`, and `kit/alkahest` have none at all. The layering
  discipline holds where kit has been used; the problem is the concerns that never
  reached it.
- `market-composition`'s "From-below kit dependencies" already requires kit to depend
  downward only, so extraction must not introduce a kit dependency on a domain or a
  deployed service.
- All three domains already pass `assert_domain_conformance`, which exercises six codecs
  and declared capabilities "without assuming a repository layout."

## Goals / Non-Goals

**Goals:** one place where the seam is defined; two concerns through it; a repeatable
pattern.

**Non-Goals:** the six larger concerns, behavior change, layout churn, core changes.

## Decisions

### Prove the seam on the smallest concerns, not the most valuable

`sync_negotiation` is 914 lines and the biggest prize. It is the wrong place to discover
that the seam is shaped wrong.

`negotiation_watchdog` (138 versus 110 lines) and `alkahest_service` (65 versus 58) are
small enough to read side by side, and their duplication is least arguable — a stale
thread sweep on an interval, and chain client construction from configuration. If the
seam cannot carry those cleanly, that is worth learning in a day rather than after a
900-line move.

### Kit owns the mechanism; the domain supplies codecs and configuration

The division that makes extraction tractable: kit owns control flow, persistence
interaction, retry and idempotency, and lifecycle. The domain supplies its contract, its
configuration values, and anything requiring domain semantics.

The test for whether something belongs in kit is whether two domains' implementations
differ **only** in which codec they call and which configuration key they read. Where
they differ in control flow, that difference is either genuine domain specificity — and
stays in the domain — or an unintended divergence between two copies, which is a finding
to record rather than a difference to preserve.

That second case is the one to watch. Two hand-maintained implementations of the same
concern will have drifted, and extraction forces a choice about which behavior is
correct. Making that choice silently is how a refactor becomes a behavior change.

### No copy survives the change that extracts it

The tempting incremental path is to extract into kit, move one domain, and leave the
others on their copies "for now." Rejected: it takes the implementation count from two
to three and defers the only outcome that has value.

So each extraction moves every domain that has the concern, and gives it to every domain
that does not. That is what makes an extraction independently valuable rather than
setup for a later payoff.

### Behavior preservation is the acceptance criterion, and drift is a finding

A domain's watchdog interval, timeout semantics, and chain client construction must
behave identically after. Where the two copies already disagree, the extraction records
which behavior was chosen and why, rather than quietly adopting whichever implementation
was read first.

### Implementation and drift record (2026-08-15)

The implementation uses one `kit/storefront` distribution. Its composition
object carries the exact validated contract, immutable service
build/start/stop callbacks, ordered routers and middleware, and app metadata.
The kit checks contract object identity across the app and lifespan container;
there is no module-global domain fallback.

The Alkahest copies agreed on failure isolation but differed in readiness
inputs. VM required both wallet address and private key; API credits required
only its private key. The shared factory therefore owns network/address
resolution, construction, and per-chain warning/skip control flow, while each
root contributes its own missing-requirements tuple. This preserves both
readiness policies. Bare metal contributes its environment-derived private key
and chain table to the same factory.

The watchdog copies differed in timestamp parsing, loop diagnostics, and API
credits' effective cadence: its old loop slept for a hard-coded 15 seconds
while startup reported the configured 60-second value. The shared runtime
keeps VM's tolerant timestamp parsing and per-row failure isolation. Logging
flags remain domain supplied. API credits deliberately adopts its documented
`negotiation_watchdog_interval` setting (60 seconds by default) rather than the
unreported hard-coded cadence; VM preserves its configured 60-second default,
and bare metal gains environment-supplied timeout and interval values.

## Risks / Trade-offs

- **[The two copies have drifted and extraction picks a winner silently]** → Named
  above; needs an explicit comparison recorded per concern, not a diff glanced at.
- **[Extraction introduces a kit dependency on a domain]** → Forbidden by "From-below
  kit dependencies"; check the direction rather than assume it, since the concerns being
  moved currently import freely from their domain.
- **[Bare metal gains behavior it never had]** → Intended, and the reason it is included
  rather than deferred. But it means bare metal's suites gain coverage for machinery
  it has never run, and gaps there are findings about bare metal rather than about the
  extraction.
- **[The seam proves wrong at `sync_negotiation` anyway]** → Possible. Two small
  concerns bound the cost of learning it; revisiting the seam then is cheaper than
  designing it against the hardest case first.
- **[Packaging churn breaks a wheel build]** → Kit gains modules and domain wheels lose
  them; build targets and Dockerfile refresh entries follow, and this repository has
  been bitten by stale lockfiles before.

## Migration Plan

1. Define the seam and its composition point, extending the injected-contract shape.
2. Extract `alkahest_service`; compose all three domains; remove both copies.
3. Extract `negotiation_watchdog`; same.
4. Packaging and build-target follow-through.

Rollback is a code revert per step; no persisted state or wire surface changes.

## Open Questions

- **Should the kit-owned runtime be one package or several?** One package per concern
  cluster keeps dependency edges narrow; one package for the storefront runtime keeps
  the composition root simple. Deferrable: the first two concerns do not force it, and
  the answer will be clearer after the negotiation extraction.
- **Does the VM storefront's size hide concerns worth extracting that the other domains
  never implemented?** `site_projection_cache`, `multi_registry_client`, `refund`, and
  `token_transfer` exist only in VM. Deferrable — they may be genuinely VM-specific, and
  deciding needs a second consumer to compare against.
