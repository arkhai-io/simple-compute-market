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

## Lossless amount boundary

Negotiation carries token and other scalar payment values in a uint256 domain, where ordinary 18-decimal amounts can exceed both JavaScript's safe-integer range and SQLite's signed 64-bit range. Python code evaluates them as arbitrary-precision non-negative integers, canonical JSON emits decimal-digit strings, and persistence stores decimal text before parsing it back to an integer. Floats, negative values, booleans, and non-digit forms are rejected rather than rounded or truncated.

Scaling human units into base units belongs to the buyer or domain adapter before negotiation. The protocol preserves the resulting integer through proposals, counters, accepted obligations, and agreed state; it does not apply floating-point pricing conversions at the transport or storage boundary.

## Persistence, continuation, and recovery

The persisted negotiation subject retains its stable negotiation identity, exact buyer and seller principals, authored message history, terminal state, agreed value, and accepted artifacts. A continuation loads that state rather than reconstructing ownership from a request body. Recovery may resume the same nonterminal thread only with the recorded buyer principal or a replacement authorized by a completed rotation, and it does not replay prior policy decisions or change the parties in already accepted Terms.

Persistence supports documented inspection and continuation, but it does not establish universal exactly-once behavior or guarantee that every request interrupted in flight can resume after process restart. Callers reconcile against the durable thread; no recovery path may silently create a second owner, rewrite an author, or infer success that is absent from stored state.

## Principal-bound history

The opening proof, not the request's buyer field, establishes the buyer that owns the thread. The storefront's configured marketplace principal establishes the seller. Negotiation persists both as complete `{scheme, identifier}` values, and accepted Terms and settlement plans copy those exact parties. Matching identifier text under another scheme, an address-like body value, provider identifier, or unsigned query value has no authorization meaning.

Every protocol-visible message records the complete principal and explicit role of the authenticated actor. Buyer messages are authored by the authorized buyer, seller responses by the seller, and administrator-driven advances or force-accepts by the exact authenticated administrator. An administrator action can change negotiation state but does not make the administrator the buyer or seller and does not rewrite the accepted parties.

The principal credential remains distinct from the durable negotiation subject. A completed two-proof rotation can authorize a replacement principal to continue the same thread; an unrelated valid signer cannot append, terminate, or derive Terms from it.

The service-local schema migration validates the complete identity-bearing population before converting address-shaped parties and message authors to canonical `eip191` principals. It preserves negotiation, message, listing, option, settlement-plan, and operation identities in one transaction. Malformed values, checksum or representation conflicts, incomplete party sets, and ambiguous ownership abort the transaction rather than leaving a mixed authorization boundary. A migrated nonterminal thread continues from its stored canonical history without replaying policy decisions.

## Related contracts

- [Marketplace identity](../marketplace-identity/spec.md)
- [Market composition](../market-composition/spec.md)
- [Buyer orchestration](../buyer-orchestration/spec.md)
- [Storefront publication](../storefront-publication/spec.md)
- [Settlement servicing](../settlement-servicing/spec.md)
