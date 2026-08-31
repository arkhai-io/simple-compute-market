# Design

## Context

Verified 2026-08-15 against `7155d014`. The composition pattern to copy is
`fiat.stripe.v1`: a kit-side `create_stripe_registration()` factory returning a
`MechanismRegistration`, a mechanism client implementing the
`materialize / get_status / check / collect / reclaim_expired` port, an option
builder returning `settlement_options`, and per-domain composition-root registration
plus `[Settlement.<key>]` config. The registry `listing_shape` accepts option-only
listings (`anyOf` over `accepted_escrows` / `settlement_options`), and
`SettlementOption` permits `rates: []`. Accepted plans, `service_terms` included, are
durably persisted at acceptance via the kit persistence hook. The hosted transient
"action" is the closest reveal analog: returned only in authenticated start/status
responses, deliberately never persisted beyond `{kind, expires_at_unix}` — the right
transport shape, the wrong durability for an introduction. Per-round free text is
still unpersisted seller-side, and the discovery filters still fail closed on missing
fields.

## Goals / Non-Goals

**Goals:** a deal that completes by durable, authenticated contact reveal; the agreed
context served with the reveal; loose listings that remain discoverable; zero new
per-domain mechanism arms (relies on the completed registration seam).

**Non-Goals:** vetting, reputation, post-reveal messaging, payment fallback,
automated bargaining.

## Decisions

### One non-financial obligation, not a zero-obligation plan

The earlier draft modeled the introduction as a plan with zero obligations. The
settlement runtime registers and services plans per obligation, so the introduction
is instead one obligation under `contact-exchange.v1` — payer and claimant are the two
parties, amount absent — whose mechanism client materializes ready
immediately. This fits `register_plan`, operation identity, and status reporting with
no runtime changes; only the servicing spec's assumption that an obligation is
financial needs the small delta this change carries.

One refinement discovered at the buyer boundary: the obligation keeps the
advertised option's nominal ``asset`` (``"introduction"``) and binds both party
principals into its params, exactly as the hosted mechanism does. The buyer
validates an accepted obligation strictly against the advertised option (asset
and params comparison); a fully assetless obligation would force that
comparison to weaken, whereas a nominal deliverable tag keeps it strict. The
*amount* stays absent — the deal's value does not reduce to a number — and the
servicing runtime tolerates full absence regardless (characterized).

### Non-provisioning deals ride the same message envelope

The bare-metal provision envelope gains ``access_method: "none"`` with no SSH
key, instead of a second message kind: an introduction deal still states the
brokered duration, but requests no machine access. Every provisioning path
re-requires SSH credentials at its own admission arm, so physical deals are
exactly as strict as before.

### The reveal is the receipt

The deal lifecycle is agreed → revealed, terminal. The claim completes when the
reveal is *available* to both parties, not when it is read: a party that never
fetches its introduction still has a completed deal. There is nothing to converge,
heartbeat, or reclaim.

### Reveal reuses the hosted route shape with inverted durability

The introductions route family mirrors the hosted settlement routes — signed start
and read keyed by the negotiation and obligation ref, authorization delegated to the
domain through callbacks — but where the hosted action is transient by design, the
contact payload is persisted and the read is idempotent: an introduction that could
be lost to a missed poll would not be an introduction. Mounted as its own family
(`/api/v1/introductions`), not overloaded onto either existing settle surface.

### The canonical ID is `contact-exchange.v1`

The registry's mechanism-ID grammar (`[a-z][a-z0-9.-]*\.vN`, enforced at
registration) forbids underscores, so the earlier `contact_exchange.v1` spelling
could never register. Hyphenated `contact-exchange.v1` is used everywhere: the
mechanism ID, the `service_terms` namespace key, and discovery projections.

### The seller payload binds at the first introduction operation

The draft bound the seller's contact from configuration "at acceptance". The
implementation binds it at introduction start instead: acceptance stays
payload-free by construction — the accepted plan carries only the public
introduction package — and a deal whose introduction is never started persists
no contact data at all, which is the better PII posture. Both payloads persist
atomically at start, so "available to both parties" remains the terminal
condition. Acceptance-as-consent stands: accept = deal, and the reveal needs no
second confirmation.

### Contact is held then revealed, never published

Options and listings carry prose terms and a channel descriptor only — the registry
is public and scrapable, and a contact-bearing listing is a spam directory. The
buyer's payload arrives in the signed introduction start (the slot analogous to the
hosted `funding_authorization_ref`); the seller's is bound from configuration at
acceptance. Both persist beside the obligation record and are revealed only to the
authenticated counterparty. Payloads are opaque bounded dicts; which channels people
trade is exactly the thing that cannot be parametrized.

### Freeform terms are prose in option params, never a rate

The mechanism declares no negotiation scalar. Price, if the seller states one, is
prose inside the option params; the agreed amount is *absent*, not zero, and ordering
treats the listing as priceless. Encoding exotic contracts as rates was considered
and rejected — the scalar machinery exists for mechanisms that want it, and this
mechanism's premise is that its terms do not reduce to one number.

### Loose listings are a registry profile, not a schema exception

An introduction market ships its own filter-spec: option-only requirements, a
minimal filter set, missing-tolerant matching, so sparse entries stay discoverable
despite the fail-closed default. Domains composing this mechanism carry an explicit
open metadata bag on the listing model rather than relying on undeclared extra keys,
which the current models silently strip.

## Risks / Trade-offs

- **[Contact scraping and spam]** → Reveal is post-acceptance and authenticated;
  rounds are signed; listings carry no contact. The cost of an address is a completed
  negotiation under a signing identity.
- **[PII retention]** → Contact payloads are deliberate PII persistence. Bound the
  size, record the retention posture in the capability spec, and treat deletion as
  part of the deal lifecycle rather than an afterthought.
- **[Disintermediation]** → Accepted by design; there is no custody to protect.
- **[Prerequisite slippage]** → The two `finish-settlement-mechanism-neutrality`
  items this change needs (declinable scalar, `service_terms` acceptance fix) are
  small and independent of that change's larger convergence work; if sequencing
  demands, they can land first as their own sections.

## Migration Plan

Purely additive: a new mechanism kit, the introductions route family, contact-payload
persistence, composition-root registration, a filter-spec profile. No existing deal
shape changes. Rollback is removal of the composition.

## Open Questions

- Is negotiation acceptance sufficient consent to reveal, or does reveal require a
  second explicit confirmation from each side? Acceptance-as-consent matches
  "accept = deal"; double-opt-in protects a seller whose accept was policy-driven.
- The retention and deletion window for contact payloads after reveal.
- Whether the buyer's payload must accompany the introduction start, or may be
  supplied at first read — the latter weakens "available to both" as the terminal
  condition.
