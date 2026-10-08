# Design

## Context

Recorded 2026-09-21 from `unify-host-identity`'s design review. Re-verify before
planning.

### What counts as an accepted artifact

Anything whose exact content another party relies on:

| Artifact | Why it is fixed | Example |
|---|---|---|
| Signed negotiation messages and terms | Counterparty signature | Bare-metal `BareMetalTerms` (`bare_metal.v1`) |
| Accepted settlement plans | Feed `obligation_ref`, shared with mechanism authorities | Bare-metal service terms keyed by `bare_metal.v1` |
| Digest-pinned bodies | Content-addressed | `accepted_binding_digest`, `public_result_digest`, `portable_evidence_digest` |
| Derived identities | Held by another service for idempotency | Bare-metal fulfillment identity |

Derived, unsigned state — published listings, site bindings, lifecycle columns,
registry rows a storefront republishes — is not an accepted artifact and migrates
normally.

### The verification defect

`BareMetalHostedLifecycle._validate_lifecycle` compares each stored digest with
`self.accepted_binding.binding_digest`, which is `bare_metal_digest(self)`:
`model_dump(mode="json", exclude_none=True)` of the freshly parsed model, canonically
serialized and hashed. A stored record therefore verifies only while the model still
serializes it identically. Adding a field with a non-`None` default, renaming one, or
changing a serializer changes the recomputed digest of untampered data.
`BareMetalLeaseReadyEvidence` repeats the pattern for its embedded result. No other
domain was found doing this (search 2026-09-21).

### Precedent

Hosted-fiat card-only accepted rows remain decodable for status, fulfillment, and
reclaim under their original identities while new publication accepts only current
profiles (`settlement-servicing`). That is rules 1, 3, and 5 for one mechanism,
without rule 4's measured retirement.

## Decisions (proposed)

### Store canonical bytes; verify over them

Persist each accepted artifact's canonical bytes exactly as accepted, alongside any
parsed columns. Verification hashes or checks the signature over those bytes. Parsing
into the current model is a separate step that may use a retained decoder. This
decouples "is this what was accepted" from "can today's code read it".

### Retained decoders convert to the current model

A retired kind's decoder is read-only and returns the current in-memory model, so no
code path downstream of decoding branches on version. Producing a retired kind is
refused at construction.

### Retirement is measured, not scheduled

Each retained decoder has a count of non-terminal records referencing its kind,
exposed by the owning service. Removing the decoder is a code change gated on that
count being zero on every deployment the operator tracks. There is no fleet-wide
deployment signal in this repository (see `pools-9`'s note), so the count is evidence
an operator supplies at removal time, not an automated gate.

## Open Questions

- **Shared kit machinery or per-domain?** A decoder registry keyed by `kind` could
  live in a foundation kit, or each domain could own a small dispatch. Decide during
  design, after inventorying every accepted artifact across VM, bare metal, API
  credits, and introductions.
- **Does `kit/negotiation-runtime` already store transcript bytes?** If its durable
  transcript is canonical bytes, rule 2 may already hold for negotiation messages and
  only domain-owned records need the change.
- **Buyer side.** Buyer run logs recover accepted deals and decode domain artifacts;
  they need the same retained decoders. Confirm the buyer plugin boundary can carry
  them.
- **Where the live count is exposed.** A system endpoint per service, a migration-tool
  report, or both.
