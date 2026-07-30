# Negotiation Protocol Architecture

The [normative contract](spec.md) defines signed round behavior. This document explains the boundary between generic protocol mechanics and domain or operator policy.

## Canonical synchronous rounds

The buyer initiates a negotiation and drives request/response rounds. Each accepted message extends one canonical shared history; the seller evaluates that complete history and returns its next signed response inline.

```text
buyer message + canonical history
        ↓ authenticate and append
seller policy over captured inputs and history
        ↓
signed response or terminal Terms
```

Synchronous response avoids a second seller-to-buyer callback authority and makes both parties agree on the history used to derive terms. Signatures authenticate authorship; sequence and history rules prevent either side from treating a different branch as the accepted conversation.

## Transport and policy separation

The protocol shell owns authentication, sequencing, persistence of protocol-visible state, and terminal handling. It does not decide whether an offer is economically acceptable or reinterpret domain fields. Domain codecs validate provision intent and terms; buyer and seller policy choose openings, counters, acceptance, or refusal from stable inputs.

Policy belongs with the role that bears its consequence. Buyer policy selects among offers and payment choices. Seller policy decides whether to commit seller resources. Generic transport carries those decisions without making them universal market rules.

## Terms and payment acceptance

What will be delivered and how payment can be accepted are related but distinct. Domain provision terms describe delivery. Accepted escrow kinds, rates, and payment parameters are policy inputs and protocol carriers. Keeping them separate allows another settlement mechanism without redefining the traded resource and prevents transport code from owning token or pricing semantics.

## Persistence and continuation

Persisted negotiation threads support documented inspection and continuation. They do not establish universal exactly-once behavior or guarantee that every in-flight failure can resume after process restart. Recovery semantics become normative only where the owning contract and evidence establish them.

## Related contracts

- [Market composition](../market-composition/spec.md)
- [Buyer orchestration](../buyer-orchestration/spec.md)
- [Storefront publication](../storefront-publication/spec.md)
- [Settlement servicing](../settlement-servicing/spec.md)
