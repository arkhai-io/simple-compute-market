# Tasks — contact payload retention

Planned. Unblocked: `kit-owned-storefront-loop-lifecycle`, whose controller the sweep
registers with, is complete.

Validation levels below are named deliberately. Per `docs/development/TESTING.md`,
integration means the real app, a real database, a wired DI container, and the
service's canonical typed client over `ASGITransport`; a kit library's integration
tests exercise its public API against a real embedded database.

## 1. Design

- [x] 1.1 **Decision gate.** Record the design decisions in `design.md`. Decided:
      kit-first placement; retention on bare metal with VM inheriting it through
      `compose-contact-exchange-across-compute`; redaction leaving a tombstone, the
      active part of the table append-only under triggers; each surface's outcome
      after deletion; the window as `retention_seconds` in `ContactSettlementConfig`;
      one disclosure object; eligibility from reveal time; one deletion operation
      behind both invocation paths; bare-metal lifecycle controls supplied by
      `kit-owned-storefront-loop-lifecycle`; the first introduction scenario on the
      bare-metal lane.
- [x] 1.2 **Decision gate.** Decide whether redaction reaches the copies of revealed
      contacts in `core_storefront`'s authenticated replay store. Decided: out of
      scope. Bounding recorded outcomes needs one answer for every authenticated
      response; recorded as unowned work, and the disclosure's scope names only the
      introduction record.
- [x] 1.3 Plan the implementation, naming the files each decision touches, the focused
      and integration suites, and the permanent documentation destinations. Planning
      decisions are recorded in `design.md`.

## 2. Persistence and redaction (kit)

All in `kit/contact-exchange/src/market_contact_exchange/migrations.py` unless named.

- [ ] 2.1 Add migration `20261001_007_contact_introduction_tombstones` to
      `CONTACT_EXCHANGE_MIGRATIONS`: the nullable `payloads_deleted_at` column, the
      update trigger permitting only the redaction, the delete trigger refusing an
      unredacted row, and an index on `created_at`. Bare metal composes the tuple
      already, so it takes the migration unchanged.
- [ ] 2.2 Replace `delete_introduction` with `delete_introduction_payloads(conn,
      obligation_ref, *, deleted_at)`: one `UPDATE` redacting an unredacted row;
      `True` when it redacts, `False` otherwise. Export it in place of the old name from
      `__init__.py`.
- [ ] 2.3 `introduction_routes.py`: `IntroductionRecord` gains
      `payloads_deleted_at: str | None`. `load_introduction` returns it; a redacted
      record carries empty contacts.
- [ ] 2.4 Add `select_expired_introductions(conn, *, cutoff, limit)` returning the
      obligation references of unredacted rows with `created_at <= cutoff`, and
      `format_introduction_timestamp(datetime)` producing the column's text form.
- [ ] 2.5 `insert_introduction` refuses to re-persist over a redacted row, distinctly
      from its existing different-payload refusal.

## 3. Configuration, disclosure, and the route service (kit)

- [ ] 3.1 `settlement_config.py`: `ContactSettlementConfig` gains `retention_seconds`
      (`int | Literal["indefinite"]`, default `2592000`, positive) and
      `retention_sweep_interval_seconds` (positive, default `3600`), both seller role.
      Confirm the role template and schema-fragment output the settlement configuration
      metadata generates, and update any golden test asserting it.
- [ ] 3.2 Add `retention.py` with `IntroductionRetentionPolicy` (window and interval,
      built from the configuration section) and `retention_disclosure(policy)` returning
      `{"window_seconds", "basis": "current_policy", "scope": "introduction_record"}`.
- [ ] 3.3 `introduction_routes.py`:
      - `introduction_projection` refuses a redacted record and, given a disclosure,
        includes it as `retention`;
      - `IntroductionRouteService` takes an optional disclosure provider;
      - `read` answers `IntroductionRouteError(410, {"code":
        "introduction_payloads_deleted", "payloads_deleted_at": ...})` for a redacted
        record;
      - `start` loads the record first; for a redacted one it drives `complete`, then
        answers the same 410 without persisting or delivering. The existing
        first-reveal check reuses that load.
- [ ] 3.4 `test_package_boundary.py`: add any standard-library root the new modules
      import (`asyncio`, `datetime`) as explicit permitted lines; leave the deny list
      unchanged.

## 4. Sweep, loop runner, and admin service (kit)

In `kit/contact-exchange/src/market_contact_exchange/retention.py`.

- [ ] 4.1 `IntroductionRetentionService`, built from injected persistence callables
      (select-expired, delete-payloads), the policy, and a clock:
      - `delete_one(obligation_ref)` → reference, whether redacted, deletion time;
      - `sweep_once()` → `{"loop": "introduction_retention", "deleted": n}`, selecting
        and redacting through `delete_one`'s operation; nothing when `indefinite`;
      - `preview()` → `{"loop": "introduction_retention", "dry_run": true,
        "eligible": [...], "eligible_count": n}`, writing nothing.
- [ ] 4.2 `run_introduction_retention_sweep(service, *, interval_seconds, paused,
      wait)`: wait, then gate with a short held poll, then `sweep_once`, logging and
      continuing on failure.
- [ ] 4.3 Export the policy, disclosure, service, runner, and route and loop names from
      `__init__.py`.

## 5. Bare-metal composition

In `domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/` unless named.

- [ ] 5.1 `sqlite_client.py`: `delete_contact_introduction_payloads` and
      `select_expired_contact_introductions` as `asyncio.to_thread` wrappers over the
      kit functions.
- [ ] 5.2 `api.py`: build the retention service and policy beside the introduction
      service from the `ContactSettlementConfig` section; pass the disclosure provider
      into the introduction service; add `DELETE
      /api/v1/admin/introductions/{obligation_ref}/payloads` authenticated by `_admin`
      as `admin_delete_introduction_payloads`.
- [ ] 5.3 `models.py` and the `/health` and `/api/v1/system/health` handler in `api.py`:
      `BareMetalHealthResponse` gains `disclosures.introduction_retention`, present only
      when contact exchange is enabled. Do not add it to `/api/v1/system/status`.
- [ ] 5.4 `server.py`: when contact exchange is enabled, start the sweep loop through the
      runtime's loop controller under route `introduction-retention`, with
      `sweep_once` as its step and `preview` as its preview, at the configured interval.
- [ ] 5.5 `delivery.py` and `introduction_routes.py`: `load_revealed_introduction`
      refuses a redacted record, so `redeliver_introduction` and the
      `redeliver-introduction` command deliver nothing for it.
- [ ] 5.6 `core/storefront-client/src/storefront_client/client.py`: add
      `admin_delete_introduction_payloads(obligation_ref)` to the async and sync clients.
- [ ] 5.7 Buyer:
      - `core/buyer/src/core_buyer/negotiation_client.py`: `_authenticated_json` raises
        an `AuthenticatedHTTPError(RuntimeError)` carrying the verified status and body
        for a non-success answer;
      - `core/buyer/src/core_buyer/introductions.py`: `IntroductionTransport` maps 410
        `introduction_payloads_deleted` to `IntroductionPayloadsDeleted`;
      - `domains/bare_metal/buyer/src/arkhai_bare_metal_buyer/cli.py`: the
        start-introduction and `introduction` commands print the outcome with
        `revealed: false` and the deletion time, delivering nothing.
- [ ] 5.8 End-to-end lane: in the root `Makefile`'s bare-metal lane environment, enable
      `contact` in `BARE_METAL_STOREFRONT_SETTLEMENT_JSON` with a seller contact
      payload, one profile, `retention_seconds: 5`, and a long sweep interval. Values
      are development fixtures, commented as such and never to be used on a public
      network.

## 6. Specification

- [ ] 6.1 Promote this change's `contact-exchange-settlement` delta into
      `openspec/specs/contact-exchange-settlement/spec.md`.
- [ ] 6.2 Promote this change's `introduction-delivery` delta into
      `openspec/specs/introduction-delivery/spec.md`.

## 7. Validation

- [ ] 7.1 **Unit (kit).** `kit/contact-exchange/tests/unit/`: `test_migrations.py`
      replaces the row-delete case with redaction, repeat redaction, and the
      re-persist refusal; `test_settlement_config.py` covers both new fields, `indefinite`,
      and the refusal of zero; new `test_retention.py` covers the disclosure object,
      eligibility at the boundary, `indefinite` deleting nothing, preview writing
      nothing, a partially failed sweep converging, and the runner's wait-gate-work
      order; `test_introduction_routes.py` covers the projection's refusal and
      disclosure, and read and start after deletion — start drives completion first and
      neither persists nor delivers.
- [ ] 7.2 **Integration (kit library).** New
      `kit/contact-exchange/tests/integration/test_retention_persistence.py` against a
      real SQLite file: both triggers refuse; a read on an independent connection
      interleaved with redaction sees the whole record or the tombstone; a shortened
      window applies to rows created before it; the sweep converges after a failure
      part-way. Add the `integration` directory to the kit's `make test`.
- [ ] 7.3 **Unit (core).** `core/buyer` tests: the typed error carries status and body
      and remains a `RuntimeError`; the transport maps the deleted outcome.
      `core/storefront-client` tests: the new method in both forms, and the sync/async
      parity test.
- [ ] 7.4 **Integration (bare metal).** `domains/bare_metal/storefront/tests/test_http_introductions.py`
      through `StorefrontClient` and the buyer transport: the readiness disclosure equals
      the reveal's and is absent when contact exchange is disabled; admin deletion
      leaves the obligation resolvable and correlatable by `obligation_ref`; read and a
      fresh-request start answer the deleted outcome and the seller receives no second
      delivery; re-delivery refuses; with the loops held, the retention preview reports
      an eligible introduction and the step redacts exactly it.
      `tests/test_introduction_delivery.py` covers re-delivery's refusal; the buyer
      CLI's outcome is covered in `domains/bare_metal/buyer/tests`.
- [ ] 7.5 **System.** A new module, `test_bare_metal_introduction.py`, in
      `e2e-tests/tests/e2e/roles/scenarios/bare_metal/`, on the bare-metal lane, pausing the storefront's loops through an opt-in
      module-scoped fixture and resuming in a finaliser: declare a pool and whole host,
      set a pool override whose clauses are one introduction option, step publication,
      discover the listing, negotiate and start two introductions through the buyer
      CLI helpers, read the disclosure on readiness and in the reveal, delete one through
      the admin route and observe the deleted outcome, poll the retention preview until
      it reports the other, step the sweep, and observe the deleted outcome.
- [ ] 7.6 Run `make test` in `kit/contact-exchange`, `core/buyer`,
      `core/storefront-client`, `domains/bare_metal/storefront`, and
      `domains/bare_metal/buyer` after `make dist`, and in every other project whose
      lock includes a changed package.

## 8. Closeout

- [ ] 8.1 **Comment hygiene.** Run `make check-comment-hygiene` and resolve every
      match. The local rationale to keep is why deletion redacts rather than removes
      the row, why the triggers permit only redaction, and why the window is read from
      running configuration rather than recorded per row.
- [ ] 8.2 **Import placement.** Review imports this change added or touched and
      migrate function-level ones to module level where no genuine circular import or
      documented lazy-load reason exists. Verify against the real test suite.
- [ ] 8.3 **Documentation compliance.** Re-check accepted decisions against
      `openspec/README.md`'s placement table. That the window is aggregate and read
      from running configuration, and that every composing storefront runs retention,
      are behaviour an implementation must satisfy, so confirm both landed as normative
      requirements rather than as design prose.
- [ ] 8.4 **Narrative compression.** Shorten completed-task notes to final behaviour
      and the accepted risks with their reasoning: that a disclosed window is current
      policy rather than a commitment, that per-storefront discoverability is not
      filterable comparison, and that tombstone removal is anticipated and unowned.
- [ ] 8.5 **Roadmap currency.** Goal 6's open-gap row in
      `docs/development/ROADMAP.md` for the unimplemented retention window leaves the
      table and its result joins Goal 6's current-state prose. Goal 7 names no row for
      this change and needs no edit. Record the update in the design-promotion
      record.
- [ ] 8.6 **Campaign index currency.** Update this change's row and the Goal 6 and
      Goal 7 dependency graphs in `openspec/changes/README.md`, keep the unowned
      replay-store entry this change recorded, and record it in the design-promotion
      record.
- [ ] 8.7 **Documentation citations.** Run
      `make check-doc-citations CHANGE=contact-payload-retention` and resolve every
      match. An unresolvable citation is a blocking defect under `AGENTS.md`'s
      cross-reference rule, and the target also rejects a citation whose target is a
      tombstone.
- [ ] 8.8 **Packaging.** Run `make check-packaging` and resolve every failure it
      reports: environment and image installs derive their internal packages from
      their locks, every lock is current, and every Python version selection reads the
      root declaration.
- [ ] 8.9 **End-to-end pipeline.** Confirm the end-to-end pipeline passes and record
      the evidence: the run, its result, and the bare-metal introduction scenario that
      exercises this change. If the pipeline cannot run for a reason unrelated to this
      change, record that as an explicit blocker naming the cause and the change that
      owns it, and treat the validations it gates as unrun rather than passed.
- [ ] 8.10 **Promotion.** Complete the design-promotion record below, including
      `docs/development/ARCHITECTURE.md`'s settlement-configuration paragraph, which
      names the deletion operation, `docs/development/DEPLOYMENT_AND_CONFIG.md` for the
      retention setting, and `docs/development/TESTING.md`'s loop table.

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
| The authenticated replay store is out of scope; bounding it is unowned work | `openspec/changes/README.md` (unowned work), `docs/development/ROADMAP.md` Goal 6 |
