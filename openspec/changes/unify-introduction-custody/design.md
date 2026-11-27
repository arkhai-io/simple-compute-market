# Design: unify-introduction-custody

## Context

`kit/contact-exchange` holds a contact-exchange deal's introduction in a storefront's SQLite
database: both contacts persist when the buyer starts the introduction, and never before. A
trigger admits no update to a revealed row but one-way redaction, which leaves a tombstone
with its deletion time. A sweep, which an operator can preview and step, redacts
introductions older than the retention window, read from the running configuration; the
window is disclosed before commitment and at reveal. Contacts are stored unencrypted, and
every reveal and read is also recorded in full in the storefront's replay records for exact
retry, which nothing bounds. Payload bounds are 16 entries, 64-character keys and
512-character values (`validate_contact_payload`). The kit owns its tables, triggers and
store (`migrations.py`, `store.py`); the storefronts inject only their accepted-state reads
and pass a database path. Delivery to each side's sinks is `introduction-delivery`'s, and
the seller-side dispatch is claimed at most once in `contact_introduction_seller_dispatches`.

The earlier RFQ implementation on `feat/buyer-compute-rfqs` (pull request #401) held RFQ
contacts in the registry with its own stack: AES-256-GCM with associated data and a keyring
mounted from a Secret, an offline rotation command, deletion in the transaction that ends
eligibility, a cutoff fixed per introduction at completion and bound into the associated
data, early end by either participant, a five-minute sweep with a one-hour target, a sweep
before admitting traffic, and a restore-redaction setting. It duplicated contact exchange's
payload bounds in `market_core.rfq.RfqContact`.

The review of that pull request on 2026-11-27 found the duplication and settled D1–D9. It
also found faults the shared layer must not carry forward: the keyring and rotation are
generic infrastructure built inside a market package; the sweep's timer is replaced in tests
by patching a class attribute, and its pause and step are reachable only in process; a
registry with no key file starts with contacts silently unavailable instead of refusing to
start; and the restore-redaction setting is documented as Secret configuration though it is
not secret.

Three facts of the current system shape what follows. The registry (`arkhai-core-registry`)
is a composition whose scope is empty, so the scope rule of
`docs/guidance/repository/package-layers.md` forbids it the contact-exchange mechanism kit.
The storefront chains run `market_schema_migrations` over `sqlite3`, while the registry's
chain is Alembic over SQLAlchemy on SQLite and PostgreSQL. And the newest release tag is
`marketplace-v0.4.0`, with the storefront chains' floor at marketplace 0.3.0, whose
storefronts already held the unencrypted table; the RFQ forms were never in a tagged
release.

## Decisions

D1–D9 were settled in the review of pull request #401 on 2026-11-27, and D10–D28 in this
change's design discussion.

### D1 — One custody layer for every introduction

One layer, introduction custody, holds introduction contacts for every host that makes
introductions: the storefronts' contact-exchange settlement now, and the registry's RFQs
when `add-buyer-compute-rfqs` composes it (D26). It holds the introduction record, its two
contacts, their encryption, redaction, retention, early end, the sweep, re-encryption,
contacts held before an introduction exists, restore redaction, the disclosure value and the
payload validator. It holds no delivery state (D20) and knows nothing of settlement or RFQs.
Contact-exchange settlement keeps its Agreement and obligation checks, its per-origin seller
contact and its seller-side dispatch claim above it; `add-buyer-compute-rfqs` adds the stage
before selection above it.

### D2 — Contacts are encrypted at rest

Every host encrypts contacts with authenticated encryption, with the key held outside the
database and rotatable without losing retained payloads (D12, D14, D19). Storefronts hold
the same kind of data with the same exposure as the registry, so they get the same
protection. No plaintext copy of a revealed contact stays beside the encrypted one: the
replay records hold none (D28), and an upgraded storefront holds none (D15).

### D3 — One-way redaction

A revealed introduction's contacts, decrypted, change at most once, by an irreversible
redaction; redaction is idempotent and atomic, and a read after it answers a stable deleted
outcome with the deletion time. What the guarantee protects is the decrypted value, so a
re-encryption of the same contact under another key (D14) is not a change. The database
enforces every part it can observe (D11); custody's service code enforces the part it cannot,
that a re-encrypted or promoted contact decrypts to the same value.

### D4 — Retention is one running policy

The retention window is an aggregate policy read from the host's running configuration,
never fixed per introduction: a shortened window applies to introductions already held, and
configuring a finite window is the operator's consent to delete past it. It is disclosed
before commitment and at reveal, as current policy rather than a promise (D23). Custody
allows an `indefinite` window; a host may refuse it by its own policy, as the registry will.

Rejected: a cutoff fixed at completion, which the RFQ stack used and bound into its
associated data. It exempts exactly the introductions an operator shortening the policy most
needs to remove.

### D5 — Either participant may end access

Either participant may end an introduction's contact access, for both, redacting it in the
same transaction through the one deletion operation that the sweep, an operator's deletion
and restore redaction also use. On the storefronts it is D27.

### D6 — The sweep

The sweep is a lifecycle worker an operator can pause, preview and step, which redacts
oldest first in bounded batches. It also runs before a host serves introductions after
downtime, and reports the age of overdue payloads (D17, D22).

### D7 — Restore redaction

An operator restoring a backup that predates later redactions can redact every contact whose
current eligibility cannot be established, before reads reopen (D18).

### D8 — One payload validator

Contact payloads are bounded by one validator, used at every ingress (D24).

### D9 — Delivery is unchanged

Each side delivers to its own configured sinks as `introduction-delivery` defines. An RFQ
participant's buyer CLI will deliver from its own process after a read; the registry
delivers nothing.

### D10 — A mechanism-neutral kit and its own capability

Custody is a new kit, `kit/introduction-custody`: kit layer, empty scope, foundation area,
with a package allowlist. Its requirements are a new capability, `introduction-custody`,
stated for any host. `contact-exchange-settlement` keeps settlement by introduction, and its
custody requirements reduce to the storefront holding its introductions in custody. Each
requirement sits with the party that enforces it, and `buyer-compute-rfqs` will cite custody
without citing a settlement mechanism.

Rejected:

- `kit/contact-exchange` as the layer. Its scope holds `contact-exchange.v1`, and the
  registry's scope is empty, so the scope rule forbids the edge, and no exception row may
  add an edge of that shape.
- The new kit with its requirements kept in `contact-exchange-settlement`. A settlement
  capability would be the authority over a registry that settles nothing; the layering
  allowed it, ownership did not.
- Keeping a registry stack of its own, which D1 removes.

### D11 — Custody owns its schema in both dialects and one store

Custody owns its tables as DDL for SQLite and PostgreSQL, including the one-way trigger in
each dialect (a `BEFORE UPDATE` trigger on SQLite, a PL/pgSQL trigger function on
PostgreSQL), and one store written in SQLAlchemy Core whose every operation takes the
caller's connection, so it joins the host's transaction: early end (D5) and the RFQ stage's
deletions (D16) need that. Each host's chain composes custody's statements: a
`market_schema_migrations` migration on the storefronts, an Alembic revision on the registry.
The storefronts open a SQLAlchemy engine over their existing SQLite file for custody alone;
their own tables stay on `sqlite3`.

The trigger admits on an introduction no update but redaction (both slots to NULL and the
redaction time set, once) and re-encryption (on an unredacted row, both slots stay non-null
and their key prefix changes); the identifier, roles, context and reveal time never change,
and an unredacted row is never deleted. A held contact (D16) is never updated but by
re-encryption, and may be deleted.

This change ships the SQLite DDL and proves the store on SQLite. Statements are keyed by
dialect so the PostgreSQL DDL is an addition: `add-buyer-compute-rfqs` adds it, with the
PostgreSQL gate that proves it, when the registry first holds contacts (D26). Nothing ships
untested.

Rejected:

- A store over a small execution port of our own, without SQLAlchemy. It builds the dialect
  shim SQLAlchemy already is.
- A store port each host implements with its own tables and triggers. Two implementations of
  a security property, which D1 exists to remove.
- Database enforcement on SQLite only, with application checks on PostgreSQL. It
  contradicts D3 on the host where the operator is a party to neither side.

### D12 — Tink AEAD keysets

Contacts are encrypted with Tink AEAD (AES-256-GCM) under a keyset loaded from outside the
database. A ciphertext carries Tink's prefix naming its key, so rows written under retained
keys keep decrypting; associated data is passed on every call (D13). A KMS-wrapped keyset is
Tink's optional extra, open to a later operator without code change. Custody wraps Tink's
cleartext keyset loading once. No keyring, key-file format or ciphertext format is built
here.

Rejected:

- AES-GCM from `cryptography` with a keyring of our own, the RFQ stack's design, even as a
  standalone `tools/` component. An existing library meets every requirement, so building
  one is not admitted.
- `MultiFernet`. It has no associated data, so a ciphertext cannot be bound to its row.
- Encrypting the database file. It protects a stolen file but not a read through the running
  service, differs per host, and rotates only by re-keying the whole database.

### D13 — One row per introduction, two slots, a host-supplied identifier

```text
custody_introductions
  introduction_id  opaque, host-supplied primary key (contact exchange: obligation_ref)
  role_a, contact_a  host's role label and Tink ciphertext; NULL once redacted
  role_b, contact_b
  context          opaque, non-secret, bounded JSON; kept after redaction
  revealed_at      from the process time source; drives retention
  redacted_at
```

A slot's associated data is the canonical JSON
`{"protocol": "arkhai.introduction-custody.v1", "introduction_id": …, "role": …}`. A
ciphertext moved to another row or slot fails to decrypt. Nothing that changes is bound: no
expiry and no window, which D4 needs; no host identity, since hosts share no key; and no
principal, since custody stores none. Authorization stays the host's. Redaction is one
statement, and the row remains as the tombstone. Contact exchange maps its roles to the
existing buyer and seller projection, so its wire is unchanged.

Custody's `reveal` keeps today's idempotency: an identical re-reveal returns the stored
record, a different one is refused, and a reveal of a redacted introduction answers the
deleted outcome. Ciphertexts are randomized, so custody compares decrypted values.

Rejected:

- An introduction row with a child table of contacts. It admits any number of parties at the
  cost of a multi-row redaction, three triggers per dialect and a blurred moment of reveal;
  introductions are pairwise.
- Identifiers custody generates, which would need a mapping in every host and lose the
  `obligation_ref` correlation.
- Domain-named columns, which teach the layer settlement and RFQ roles.

### D14 — Rotation re-encrypts; the one-way rule is over decrypted values

An operator rotates by adding a key to the keyset and making it primary. A custody worker,
`introduction-rekey`, then re-encrypts unredacted contacts and held contacts not under the
primary key, in bounded batches, oldest first, with the same pause, preview and step as the
sweep (D17). Custody's single re-encryption operation decrypts, encrypts under the primary
key, decrypts the result and compares it with the original before committing; no host is
given a write over a stored contact. Each host's status reports the unredacted contacts each
key holds, and a key is removable once its count is zero. A host refuses to start when a
stored ciphertext names a key missing from its keyset, naming the key ids. A compromised key
is answered by rotating.

Rejected:

- Rotation that never rewrites a row, retiring keys by retention and answering compromise by
  redacting every introduction under the key. It leaves an `indefinite` storefront unable to
  retire a key and destroys custody's copy on a compromise.
- An offline rotation command with the writers stopped, the RFQ stack's. Custody's updates
  are single statements, and downtime buys nothing.
- A keyed commitment to each contact, checked on every read, to catch a bug in custody's own
  code rewriting a contact under a new key. It is a guard no test could trigger without
  writing the bug.

### D15 — Upgraded storefronts redact pre-upgrade contacts

One storefront migration, needing no key, creates custody's tables, copies every
`contact_introductions` row into `custody_introductions` as a tombstone — contact slots
NULL, roles `buyer` and `seller`, `revealed_at` from `created_at`, `redacted_at` from the
row's deletion time or else the migration's, `context` from `introduction_package` — and
drops the old table and its triggers. A start or read of a pre-upgrade introduction answers
the deleted outcome, so nothing is revealed twice, and the obligation stays settled. The
seller-side dispatch claim table is untouched (D20). Both parties already hold the reveal and
any copies their sinks delivered, and the disclosure states the operator may remove a
payload at any time. The release read is `marketplace-v0.4.0`, with the chains' floor at
marketplace 0.3.0; both carry the plaintext table, and the migration serves both.

The old table is dropped in the same migration: an older image refuses a migrated database
as ahead, and no two versions share a database, so no reader needs it.

Rejected:

- Encrypting existing rows at the first startup with the key. It keeps re-reads of recent
  introductions at the price of a compatibility path, its retirement row, a refusal in a
  later release, and plaintext on disk until first start.
- An operator command that encrypts before the new image starts. The same path, with a
  procedure added to every upgrade.
- Reading plaintext rows until they age out. It contradicts D2 for the data already held, and
  its retirement cannot be checked when a release is prepared.

### D16 — Held contacts for a stage before selection

Custody holds a single contact before any introduction exists, for the RFQ stage before
selection:

```text
custody_held_contacts
  held_id   opaque, host-supplied primary key (the registry: the response id)
  role      host's role label, e.g. "respondent"
  contact   Tink ciphertext, associated data {protocol, held_id, role, "stage": "held"}
  held_at
```

Its operations, each on the caller's connection, are `hold`; `discard`, which deletes the
row (a held contact was never revealed, so leaves no tombstone) and converges when it is
already gone; and `promote`, which in one transaction re-encrypts the held contact into a new
introduction's slot beside the other party's contact and deletes the held row, custody
holding plaintext equality across it. The host owns when each happens: deadlines and expiry
are the RFQ change's, so a deadline the buyer moves needs nothing from custody. Held contacts
are covered by re-encryption, its per-key count and startup refusal, and by restore
redaction.

Rejected:

- A held contact as an introduction row with one slot filled. It breaks "revealed when
  persisted" and needs a third trigger state.
- Encryption primitives only, with the registry storing pending contacts in its own table. A
  second custody stack, invisible to re-encryption and restore redaction.
- Deferring held contacts to the RFQ change. Re-encryption and restore redaction would be
  designed without the rows they must cover.

### D17 — Custody's loops are pausable workers

The sweep and re-encryption are framework-free workers, `IntroductionRetentionSweep` and
`IntroductionRekey`, on the compute provisioning service's pattern: each owns its gate
(`pause`, `resume`, `is_at_gate`), a `run_cycle` under its own lock that both the timer and an
operator's step run, a `preview` that writes nothing, and a bounded `status`. A gate holds at
a cycle boundary and never cancels a cycle. On the storefronts each registers with the
storefront loop controller, which runs its timer with its gate and wait injected, as the
retention sweep does today. On the registry, `add-buyer-compute-rfqs` runs them on their own
timers and binds `/admin/lifecycle/<loop>/pause|resume|run-cycle|preview` behind the
registry's administrator key, reporting both loops on its status. Tests drive the workers
through these controls, never by patching a timer.

Rejected:

- A shared loop controller component under `tools/` used by the registry alone. No shared
  controller exists outside the storefronts, and this would start one half-way.
- Extracting the storefront controller and moving every host onto it here. The right end
  state for that pattern, but a large unification in another subsystem.
- A controller local to the registry, which places generic code in a service.
- Scheduled external commands. A SQLite registry is a single writer, and Compose stacks have
  no scheduler.

### D18 — Restore redaction is a mode of each host's migration command

Custody's `redact_restored` redacts, in the caller's transaction, every unredacted
introduction and discards every held contact through the one deletion operation, and reports
the counts. A restore undoes every redaction made after the backup, and the evidence of an
early end, an operator's deletion or a discard is in the database that was lost, so every
contact the restored database holds is one whose eligibility cannot be established;
expiries need nothing, since the first sweep applies the current window. A host may add its
own state changes in the same transaction.

Each host's migration command gains `--redact-restored-introductions`, with `--preview`
printing the counts and changing nothing. It reads only the database location and log
level, and needs no key. The operator handbook's restore procedure becomes: restore, run the
command's `--check`, run the redaction, then start. In this change the storefronts'
commands, `market-storefront-migrate` and `bare-metal-storefront-migrate`, carry it;
`registry-migrate` carries it with the registry's composition. No setting is involved.

Rejected:

- A non-secret startup setting, the RFQ stack's approach. Two restarts, and a setting left on
  redacts everything at every start.
- An admin route on the running service, which reopens reads before it runs.
- A separate command per host. The same behaviour at three new entry points.

### D19 — The storefront's key and its settings

```toml
# storefront.secrets.toml, the Secret overlay
[introduction_custody]
keyset = '''{"primaryKeyId": 2208112954, "key": [ … ]}'''

# storefront.toml
[introduction_custody]
rekey_interval_seconds = 3600

[Settlement.contact]
retention_seconds = 2592000
retention_sweep_interval_seconds = 3600
```

Custody is composed under the condition the retention sweep is composed today. A storefront
composing it refuses to start with no keyset or a malformed one, and with a keyset missing a
key a stored ciphertext names, naming the setting or the key ids. The retention keys keep
their names and meaning. The storefront charts' values schemas gain the overlay field through
`kit/config`'s generator; the lanes use a committed public development keyset, and
hand-run stacks a gitignored copy of a committed `.example`, generated by a make target that
leaves an existing copy untouched. The registry's form, a keyset file its profile names, is
its own precedent, applied by `add-buyer-compute-rfqs`.

Rejected: a public path to a keyset file mounted from the Secret on the storefronts, a second
channel beside the overlay the storefronts already use for secrets.

### D20 — The seller-side dispatch claim stays with contact exchange

`contact_introduction_seller_dispatches` stays `kit/contact-exchange`'s, in the storefront
chain, keyed by `obligation_ref`, which is custody's `introduction_id`. Custody holds no
delivery state: `DeliveryEvent` is `kit/delivery`'s, the contact-exchange kit takes no
delivery dependency, and the registry delivers nothing.

Rejected: an optional claim in custody, a delivery concern of one host in the neutral layer.

### D21 — The deleted outcome states when, not why

Every host answers the existing outcome, `{"code": "introduction_payloads_deleted",
"payloads_deleted_at": …}`. Expiry, early end, an operator's deletion and restore redaction
read alike, and custody records only `redacted_at`.

Rejected: an additive `reason`. It would tell one party the other ended access early, a
disclosure no requirement weighs, and store a cause nothing reads.

### D22 — The startup sweep and overdue reporting

At startup, after the key checks, each host runs the sweep worker's own `run_cycle` until no
eligible introduction remains, before it serves introductions; on the storefronts, in the
composition's startup before the server accepts requests. The sweep worker's status reports
`oldest_overdue_seconds` — the age past the window of the oldest unredacted introduction, or
`null` — and the last cycle's count, and the startup logs the same figure.

Rejected: a warning or operator event past a configured age, a constant nothing reads today;
it can become an event kind when an operator needs paging.

### D23 — The disclosure value is custody's

Custody owns the disclosure value, `{"window_seconds", "basis": "current_policy", "scope":
"introduction_record"}`. Every host serves it before a party commits a contact and at reveal,
from one running configuration; the storefronts serve it as today. Where the registry serves
it, and how it covers held contacts, which a respondent commits when responding, is
`add-buyer-compute-rfqs`'s, with the registry's composition; its public descriptor is the
nearest precedent.

### D24 — One payload validator, in custody

`validate_contact_payload` moves to custody with the rules a release has shipped: at most 16
entries, keys of 1 to 64 characters, values non-blank and at most 512 characters. Custody
applies it on `reveal` and `hold`; contact exchange's configuration and start route call it
from custody. `market_core.rfq.RfqContact` does not carry forward.

Rejected: the RFQ branch's stricter refusal of blank keys, which would refuse a
configuration 0.4.0 accepted for no stated harm.

### D25 — Implementation cadence

Two rounds, the kit reviewed before anything adopts it:

- Round 1, one session: `kit/introduction-custody` — the SQLite schema and trigger, the Core
  store (`reveal`, `read`, `redact`, `end`, `hold`, `discard`, `promote`, per-key counts,
  `redact_restored`), Tink keyset loading and startup checks, the validator, the disclosure
  value, the two workers, and the conformance suite.
- Round 2, two sessions: first, `kit/contact-exchange` onto custody — its asynchronous
  adapter for the storefronts, the D15 migration, the D27 route, client and buyer command,
  the dispatch claim untouched; second, both storefronts' wiring — keyset settings and
  refusals, the startup sweep, `introduction-rekey` registration, the migration-command mode,
  the credential-capable routes and the D28 migration, the charts' values schemas, and the
  lane and local keysets — closing with the integration and lane scenarios.

### D26 — The registry composes custody with RFQs

This change delivers the kit and composes it into the VM and bare-metal storefronts. The
`introduction-custody` specification states what every host must do, and
`add-buyer-compute-rfqs` composes custody into the registry when the registry first holds
contacts, implementing the registry's form of D17, D18, D19 and D23 and the PostgreSQL
dialect (D11). The change index records the move in that change's row.

Rejected:

- Composing the registry here. Every registry deployment would need a keyset, a disclosure
  and admin routes for custody holding nothing, or an enabling switch RFQs would replace.
- Composing only the registry's schema here, which proves nothing and splits one host's
  composition across two changes.

### D27 — Early end on the storefronts

A signed operation, `introduction_end`, sits beside start and read in contact exchange's
route contract and admits the Agreement's buyer and seller principals. It calls custody's
`end`, which redacts through the one deletion operation, and answers the deleted outcome; a
repeat converges. The buyer ends access with `introduction end`, a command in the
mechanism's buyer command group; the seller's side remains the operator's deletion of one
introduction, since the storefront is the seller's. The route and command are additive.

Rejected: ending a buyer's access only by asking the seller's operator, which fails D5.

### D28 — Introduction routes record no contact for exact retry

Introduction start, read and end are credential-capable routes on both storefronts
(`CREDENTIAL_CAPABLE_ROUTES`): their recorded outcomes hold no contact, and an exact retry
runs again under current authorization, so after a redaction it answers the deleted outcome
rather than replaying a contact. A storefront migration removes the contact members from the
introduction outcomes already recorded. A response the system can re-derive from a record it
protects from modification gains nothing from being recorded for replay: a retry cannot
differ from running the request again.

This takes the introduction slice of the unbounded-replay gap `redesign-authenticated-requests`
owns; the change index records the move in that change's row, and the roadmap's row narrows
at closeout.

Rejected:

- Leaving the replay copies to `redesign-authenticated-requests`, which keeps a plaintext
  copy of every reveal beside the encrypted one until that redesign lands.
- Encrypting the replay records, which redesigns replay state for one route family.

## Open Questions

None. What `add-buyer-compute-rfqs` implements for the registry is decided here (D11, D16,
D17, D18, D19, D23, D26).

## Verification

Integration tests in `kit/introduction-custody` prove, on SQLite: encryption and the
associated-data binding, re-encryption with plaintext equality and per-key counts, the
startup refusals, one-way redaction under the trigger and under concurrent reads, reveal
idempotency, window changes, early end, held contacts and their promotion, restore
redaction, and the workers' pause, preview and step. Each storefront's integration tests
prove its composition through its own routes: the keyset refusals, the startup sweep, early
end, credential-capable retries after a redaction, and the migration-command mode. The
storefront migration-chain tests prove the D15 and D28 migrations from 0.3.0 and 0.4.0
databases. The contact-exchange lane scenarios keep passing, with early end added.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| D1–D8, D13, D14, D16, D18, D21–D24 | `openspec/specs/introduction-custody/spec.md` |
| D1, D10–D14, D16, D17 | `openspec/specs/introduction-custody/architecture.md` |
| D19 | `openspec/specs/introduction-custody/configuration.md`; `openspec/specs/contact-exchange-settlement/configuration.md`; `docs/development/DEPLOYMENT_AND_CONFIG.md` |
| D10, D15, D27, D28 | `openspec/specs/contact-exchange-settlement/spec.md` |
| D10 | `openspec/specs/README.md`; `docs/development/ARCHITECTURE.md`, "Kit areas" |
| D12 | `docs/guidance/repository/production-code.md`, "Libraries" |
| D14 | `docs/guidance/engineering/persistence.md`, an integrity rule over encrypted data, with an example |
| D6, D7, D14, D15, D18, D22 | `docs/operator-handbook.md` |
| D15, D18 | `docs/development/DEPLOYMENT_AND_CONFIG.md`, "Migrations at startup" |
| D17 | `docs/development/ARCHITECTURE.md`, "Operator lifecycle controls" |
| D20 | `openspec/specs/introduction-delivery/architecture.md` |
| D26, D28 | `docs/development/ROADMAP.md`, Goals 6 and 9 |
| D28 | `docs/guidance/repository/`, a rule on what a route records for exact retry |
