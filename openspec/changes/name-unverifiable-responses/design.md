## Context

Every authenticated buyer call funnels through one reader in `core_buyer`. It
takes the response headers, builds an `AuthenticatedResponse` out of them, and
verifies that record against the expected principals. When the headers are not
there — because the answer was a `404`, a `403`, a gateway page, or a route that
never signed — model validation fails and the reader raises "returned malformed
or legacy response authentication".

That is one sentence for two very different situations: an authority that signed
badly, and an answer that was never an acknowledgement at all. The first is a
protocol fault; the second is usually a routing, identity, or authorization
problem several layers away. Reporting them identically means the reader is
accurate about its own expectations and silent about the world.

## Goals / Non-Goals

**Goals.** A refusal names the status it refused and whether the response was
authenticated at all. A development run of the hosted lane gets past buyer
status polling, or learns precisely why not. The private registry the harness
configures is one the harness can actually talk to.

**Non-Goals.** Accepting anything. Every response refused today is still
refused, on the same conditions, in the same place. This change also does not
qualify a lane; that needs a protected run.

## Decisions

### The status is not the body

The redaction here protects a response body that can carry provider detail,
buyer actions, and identifiers. An HTTP status is none of those: it is the
answer's own classification, chosen by whatever answered, and it is already
visible to anything watching the connection. Reporting it costs nothing and is
the single most useful fact about a refusal.

Whether authentication headers were present at all is the second fact, and it is
what separates "the authority signed badly" from "this was never an
acknowledgement". Header *values* stay out: a signature or identifier in a log
is a fingerprint of the exchange.

### The harness authenticates to the registry it locked

`registry-b` is configured by the harness to require read and write API keys,
seeded from a bootstrap key the harness generates. Neither the storefront's
secrets file nor the buyer's configuration ever received it, so the storefront's
publications to it answer `401` and the buyer cannot discover through it. The
harness generated the key and configured the requirement; it supplies the
authorization too, in the same private material it already writes.

This is the same class as the storefront caller allowlist: a topology the
harness builds and then does not tell its own participants about.

## Risks / Trade-offs

A status in a message is one more thing an operator might paste somewhere. It is
already in every proxy log and carries no secret, so this is a small increase in
surface for a large increase in diagnosability.

The refusal the lane names next may be a marketplace defect, a configuration
gap, or another harness omission. The task sequence does not assume which.

## Migration Plan

None. No stored data, wire format, or configuration schema changes; a client
that refuses today refuses tomorrow, with a longer sentence.

## Open Questions

Whether buyer status polling fails because the storefront answered without
authentication, or because it answered an error, is exactly what this change is
built to find out.
