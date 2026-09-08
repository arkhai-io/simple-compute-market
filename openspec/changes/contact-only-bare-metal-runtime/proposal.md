# Contact-only bare-metal runtime

## Scope

Run the existing bare-metal seller with only `contact-exchange.v1`, using its
ordinary environment factory and signed HTTP protocol. Persist listings without
claiming a site, pool, or physical resource authority. Preserve physical flows.
The second stage adds opt-in file publication and chart wiring. Registry runtime,
financial mechanisms, delivery sinks, and provisioning implementations stay unchanged.

## Proposed acceptance

An operator can start a wallet-free Ed25519 seller with no site configuration.
Health reports physical capabilities as not applicable, not healthy. A buyer can
negotiate a contact option, explicitly submit contact-sharing input, and reread
the protected durable reveal after restart. Acceptance alone persists no contact.
Unbacked listings and runtime admission refuse physical or financial selections.
Existing site-backed rows and negotiations survive the versioned migration.

The publication acceptance adds five explicit synthetic offers, signed registry
upserts behind independent API-key and identity gates, local immutable intent
before remote writes, and restart/lost-acknowledgement convergence. No edit or
omission of an input file may rewrite accepted artifacts or reopen closed offers.

## Permanent documentation impact

- [x] `openspec/specs/contact-exchange-settlement/spec.md` and companion:
  introduction-only startup/admission, pending acceptance, explicit capture,
  party reads, and literal privacy protection.
- [x] `openspec/specs/market-composition/spec.md` and companion:
  unbacked immutable bindings and shared accepted-plan/bookkeeping transaction.
- [x] `openspec/specs/buyer-orchestration/spec.md` and companion:
  explicit amountless negotiation with exact advertised semantics.
- [x] `openspec/specs/storefront-publication/spec.md` and companion:
  whole-file validation, stable local intent, signed retry and restart lifecycle.
- [x] `docs/development/ARCHITECTURE.md`: capacity applicability and separation
  of acceptance, capture, and optional recipient delivery.
- [x] `docs/development/DEPLOYMENT_AND_CONFIG.md`: actual environment/chart inputs.
- [x] Roadmap, campaign index, and capability index currency; exact destinations
  are recorded in [design.md](design.md#design-promotion-record).

General contact runtime can use optional recipient delivery; the synthetic file
publisher requires none. Whole-file validation precedes listing intent and remote
mutations, not runtime database initialization or signed schema reads. These are
source boundaries, not broader claims of no persistence or registry calls.

Local fixtures do not establish release/image provenance, deployment activation,
physical delivery, encrypted storage, or end-to-end browser success. Those
qualification boundaries remain open in [tasks.md](tasks.md).
