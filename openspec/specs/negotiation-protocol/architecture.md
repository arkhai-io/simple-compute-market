# Negotiation Protocol Architecture

The [normative contract](spec.md) defines signed round behavior. This document explains the boundary between generic protocol mechanics and domain or operator policy.

## Canonical synchronous rounds

The buyer initiates a negotiation with a body-bound request that establishes the authenticated buyer principal; the storefront supplies its configured seller principal. The buyer then drives request/response rounds. Each accepted message extends one canonical shared history, and the seller evaluates that complete history and returns its next authenticated response inline.

```text
buyer message + canonical history
        ↓ authenticate and append
seller policy over captured inputs and history
        ↓
signed response or terminal Terms
```

Synchronous response avoids a second seller-to-buyer callback authority and makes both parties agree on the history used to derive terms. Body-bound proofs authenticate the complete principal, role, operation, resource, request identity, time, and decision-bearing content. Sequence and history rules prevent either side from treating a mutated body or different branch as the accepted conversation.

## Transport and policy separation

The protocol shell owns authentication, sequencing, persistence of protocol-visible state, and terminal handling. It does not decide whether an offer is economically acceptable or reinterpret domain fields. Domain codecs validate provision intent and terms; buyer and seller policy choose openings, counters, acceptance, or refusal from stable inputs.

Policy belongs with the role that bears its consequence. Buyer policy selects among offers and payment choices. Seller policy decides whether to commit seller resources. Generic transport carries those decisions without making them universal market rules.

## Terms and payment acceptance

What will be delivered and how payment can be accepted are related but distinct. Domain provision terms describe delivery. Accepted escrow kinds, rates, and payment parameters are policy inputs and protocol carriers. Keeping them separate allows another settlement mechanism without redefining the traded resource and prevents transport code from owning token or pricing semantics.

What can settle is the listing's: policies decide only whether, and at what price, to deal within what the listing offers. An escrow proposal naming no escrow contract is refused rather than read as a negotiation carrying no escrow, by the default escrow-shape guard and again at `kit/alkahest`'s materialization chokepoint, which a seller's policy chain cannot skip; an escrow outside the listing's accepted set, or with a literal field such as the token other than its entry's, is refused there too. A VM deal selecting an Alkahest option funds the escrow the option names, so VM's seller stage refuses an unpinned escrow carrier beside a selection at acceptance but does not compare a pinned one with the option's entry: a carrier naming another contract is accepted, and the deal settles against the option's. The unpinned predicate is written twice, in `kit/policy` and `kit/alkahest`, because the mechanism-neutral policy kit may not import the Alkahest kit.

## Lossless amount boundary

Negotiation carries token and other scalar payment values in a uint256 domain, where ordinary 18-decimal amounts can exceed both JavaScript's safe-integer range and SQLite's signed 64-bit range. Python code evaluates them as arbitrary-precision non-negative integers, canonical JSON emits decimal-digit strings, and persistence stores decimal text before parsing it back to an integer. Floats, negative values, booleans, and non-digit forms are rejected rather than rounded or truncated.

Scaling human units into base units belongs to the buyer or domain adapter before negotiation. The protocol preserves the resulting integer through proposals, counters, accepted obligations, and agreed state; it does not apply floating-point pricing conversions at the transport or storage boundary.

## Negotiating a shape

A round after the first may change the capacity shape being sold, as well as the price. The revised shape is a child of `proposal`, because it is part of what the round proposes, and it reuses the opaque `ProvisionTerms` envelope rather than adding a core-level concept, so core stays schema-opaque. The domain's codec is the only component that reads it. Core's request models refuse an unknown top-level key, but that is not what guards a shape: the risk is a nested field passing through unexamined, which would let a buyer claim disk or memory the seller never priced, and core cannot judge nested content without knowing the domain. The VM codec validates the whole family-grouped shape against its capability schema, keeps the opening's duration, start, and delivery credentials, and replaces only the shape. A revision is a whole shape: an omitted family is not inherited from the listing, though round zero's flat form, which may be partial, inherits the listing's omitted dimensions once.

### Why the negotiated quantity is a multiplier

With the shape fixed, negotiating an absolute total works: each round moves one number toward or away from a bound, and who conceded is well defined. Once the shape can vary, a total stops being comparable between rounds — a buyer who asks for less memory and more disk and quotes a different total has not obviously conceded, and the bisection middleware has no axis to bisect. Two other models were rejected:

- **Negotiating the total and re-anchoring the bounds whenever the shape changes** resets the concession history on every change, so a buyer escapes an unfavourable position by perturbing the shape, and convergence need not terminate.
- **Fixing the rates and letting the buyer choose the shape** leaves nothing to negotiate: it is configure-and-quote, and discards the policy machinery.

So on a shape-priced listing the parties negotiate a multiplier over the listing's advertised rates, carried as integer basis points so the kit's integer amount hooks and the bisection middleware work unchanged. Shape and price vary independently and the multiplier stays one monotone axis. The seller's floor is one bound on it, which applies to every shape without being restated per shape — the restatement where a shape-perturbation attack would otherwise enter. The floor is at most 10,000, so the advertised rates are always a price the storefront accepts; a seller wanting more advertises higher rates, and one clearing idle capacity lowers the floor explicitly.

The quote for a shape is the selected option's advertised rate scaled by the ratio of the requested shape's composed price to the advertised shape's, both evaluated in the option's asset. Scaling the option's already materialized rate reuses its base-unit scale, so the quote needs no token metadata read and infers no decimal precision; the family rates set only the ratio. The ratio, duration, and multiplier are applied in exact arithmetic and the product is rounded up once, so a quote never falls below what the multiplier promises the seller, and a quote too large for uint256 is refused rather than truncated. Both parties derive the quote from the published rates and the round's shape and multiplier; it is not carried on the wire. A flat-priced listing has a rate for its own shape only, so it cannot price another and is shape-fixed by construction.

Because the scalar is a multiplier on one listing and an amount on another, it is never stored or sent under a name that reads as money: the storefront records it as `negotiated_scalar`, and only the derived payment reaches the Agreement, its mandate, and settlement. The buyer's public price surface stays monetary; its amount codec converts the bounds against the shape it opens with and refuses an acceptance whose payment exceeds its ceiling, which keeps overspend impossible once the seller's advertised-shape cap lifts.

### The rates a negotiation is held to

The seller prices and pins a negotiation from its most recent successful registry publication, not from its stored listing record, because that publication is what the buyer read. A failed republication therefore changes nothing a negotiation reads. The pin is a digest of the whole rate structure, so any change to any family's or asset's rates refuses every open thread on the listing, including threads the change does not affect. A narrower pin would need per-thread price derivation at every check; the over-refusal is accepted while sellers rarely reprice live listings. Honouring the old rates instead would bind the seller to rates it withdrew, and repricing a live thread explicitly would change the wire.

Registries whose last accepted rates differ, or a registry holding the listing with no retained payload while another's is known, refuse until they converge, because a buyer at one could otherwise be quoted from rates another serves. A buyer cannot yet name the publication it read, which would let a matching thread continue through a divergence. Exit is never refused, so withdrawn or unpriceable rates never trap a buyer in a thread.

### Evaluation order

For a round carrying a shape, the VM seller resolves the shape's policy, checks admissibility, checks feasibility, applies its commercial guard — GPU model and region compared by equality — and only then prices. Each refusal is distinct because each leads the buyer somewhere different: change the ask, retry later, or take the seller's counter. Authoritative feasibility is not composed: the listing-source confirmation concerns only the advertised shape, so until a non-consuming probe of the site is composed, the seller refuses any quantity above the advertised shape. A smaller shape fits wherever the advertised one does; negotiating a larger one needs the probe. Round zero is evaluated by the same composition, so a first-round shape differing from the listing is a proposal, not a defect.

### Current limits

- Requested shapes are capped at the advertised quantities until the feasibility probe is composed.
- The selected settlement option's rate, which the quote scales, and the `pinned_option_withdrawn` refusal still read the stored listing, which a failed republication can leave ahead of what was last published.
- A multi-registry seller whose registries diverge refuses every thread on the listing until the targeted resend repairs them.

## Persistence, continuation, and recovery

The persisted negotiation subject retains its stable negotiation identity, exact buyer and seller principals, authored message history, terminal state, agreed value, and accepted artifacts. A continuation loads that state rather than reconstructing ownership from a request body. Recovery may resume the same nonterminal thread only with the recorded buyer principal or a replacement authorized by a completed rotation, and it does not replay prior policy decisions or change the parties in already accepted Terms.

Persistence supports documented inspection and continuation, but it does not establish universal exactly-once behavior or guarantee that every request interrupted in flight can resume after process restart. Callers reconcile against the durable thread; no recovery path may silently create a second owner, rewrite an author, or infer success that is absent from stored state.

## Principal-bound history

The opening proof, not the request's buyer field, establishes the buyer that owns the thread. The storefront's configured marketplace principal establishes the seller. Negotiation persists both as complete `{scheme, identifier}` values, and accepted Terms and settlement plans copy those exact parties. Matching identifier text under another scheme, an address-like body value, provider identifier, or unsigned query value has no authorization meaning.

Every protocol-visible message records the complete principal and explicit role of the authenticated actor. Buyer messages are authored by the authorized buyer, seller responses by the seller, and administrator-driven advances or force-accepts by the exact authenticated administrator. An administrator action can change negotiation state but does not make the administrator the buyer or seller and does not rewrite the accepted parties.

The principal credential remains distinct from the durable negotiation subject. A completed two-proof rotation can authorize a replacement principal to continue the same thread; an unrelated valid signer cannot append, terminate, or derive Terms from it.

A supported database already holds canonical parties and authors: the conversion of address-shaped values is part of the service's v0.3.0 floor, and a database from before it is refused as unsupported ([deployment state](../deployment-state/architecture.md#transactional-identity-cutover)). A nonterminal thread recovered after a restart continues from its stored canonical history without replaying policy decisions, and only its recorded buyer or a replacement principal bound by a completed rotation may continue it.

## Record-bound domain dispatch

The negotiation shell never chooses a domain from an opening payload. It loads
the authoritative listing binding, resolves its exact registered contract,
treats caller discriminators as consistency assertions, validates the
versioned provision envelope, and transactionally copies the binding into the
new thread before seller policy runs. Continuation and accepted Terms resolve
only from that thread binding, so a later publication/configuration change
cannot cross-switch an in-flight negotiation.

## Related contracts

- [Marketplace identity](../marketplace-identity/spec.md)
- [Market composition](../market-composition/spec.md)
- [Buyer orchestration](../buyer-orchestration/spec.md)
- [Storefront publication](../storefront-publication/spec.md)
- [Settlement servicing](../settlement-servicing/spec.md)
