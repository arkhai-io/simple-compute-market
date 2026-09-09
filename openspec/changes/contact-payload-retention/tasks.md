# Tasks — contact payload retention

## 1. Deletion path

- [ ] 1.1 Add a deletion operation to the introduction persistence contract that
      removes both contact payloads for one `obligation_ref`.
- [ ] 1.2 Leave the settled obligation record, the deal's terminal state, and
      `obligation_ref` resolvability untouched. Cover with a test that resolves
      the deal after deletion, not only one that checks the payloads are gone.
- [ ] 1.3 Make deletion idempotent: deleting an already-deleted or never-revealed
      introduction converges rather than failing.
- [ ] 1.4 Confirm the authenticated read returns a clean already-deleted outcome
      rather than a partially populated record, including when it interleaves
      with a deletion.

## 2. Window and disclosure

- [ ] 2.1 Add the retention window as storefront configuration with an explicit
      operator default.
- [ ] 2.2 Disclose the effective window through the reveal projection both
      parties already read.
- [ ] 2.3 Scope the disclosure text to storefront retention. Copies already
      dispatched to configured delivery sinks are outside it, and the text must
      not imply otherwise.
- [ ] 2.4 Confirm the obligation-servicing path never re-reads contact payloads
      after the reveal. If it does, record that the window has a functional floor
      rather than being purely an operator preference.

## 3. Sweep

- [ ] 3.1 Add a sweep that deletes payloads for introductions past their window,
      reusing the Section 1 operation so there is one deletion implementation.
- [ ] 3.2 Add the operator-invoked single-introduction path for on-request
      deletion.
- [ ] 3.3 **Decision gate:** decide whether the sweep runs unattended by default,
      and record the reasoning in `design.md` before implementing a default. The
      question is open there; do not resolve it by choosing one here.

## 4. Specification

- [ ] 4.1 Extend `openspec/specs/contact-exchange-settlement/spec.md`'s bounded-PII
      requirement with the configured window, its disclosure, and deletion's
      idempotency.
- [ ] 4.2 Add a scenario for deletion preserving the settled obligation record.
- [ ] 4.3 Add a scenario for disclosure at reveal, including its scope against
      delivered copies.

## 5. Validation

- [ ] 5.1 Unit coverage for deletion, idempotent re-deletion, and read-after-delete.
- [ ] 5.2 Coverage that a deal remains resolvable and correlatable by
      `obligation_ref` after its payloads are deleted.
- [ ] 5.3 An end-to-end path covering reveal, disclosure, expiry, and deletion.

## 6. Closeout

- [ ] 6.1 **Comment hygiene.** Run `make check-comment-hygiene` and resolve every
      match. The local rationale to keep is why deletion is scoped to payload
      columns rather than the obligation row.
- [ ] 6.2 **Import placement.** Review imports this change added or touched and
      migrate function-level ones to module level where no genuine circular
      import or documented lazy-load reason exists. Verify against the real test
      suite.
- [ ] 6.3 **Documentation compliance.** Re-check accepted decisions against
      `openspec/README.md`'s placement table.
- [ ] 6.4 **Narrative compression.** Shorten completed-task notes to final
      behaviour, the sweep-default decision and its reasoning, and any remaining
      open work.
- [ ] 6.5 **Roadmap currency.** Update Goal 6's open-gap row in
      `docs/development/ROADMAP.md`: contact-payload retention automation is
      owned by this change rather than unowned.
- [ ] 6.6 **Campaign index currency.** Update this change's row and its campaign's
      dependency graph in `openspec/changes/README.md`.
- [ ] 6.7 **Promotion.** Complete the design-promotion record below.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| Configured retention window with an explicit default, disclosed at reveal | `openspec/specs/contact-exchange-settlement/spec.md` |
| Deletion is idempotent, removes both payloads, preserves the obligation record | `openspec/specs/contact-exchange-settlement/spec.md` |
| Disclosure is scoped to storefront retention, not to delivered copies | `openspec/specs/contact-exchange-settlement/spec.md` |
