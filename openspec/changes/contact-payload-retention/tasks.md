# Tasks — contact payload retention

Implemented, reviewed, and promoted. The end-to-end pipeline passed on the
pre-review fileset (8.9); a confirming run on the final fileset is the one
outstanding item.

Validation levels below are named deliberately. Per `docs/development/TESTING.md`,
integration means the real app, a real database, a wired DI container, and the
service's canonical typed client; a kit library's integration tests exercise its
public API against a real embedded database.

## 1. Design

- [x] 1.1 **Decision gate.** Design decisions recorded in `design.md`: kit-first
      placement; retention on bare metal, VM inheriting it through
      `compose-contact-exchange-across-compute`; redaction leaving a tombstone under
      triggers; each surface's outcome after deletion; `retention_seconds` in
      `ContactSettlementConfig`; one disclosure object; eligibility from reveal time;
      one deletion operation behind both invocation paths; the first introduction
      scenario on the bare-metal lane.
- [x] 1.2 **Decision gate.** The authenticated replay store's copies of revealed
      contacts are out of scope and the disclosure is scoped to the introduction
      record. The replay store's redesign is owned by
      `redesign-authenticated-replay-state`.
- [x] 1.3 Implementation planned; planning and implementation decisions are in
      `design.md`.

## 2. Persistence and redaction (kit)

In `kit/contact-exchange/src/market_contact_exchange/`.

- [x] 2.1 Migration `20261001_007_contact_introduction_tombstones`: the
      `payloads_deleted_at` column, a trigger permitting only one-way redaction, a
      trigger refusing removal of an unredacted row, and a partial index on
      `created_at`.
- [x] 2.2 `delete_introduction_payloads` redacts in one `UPDATE`, returning whether it
      did; it replaces `delete_introduction`.
- [x] 2.3 `IntroductionRecord.payloads_deleted_at`; a redacted record loads with empty
      contacts.
- [x] 2.4 `select_expired_introductions`, oldest first and bounded, and
      `format_introduction_timestamp`.
- [x] 2.5 `insert_introduction` refuses to persist over a tombstone with
      `IntroductionPayloadsDeletedError`, distinct from the different-payload conflict.

## 3. Configuration, disclosure, and the route service (kit)

- [x] 3.1 `retention_seconds` (default 30 days, positive or `indefinite`) and
      `retention_sweep_interval_seconds` (default one hour), seller role. No generated
      output names the contact section, so nothing regenerated.
- [x] 3.2 `IntroductionRetentionPolicy` and `retention_disclosure` in `retention.py`.
- [x] 3.3 The projection refuses a redacted record and carries the disclosure; read
      answers 410 `introduction_payloads_deleted`; a start that finds the payloads
      deleted, on its read or its persist, drives completion and answers the same 410.
- [x] 3.4 Package boundary permits `asyncio`, `datetime`, and `logging`.

## 4. Sweep, loop runner, and admin service (kit)

- [x] 4.1 `IntroductionRetentionService`: `delete_one` (whether redacted, and the
      tombstone's time), `sweep_once`, and `preview`, all through one deletion
      operation.
- [x] 4.2 `run_introduction_retention_sweep` gates on entry, sweeps once due, and waits
      through the controller.
- [x] 4.3 Exports, including the kit-owned `IntroductionAdminClient` and
      `SyncIntroductionAdminClient` with the route path and operation name.

## 5. Bare-metal composition

In `domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/` unless named.

- [x] 5.1 `sqlite_client.py` wrappers for redaction and expired selection.
- [x] 5.2 `runtime.introduction_retention()` builds the service from running
      configuration; the reveal carries its disclosure; the operator route binds the
      kit's path and operation.
- [x] 5.3 Readiness carries `disclosures.introduction_retention` while contact exchange
      is enabled; the core client's `HealthResponse` reads it as a typed field.
- [x] 5.4 The sweep's step and preview register in `lifecycle_steps.py`; `server.py`
      starts its timer.
- [x] 5.5 Re-delivery refuses a deleted introduction, and the
      `redeliver-introduction` command reports the refusal.
- [x] 5.6 The operator deletion client is kit-owned (4.3); the core storefront client
      is unchanged apart from `HealthResponse.disclosures`.
- [x] 5.7 Buyer: `AuthenticatedHTTPError` carries a verified status and body;
      `IntroductionTransport` raises `IntroductionPayloadsDeleted`; the bare-metal
      `introduce` and `introduction` commands print the deleted outcome, log it, and
      deliver nothing.
- [x] 5.8 The bare-metal lane enables contact exchange with development-fixture
      values, a 5-second window, and a day-long sweep interval.

## 6. Specification

- [x] 6.1 `contact-exchange-settlement` delta promoted into
      `openspec/specs/contact-exchange-settlement/spec.md`.
- [x] 6.2 `introduction-delivery` delta promoted into
      `openspec/specs/introduction-delivery/spec.md`.

## 7. Validation

- [x] 7.1 **Unit (kit).** Configuration fields and refusals; the disclosure;
      eligibility at the boundary; `indefinite`; preview writing nothing; the step
      deleting a superset of a preview under an advancing clock and a batch limit; a
      partially failed sweep converging; the runner's gate order; the route service's
      outcomes after deletion, including a redaction racing a start; the admin client's
      request and sync/async parity.
- [x] 7.2 **Integration (kit library).** Against real SQLite: redaction, repeat
      redaction, re-persist refusal, and expired selection (`test_migrations.py`); both
      triggers; an independent-connection read interleaved with redaction; a
      shortened window; convergence after a part-way failure
      (`test_retention_persistence.py`).
- [x] 7.3 **Unit (core).** The typed error carries status and body and stays a
      `RuntimeError`; the transport maps the deleted outcome and no other refusal.
- [x] 7.4 **Integration (bare metal).** Through the canonical client, the kit admin
      client, and the production buyer transport: readiness disclosure equal to the
      reveal's, `indefinite`, absent without contact exchange; operator deletion keeping
      the obligation, converging, and stopping read, start, and a second delivery; the
      held sweep's preview and step; re-delivery's refusal. Buyer CLI outcome in
      `domains/bare_metal/buyer/tests`.
- [x] 7.5 **System.** `e2e_bare_metal_introduction` on the bare-metal lane: disclosure
      before commitment, an introduction offered by pool override, two reveals through
      the production buyer transport, operator deletion, and the held sweep stepped
      once the preview reports the expired introduction. Each introduction has its own
      whole-host listing. Re-delivery runs inside the storefront container and is
      proven by the storefront's tests.
- [x] 7.6 Package suites, against freshly built wheels. Final fileset: kit 84,
      `core/storefront-client` 44, `core/buyer` unit 131, bare-metal storefront 226,
      bare-metal buyer 16, the VM storefront's whole-surface client parity test, and
      e2e collection. `make test` across the repository passed on the pre-review
      fileset. *Pre-existing, unrelated:* e2e unit
      `test_buyer_deployment_mounts_separate_profile_state_and_credential` fails
      identically without this change.
- [x] 7.7 **Overlap ordering.** A first start whose completion is held while a
      redaction commits still answers and delivers its reveal once; later reads and
      starts answer the deleted outcome.

## 8. Closeout

- [x] 8.1 **Comment hygiene.** `make check-comment-hygiene` passes.
- [x] 8.2 **Import placement.** The one function-level import added, in the
      storefront's `redeliver-introduction` command, follows that CLI's per-command
      imports so `--help` loads no runtime.
- [x] 8.3 **Documentation compliance.** The aggregate, configuration-read window and
      the requirement that every composing storefront run retention are normative in
      `contact-exchange-settlement`; rationale is in `design.md`.
- [x] 8.4 **Narrative compression.** Task notes reduced to final behaviour and
      evidence; alternatives, review rationale, and the accepted risks are in
      `design.md`.
- [x] 8.5 **Roadmap currency.** Goal 6's retention gap left the table for the
      current-state prose; its replay-store row is owned by
      `redesign-authenticated-replay-state`. Goal 7 needed no edit.
- [x] 8.6 **Campaign index currency.** This change's row, its unowned replay entry
      retired in favour of `redesign-authenticated-replay-state`'s row, and
      `compose-contact-exchange-across-compute` blocked only on 8.9.
- [x] 8.7 **Documentation citations.** Passes for this change; repository-wide
      failures are unchanged from the baseline.
- [x] 8.8 **Packaging.** `make check-packaging` passes.
- [ ] 8.9 **End-to-end pipeline.** [Actions run 36921556410](https://github.com/arkhai-io/simple-compute-market/actions/runs/36921556410)
      passed both lanes on the pre-review fileset: VM 129 passed; bare metal 16
      passed, the 11 publication stages and all 5 `e2e_bare_metal_introduction`
      stages. Storefront logs show the reveals, the operator deletion, `410` on a
      read and on a fresh start, the preview polled across the 5-second window, the
      sweep step, and `410` on the swept introduction. *Outstanding:* one run on the
      final fileset. Since that run the scenario sends its deletion through the
      kit's admin client, an identical wire request, and the preview's guarantee is
      restated; no wire contract changed.
- [x] 8.10 **Promotion.** Recorded below.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| Deletion redacts in place and leaves a tombstone; the active part of the table is append-only | `openspec/specs/contact-exchange-settlement/spec.md` |
| Each surface's outcome after deletion | `openspec/specs/contact-exchange-settlement/spec.md` |
| A deleted introduction is never delivered | `openspec/specs/introduction-delivery/spec.md` |
| `retention_seconds` with a 30-day default; `indefinite` means no deletion | `openspec/specs/contact-exchange-settlement/spec.md`, `docs/development/DEPLOYMENT_AND_CONFIG.md` |
| The window is an aggregate policy read from running configuration, not pinned per deal | `openspec/specs/contact-exchange-settlement/spec.md` |
| The scheduled sweep and the operator-invoked path share one deletion operation | `openspec/specs/contact-exchange-settlement/spec.md` |
| The window is disclosed before a buyer commits contact data and again at reveal, as current policy scoped to the introduction record | `openspec/specs/contact-exchange-settlement/spec.md` |
| Every storefront composing the mechanism runs the sweep and serves both disclosures | `openspec/specs/contact-exchange-settlement/spec.md` |
| The retention sweep is a held and stepped storefront loop | `docs/development/TESTING.md` |
| The retention boundary and the deletion operation's name | `docs/development/ARCHITECTURE.md#settlement-configuration` |
| A reveal is ordered by its persist; deletion does not recall a reveal already made | `openspec/specs/contact-exchange-settlement/spec.md`, `openspec/specs/introduction-delivery/spec.md`, `docs/development/ARCHITECTURE.md#settlement-configuration` |
| A preview is a snapshot; the next step deletes every previewed introduction still present, plus any expired since | `openspec/specs/contact-exchange-settlement/spec.md`, `docs/development/TESTING.md` |
| Retention settings, the operator route, and the disclosure's scope | `docs/development/DEPLOYMENT_AND_CONFIG.md#contact-exchange-retention` |
| The operator deletion client is a kit-owned extension over core's generic transport | Temporary: follows the existing pool-overrides rule in `docs/development/ARCHITECTURE.md`; no new permanent text |
| Goal 6 current state | `docs/development/ROADMAP.md` |
| Campaign index rows | `openspec/changes/README.md` |
| The authenticated replay store is out of scope; redesigning it is owned elsewhere | `openspec/changes/README.md` (`redesign-authenticated-replay-state`), `docs/development/ROADMAP.md` Goal 6 |
