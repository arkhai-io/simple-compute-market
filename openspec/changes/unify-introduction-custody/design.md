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

One more fact bears on encryption. `kit/config` already holds an encryption-at-rest helper,
`market_config.secret_at_rest`: one Fernet key from the service's profile, no associated
data, no key id in a token, and nothing that re-encrypts. The compute provisioning service
stores a host's SSH key and each relay's admission token and grant keys with it, and after a
key change the operator handbook has every such secret submitted again. `harden-shared-relays`
(deferred) owns replacing that scheme with one that names each value's key, binds it to its
host and rotates without losing a secret, its gap (4).

## Decisions

D1–D9 were settled in the review of pull request #401 on 2026-11-27, D10–D28 in this
change's design discussion, and D29 and D30 when planning's return reopened it the same day.

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

### D9 — Delivery is unchanged but for the exact retry of a failed start

Each side delivers to its own configured sinks as `introduction-delivery` defines. An RFQ
participant's buyer CLI will deliver from its own process after a read; the registry
delivers nothing.

One rule of `introduction-delivery` changes with D28 (17 F1): an exact retry of a start
whose completion failed runs the start again and completes the reveal, as a new start
does, instead of answering its recorded 503. The rule it replaces rested only on every
route answering an exact replay with its recorded outcome, which `marketplace-identity`'s
credential-capable routes no longer do. Dispatch stays at most once, held by the seller
dispatch claim, and completion stays the buyer's, by a start of its own.

### D10 — A mechanism-neutral kit and its own capability

Custody is a new kit, `kit/introduction-custody`: kit layer, empty scope, foundation area,
with a package allowlist of `arkhai-keyset-aead` (D29) and `sqlalchemy`. Its requirements are a new capability, `introduction-custody`,
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
Tink's optional extra, open to a later operator without code change. Custody reaches Tink only
through the standalone keyed-encryption component (D29), and an operator edits a keyset with
Tink's own tool, Tinkey. No keyring, key-file format or ciphertext format is built here.

Custody's requirements differ from those of the secrets `market_config.secret_at_rest`
protects today: a ciphertext bound to its record and slot (D13), and rotation that loses no
payload and can count what each key still holds (D14). Fernet tokens carry neither associated
data nor a key id, so custody does not compose that helper; `harden-shared-relays` moves its
secrets onto custody's component (D30).

Rejected:

- AES-GCM from `cryptography` with a keyring of our own, the RFQ stack's design, even as a
  standalone `tools/` component. An existing library meets every requirement, so building
  one is not admitted.
- `MultiFernet`, or `kit/config`'s Fernet helper with the associated data sealed inside the
  plaintext and checked on decrypt. Either builds the binding Fernet lacks, and a Fernet token
  names no key, so D14's per-key counts and the refusal naming a missing key could come only
  from trial-decrypting every row under every key.
- `sqlalchemy-utils`' encrypted column types, which bind nothing per row and name no key, and
  the AWS Encryption SDK's raw AES keyrings, which bind an encryption context but need a
  keyring of our own to hold their keys.
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
`{"protocol": "arkhai.introduction-custody.v1", "introduction_id": …, "slot": "a"|"b",
"role": …}`. A ciphertext moved to another row or slot fails to decrypt, whatever role
labels the host supplied: the slot is bound because labels may repeat, as two parties of
a symmetric introduction may share one (17 F2). Nothing that changes is bound: no
expiry and no window, which D4 needs; no host identity, since hosts share no key; and no
principal, since custody stores none. Authorization stays the host's. Redaction is one
statement, and the row remains as the tombstone. Contact exchange maps its roles to the
existing buyer and seller projection, so its wire is unchanged.

Custody's `reveal` keeps today's idempotency: an identical re-reveal returns the stored
record, a different one is refused, and a reveal of a redacted introduction answers the
deleted outcome. Ciphertexts are randomized, so custody compares decrypted values. A
`read` has three results: absent, for an identifier never revealed; revealed, with both
slots, either of which may be an empty contact, which the validator admits (D24) and which
is not absence; and redacted, with its redaction time (17 F4). Role labels are non-blank
strings of at most 64 characters, and the context is a JSON object whose canonical JSON is
at most 65,536 bytes in UTF-8, far above anything contact exchange's agreed introduction
context carries — its option and listing identifiers, profile, a channel of at most 128
characters and terms of at most 4,000 — since nothing bounds that context today; both are
checked on `reveal`, `hold` and `promote`, before anything is written. The D15 migration
copies stored contexts as they are, since it reveals nothing.

Rejected:

- Requiring the two role labels to differ, with the associated data left as it was (17 F2).
  It narrows the neutral interface, making a host with symmetric parties invent labels, to
  stand in for binding the slot itself.
- An introduction row with a child table of contacts. It admits any number of parties at the
  cost of a multi-row redaction, three triggers per dialect and a blurred moment of reveal;
  introductions are pairwise.
- Identifiers custody generates, which would need a mapping in every host and lose the
  `obligation_ref` correlation.
- Domain-named columns, which teach the layer settlement and RFQ roles.

### D14 — Rotation re-encrypts; the one-way rule is over decrypted values

An operator rotates by adding a key to the keyset and making it primary, with Tinkey's
`add-key` and `promote-key` (D29), and updating the Secret the host reads it from. A custody worker,
`introduction-rekey`, then re-encrypts unredacted contacts and held contacts not under the
primary key, in bounded batches, oldest first, with the same pause, preview and step as the
sweep (D17). Custody's single re-encryption operation uses the component's verified
re-encryption, which decrypts, encrypts under the primary key, decrypts the result and
compares it with the original, and commits only what that returns; no host is given a write
over a stored contact. Each host's status reports the unredacted contacts each key holds,
counted from the key id the component reads from each stored ciphertext's prefix, and a key
is removable once its count is zero. A host refuses to start when a
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
introduction's slot, under that slot's associated data (D13), beside the other party's
contact and deletes the held row, custody holding plaintext equality across it.

Their repeats follow `reveal`'s idempotency (17 F4), so a host's exact retry, which runs
the operation again, needs no special case:

- `hold` repeated with the same role and contact returns the held contact and writes
  nothing; with a different role or contact under the same identifier it is refused, and
  the held contact is unchanged.
- `promote` whose held contact is gone converges when the target introduction exists with
  the same other party's contact, roles and context, returning it; answers the deleted
  outcome when that introduction is redacted; and is refused as not held when no
  introduction exists either, writing nothing.
- `promote` whose held contact remains but whose target introduction already exists is
  refused, and changes nothing.

The host owns when each happens: deadlines and expiry
are the RFQ change's, so a deadline the buyer moves needs nothing from custody. Held contacts
are covered by re-encryption, its per-key count and startup refusal, and by restore
redaction.

Rejected:

- A typed refusal for every repeated or absent case, leaving retries to the host's own
  rows (17 F4). Sound, since those rows commit with custody's, but it gives custody two
  creating operations with different repeat rules and gives every credential-capable
  selection retry a special case in the host.
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
`kit/config`'s generator. The keyset in every stack this repository runs is a committed
public development value, the case `configuration.md` gives for a stack run unattended from
a clean checkout: each storefront's Secret overlay under `dev-env/identities/` is one file
that the lanes, which run unattended, and the full local stack both mount
(`compose.vms-local.yml`, `compose.bare-metal-local.yml`, layered under each lane), and the
local cluster's topology script writes the same keyset into the storefronts' Secrets. Those
keysets are generated once with Tink's Python API and committed. No
storefront stack reads a gitignored copy of its overlay, so no `.example` and no generating
target are added; a stack that comes to take its own copy follows `configuration.md` then.
The registry's form, a keyset file its profile names, is its own precedent, applied by
`add-buyer-compute-rfqs`.

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

Two rounds, the component and the kit reviewed before anything adopts them:

- Round 1, two sessions: first, `tools/keyset-aead` (D29) — the component, its capability,
  its structure test, its root test target, its published-package row and release unit, and
  its README as its published interface; second, `kit/introduction-custody` on it — the
  SQLite schema and trigger, the Core store (`reveal`, `read`, `redact`, `end`, `hold`,
  `discard`, `promote`, per-key counts, `redact_restored`), the keyset setting and startup
  checks, the validator, the disclosure value, the two workers, and the conformance suite.
- Round 2, two sessions: first, `kit/contact-exchange` onto custody — its asynchronous
  adapter for the storefronts, the D15 migration, the D27 route, client and buyer command,
  the route service's exact retry running again (D28), the dispatch claim untouched; second, both storefronts' wiring — keyset settings and
  refusals, the startup sweep, `introduction-rekey` registration, the migration-command mode,
  the credential-capable routes and the D28 migration, the charts' values schemas, and the
  lane and local keysets — closing with the integration and lane scenarios. The storefronts
  pin `kit/contact-exchange` exactly, so the first session keeps their composition working
  until the second switches them over.

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

Ending an introduction never revealed is refused with a stable not-revealed answer and
persists nothing (17 F4): D5 ends contact access, and before a reveal there is none.

Rejected:

- Ending a buyer's access only by asking the seller's operator, which fails D5.
- Ending an unrevealed introduction by writing a tombstone (17 F4). It would let either
  party prevent a reveal before it happens, a policy beyond this change.

### D28 — Introduction routes record no contact for exact retry

Introduction start, read and end are credential-capable routes on both storefronts
(`CREDENTIAL_CAPABLE_ROUTES`): their recorded outcomes hold no contact, and an exact retry
runs again under current authorization, so after a redaction it answers the deleted outcome
rather than replaying a contact. A storefront migration removes the contact members from the
introduction outcomes already recorded. The replay table, `auth_replay_reservations`, keeps
no operation name, so the migration finds a recorded reveal by its body: a JSON object
whose `mechanism` is `contact-exchange.v1`, whose `revealed` is true, and which carries
`counterparty_contact`, the shape `introduction_projection` writes; it removes that member
and leaves every other row as it is. The table is core storefront's and the shape contact
exchange's, so each storefront chain composes the migration from a core storefront helper
that rewrites recorded outcomes and contact exchange's own function that strips a reveal.
A response the system can re-derive from a record it
protects from modification gains nothing from being recorded for replay: a retry cannot
differ from running the request again.

Every exact retry runs again, whatever the outcome recorded (17 F1). A retried start
resumes, as `marketplace-identity` has a credential-capable route's mutation resume:
custody's identical reveal returns the stored record, completion is idempotent, and the
seller dispatch claim, already taken, dispatches nothing; a start whose completion failed
is completed by its exact retry, which amends `introduction-delivery` (D9). The retry is
resolved in two places today, and both change: each storefront's map, and
`IntroductionRouteService._replay` in `kit/contact-exchange`, which answers a recorded
outcome after authorization and before custody is read, and which the start, read and end
operations no longer call.

Rejected (17 F1): replaying a recorded refusal, the failed start's 503 among them, while
running a recorded reveal again. It keeps `introduction-delivery`'s rule at the cost of a
start route that resumes one mutation and replays another, an exception to the identity
rule for a case a retry can complete.

This takes the introduction slice of the unbounded-replay gap `redesign-authenticated-requests`
owns; the change index records the move in that change's row, and the roadmap's row narrows
at closeout.

Rejected:

- Leaving the replay copies to `redesign-authenticated-requests`, which keeps a plaintext
  copy of every reveal beside the encrypted one until that redesign lands.
- Encrypting the replay records, which redesigns replay state for one route family.

### D29 — Keyed encryption is a standalone component, and Tinkey edits keysets

Custody's keyed encryption is generic infrastructure, not specific to the market, so it is a
standalone component under `tools/`, as `package-layers.md` and `implementation.md`'s
"Generic infrastructure is a standalone component" place such work: `tools/keyset-aead`,
published as `arkhai-keyset-aead`, imported as `keyset_aead`, with its own capability,
`keyset-aead`. It depends on `tink` alone, names no market concept, carries its own licence,
semantic version and structure test, and can be lifted into a repository of its own as it
stands; `tools/injected-time` is the precedent. Custody consumes it as a wheel.

```python
from keyset_aead import Keyset, KeysetError, DecryptionError

keyset = Keyset.load(text)            # refuses a non-AEAD keyset, a RAW-prefix key, no enabled primary
token = keyset.encrypt(b"...", associated_data=b'{"protocol": ...}')
keyset.decrypt(token, associated_data=...)      # DecryptionError: moved, forged or unknown key
keyset.key_id_of(token) -> int                  # from Tink's prefix, without decrypting
keyset.primary_key_id -> int; keyset.key_ids -> frozenset[int]
keyset.reencrypt(token, associated_data) -> bytes | None  # None when under the primary; verifies equality
```

The component holds what Tink's Python package leaves to its user: reading a ciphertext's key
id from its prefix, whose helper Tink keeps private; refusing a keyset that is not
AES-256-GCM AEAD, has no enabled primary, or holds a `RAW`-prefix key whose ciphertexts would
name no key; verified re-encryption (D14); and errors that name the problem and never key
material. What is the market's stays in custody: the associated-data layout (D13), the
tables, the workers, the per-key counts over its own rows, and the startup refusal naming its
setting. An operator generates, adds and promotes keys with Tinkey, Tink's own tool, so no
keyset-editing command is built; tests that rotate build keysets with Tink's own helpers.

Rejected:

- The Tink wrapper inside `kit/introduction-custody`. Generic infrastructure in a market
  package, the fault the review of pull request #401 found in the RFQ stack, and out of
  provisioning's reach without an extraction.
- A keyset module in `kit/config` beside the Fernet helper. Encryption at rest is a
  persistence concern, not configuration; it would also give the registry, which does not
  depend on `kit/config`, `dynaconf`, `eth-account` and `arkhai-kit-settlement-runtime`, and
  give Tink to every one of `kit/config`'s dependents, the buyers among them.
- A new foundation kit for keyed encryption. A kit is a market package, which the
  standalone-component rule excludes for generic infrastructure however few packages use it.
- The component in a repository of its own now. Every fix during this change would need a
  release and a cross-repository pin; `tools/` holds it ready to lift when a second
  repository consumes it.
- A keyset-editing command of our own (`generate`, `add-key`, `promote`, `list`). Tinkey
  exists and does it; rotation is rare, and a JVM on the operator's machine is its only cost.
- Moving provisioning onto the component here. A conversion of values released in marketplace
  0.4.0 and a second subsystem, which is `harden-shared-relays`' gap (4), none of whose
  triggers has fired (D30).

### D30 — `secret_at_rest` is recorded as superseded, retired by `harden-shared-relays`

The repository has two encryption-at-rest components until `harden-shared-relays` runs:
custody's keyed component and `kit/config`'s Fernet helper. That change's row records that its
keyed scheme for provisioning's secrets is `arkhai-keyset-aead`, and that it retires
`market_config.secret_at_rest`, whose placement in configuration the same reasoning as D29's
rejects. This change amends that helper's docstring, which today calls it the one place such
encryption lives, to say the keyed component supersedes it and why it remains.

Rejected:

- An unowned row in the change index, which would duplicate the gap `harden-shared-relays`
  already owns.
- Leaving the docstring as it is, which would keep stating something false.

## Open Questions

What `add-buyer-compute-rfqs` implements for the registry is decided here (D11, D16, D17,
D18, D19, D23, D26).

## Verification

Unit tests in `tools/keyset-aead` prove encryption and decryption with associated data, a
refused moved or forged ciphertext, key ids read from prefixes, the keyset refusals, verified
re-encryption, and that no error carries key material; its structure test holds its boundary.
Integration tests in `kit/introduction-custody` prove, on SQLite: encryption and the
associated-data binding, a slot swap failing under repeated role labels among it,
re-encryption with plaintext equality and per-key counts, the startup refusals, one-way
redaction under the trigger and under concurrent reads, reveal idempotency, read's three
results, window changes, early end, held contacts with their repeated, conflicting and
absent holds and promotions, restore redaction, and the workers' pause, preview and step.
Each storefront's integration tests prove its composition through its own routes: the
keyset refusals, the startup sweep, early end and its refusal for an unrevealed
introduction, credential-capable retries after a redaction, an exact retry completing a
failed start with one seller dispatch, and the migration-command mode. The
storefront migration-chain tests prove the D15 and D28 migrations from 0.3.0 and 0.4.0
databases. The contact-exchange lane scenarios keep passing, with early end added.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| D1–D8, D13, D14, D16, D18, D21–D24 | `openspec/specs/introduction-custody/spec.md` |
| D1, D10–D14, D16, D17 | the `introduction-custody` capability's architecture companion, created at closeout |
| D19 | the `introduction-custody` capability's configuration guidance, created at closeout; `openspec/specs/contact-exchange-settlement/configuration.md`; `docs/development/DEPLOYMENT_AND_CONFIG.md` |
| D10, D15, D27, D28 | `openspec/specs/contact-exchange-settlement/spec.md` |
| D9, D28 | `openspec/specs/introduction-delivery/spec.md` |
| D10 | `openspec/specs/README.md`; `docs/development/ARCHITECTURE.md`, "Kit areas" |
| D12 | `docs/guidance/repository/production-code.md`, "Libraries" |
| D14 | `docs/guidance/engineering/persistence.md`, an integrity rule over encrypted data, with an example |
| D6, D7, D14, D15, D18, D22 | `docs/operator-handbook.md` |
| D15, D18 | `docs/development/DEPLOYMENT_AND_CONFIG.md`, "Migrations at startup" |
| D17 | `docs/development/ARCHITECTURE.md`, "Operator lifecycle controls" |
| D20 | `openspec/specs/introduction-delivery/architecture.md` |
| D26, D28 | `docs/development/ROADMAP.md`, Goals 6 and 9 |
| D28 | `docs/guidance/repository/`, a rule on what a route records for exact retry |
| D29 | the `keyset-aead` capability's specification and architecture companion, created at closeout; `tools/README.md`, "Standalone infrastructure components"; `docs/guidance/repository/package-layers.md`; `docs/guidance/repository/published-packages.md`; `docs/operator-handbook.md` |
| D30 | `openspec/changes/README.md`, `harden-shared-relays`' row; `kit/config/src/market_config/secret_at_rest.py`'s docstring |
