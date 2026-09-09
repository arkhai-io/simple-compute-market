# Tasks — name the cardinality hint for its scope

## 1. Survey

- [ ] 1.1 Grep every producer, consumer, test, fixture, operator pool-definitions
      sample, and document mentioning `listing_mode`. Record the full list before
      editing; a rename's risk is entirely in the sites it misses.
- [ ] 1.2 Confirm which side of the projection boundary each site sits on.
      Producer-side and consumer-side sites upgrade independently and the alias
      window exists for exactly that reason.

## 2. Producer

- [ ] 2.1 Emit `listing_cardinality_mode` from the resource-pool projection
      alongside the existing key.
- [ ] 2.2 Accept the new key in operator-supplied pool definitions, continuing to
      accept the old one.

## 3. Consumers

- [ ] 3.1 Prefer `listing_cardinality_mode` in the storefront hint consumers,
      falling back to the old key and emitting an operator-visible deprecation
      notice when the alias is taken.
- [ ] 3.2 Confirm the hint is still read live from the current projection at each
      point of need and is not persisted into storefront-local storage. The
      rename must not become an occasion to cache it.
- [ ] 3.3 Cover the skew case directly: an unupgraded projection carrying only the
      old key must resolve to the same cardinality it resolves to today, not to
      the structural default. This is the defect the alias exists to prevent and
      it needs its own test rather than being implied by the alias's presence.

## 4. Specification

- [ ] 4.1 Synchronize the `MODIFIED` delta for "Domain-owned publication and hold
      hints". The delta replaces the existing requirement in full rather than
      adding a second one — an `ADDED` operation would leave the permanent spec
      carrying two live requirements naming the same hint differently.
- [ ] 4.2 Confirm after synchronization that no requirement in
      `openspec/specs/storefront-publication/spec.md` still names `listing_mode`
      except as the deprecated ingestion alias.

## 5. Producer cleanup

- [ ] 5.1 Stop emitting the old key from the producer once consumers accept both.
      Do not remove consumer-side alias acceptance in this change; its removal is
      an open question in `design.md` with no owner yet, and a task that removed
      it would be deciding that question in a place a reviewer will not look.

## 6. Validation

Levels are named deliberately. Per `docs/development/TESTING.md`, integration
means the real app, a real database, a wired DI container, and the service's
canonical typed client over `ASGITransport` — a hand-built HTTP payload does not
satisfy the no-raw-calls rule, and neither does a model-level unit test.

- [ ] 6.1 **Unit.** Exhaustive key-resolution cases: new key, deprecated alias,
      both present, unrecognized value, absence.
- [ ] 6.2 **Integration.** The producer serializes `listing_cardinality_mode`
      through the real projection API, read back through the canonical site
      client. This is the client-to-API contract and must not be satisfied by a
      unit test over the serializer.
- [ ] 6.3 **Integration.** The storefront consumes a real projection response
      through the canonical site client and resolves cardinality from it.
- [ ] 6.4 **System.** Old-producer/new-consumer skew across deployable services.
      This is system-level evidence for the alias, not a substitute for 6.2
      and 6.3.
- [ ] 6.5 Run the end-to-end scenarios that depend on projected listing shape,
      including at least one `specific_resource` path, since a silent fallback to
      the structural default would otherwise pass a `fungible`-only suite.
- [ ] 6.6 **Boundary-change validation.** This renames a key crossing a service
      boundary, so follow `docs/development/TESTING.md`'s boundary-change
      procedure: package build and type checks, and an audit of every public
      producer and consumer of the renamed constant rather than only the
      publication suites.

## 7. Closeout

- [ ] 7.1 **Comment hygiene.** Run `make check-comment-hygiene` and resolve every
      match. A rename tempts explanatory comments naming the old key; the local
      rationale to keep is the alias's skew-protection purpose, not its history.
- [ ] 7.2 **Import placement.** Review imports this change added or touched and
      migrate function-level ones to module level where a real reason to stay
      local does not exist. Verify each move against the test suite rather than a
      syntax check.
- [ ] 7.3 **Documentation compliance.** Re-check this change's decisions against
      `openspec/README.md`'s placement table. Confirm the scope statement landed
      as a normative requirement rather than as prose in a companion document.
- [ ] 7.4 **Narrative compression.** Shorten completed-task notes to final
      behavior, the alias window's rationale, and the deferred removal question.
- [ ] 7.5 **Roadmap currency.** Remove this change's row from Goal 7's gap table
      in `docs/development/ROADMAP.md` and absorb the result into that goal's
      current-state prose, which currently names the hint's ambiguity as live.
- [ ] 7.6 **Campaign index currency.** Update this change's row and the
      unbacked-listing campaign's dependency graph in
      `openspec/changes/README.md`.
- [ ] 7.7 **Promotion.** Complete the design-promotion record below.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| The cardinality hint's normative scope | `openspec/specs/storefront-publication/spec.md` |
| Absence encodes "no cardinality question"; explanation owed for unrecognized values | `openspec/specs/storefront-publication/spec.md` |
| Deprecated-alias ingestion prevents silent reclassification across version skew | `openspec/specs/storefront-publication/spec.md` |
