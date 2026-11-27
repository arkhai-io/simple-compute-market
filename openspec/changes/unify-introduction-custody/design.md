# Design: unify-introduction-custody

## Context

`kit/contact-exchange` holds a contact-exchange deal's introduction in a storefront's SQLite
database: both contacts persist when the buyer starts the introduction, and never before. A
trigger admits no update to a revealed row but one-way redaction, which leaves a tombstone
with its deletion time. A sweep, which an operator can preview and step, redacts
introductions older than the retention window, read from the running configuration; the
window is disclosed before commitment and at reveal. Contacts are stored unencrypted. Payload
bounds are 16 entries, 64-character keys and 512-character values
(`validate_contact_payload`). Delivery to each side's sinks is `introduction-delivery`'s.

The earlier RFQ implementation on `feat/buyer-compute-rfqs` (pull request #401) held RFQ
contacts in the registry with its own stack: AES-256-GCM with associated data and a keyring
mounted from a Secret, a rotation command, deletion in the transaction that ends eligibility,
a cutoff fixed per introduction at completion, early end by either participant, a five-minute
sweep with a one-hour target and a sweep before admitting traffic, and a restore-redaction
mode. It redefined contact exchange's payload bounds.

The review of that pull request on 2026-11-27 found the duplication and settled the
decisions below. It also found, against the RFQ stack's code, faults the shared layer must not
carry forward: the keyring and rotation are generic infrastructure built inside a market
package; the sweep's timer is replaced in tests by patching a class attribute, and its pause
and step are reachable only in process; a partly configured registry starts with contacts
silently unavailable instead of refusing to start; and the restore-redaction setting is
documented as Secret configuration though it is not secret. The full findings are recorded on
the pull request.

## Decisions

Settled with the owner in the review of 2026-11-27.

### D1 — One custody layer for every introduction

One layer holds introduction contacts for every host that makes introductions: the
storefronts' contact-exchange settlement and the registry's RFQs. It holds the introduction
record, its two contacts, their redaction, retention, early end, sweep, restore redaction and
the delivery event, and knows nothing of settlement or RFQs. Contact-exchange settlement keeps
its Agreement and obligation checks and its per-origin seller contact above it;
`add-buyer-compute-rfqs` adds the stage before selection above it.

### D2 — Contacts are encrypted at rest everywhere

Every host encrypts contacts with authenticated encryption, with the key held outside the
database and rotatable without losing retained payloads. Storefronts hold the same kind of
data with the same exposure as the registry, so they get the same protection.

### D3 — One-way redaction, enforced by the database

Contact exchange's redaction carries over: a revealed introduction changes at most once, by
redaction, enforced in persistence rather than by callers; redaction is idempotent; a read
after it answers a stable deleted outcome with the deletion time.

### D4 — Retention is one running policy

The retention window is an aggregate policy read from the running configuration, never fixed
per introduction: a shortened window applies to introductions already held, and configuring a
finite window is the operator's consent to delete past it. It is disclosed before commitment
and at reveal, as current policy rather than a promise. The layer allows an `indefinite`
window; a host may refuse it by its own policy, as the registry does.

Rejected: a cutoff fixed at completion, which the RFQ stack used. It exempts exactly the
introductions an operator shortening the policy most needs to remove.

### D5 — Either participant may end access

Either participant may end an introduction's contact access, for both, redacting it in the
same transaction.

### D6 — The sweep

The sweep is a lifecycle loop an operator can pause, preview and step, which redacts oldest
first in bounded batches. It also runs before a host admits introduction traffic after
downtime, and reports the age of overdue payloads.

### D7 — Restore redaction

An operator restoring a backup that predates later redactions can redact every contact whose
current eligibility cannot be established, before reads reopen.

### D8 — One payload validator

Contact payloads are bounded by one validator, used at every ingress.

### D9 — Delivery is unchanged

Each side delivers to its own configured sinks as `introduction-delivery` defines. An RFQ
participant's buyer CLI delivers from its own process after a read; the registry delivers
nothing.

## Open Questions

### Q1 — The encryption component

The engineering guidance prefers an existing library to building one, and puts generic
infrastructure built here in a standalone component, never in a market package. Which library
(for example Tink keysets with an AEAD primitive), or which standalone component, provides
encryption and key rotation is open.

### Q2 — Where the layer lives

Whether `kit/contact-exchange` becomes the layer or the layer is a kit beneath it, and how its
persistence is injected so that a storefront's SQLite store and the registry's
SQLAlchemy store on SQLite and PostgreSQL both host it.

### Q3 — The upgrade from marketplace 0.4.0

Storefronts of 0.4.0 hold unencrypted contacts. Whether an upgrade encrypts them in place or
redacts them, and what an operator does.

### Q4 — Operator controls

The authenticated controls a host exposes for pause, preview, step, deletion of one
introduction, key rotation and restore redaction, and how a host refuses to start when its
key is missing.

### Q5 — Disclosure on the registry

Where the registry discloses its window before a respondent commits a contact.

### Q6 — What the stage before selection needs

The primitives `add-buyer-compute-rfqs` needs to hold a respondent's contact before selection
and delete or promote it transactionally.

## Verification

Integration tests run each host's composition of the layer: encryption with key rotation,
redaction under concurrent reads, window changes, early end, the sweep's preview and step, the
startup sweep after downtime, restore redaction, and the 0.4.0 upgrade. The contact-exchange
lane scenarios keep passing.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| D1–D9 | `openspec/specs/contact-exchange-settlement/spec.md`, `architecture.md` and `configuration.md` |
| D2, D6, D7 | `docs/operator-handbook.md`; `docs/development/DEPLOYMENT_AND_CONFIG.md` |
| D1 | `docs/development/ARCHITECTURE.md` |
| Goal 9 | `docs/development/ROADMAP.md`, Goal 9 |
