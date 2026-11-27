# Unify introduction custody

## Why

The contact-exchange mechanism introduces a buyer and a seller after an accepted deal, and
`kit/contact-exchange` holds the contacts it reveals. Goal 9's RFQs introduce a buyer and a
respondent after both consent, and the registry must hold those contacts too, since buyers
run no service of their own. The earlier implementation of RFQs built a second custody stack
in the registry with different protection, different retention rules and different operator
procedures. Two mechanisms for one job is duplication to remove before RFQs land.

Each had strengths the other lacked. Contact exchange redacts one-way, enforced in the
database, discloses its retention window before commitment, and gives operators a sweep they
can preview and step. The RFQ stack encrypted contacts at rest, let either participant end
access early, swept before admitting traffic after downtime, and redacted a restored backup.
This change builds one custody layer with both sets, and composes it into the storefronts.

## What Changes

- **One introduction custody layer**, a new mechanism-neutral kit,
  `kit/introduction-custody`, with its own capability. It knows nothing of settlement or
  RFQs, owns its schema and one SQLAlchemy Core store whose operations join the host's
  transaction (design D1, D10, D11, D13).
- **Contacts are encrypted at rest** with Tink AEAD keysets held outside the database, and a
  storefront refuses to start without a usable keyset (D2, D12, D19).
- **Keyed encryption is a standalone component**, `tools/keyset-aead`, published as
  `arkhai-keyset-aead` with its own capability, which custody consumes and provisioning's
  secrets can later move onto; operators edit keysets with Tinkey (D29, D30).
- **Redaction is one-way over decrypted values**: the database enforces what it can observe
  and custody the rest, and a read after redaction answers the existing deleted outcome (D3,
  D21).
- **Rotation re-encrypts** retained contacts online, through a pausable worker, and status
  shows when an old key is removable (D14).
- **Retention is one running policy** over revealed introductions, disclosed before
  commitment and at reveal as current policy; a held contact's expiry is the host's (D4, D16,
  D23).
- **Either participant may end access** for both; on the storefronts the buyer gains a signed
  end route and command (D5, D27).
- **Operators preview and step the sweep**, which also runs before a host serves
  introductions after downtime and reports overdue payloads (D6, D17, D22).
- **A restored backup can be redacted** by a mode of each host's migration command, before
  the service starts (D7, D18).
- **Contacts can be held before an introduction exists**, and promoted or discarded in the
  host's transaction, for the RFQ stage before selection (D16).
- **Contact payloads are validated once**, by one bounded validator (D8, D24).
- **Upgrading a 0.3.0 or 0.4.0 storefront redacts the contacts it held**, keeping every
  introduction as a tombstone (D15).
- **Introduction routes record no contact for exact retry**: every exact retry runs again,
  and the contacts already recorded are removed (D28).
- **Each side's delivery to its own sinks** stays as `introduction-delivery` defines it, but
  for an exact retry of a start whose completion failed, which now completes the reveal; the
  seller-side dispatch claim stays contact exchange's (D9, D20).

### Non-goals

- Composing custody into the registry: `add-buyer-compute-rfqs` does it when the registry
  first holds contacts, with the PostgreSQL dialect and the gate that proves it (D26).
- Unifying the storefront loop controller with the provisioning service's worker gates.
- Bounding replay records of routes other than the introduction routes, which stays
  `redesign-authenticated-requests`'.

## Capabilities

### New Capabilities

- `introduction-custody`: the custody of introduction contacts for any host — encryption,
  one-way redaction, retention, early end, the sweep, re-encryption, held contacts, restore
  redaction, disclosure and the payload validator.
- `keyset-aead`: the standalone keyed-encryption component — authenticated encryption under a
  Tink keyset with associated data, the key id a ciphertext names, the keysets it admits, and
  verified re-encryption.

### Modified Capabilities

- `contact-exchange-settlement`: a storefront holds its introductions in introduction
  custody; buyers may end an introduction early; introduction routes record no contact for
  exact retry; an upgraded storefront holds no plaintext contact.
- `introduction-delivery`: an exact retry of a start whose completion failed completes the
  reveal, as a new start does; the seller-side dispatch claim stays beside custody.

## Impact

- New standalone component `tools/keyset-aead`, published as `arkhai-keyset-aead`,
  depending on Tink alone.
- New kit `kit/introduction-custody`, depending on SQLAlchemy and `arkhai-keyset-aead`.
- `kit/config`: `secret_at_rest`'s docstring names the keyed component as its successor (D30).
- `kit/contact-exchange` onto custody, with a new route, client method and buyer command.
- The VM and bare-metal storefronts: a SQLAlchemy runtime dependency, a keyset in the Secret
  overlay, two storefront migrations, a new lifecycle loop, a migration-command mode, the
  credential-capable route declarations, and their charts' values schemas.
- Local stacks and lanes: a committed public development keyset in each storefront's Secret
  overlay and in the local cluster's topology script; no generating target (D19).
- Operators: keysets are generated and rotated with Tinkey (D14, D29).

## Dependencies and Related Changes

- `add-buyer-compute-rfqs` depends on it, adds the stage before selection on top of it, and
  takes the registry's composition of custody (D26).
- `redesign-authenticated-requests` owns the unbounded replay records; this change takes
  their introduction slice (D28).
- `harden-shared-relays` (deferred) owns replacing provisioning's Fernet scheme, its gap (4);
  its row records that the replacement is `arkhai-keyset-aead` and that it retires
  `market_config.secret_at_rest` (D30).

## Permanent documentation impact

- [x] The repository's architecture document
- [x] Existing subsystem specification
- [x] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

- D1: one custody layer to the new `introduction-custody` specification and companion.
- D2: encryption at rest to `introduction-custody`.
- D3: one-way redaction over decrypted values to `introduction-custody`.
- D4: retention as one running policy to `introduction-custody`.
- D5: early end by a participant to `introduction-custody`.
- D6: the sweep to `introduction-custody` and `docs/operator-handbook.md`.
- D7: restore redaction to `introduction-custody` and `docs/operator-handbook.md`.
- D8: one payload validator to `introduction-custody`.
- D9: the exact retry of a failed start to `introduction-delivery`; the rest of delivery is
  unchanged, and `introduction-delivery` already states it.
- D10: the kit and its capability to `openspec/specs/README.md`, `introduction-custody`'s
  companion, `contact-exchange-settlement`, `docs/development/ARCHITECTURE.md`, "Kit
  areas", and `docs/guidance/repository/published-packages.md`'s table of packages.
- D11: the schema in both dialects and the Core store to `introduction-custody`'s companion.
- D12: Tink, reached through the keyed-encryption component, to `introduction-custody`'s
  companion and `docs/guidance/repository/production-code.md`, "Libraries".
- D13: the record and its associated data to `introduction-custody` and its companion.
- D14: rotation by re-encryption, with keys added and promoted through Tinkey, to
  `introduction-custody`, its companion and `docs/operator-handbook.md`; the rule that an integrity guarantee over encrypted data is
  stated over its decrypted value, the database enforcing what it can observe and the
  service the rest, to `docs/guidance/engineering/persistence.md`, with a short example.
- D15: the upgrade's redaction to `contact-exchange-settlement`,
  `docs/operator-handbook.md` and `docs/development/DEPLOYMENT_AND_CONFIG.md`, "Migrations
  at startup".
- D16: held contacts to `introduction-custody`.
- D17: the pausable workers to `introduction-custody`'s companion and
  `docs/development/ARCHITECTURE.md`, "Operator lifecycle controls".
- D18: the migration-command mode to `introduction-custody`, `docs/operator-handbook.md` and
  `docs/development/DEPLOYMENT_AND_CONFIG.md`, "Migrations at startup".
- D19: the storefront's keyset and settings to `introduction-custody`'s configuration,
  `contact-exchange-settlement`'s configuration and
  `docs/development/DEPLOYMENT_AND_CONFIG.md`.
- D20: the dispatch claim beside custody to `introduction-delivery`'s architecture.
- D21: the deleted outcome to `introduction-custody`.
- D22: the startup sweep and overdue report to `introduction-custody` and
  `docs/operator-handbook.md`.
- D23: the disclosure value to `introduction-custody`.
- D24: the validator's rules to `introduction-custody`.
- D25: no permanent destination — the implementation cadence is change history.
- D26: the registry's composition with RFQs to `docs/development/ROADMAP.md`, Goal 9's open
  gaps.
- D27: early end on the storefronts to `contact-exchange-settlement`.
- D28: credential-capable introduction routes to `contact-exchange-settlement`; the rule that
  a response re-derivable from a record protected from modification is not recorded for
  exact retry to a new file in `docs/guidance/repository/`, `exact-retry-records.md`; the narrowed replay gap to
  `docs/development/ROADMAP.md`, Goal 6.
- D29: the standalone keyed-encryption component to the new `keyset-aead` specification and
  companion, `tools/README.md`, "Standalone infrastructure components",
  `docs/guidance/repository/package-layers.md`'s list of standalone components,
  `docs/guidance/repository/published-packages.md`, and `docs/operator-handbook.md` for
  rotating with Tinkey.
- D30: the superseded Fernet helper to `harden-shared-relays`' row in
  `openspec/changes/README.md` and `secret_at_rest`'s docstring.
