# Tasks — contact payload retention

Validation levels below are named deliberately. Per `docs/development/TESTING.md`,
integration means the real app, a real database, a wired DI container, and the
service's canonical typed client over `ASGITransport`.

## 1. Deletion path

Most of this section is already implemented and needs confirming rather than
building. `delete_introduction(conn, obligation_ref)` exists in the mechanism
kit's persistence module beside `insert_introduction` and `load_introduction`, is
exported, and is unit-tested for repeat-call convergence. It has no production
caller.

- [ ] 1.1 Confirm the existing deletion primitive removes both contact payloads
      for one `obligation_ref` and touches nothing else. Do not add a second
      deletion implementation beside it.
- [ ] 1.2 Confirm the settled obligation record, the deal's terminal state, and
      `obligation_ref` resolvability are untouched by it. Cover with a test that
      resolves the deal after deletion, not only one that checks the payloads are
      gone — the existing kit test checks only the latter.
- [ ] 1.3 Confirm deletion is idempotent for an already-deleted row and for a deal
      that never started its introduction, and that it converges rather than
      raising. The primitive returns a boolean rather than raising today; keep that
      property when a caller is added.
- [ ] 1.4 Confirm the authenticated read returns a clean already-deleted outcome
      rather than a partially populated introduction package, including when it
      interleaves with a deletion.
- [ ] 1.5 Add a select-by-age query beside the deletion primitive, reading the
      `created_at` column the table already carries. This is the one piece of
      persistence work the section needs.

## 2. Window and disclosure

- [ ] 2.1 Add the retention window as storefront configuration, defaulting to 30
      days, with an unset value meaning indefinite retention and no deletion.
      Read it live wherever it is used; do not record it per row. Retention is an
      aggregate policy over a dataset the storefront owns and pays for, and a
      pinned value would exempt exactly the rows an operator shortening the policy
      most wants gone. See `design.md`.
- [ ] 2.2 Expose the effective window on the storefront's existing public
      readiness projection, served at `/health` and `/api/v1/system/health` in
      both composing domains, so a buyer can read it before negotiating. Put it in
      a nested object rather than as a flat field, so operator tooling parsing the
      readiness shape is unaffected and later configuration disclosures have one
      place to land.
- [ ] 2.2a Do **not** put it on `/api/v1/system/status`. That route is admin-gated
      in both domains — `_admin(...)` on bare metal, admin-identity and
      service-peer middleware on VM — so a buyer cannot read it.
- [ ] 2.3 Disclose the effective window through the reveal projection both parties
      already read, reading the same live value as 2.2 so the two cannot disagree.
      Reveal alone is too late to inform a decision: the buyer's contact payload
      accompanies the start request, so by the time they read the reveal they have
      already committed it.
- [ ] 2.4 Word both disclosures as current storefront policy rather than as a
      commitment. The operator may change the window or delete a row directly at
      any time, and nothing the storefront states binds them.
- [ ] 2.5 Scope both disclosures to storefront retention. Copies already
      dispatched to configured delivery sinks are outside it, and the text must
      not imply otherwise.
- [ ] 2.6 Confirm the obligation-servicing path never re-reads contact payloads
      after the reveal. If it does, record that the window has a functional floor
      rather than being purely an operator preference.

## 3. Invocation

Both paths call the same handler. `ARCHITECTURE.md`'s operator lifecycle rule
requires a manual cycle to invoke the same production handler as the timer-driven
worker, and `kit/storefront`'s `sweep_stale_negotiations` /
`run_negotiation_watchdog` pair is the shape to follow.

- [ ] 3.1 Add a one-cycle sweep function that deletes payloads for introductions
      past the window and returns a count, reusing the Section 1 primitive and the
      1.5 query.
- [ ] 3.2 Add a background loop over that function on a configurable interval,
      composed at the same startup seam the negotiation watchdog uses in both
      domains.
- [ ] 3.3 Add an admin API method invoking deletion for a single introduction on
      request, calling the same primitive. This serves an out-of-schedule request
      the sweep cannot.
- [ ] 3.4 Skip the sweep entirely when the window is unset, and confirm no
      deletion occurs in that configuration.
- [ ] 3.5 Confirm a partially failed sweep converges on retry rather than failing
      on rows it already deleted.

## 4. Specification

- [ ] 4.1 Extend `openspec/specs/contact-exchange-settlement/spec.md`'s bounded-PII
      requirement with the configured window, both disclosure surfaces, the shared
      deletion handler, and deletion's idempotency.
- [ ] 4.2 Add a scenario for deletion preserving the settled obligation record and
      its correlatability by `obligation_ref`.
- [ ] 4.3 Add a scenario for the window being readable before a buyer commits
      contact data, and one for disclosure at reveal including its scope against
      delivered copies.
- [ ] 4.4 Add a scenario for an unset window retaining indefinitely and deleting
      nothing.
- [ ] 4.5 State that the window is applied as an aggregate policy read live rather
      than pinned per deal, so a later implementation does not reintroduce a
      per-row window.

## 5. Validation

- [ ] 5.1 **Unit.** Deletion, idempotent re-deletion, read-after-delete including
      the interleaving, and the select-by-age query at its boundary.
- [ ] 5.2 **Unit.** A deal remains resolvable and correlatable by
      `obligation_ref` after its payloads are deleted.
- [ ] 5.3 **Unit.** An unset window produces no deletions; a shortened window
      applies to rows revealed before it was shortened, confirming the policy is
      aggregate rather than pinned.
- [ ] 5.4 **Integration.** The window is readable from the public readiness
      projection through the domain's canonical typed client, and matches the value
      the reveal projection discloses.
- [ ] 5.5 **Integration.** The admin single-introduction path deletes through the
      real app and leaves the obligation resolvable.
- [ ] 5.6 **System.** Reveal, disclosure, expiry, sweep, and deletion end to end.

## 6. Closeout

- [ ] 6.1 **Comment hygiene.** Run `make check-comment-hygiene` and resolve every
      match. The local rationale to keep is why deletion is scoped to payload
      columns rather than the obligation row, and why the window is read live
      rather than recorded per row.
- [ ] 6.2 **Import placement.** Review imports this change added or touched and
      migrate function-level ones to module level where no genuine circular
      import or documented lazy-load reason exists. Verify against the real test
      suite.
- [ ] 6.3 **Documentation compliance.** Re-check accepted decisions against
      `openspec/README.md`'s placement table. That the window is aggregate and read
      live is behaviour an implementation must satisfy, so confirm it landed as a
      normative requirement rather than as design prose.
- [ ] 6.4 **Narrative compression.** Shorten completed-task notes to final
      behaviour, and the accepted risks with their reasoning: that a disclosed
      window is current policy rather than a commitment, and that per-storefront
      discoverability is not filterable comparison.
- [ ] 6.5 **Roadmap currency.** Update Goal 6's open-gap row in
      `docs/development/ROADMAP.md`: contact-payload retention automation is
      owned by this change rather than unowned.
- [ ] 6.6 **Campaign index currency.** Update this change's row and its campaign's
      dependency graph in `openspec/changes/README.md`.
- [ ] 6.7 **Promotion.** Complete the design-promotion record below.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| Configured retention window with a 30-day default; unset means indefinite | `openspec/specs/contact-exchange-settlement/spec.md` |
| The window is an aggregate policy read live, not a per-deal term pinned at reveal | `openspec/specs/contact-exchange-settlement/spec.md` |
| Deletion is idempotent, removes both payloads, preserves the obligation record | `openspec/specs/contact-exchange-settlement/spec.md` |
| The scheduled sweep and the operator-invoked path share one deletion handler | `openspec/specs/contact-exchange-settlement/spec.md` |
| The window is queryable before a buyer commits contact data, and disclosed again at reveal | `openspec/specs/contact-exchange-settlement/spec.md` |
| Disclosure states current policy, scoped to storefront retention, not to delivered copies | `openspec/specs/contact-exchange-settlement/spec.md` |
